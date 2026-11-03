""" 本文とメタの型を、Repository・固定ファイルサービスの両方で推論できる。
"""
from pathlib import Path

from pydantic import BaseModel

from DataManager import FileService, RowsDocument, RowsDocumentRepository, RowsRepository


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
