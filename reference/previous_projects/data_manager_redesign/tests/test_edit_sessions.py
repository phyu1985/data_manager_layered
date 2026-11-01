""" 初回保存の後始末と、画面の寿命に対応する編集排他を確認する。
"""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys

import portalocker
import pytest

from data_manager import lock_directory
from examples.analysis_files import AnalysisFiles
from examples.analysis_models import AnalysisPresets, Measurement
from examples.analysis_workflow import AnalysisService


def create_presets() -> AnalysisPresets:
    return AnalysisPresets(threshold=10, gain=1, measurements=[
        Measurement(measurement_id="a", value=20),
    ])


def test_initial_failure_removes_only_new_data_and_can_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    directory = tmp_path / "analysis"
    directory.mkdir()
    unrelated_file = directory / "keep.txt"
    unrelated_file.write_text("keep", encoding="utf-8")
    application = AnalysisService(directory)
    original_save = AnalysisFiles.save_measurements

    def fail_after_write(files: AnalysisFiles, presets: AnalysisPresets, *, overwrite: bool = False):
        original_save(files, presets, overwrite=overwrite)
        raise OSError("measurement save failed")

    monkeypatch.setattr(AnalysisFiles, "save_measurements", fail_after_write)
    with pytest.raises(OSError, match="measurement save failed"):
        application.save_initial(create_presets())

    assert not (directory / "settings.yaml").exists()
    assert not (directory / "measurements.jsonl").exists()
    assert unrelated_file.read_text(encoding="utf-8") == "keep"
    assert (directory / ".edit-session.lock").exists()

    monkeypatch.setattr(AnalysisFiles, "save_measurements", original_save)
    application.save_initial(create_presets())
    assert application.load().threshold == 10


@pytest.mark.parametrize("existing_name", ["settings.yaml", "measurements.jsonl"])
def test_initial_save_refuses_existing_target_before_writing(tmp_path: Path, existing_name: str):
    existing = tmp_path / existing_name
    existing.write_bytes(b"original")
    with pytest.raises(FileExistsError):
        AnalysisService(tmp_path).save_initial(create_presets())
    assert existing.read_bytes() == b"original"
    other_name = "measurements.jsonl" if existing_name == "settings.yaml" else "settings.yaml"
    assert not (tmp_path / other_name).exists()


def test_cleanup_failure_preserves_original_error_and_identifies_remaining_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    original_unlink = Path.unlink

    def fail_measurements(files: AnalysisFiles, presets: AnalysisPresets, *, overwrite: bool = False):
        raise OSError("save failed")

    def fail_settings_delete(path: Path, missing_ok: bool = False):
        if path == tmp_path / "settings.yaml":
            raise PermissionError("cleanup failed")
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(AnalysisFiles, "save_measurements", fail_measurements)
    monkeypatch.setattr(Path, "unlink", fail_settings_delete)
    with pytest.raises(ExceptionGroup) as captured:
        AnalysisService(tmp_path).save_initial(create_presets())

    assert str(captured.value.exceptions[0]) == "save failed"
    cleanup_error = captured.value.exceptions[1]
    assert isinstance(cleanup_error, PermissionError)
    assert "settings.yaml" in " ".join(cleanup_error.__notes__)
    assert (tmp_path / "settings.yaml").exists()


def test_initial_keyboard_interrupt_cleans_new_files_and_releases_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    def interrupt(files: AnalysisFiles, presets: AnalysisPresets, *, overwrite: bool = False):
        raise KeyboardInterrupt()

    monkeypatch.setattr(AnalysisFiles, "save_measurements", interrupt)
    with pytest.raises(KeyboardInterrupt):
        AnalysisService(tmp_path).save_initial(create_presets())

    assert not (tmp_path / "settings.yaml").exists()
    with lock_directory(tmp_path):
        assert not (tmp_path / "measurements.jsonl").exists()


