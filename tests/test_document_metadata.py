""" CSVの境界規則と、CSV・JSONL共通のメタ情報APIのデータ保護を確認する。
"""
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, Field

from DataManager import (
    ConfigurationError, CsvOptions, CsvKeyValueHeaderOptions, CsvSerializer,
    JSONLLoadOptions, JsonlSerializer, RowsDocument, RowsFileService,
    RowsRepository, SerializationError, VersionConverter, VersionedRowsRepository,
)


class Metadata(BaseModel):
    version: int
    device: str


class Measurement(BaseModel):
    time: int
    value: float


BOUNDARIES = [
    CsvKeyValueHeaderOptions.until_blank_line(),
    CsvKeyValueHeaderOptions.until_marker('[data]'),
    CsvKeyValueHeaderOptions.fixed_rows(2),
]


def csv_repository(directory: Path, options: CsvKeyValueHeaderOptions) -> RowsRepository[Measurement]:
    """ 対象CSVの規則だけを明示し、業務の項目はSerializerへ渡さない。
    """
    return RowsRepository(
        model=Measurement, base_directory=directory,
        serializers_by_extension={".csv": CsvSerializer(metadata=options)},
    )


@pytest.mark.parametrize("options", BOUNDARIES)
def test_csv_typed_document_roundtrip_and_rows_only_load(tmp_path: Path, options: CsvKeyValueHeaderOptions):
    repository = csv_repository(tmp_path, options)
    metadata = Metadata(version=4, device='A,001\n[device]')
    rows = [Measurement(time=0, value=1.2), Measurement(time=1, value=1.5)]
    repository.save_document("data.csv", RowsDocument(metadata=metadata, rows=rows))

    restored = repository.load_document("data.csv", metadata_model=Metadata)
    assert restored.metadata == metadata
    assert restored.rows == rows
    assert repository.load("data.csv") == rows
    # CSVの辞書モードは元の文字列を保持し、数値の推測をしない。
    raw = repository.load_document("data.csv")
    assert raw.metadata == {"version": "4", "device": metadata.device}


@pytest.mark.parametrize("options", BOUNDARIES)
def test_csv_empty_table_keeps_metadata_and_model_columns(tmp_path: Path, options: CsvKeyValueHeaderOptions):
    repository = csv_repository(tmp_path, options)
    document = RowsDocument[Metadata, Measurement](metadata=Metadata(version=4, device="001"), rows=[])
    repository.save_document("empty.csv", document)
    assert repository.load_document("empty.csv", metadata_model=Metadata) == document
    assert (tmp_path / "empty.csv").read_text(encoding="utf-8").endswith("time,value\n")


@pytest.mark.parametrize("options", [
    CsvKeyValueHeaderOptions.until_blank_line(), CsvKeyValueHeaderOptions.until_marker('---'),
    CsvKeyValueHeaderOptions.fixed_rows(0),
])
def test_empty_metadata_is_an_explicit_document(tmp_path: Path, options: CsvKeyValueHeaderOptions):
    repository = csv_repository(tmp_path, options)
    document = RowsDocument[dict[str, Any], Measurement](metadata={}, rows=[Measurement(time=0, value=1)])
    repository.save_document("data.csv", document)
    assert repository.load_document("data.csv") == document


def test_csv_quoted_empty_key_is_not_a_blank_separator(tmp_path: Path):
    repository = csv_repository(tmp_path, CsvKeyValueHeaderOptions.until_blank_line())
    (tmp_path / "bad.csv").write_text('""\ntime,value\n0,1\n', encoding="utf-8")
    with pytest.raises(SerializationError, match="2列"):
        repository.load_document("bad.csv")


@pytest.mark.parametrize("text", [
    "version,4\nversion,5\n\ntime,value\n0,1\n",
    "version,4,extra\n\ntime,value\n0,1\n",
    ",4\n\ntime,value\n0,1\n",
    "version,4\ntime,value\n0,1\n",
    'version,"unfinished\n',
])
def test_csv_malformed_metadata_does_not_become_table_data(tmp_path: Path, text: str):
    repository = csv_repository(tmp_path, CsvKeyValueHeaderOptions.until_blank_line())
    (tmp_path / "bad.csv").write_text(text, encoding="utf-8")
    with pytest.raises(SerializationError):
        repository.load_document("bad.csv")


