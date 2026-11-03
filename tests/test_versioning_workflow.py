""" 実際のファイルで版変換・再読・差分保存・帳票出力の境界を確認する。
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from DataManager import ConfigurationError, ObjectRepository, RowsRepository, SerializationError, VersionConverter
from UseCase.processing import load_processing_presets
from UseCase.analysis import AnalysisWorkspace
from Domain.processing import process_data
from DataManager.report_export import ReportExportService
from Domain.reporting import ReportRow, build_report_rows
from DataManager.settings_versions import create_settings_repository


def test_chain_converts_both_directions_without_mutating_input():
    visited: list[str] = []

    def upcast(value: dict[str, Any]) -> dict[str, Any]:
        visited.append(f"up{value['version']}")
        value["nested"]["value"] += 1
        return value

    def downcast(value: dict[str, Any]) -> dict[str, Any]:
        visited.append(f"down{value['version']}")
        value["nested"]["value"] -= 1
        return value

    converter = VersionConverter(current_version=6, upcasts={index: upcast for index in range(6)},
                                 downcasts={index: downcast for index in range(1, 7)})
    source = {"version": 2, "nested": {"value": 10}}
    original = deepcopy(source)
    latest = converter.to_current(source)

    assert source == original
    assert latest == {"version": 6, "nested": {"value": 14}}
    assert converter.convert(latest, target_version=2) == original
    assert visited == ["up2", "up3", "up4", "up5", "down6", "down5", "down4", "down3"]


@pytest.mark.parametrize("version", [None, True, -1, 4, "2", 2.0])
def test_invalid_version_is_not_treated_as_missing(version: Any):
    converter = VersionConverter(current_version=3, upcasts={}, downcasts={})
    with pytest.raises(SerializationError):
        converter.to_current({"version": version})


def test_missing_version_means_zero_and_missing_path_is_checked_first():
    calls: list[int] = []

    def upcast(value: dict[str, Any]) -> dict[str, Any]:
        calls.append(1)
        return value

    converter = VersionConverter(current_version=2, upcasts={0: upcast}, downcasts={})
    with pytest.raises(ConfigurationError, match="V1→V2"):
        converter.to_current({})
    assert calls == []
    assert VersionConverter(current_version=0, upcasts={}, downcasts={}).to_current({}) == {"version": 0}


def test_cast_failure_identifies_step_and_preserves_cause():
    def broken(value: dict[str, Any]) -> dict[str, Any]:
        raise ValueError("bad old field")

    with pytest.raises(SerializationError, match="V0→V1") as captured:
        VersionConverter(current_version=1, upcasts={0: broken}, downcasts={}).to_current({})
    assert isinstance(captured.value.__cause__, ValueError)


@pytest.mark.parametrize("extension", ["json", "yaml", "txt"])
@pytest.mark.parametrize("retained_value", [None, "", 0, False])
def test_retained_and_discarded_fields_survive_restart_as_intended(tmp_path: Path, extension: str, retained_value: Any):
    repository = ObjectRepository(model=dict, base_directory=tmp_path)
    repository.save("old.json", {"version": 2, "threashold": 4.0, "operator_note": retained_value, "draft_flag": "discard"})
    source_bytes = (tmp_path / "old.json").read_bytes()
    first_service = create_settings_repository(tmp_path)
    document = first_service.load("old.json")
    document.settings.threshold = 8.0
    first_service.save(f"latest.{extension}", document)

    # サービスを作り直しても、元ファイルなしで維持対象だけが引き継がれる。
    assert (tmp_path / "old.json").read_bytes() == source_bytes
    (tmp_path / "old.json").unlink()
    second_service = create_settings_repository(tmp_path)
    restored = second_service.load(f"latest.{extension}")
    restored.settings.gain = 2.0
    second_service.save("export.json", restored, target_version=2)

    assert repository.load("export.json") == {"version": 2, "threashold": 8.0, "operator_note": retained_value}
    assert "draft_flag" not in (tmp_path / f"latest.{extension}").read_text(encoding="utf-8")


def test_yaml_versioned_overwrite_does_not_resurrect_removed_keys(tmp_path: Path):
    (tmp_path / "settings.yaml").write_text("version: 2\nthreashold: 4\ndraft_flag: discard\n", encoding="utf-8")
    service = create_settings_repository(tmp_path)
    document = service.load("settings.yaml")
    with pytest.raises(FileExistsError):
        service.save("settings.yaml", document)
    service.save("settings.yaml", document, overwrite=True)
    assert "draft_flag" not in (tmp_path / "settings.yaml").read_text(encoding="utf-8")


def test_reanalysis_saves_only_settings_and_reload_reads_manual_edit(tmp_path: Path):
    settings = create_settings_repository(tmp_path)
    (tmp_path / "source.json").write_text('{"version":2,"threashold":3}', encoding="utf-8")
    application = AnalysisWorkspace(tmp_path / "analysis")
    processing, retained = load_processing_presets(tmp_path / "source.json", [1, 5])
    presets = process_data(processing)
    application.save_initial(presets, retained_values=retained)
    measurements_path = tmp_path / "analysis" / "measurements.jsonl"
    before = measurements_path.stat().st_mtime_ns, measurements_path.read_bytes()

    with application.edit() as presets:
        presets.threshold = 4
        application.save_settings(presets, overwrite=True)
    assert (measurements_path.stat().st_mtime_ns, measurements_path.read_bytes()) == before

    # 外部で手修正したファイルを、キャッシュや元の設定で巻き戻さない。
    settings_path = tmp_path / "analysis" / "settings.yaml"
    settings_path.write_text("version: 3\nthreshold: 7\ngain: 1\n", encoding="utf-8")
    assert application.load().threshold == 7
    assert settings.load(tmp_path / "source.json").settings.threshold == 3


def test_flat_presets_api_preserves_legacy_values_without_exposing_edit_metadata(tmp_path: Path):
    source = tmp_path / "source.json"
    source.write_text(
        '{"version":2,"threashold":3,"operator_note":"keep","draft_flag":"discard"}',
        encoding="utf-8",
    )
    analysis = AnalysisWorkspace(tmp_path / "analysis")
    processing, retained = load_processing_presets(source, [1, 5])
    analysis.save_initial(process_data(processing), retained_values=retained)
    source.unlink()

    # 再生成したサービスでも、Presetsだけを編集して旧版へ戻せる。
    analysis = AnalysisWorkspace(tmp_path / "analysis")
    with analysis.edit() as presets:
        presets.threshold = 8
        analysis.save_settings(presets, overwrite=True)
        analysis.export_settings("export.json", presets, target_version=2)

    exported = ObjectRepository(model=dict, base_directory=analysis.directory).load("export.json")
    assert exported == {"version": 2, "threashold": 8, "operator_note": "keep"}


@pytest.mark.parametrize("rows_mode", [False, True])
def test_concurrent_create_does_not_overwrite(tmp_path: Path, rows_mode: bool):
    def save(index: int) -> bool:
        try:
            if rows_mode:
                RowsRepository(model=dict, base_directory=tmp_path).save("result.jsonl", [{"index": index}])
            else:
                ObjectRepository(model=dict, base_directory=tmp_path).save("result.json", {"index": index})
            return True
        except FileExistsError:
            return False

    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(save, range(8)))
    assert results.count(True) == 1


def test_same_report_rows_are_exported_as_csv_jsonl_and_excel_callback(tmp_path: Path):
    rows = [ReportRow(measurement_id="a", value=4, exceeds_threshold=True)]
    received: list[ReportRow] = []

    def excel_writer(report_rows: Any) -> bytes:
        received.extend(report_rows)
        return b"excel adapter output"

    service = ReportExportService(tmp_path, excel_writer=excel_writer)
    for extension in ("csv", "jsonl", "xlsx"):
        service.export(f"report.{extension}", rows)
        with pytest.raises(FileExistsError):
            service.export(f"report.{extension}", rows)

    repository = RowsRepository(model=ReportRow, base_directory=tmp_path)
    assert repository.load("report.csv") == rows
    assert repository.load("report.jsonl") == rows
    assert received == rows * 2
    assert (tmp_path / "report.xlsx").read_bytes() == b"excel adapter output"
    assert build_report_rows([]) == []
