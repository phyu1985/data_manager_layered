""" 外部反映だけの失敗・再試行と、未保存編集値の混入防止を確認する。
"""
import json
from pathlib import Path

import pytest

from Domain.models import AnalysisPresets
from UseCase.analysis import AnalysisWorkspace
from UseCase.external_updates import ExternalUpdater
from DataManager.summary import create_summary_writer


def create_presets() -> AnalysisPresets:
    return AnalysisPresets(threshold=10, gain=1, measurements=[])


def test_failure_does_not_undo_saved_data_and_selective_retry_does_not_duplicate(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
):
    application = AnalysisWorkspace(tmp_path / "analysis")
    application.save_initial(create_presets())
    saved_bytes = (application.directory / "settings.yaml").read_bytes()
    database: dict[str, float] = {}
    attempts = 0

    def update_database(directory: Path, snapshot: AnalysisPresets):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionError("offline")
        database[str(directory)] = snapshot.threshold

    service = ExternalUpdater(application, targets={
        "database": update_database,
        "summary": create_summary_writer(tmp_path / "latest_status"),
    })
    result = service.refresh()
    assert result.succeeded_targets == ("summary",)
    assert result.failures[0].target == "database"
    assert isinstance(result.failures[0].error, ConnectionError)
    assert "database" in caplog.text
    assert (application.directory / "settings.yaml").read_bytes() == saved_bytes

    retry = service.refresh(target_names=[failure.target for failure in result.failures])
    assert retry.succeeded_targets == ("database",)
    assert retry.failures == ()
    service.refresh()
    assert len(database) == 1
    summaries = list((tmp_path / "latest_status").glob("*.json"))
    assert len(summaries) == 1
    assert json.loads(summaries[0].read_text(encoding="utf-8"))["threshold"] == 10


def test_refresh_uses_saved_values_without_discarding_unsaved_edits(tmp_path: Path):
    application = AnalysisWorkspace(tmp_path)
    application.save_initial(create_presets())
    received: list[float] = []

    def modifying_target(directory: Path, snapshot: AnalysisPresets):
        received.append(snapshot.threshold)
        snapshot.threshold = -1

    def other_target(directory: Path, snapshot: AnalysisPresets):
        received.append(snapshot.threshold)

    service = ExternalUpdater(application, targets={"first": modifying_target, "second": other_target})
    with application.edit() as presets:
        presets.threshold = 999
        assert service.refresh(presets=presets).failures == ()
        assert received == [10, 10]
        assert presets.threshold == 999

        application.save_settings(presets, overwrite=True)
        service.refresh(presets=presets)
        assert received == [10, 10, 999, 999]

    with pytest.raises(RuntimeError):
        service.refresh(presets=presets)


def test_refresh_rejects_foreign_session_and_invalid_targets(tmp_path: Path):
    application = AnalysisWorkspace(tmp_path / "one")
    other_application = AnalysisWorkspace(tmp_path / "two")
    application.save_initial(create_presets())
    other_application.save_initial(create_presets())
    service = ExternalUpdater(application, targets={"summary": create_summary_writer(tmp_path / "summary")})

    with other_application.edit() as presets:
        with pytest.raises(RuntimeError, match="有効な編集"):
            service.refresh(presets=presets)

    for names in ([], ["summary", "summary"], ["missing"]):
        with pytest.raises(ValueError):
            service.refresh(target_names=names)