@pytest.mark.parametrize("options", [
    CsvKeyValueHeaderOptions.until_marker('---'),
    CsvKeyValueHeaderOptions.fixed_rows(2),
])
def test_csv_missing_marker_or_insufficient_records_is_an_error(tmp_path: Path, options: CsvKeyValueHeaderOptions):
    repository = csv_repository(tmp_path, options)
    (tmp_path / "bad.csv").write_text("version,4\n", encoding="utf-8")
    with pytest.raises(SerializationError, match="境界"):
        repository.load_document("bad.csv")


def test_marker_has_to_be_a_complete_record_and_fixed_count_uses_csv_records(tmp_path: Path):
    repository = csv_repository(tmp_path, CsvKeyValueHeaderOptions.until_marker('---'))
    document = RowsDocument[dict[str, Any], Measurement](
        metadata={"---": "not a boundary", "note": "line1\n\nline2"},
        rows=[Measurement(time=0, value=1)],
    )
    repository.save_document("marker.csv", document)
    assert repository.load_document("marker.csv") == document

    fixed = csv_repository(tmp_path, CsvKeyValueHeaderOptions.fixed_rows(2))
    fixed.save_document("fixed.csv", document)
    assert fixed.load_document("fixed.csv") == document


@pytest.mark.parametrize("create_options", [
    lambda: CsvKeyValueHeaderOptions.until_marker(""),
    lambda: CsvKeyValueHeaderOptions.until_marker(" "),
    lambda: CsvKeyValueHeaderOptions.until_marker("a\nb"),
    lambda: CsvKeyValueHeaderOptions.fixed_rows(-1),
    lambda: CsvKeyValueHeaderOptions.fixed_rows(True),
    lambda: CsvKeyValueHeaderOptions.fixed_rows("2"),
    lambda: CsvKeyValueHeaderOptions.fixed_rows(1, separator=""),
    lambda: CsvKeyValueHeaderOptions.fixed_rows(1).as_text(prefix="a\nb"),
])
def test_csv_rejects_ambiguous_options(create_options):
    with pytest.raises(ConfigurationError):
        create_options()


def test_csv_preserves_leading_zero_and_configurable_empty_metadata(tmp_path: Path):
    options = CsvKeyValueHeaderOptions.until_blank_line(empty_as_none=False)
    repository = csv_repository(tmp_path, options)
    document = RowsDocument[dict[str, Any], Measurement](
        metadata={"device": "001", "note": ""}, rows=[],
    )
    repository.save_document("data.csv", document)
    assert repository.load_document("data.csv").metadata == document.metadata
    default = csv_repository(tmp_path, CsvKeyValueHeaderOptions.until_blank_line())
    assert default.load_document("data.csv").metadata == {"device": "001", "note": None}


def test_csv_dict_body_and_headerless_table_can_be_used(tmp_path: Path):
    serializer = CsvSerializer(metadata=CsvKeyValueHeaderOptions.fixed_rows(1), read_options=CsvOptions(header=False, columns=('time', 'value')))
    repository = RowsRepository[dict[str, Any]](
        model=dict, base_directory=tmp_path, serializers_by_extension={".csv": serializer},
    )
    (tmp_path / "data.csv").write_text("version,4\n0,1.2\n1,1.5\n", encoding="utf-8")
    document = repository.load_document("data.csv")
    assert document.metadata == {"version": "4"}
    assert document.rows == [{"time": "0", "value": "1.2"}, {"time": "1", "value": "1.5"}]


@pytest.mark.parametrize("extension", ["csv", "jsonl"])
def test_repository_and_service_have_same_document_api(tmp_path: Path, extension: str):
    repository = RowsRepository(
        model=Measurement, base_directory=tmp_path,
        serializers_by_extension={
            ".csv": CsvSerializer(metadata=CsvKeyValueHeaderOptions.until_blank_line()), ".jsonl": JsonlSerializer(),
        },
    )
    service = RowsFileService(repository=repository, path=f"data.{extension}")
    document = RowsDocument(
        metadata=Metadata(version=4, device="A001"), rows=[Measurement(time=0, value=1.2)],
    )
    service.save_document(document)
    assert service.load_document(metadata_model=Metadata) == document
    with pytest.raises(FileExistsError):
        service.save_document(document)
    service.save_document(document, overwrite=True)
    assert service.load() == document.rows


