""" サービス経由でも、誤った入力型のreportArgumentTypeを3件検出する例。
"""
from pathlib import Path

from pydantic import BaseModel

from DataManager import ObjectFileService, ObjectRepository, RowsFileService, RowsRepository


class User(BaseModel):
    id: str


class Event(BaseModel):
    message: str


def rejected(event: Event):
    object_service = ObjectFileService(
        repository=ObjectRepository(model=User, base_directory=Path("data")), path="user.json",
    )
    object_service.save(event)

    rows_service = RowsFileService(
        repository=RowsRepository(model=User, base_directory=Path("data")), path="users.jsonl",
    )
    rows_service.save([event])
    rows_service.append([event])
