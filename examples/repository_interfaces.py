""" 版の有無によらない行・文書の操作と、形式専用設定を確認する。
"""
import argparse
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from DataManager import (
    ConfigurationError, FileService, JSONLDumpOptions, JSONLLoadOptions, JsonlSerializer,
    JsonSerializer, KvSerializer, ObjectRepository, RowsDocument, RowsDocumentRepository,
    RowsFileService, RowsRepository, SerializationError, VersionConverter,
    VersionedObjectRepository, VersionedRowsRepository, YamlRowsDumpOptions,
    YamlRowsSerializer, YamlSerializer,
)
from DataManager.model_conversion import ModelBinding


class Reading(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: int


class Metadata(BaseModel):
    version: int
    label: str = "sample"


def sample_rows(directory: Path):
    """ 行一覧と文書を同じ名前で扱い、tupleもServiceから保存する。
    """
    plain = RowsRepository(model=Reading, base_directory=directory)
    plain_file = FileService(repository=plain, path="plain.jsonl")
    rows = (Reading(value=1), Reading(value=2))
    plain_file.save(rows)
    assert plain_file.load() == list(rows)

    versioned = VersionedRowsRepository.for_models(
        repository=RowsRepository(model=dict, base_directory=directory),
        converter=VersionConverter(current_version=1, upcasts={}, downcasts={}),
        metadata_model=Metadata, model_tags={Reading: "reading"},
    )
    file = FileService(repository=versioned, path="versioned_rows.jsonl")
    file.save(rows)
    assert file.load() == list(rows)
    assert versioned.load_document("versioned_rows.jsonl").metadata == Metadata(version=1)

    document_file = FileService(
        repository=RowsDocumentRepository(repository=versioned, metadata_model=Metadata),
        path="versioned_document.jsonl",
    )
    document = RowsDocument(metadata=Metadata(version=1, label="keep"), rows=list(rows))
    document_file.save(document)
    assert document_file.load() == document
    service = RowsFileService(repository=versioned, path="versioned_document.jsonl")
    assert service.load() == document.rows
    assert service.load_document(metadata_model=Metadata) == document
    assert service.load_document().metadata == {"version": 1, "label": "keep"}
    service.save_document(document, overwrite=True)
    try:
        service.append([Reading(value=3)])
    except ConfigurationError:
        pass
    else:
        raise AssertionError("VersionedRowsは追記に対応しません")


def sample_custom_codec(directory: Path):
    """ メタの件数と本文が関連するcodecでも、文書全体で読み書きする。
    """
    class CountMetadata(BaseModel):
        version: int
        count: int

    def decode(value: dict[str, Any]) -> RowsDocument[CountMetadata, Reading]:
        metadata = CountMetadata.model_validate(value["metadata"])
        rows = [Reading.model_validate(row) for row in value["rows"]]
        if metadata.count != len(rows):
            raise ValueError("メタの件数と本文が一致しません")
        return RowsDocument(metadata=metadata, rows=rows)

    def encode(document: RowsDocument[CountMetadata, Reading]) -> dict[str, Any]:
        return {
            "version": 1, "metadata": document.metadata.model_dump(),
            "rows": [row.model_dump() for row in document.rows],
        }

    repository = VersionedRowsRepository(
        repository=RowsRepository(model=dict, base_directory=directory),
        converter=VersionConverter(current_version=1, upcasts={}, downcasts={}),
        decode_current=decode, encode_current=encode, metadata_model=CountMetadata,
    )
    file = RowsFileService(repository=repository, path="custom_document.jsonl")
    document = RowsDocument(metadata=CountMetadata(version=1, count=1), rows=[Reading(value=9)])
    file.save_document(document)
    assert file.load_document(metadata_model=CountMetadata) == document
    file.save_document(file.load_document(), overwrite=True)
    assert repository.load_document("custom_document.jsonl") == document

    try:
        repository.save("missing_metadata.jsonl", document.rows)
    except SerializationError:
        pass
    else:
        raise AssertionError("必須メタを省略して保存してはいけません")
    assert not (directory / "missing_metadata.jsonl").exists()


def sample_object(directory: Path):
    """ 現在モデル一つを登録し、旧キーのJSONを読み戻す。
    """
    raw = ObjectRepository(model=dict, base_directory=directory)
    raw.save("old.json", {"version": 0, "old_value": 7})
    repository = VersionedObjectRepository.for_model(
        repository=raw, model=Reading,
        converter=VersionConverter(
            current_version=1,
            upcasts={0: lambda value: {"value": value["old_value"]}},
            downcasts={1: lambda value: {"old_value": value["value"]}},
        ),
    )
    value = repository.load("old.json")
    assert value == Reading(value=7)
    FileService(repository=repository, path="new.json").save(value)
    repository.for_version(0).save("export_old.json", value)
    assert raw.load("export_old.json") == {"version": 0, "old_value": 7}
    assert repository.load("new.json") == value


def sample_format_options(directory: Path):
    """ JSONLのメタにも文字設定を適用し、YAMLの字下げを明示する。
    """
    binding: ModelBinding[dict[str, Any]] = ModelBinding(dict)
    jsonl = JsonlSerializer(dump_options=JSONLDumpOptions(ensure_ascii=True))
    text = jsonl.dumps_document([{"name": "本文"}], binding, metadata={"label": "メタ"})
    assert text.isascii()
    assert len(text.splitlines()) == 2

    external = JsonlSerializer(load_options=JSONLLoadOptions(metadata="absent"))
    assert external.loads('{"value": 1}\n', binding) == [{"value": 1}]
    try:
        external.dumps([{"value": 1}], binding)
    except ConfigurationError:
        pass
    else:
        raise AssertionError("読取専用設定で保存してはいけません")

    yaml = YamlRowsSerializer(dump_options=YamlRowsDumpOptions(
        indent_mapping=4, indent_sequence=6, indent_offset=2,
    ))
    records = [{"name": "A", "values": {"first": 1}}]
    text = yaml.dumps(records, binding)
    assert text.startswith("  -")
    assert yaml.loads(text, binding) == records
    (directory / "indented_rows.yaml").write_text(text, encoding="utf-8")


def sample_validation_errors():
    """ Object形式でも、Pydantic例外を原因に持つSerializationErrorを受け取る。
    """
    binding = ModelBinding(Reading)
    for serializer, text in (
        (JsonSerializer(), '{"value": "invalid"}'),
        (YamlSerializer(), 'value: invalid'),
        (KvSerializer(), 'value: "invalid"'),
    ):
        try:
            serializer.loads(text, binding)
        except SerializationError as error:
            assert isinstance(error.__cause__, ValidationError)
        else:
            raise AssertionError("モデル検証の失敗を検出できませんでした")


def main():
    parser = argparse.ArgumentParser(description="Repository・Serviceの共通I/F")
    parser.add_argument("output", type=Path)
    directory = parser.parse_args().output
    directory.mkdir(parents=True, exist_ok=False)
    sample_rows(directory)
    sample_custom_codec(directory)
    sample_object(directory)
    sample_format_options(directory)
    sample_validation_errors()
    print("Repository interfaces:", directory.resolve())


if __name__ == "__main__":
    main()