def test_normal_csv_does_not_acquire_metadata_implicitly(tmp_path: Path):
    repository = RowsRepository(model=Measurement, base_directory=tmp_path)
    repository.save("normal.csv", [Measurement(time=0, value=1.2)])
    original = (tmp_path / "normal.csv").read_bytes()
    document = repository.load_document("normal.csv")
    assert document.metadata == {}
    repository.save_document("copy.csv", document)
    assert (tmp_path / "copy.csv").read_bytes() == original
    with pytest.raises(ConfigurationError, match="metadata"):
        repository.save_document("bad.csv", RowsDocument(metadata={"version": 4}, rows=document.rows))

    serializer = CsvSerializer(options=CsvOptions(
        delimiter=" ", column_prefix="# ", comment_prefixes=("#",), header_line="# time value",
    ))
    source = RowsRepository(
        model=Measurement, base_directory=tmp_path, serializers_by_extension={".csv": serializer},
    )
    (tmp_path / "commented.csv").write_text("#\n# description\n#\n#   time    value  # saved table\n0 1.2\n", encoding="utf-8")
    assert source.load_document("commented.csv") == document
    (tmp_path / "compact.csv").write_text("# description\n#time value # comment, with extra columns\n0 1.2\n", encoding="utf-8")
    assert source.load_document("compact.csv") == document
    repository.save_document("normalized.csv", source.load_document("commented.csv"))
    assert repository.load_document("normalized.csv") == document


def test_save_without_metadata_cannot_erase_configured_csv_metadata(tmp_path: Path):
    repository = csv_repository(tmp_path, CsvKeyValueHeaderOptions.until_blank_line())
    document = RowsDocument(metadata=Metadata(version=4, device="A001"), rows=[Measurement(time=0, value=1)])
    repository.save_document("data.csv", document)
    before = (tmp_path / "data.csv").read_bytes()
    with pytest.raises(ConfigurationError, match="save_document"):
        repository.save("data.csv", document.rows, overwrite=True)
    assert (tmp_path / "data.csv").read_bytes() == before


@pytest.mark.parametrize("metadata", [{"version": 4}, {"version": 4, "device": [1, 2]}, {"version": 4, " ": 1}])
def test_invalid_metadata_does_not_replace_existing_file(tmp_path: Path, metadata: dict[str, Any]):
    repository = csv_repository(tmp_path, CsvKeyValueHeaderOptions.fixed_rows(2))
    repository.save_document("data.csv", RowsDocument(metadata={"version": 4, "device": "001"}, rows=[]))
    before = (tmp_path / "data.csv").read_bytes()
    with pytest.raises(SerializationError):
        repository.save_document("data.csv", RowsDocument(metadata=metadata, rows=[]), overwrite=True)
    assert (tmp_path / "data.csv").read_bytes() == before


@pytest.mark.parametrize("extension", ["csv", "jsonl"])
def test_metadata_model_validation_and_alias_are_not_manual_casts(tmp_path: Path, extension: str):
    class AliasedMetadata(BaseModel):
        model_config = ConfigDict(populate_by_name=True)
        version: int = Field(alias="format_version")

    repository = RowsRepository(
        model=Measurement, base_directory=tmp_path,
        serializers_by_extension={
            ".csv": CsvSerializer(metadata=CsvKeyValueHeaderOptions.until_blank_line()), ".jsonl": JsonlSerializer(),
        },
    )
    document = RowsDocument[AliasedMetadata, Measurement](metadata=AliasedMetadata(version=4), rows=[])
    repository.save_document(f"data.{extension}", document, metadata_by_alias=True)
    assert repository.load_document(f"data.{extension}", metadata_model=AliasedMetadata) == document
    assert "format_version" in repository.load_document(f"data.{extension}").metadata
    with pytest.raises(SerializationError, match="メタ情報のモデル検証"):
        repository.load_document(f"data.{extension}", metadata_model=Metadata)


