""" ユースケースから、固定したファイルと方針で入出力できることを確認する。
"""
from typing import Any

import numpy as np
from pydantic import BaseModel, ValidationError
import pytest

from DataManager import (
    ConfigurationError, ObjectFileService, ObjectRepository, RowsFileService,
    RowsRepository, SerializationError, WaveformFileService, WaveformHeader,
    WaveformOptions, WaveformRepository,
)


class Settings(BaseModel):
    project_name: str


class Event(BaseModel):
    message: str


class Audit(BaseModel):
    operation: str


def test_object_service_reuses_fixed_path_and_template(tmp_path):
    templates = tmp_path / "templates"
    templates.mkdir()
    template = templates / "settings.yaml"
    template.write_text("# project settings\nproject_name: template\n")
    service = ObjectFileService(
        repository=ObjectRepository(
            model=Settings, base_directory=tmp_path, template_directory=templates,
        ),
        path="config/settings.yaml", template_name="settings.yaml",
    )
    assert not (tmp_path / "config").exists()

    service.save(Settings(project_name="first"))
    service.save(Settings(project_name="second"), overwrite=True)
    assert service.load() == Settings(project_name="second")
    assert "# project settings" in (tmp_path / "config/settings.yaml").read_text()
    assert "template" in template.read_text()


def test_rows_service_reads_and_writes_csv_without_repeating_path(tmp_path):
    service = RowsFileService(
        repository=RowsRepository(model=Settings, base_directory=tmp_path),
        path="projects.csv",
    )
    service.save([Settings(project_name="first"), Settings(project_name="second")])
    assert [value.project_name for value in service.load()] == ["first", "second"]
    with pytest.raises(ConfigurationError):
        service.append([Settings(project_name="third")])


def test_mixed_rows_service_saves_and_appends_real_models(tmp_path):
    service = RowsFileService[Event | Audit](
        repository=RowsRepository[Event | Audit](model=(Event, Audit), base_directory=tmp_path),
        path="logs/events.jsonl",
    )
    service.save([Event(message="started")])
    service.append(iter([Audit(operation="saved")]))
    assert service.load() == [Event(message="started"), Audit(operation="saved")]

    original = (tmp_path / "logs/events.jsonl").read_bytes()
    with pytest.raises(SerializationError):
        service.append([{"message": "invalid model type"}])
    assert (tmp_path / "logs/events.jsonl").read_bytes() == original


def test_dictionary_service_uses_the_same_typed_interface(tmp_path):
    service = ObjectFileService[dict[str, Any]](
        repository=ObjectRepository[dict[str, Any]](model=dict, base_directory=tmp_path),
        path="settings.json",
    )
    service.save({"enabled": True})
    assert service.load() == {"enabled": True}


def test_service_preserves_missing_file_and_validation_errors(tmp_path):
    service = ObjectFileService(
        repository=ObjectRepository(model=Settings, base_directory=tmp_path), path="settings.json",
    )
    with pytest.raises(FileNotFoundError):
        service.load()
    (tmp_path / "settings.json").write_text("{}")
    with pytest.raises(SerializationError) as failure:
        service.load()
    assert isinstance(failure.value.__cause__, ValidationError)


def test_waveform_service_uses_injected_private_header_policy(tmp_path):
    (tmp_path / "wave.bin").write_bytes(b"\x01\x00\x02\x00")
    options = WaveformOptions(
        header_reader=lambda stream: WaveformHeader(values={"channels": [0], "samples": 1}, data_offset=0),
    )
    service = WaveformFileService(
        repository=WaveformRepository(base_directory=tmp_path, options=options), path="wave.bin",
    )
    np.testing.assert_array_equal(service.load().data, [[[1, 2]]])
    np.testing.assert_array_equal(service.peek(), [[[1, 2]]])
