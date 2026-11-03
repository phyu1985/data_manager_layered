""" 利用手順の例を、保存内容・再解析・生成ファイル数まで通して確認する。
"""
from pathlib import Path

import pytest

from DataManager import RowsRepository
from Domain.models import ProcessingPresets
from UseCase.analysis import AnalysisWorkspace, apply_analysis_result
from Domain.analysis import analyze_readings
from UseCase.end_to_end import list_analyses, run, select_analysis
from Domain.processing import process_readings
from DataManager.raw_readings import read_raw
from Domain.reporting import ReportRow


def create_raw(path: Path):
    """ テスト用の生データを作る。出力例とは分けて元データの保護も確認する。
    """
    path.write_text("value\n10\n18\n22\n30\n", encoding="utf-8")


@pytest.mark.parametrize("report_format", ["csv", "jsonl"])
def test_complete_flow_keeps_three_data_files_and_saves_latest_result(tmp_path: Path, report_format: str):
    raw_path = tmp_path / "raw.csv"
    create_raw(raw_path)
    original = raw_path.read_bytes()
    output = tmp_path / "output"

    result = run(output, raw_path=raw_path, report_format=report_format)

    assert raw_path.read_bytes() == original
    assert result.first.order == ("1", "2", "0", "3")
    assert result.second.order == ("3", "2", "1", "0")
    assert result.first.exceeded_count == 2
    assert result.second.exceeded_count == 1
    assert result.first.mean_value == result.second.mean_value == 10

    saved = AnalysisWorkspace(result.analysis_directory).load()
    assert saved.threshold == 18
    assert [row.value for row in saved.measurements] == [20, 12, 8, 0]

    report = RowsRepository(model=ReportRow, base_directory=output).load(result.report_path)
    assert [row.measurement_id for row in report] == ["3", "2", "1", "0"]
    assert [row.exceeds_threshold for row in report] == [True, False, False, False]

    # 繰り返した段階ごとの別名ファイルや中間集計ファイルは作らない。
    data_files = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file() and not path.name.endswith(".lock")
    }
    assert data_files == {
        "datasets/sample01/settings.yaml", "datasets/sample01/measurements.jsonl",
        f"report.{report_format}",
    }


def test_processing_and_reanalysis_do_not_change_raw_values_or_accumulate_gain():
    processing = ProcessingPresets(threshold=10, gain=2, raw_values=[10, 18, 22, 30])
    presets = process_readings(processing)
    assert processing.raw_values == [10, 18, 22, 30]
    assert [row.value for row in presets.measurements] == [0, 16, 24, 40]

    presets.threshold = 18
    before = presets.model_dump()
    original_rows = tuple(presets.measurements)
    first = analyze_readings(presets)
    assert analyze_readings(presets) == first
    assert presets.model_dump() == before
    assert all(row is original for row, original in zip(presets.measurements, original_rows, strict=True))

    apply_analysis_result(presets, first)
    assert [row.measurement_id for row in presets.measurements] == list(first.summary.order)
    assert all(presets.measurements[i] is original_rows[j] for i, j in enumerate(first.measurement_indices))
    second = analyze_readings(presets)
    apply_analysis_result(presets, second)
    assert first.summary == second.summary
    assert sorted(row.value for row in presets.measurements) == [0, 16, 24, 40]

    presets.threshold = 20
    changed = presets.model_dump()
    with pytest.raises(ValueError, match="再計算"):
        apply_analysis_result(presets, second)
    assert presets.model_dump() == changed


def test_selection_uses_saved_datasets_and_does_not_pick_incomplete_folder(tmp_path: Path):
    presets = process_readings(ProcessingPresets(threshold=10, gain=1, raw_values=[10, 20]))
    for name in ("one", "two"):
        AnalysisWorkspace(tmp_path / name).save_initial(presets)
    (tmp_path / "incomplete").mkdir()
    (tmp_path / "incomplete" / "settings.yaml").write_text("version: 3", encoding="utf-8")

    candidates = list_analyses(tmp_path)
    assert [path.name for path in candidates] == ["one", "two"]
    selected = select_analysis(candidates, "two")
    other_bytes = (tmp_path / "one" / "settings.yaml").read_bytes()

    analysis = AnalysisWorkspace(selected)
    with analysis.edit() as current:
        current.threshold = 30
        analysis.save_settings(current, overwrite=True)

    assert analysis.load().threshold == 30
    assert (tmp_path / "one" / "settings.yaml").read_bytes() == other_bytes
    with pytest.raises(ValueError, match="解析対象がありません"):
        select_analysis(candidates, "missing")


def test_external_jsonl_is_input_only_and_internal_output_gets_metadata(tmp_path: Path):
    raw_path = tmp_path / "raw.jsonl"
    raw_path.write_text('{"value":10}\n{"value":20}\n', encoding="utf-8")
    original = raw_path.read_bytes()
    result = run(tmp_path / "output", raw_path=raw_path)

    assert raw_path.read_bytes() == original
    assert [row.value for row in read_raw(raw_path)] == [10, 20]
    saved_lines = (result.analysis_directory / "measurements.jsonl").read_text(encoding="utf-8").splitlines()
    assert '"__meta__"' in saved_lines[0]


@pytest.mark.parametrize("raw_text", ["value\n", "value\nNaN\n", "value\nnot-a-number\n"])
def test_invalid_raw_data_does_not_create_output(tmp_path: Path, raw_text: str):
    raw_path = tmp_path / "raw.csv"
    raw_path.write_text(raw_text, encoding="utf-8")
    output = tmp_path / "output"
    with pytest.raises(ValueError):
        run(output, raw_path=raw_path)
    assert not output.exists()


def test_existing_output_is_refused_without_changing_files(tmp_path: Path):
    output = tmp_path / "output"
    output.mkdir()
    keep = output / "keep.txt"
    keep.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        run(output)
    assert keep.read_text(encoding="utf-8") == "keep"
