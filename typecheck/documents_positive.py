""" 本文とメタの型を、Repository・固定ファイルサービスの両方で推論できる。
"""
from pathlib import Path
from typing import assert_type

from pydantic import BaseModel

from DataManager import FileService, ObjectRepository, RowsDocument, RowsDocumentRepository, RowsRepository, TwoTableCsvSerializer


class Metadata(BaseModel):
    version: int


class Measurement(BaseModel):
    value: float


def accepted(directory: Path):
    """ 呼出側でcastをせず、復元先を指定した型を使えることを確認する。
    """
    repository = RowsRepository(model=Measurement, base_directory=directory)
    document: RowsDocument[Metadata, Measurement] = repository.load_document(
        "data.jsonl", metadata_model=Metadata,
    )
    value: int = document.metadata.version
    rows: list[Measurement] = document.rows
    repository.save_document("copy.jsonl", RowsDocument(metadata=Metadata(version=value), rows=rows))
    service = FileService(repository=RowsDocumentRepository(repository=repository, metadata_model=Metadata), path="data.jsonl")
    restored: RowsDocument[Metadata, Measurement] = service.load()
    service.save(restored, overwrite=True)
    service.save_as("document-copy.jsonl", restored)

def accepted_two_tables(directory: Path, serializer: TwoTableCsvSerializer):
    """ 二段の行型も、文書モデルの注釈からcastなしで推論できる。
    """
    class Upper(BaseModel):
        value: float

    class Lower(BaseModel):
        position: int

    class Document(BaseModel):
        metadata: dict[str, int]
        upper: list[Upper]
        lower: list[Lower]

    repository = ObjectRepository(
        model=Document, base_directory=directory, serializers_by_extension={".csv": serializer},
    )
    service = FileService(repository=repository, path="tables.csv")
    document = service.load()
    assert_type(document, Document)
    assert_type(document.upper, list[Upper])
    assert_type(document.lower, list[Lower])
    service.save_as("tables-copy.csv", document)

