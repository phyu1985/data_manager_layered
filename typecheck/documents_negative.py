""" 本文の型違いと、辞書をモデルだと思って使う誤りの2件を検出する。
"""
from pathlib import Path

from pydantic import BaseModel

from DataManager import RowsDocument, RowsRepository
from typecheck.documents_positive import Metadata, Measurement


class Event(BaseModel):
    message: str


def require_metadata(value: Metadata) -> int:
    """ 型が復元されていない辞書を渡せないことを確認するための受取先。
    """
    return value.version


def rejected(directory: Path):
    """ キャストで誤りを隠さず、型チェックで検出させる。
    """
    repository = RowsRepository(model=Measurement, base_directory=directory)
    wrong_document = RowsDocument(metadata=Metadata(version=4), rows=[Event(message="wrong")])
    repository.save_document("wrong.jsonl", wrong_document)
    dictionary_document = repository.load_document("data.jsonl")
    require_metadata(dictionary_document.metadata)
