""" 版変換の手前が辞書でも、利用側の戻り値は指定型になることを確認する。
"""
from pathlib import Path
from typing import Any, assert_type

from pydantic import BaseModel

from examples.number_count_csv import (
    NumberModel, CountModel, TableMetadata, create_repository as create_number_count_repository,
)

from DataManager import (
    FileService, ObjectRepository, RowsDocument, RowsRepository, VersionConverter,
    RowsDocumentRepository, RowsFileService, VersionedObjectRepository, VersionedRowsRepository,
)


class Settings(BaseModel):
    threshold: float


def decode_current(value: dict[str, Any]) -> Settings:
    return Settings.model_validate(value)


def encode_current(value: Settings) -> dict[str, Any]:
    return {"version": 1, **value.model_dump(mode="json")}


def verify_types(directory: Path):
    repository = VersionedObjectRepository(
        repository=ObjectRepository(model=dict, base_directory=directory, template_directory=directory / "templates"),
        converter=VersionConverter(current_version=1, upcasts={}, downcasts={}),
        decode_current=decode_current, encode_current=encode_current,
        templates_by_version={1: {".yaml": "v1.yaml"}, 0: {".yaml": "v0.yaml"}},
    )
    file = FileService(repository=repository, path="settings.yaml")
    assert_type(file.load(), Settings)
    file.save_as("new.yaml", Settings(threshold=1))
    legacy = FileService(repository=repository.for_version(0), path="legacy.yaml")
    assert_type(legacy.load(), Settings)


def decode_rows(value: dict[str, Any]) -> RowsDocument[dict[str, Any], Settings]:
    return RowsDocument(metadata=value["metadata"], rows=[Settings.model_validate(row) for row in value["rows"]])


def encode_rows(value: RowsDocument[dict[str, Any], Settings]) -> dict[str, Any]:
    return {"version": 1, "metadata": value.metadata, "rows": [row.model_dump() for row in value.rows]}


def verify_rows_types(directory: Path):
    repository = VersionedRowsRepository(
        repository=RowsRepository(model=dict, base_directory=directory),
        converter=VersionConverter(current_version=1, upcasts={}, downcasts={}),
        decode_current=decode_rows, encode_current=encode_rows,
    )
    assert_type(repository.load("readings.jsonl"), list[Settings])
    file = FileService(repository=RowsDocumentRepository[dict[str, Any], Settings](repository=repository, metadata_model=dict), path="readings.jsonl")
    document = file.load()
    assert_type(document, RowsDocument[dict[str, Any], Settings])
    assert_type(document.rows[0], Settings)
    file.save_as("copy.jsonl", document)
    rows_file = FileService(repository=RowsRepository(model=Settings, base_directory=directory), path="rows.jsonl")
    assert_type(rows_file.load(), list[Settings])
    rows_file.save((Settings(threshold=1),))
    rows_file.save_as("tuple.jsonl", (Settings(threshold=2),))


class AnalysisMetadata(BaseModel):
    """ 現在版のメタの型。
    """

    version: int


class Note(BaseModel):
    """ 混在型の確認用。
    """

    message: str


def verify_registered_rows_types(directory: Path):
    model_tags: dict[type[Settings | Note], str] = {Settings: "settings", Note: "note"}
    repository = VersionedRowsRepository.for_models(
        repository=RowsRepository(model=dict, base_directory=directory),
        converter=VersionConverter(current_version=1, upcasts={}, downcasts={}),
        metadata_model=AnalysisMetadata, model_tags=model_tags,
        metadata_version_fields={0: None},
    )
    assert_type(repository.load("current.jsonl"), list[Settings | Note])
    rows_file = RowsFileService(repository=repository, path="current.jsonl")
    assert_type(rows_file.load(), list[Settings | Note])
    assert_type(rows_file.load_document(metadata_model=AnalysisMetadata), RowsDocument[AnalysisMetadata, Settings | Note])
    file = FileService(repository=RowsDocumentRepository(repository=repository, metadata_model=AnalysisMetadata), path="current.jsonl")
    assert_type(file.load(), RowsDocument[AnalysisMetadata, Settings | Note])
    assert_type(repository.for_version(0).load_document("old.txt"), RowsDocument[AnalysisMetadata, Settings | Note])
    file.save(RowsDocument(
        metadata=AnalysisMetadata(version=1), rows=[Settings(threshold=1), Note(message="checked")],
    ))


def verify_number_count_types(directory: Path):
    """ 実行例の混在モデルも、利用側でcastをせずに扱える。
    """
    repository = create_number_count_repository(directory)
    file = FileService(repository=RowsDocumentRepository(repository=repository, metadata_model=TableMetadata), path="current.jsonl")
    assert_type(file.load(), RowsDocument[TableMetadata, NumberModel | CountModel])
    legacy = FileService(repository=RowsDocumentRepository(repository=repository.for_version(0), metadata_model=TableMetadata), path="export.csv")
    assert_type(legacy.load(), RowsDocument[TableMetadata, NumberModel | CountModel])