def test_jsonl_legacy_files_and_new_metadata_have_separate_format_versions(tmp_path: Path):
    repository = RowsRepository(model=Measurement, base_directory=tmp_path)
    rows = [Measurement(time=0, value=1.2)]
    repository.save("legacy.jsonl", rows)
    assert repository.load_document("legacy.jsonl").metadata == {}
    legacy_header = json.loads((tmp_path / "legacy.jsonl").read_text().splitlines()[0])
    assert legacy_header["__meta__"]["schema_version"] == 1
    assert "metadata" not in legacy_header

    repository.save_document("current.jsonl", RowsDocument(metadata={"version": 4}, rows=rows))
    header = json.loads((tmp_path / "current.jsonl").read_text().splitlines()[0])
    assert header["__meta__"]["schema_version"] == 2
    assert header["metadata"] == {"version": 4}
    assert repository.load("current.jsonl") == rows


def test_jsonl_append_preserves_metadata_and_mixed_model_identity(tmp_path: Path):
    class Event(BaseModel):
        message: str

    repository = RowsRepository[Measurement | Event](model=(Measurement, Event), base_directory=tmp_path)
    document = RowsDocument[Metadata, Measurement | Event](
        metadata=Metadata(version=4, device="A001"), rows=[Measurement(time=0, value=1.2)],
    )
    repository.save_document("mixed.jsonl", document)
    first_line = (tmp_path / "mixed.jsonl").read_bytes().splitlines()[0]
    repository.append_jsonl("mixed.jsonl", [Event(message="checked")])
    assert (tmp_path / "mixed.jsonl").read_bytes().splitlines()[0] == first_line
    restored = repository.load_document("mixed.jsonl", metadata_model=Metadata)
    assert restored.metadata == document.metadata
    assert restored.rows == [*document.rows, Event(message="checked")]
    assert type(restored.rows[1]) is Event

    raw = RowsRepository(model=dict, base_directory=tmp_path)
    model_tags: dict[type[Measurement | Event], str] = {Measurement: "measurement", Event: "event"}
    versioned = VersionedRowsRepository.for_models(
        repository=raw, converter=VersionConverter(current_version=4, upcasts={}, downcasts={}),
        metadata_model=Metadata, model_tags=model_tags,
    )
    raw.save_document("raw.jsonl", RowsDocument(
        metadata=restored.metadata.model_dump(),
        rows=[{"type": "measurement", "time": 0, "value": 1.2}, {"type": "event", "message": "checked"}],
    ))
    assert versioned.load("raw.jsonl") == restored
    versioned.save("versioned.jsonl", restored)
    assert versioned.load("versioned.jsonl") == restored
    header = json.loads((tmp_path / "versioned.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert header["__meta__"]["models"] == ["event", "measurement"]
    assert header["metadata"] == restored.metadata.model_dump()
    with pytest.raises(SerializationError):
        raw.load_document("versioned.jsonl")


@pytest.mark.parametrize("bad_metadata", [None, [], "invalid", 1])
def test_jsonl_rejects_invalid_metadata_before_append(tmp_path: Path, bad_metadata: object):
    repository = RowsRepository(model=Measurement, base_directory=tmp_path)
    repository.save_document("data.jsonl", RowsDocument(metadata={}, rows=[Measurement(time=0, value=1)]))
    lines = (tmp_path / "data.jsonl").read_text().splitlines()
    header = json.loads(lines[0])
    header["metadata"] = bad_metadata
    (tmp_path / "data.jsonl").write_text(json.dumps(header) + "\n" + lines[1] + "\n")
    before = (tmp_path / "data.jsonl").read_bytes()
    with pytest.raises(SerializationError):
        repository.load_document("data.jsonl")
    with pytest.raises(SerializationError):
        repository.append_jsonl("data.jsonl", [Measurement(time=1, value=2)])
    assert (tmp_path / "data.jsonl").read_bytes() == before


def test_external_jsonl_has_empty_user_metadata_and_cannot_save_metadata(tmp_path: Path):
    repository = RowsRepository(
        model=Measurement, base_directory=tmp_path,
        serializers_by_extension={".jsonl": JsonlSerializer(load_options=JSONLLoadOptions(metadata="absent"))},
    )
    (tmp_path / "external.jsonl").write_text('{"time": 0, "value": 1.2}\n', encoding="utf-8")
    document = repository.load_document("external.jsonl")
    assert document.metadata == {}
    assert document.rows == [Measurement(time=0, value=1.2)]
    with pytest.raises(ConfigurationError, match="required"):
        repository.save_document("output.jsonl", document)