def test_edit_lock_covers_read_edit_save_and_releases_on_exception(tmp_path: Path):
    application = AnalysisService(tmp_path)
    application.save_initial(create_presets())
    other_window = AnalysisService(tmp_path)

    with pytest.raises(ValueError, match="processing failed"):
        with application.edit() as presets:
            presets.threshold = 30
            with pytest.raises(portalocker.exceptions.LockException):
                other_window.load()
            with pytest.raises(portalocker.exceptions.LockException):
                with other_window.edit():
                    pytest.fail("two editors entered")

            application.save_settings(presets, overwrite=True)
            with pytest.raises(portalocker.exceptions.LockException):
                other_window.load()
            raise ValueError("processing failed")

    assert other_window.load().threshold == 30
    with pytest.raises(RuntimeError, match="有効な編集"):
        application.save_settings(presets, overwrite=True)


def test_editor_refuses_other_thread_and_failed_read_releases_lock(tmp_path: Path):
    application = AnalysisService(tmp_path)
    with pytest.raises(FileNotFoundError):
        with application.edit():
            pytest.fail("missing input should fail")

    application.save_initial(create_presets())
    with application.edit() as presets:
        with ThreadPoolExecutor(max_workers=1) as workers:
            operation = workers.submit(application.save_measurements, presets, overwrite=True)
            with pytest.raises(RuntimeError, match="同じスレッド"):
                operation.result()


def test_export_to_another_folder_respects_that_folders_edit_lock(tmp_path: Path):
    application = AnalysisService(tmp_path / "source")
    other_application = AnalysisService(tmp_path / "destination")
    application.save_initial(create_presets())
    other_application.save_initial(create_presets())
    export_path = other_application.directory / "export.json"

    with application.edit() as presets:
        with other_application.edit():
            with pytest.raises(portalocker.exceptions.LockException):
                application.save_settings(presets, path=export_path, target_version=2)
            assert not export_path.exists()

        application.save_settings(presets, path=export_path, target_version=2)
    assert export_path.exists()


def test_detached_or_previous_presets_cannot_be_saved_as_current_edit(tmp_path: Path):
    analysis = AnalysisService(tmp_path)
    analysis.save_initial(create_presets())
    detached = analysis.load()

    with pytest.raises(RuntimeError):
        analysis.save_settings(detached, overwrite=True)

    with analysis.edit() as presets:
        with pytest.raises(RuntimeError):
            analysis.save_settings(detached, overwrite=True)
        presets.threshold = 15
        analysis.save_settings(presets, overwrite=True)
        previous = presets

    with analysis.edit() as presets:
        with pytest.raises(RuntimeError):
            analysis.save_settings(previous, overwrite=True)
        assert presets.threshold == 15


def test_rejected_nested_edit_does_not_end_the_current_edit(tmp_path: Path):
    analysis = AnalysisService(tmp_path)
    analysis.save_initial(create_presets())

    with analysis.edit() as presets:
        with pytest.raises(portalocker.exceptions.LockException):
            with analysis.edit():
                pytest.fail("nested edit should fail")

        presets.threshold = 25
        analysis.save_settings(presets, overwrite=True)

    assert analysis.load().threshold == 25


def test_directory_lock_excludes_other_process_and_survives_abrupt_exit(tmp_path: Path):
    child_environment = dict(os.environ)
    child_environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    child_script = """
import os, sys
from pathlib import Path
import portalocker
from data_manager import lock_directory
try:
    with lock_directory(Path(sys.argv[1])):
        print('acquired', flush=True)
        os._exit(0)
except portalocker.exceptions.LockException:
    print('busy', flush=True)
"""

    def run_child() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-c", child_script, str(tmp_path)],
            env=child_environment, capture_output=True, text=True, timeout=15, check=True,
        )

    with lock_directory(tmp_path):
        assert run_child().stdout.strip() == "busy"
    assert run_child().stdout.strip() == "acquired"

    # 子プロセスがwithの後始末を実行せず終了しても、OSがロックを解放する。
    with lock_directory(tmp_path):
        assert (tmp_path / ".edit-session.lock").exists()
