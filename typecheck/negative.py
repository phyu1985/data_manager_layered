""" 3つのreportArgumentTypeが必要。通常のPyright対象からは除外する。
"""
from pathlib import Path
from pydantic import BaseModel
from DataManager import ObjectRepository, RowsRepository


class User(BaseModel):
    id: str


class Event(BaseModel):
    message: str


def rejected(event: Event):
    objects = ObjectRepository(model=User, base_directory=Path("data"))
    objects.save("user.json", event)
    rows = RowsRepository(model=User, base_directory=Path("data"))
    rows.save("users.jsonl", [event])
    rows.append_jsonl("users.jsonl", [event])
