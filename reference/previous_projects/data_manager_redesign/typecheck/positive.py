""" 実行用ではなく、Pylanceと同系のPyrightで型推論を検証する例。
"""
from pathlib import Path
from typing import Any, assert_type

from pydantic import BaseModel
from data_manager import (
    HeaderReader, ObjectFileService, ObjectRepository, RowsFileService, RowsRepository,
    WaveformArray, WaveformFileService, WaveformObject, WaveformOptions, WaveformRepository,
)


class User(BaseModel):
    id: str
    name: str = ""


class Event(BaseModel):
    message: str


def examples(user: User, event: Event):
    objects = ObjectRepository(model=User, base_directory=Path("data"))
    assert_type(objects.load("user.json"), User)
    assert_type(objects.load("user.yaml"), User)
    assert_type(objects.load("user.txt"), User)
    objects.save("user.json", user)
    object_service = ObjectFileService(repository=objects, path="user.json")
    assert_type(object_service.load(), User)
    object_service.save(user)

    single = RowsRepository(model=User, base_directory=Path("data"))
    assert_type(single.load("users.jsonl"), list[User])
    assert_type(single.load("users.csv"), list[User])
    single.save("users.jsonl", [user])

    mixed = RowsRepository[User | Event](model=(User, Event), base_directory=Path("data"))
    rows = mixed.load("events.jsonl")
    assert_type(rows, list[User | Event])
    mixed.save("events.jsonl", [user, event])
    rows_service = RowsFileService(repository=mixed, path="events.jsonl")
    assert_type(rows_service.load(), list[User | Event])
    rows_service.append([user, event])
    for row in rows:
        if isinstance(row, User):
            assert_type(row, User)
        else:
            assert_type(row, Event)

    dictionaries = ObjectRepository[dict[str, Any]](model=dict, base_directory=Path("data"))
    assert_type(dictionaries.load("settings.json"), dict[str, Any])
    dictionary_rows = RowsRepository[dict[str, Any]](model=dict, base_directory=Path("data"))
    assert_type(dictionary_rows.load("rows.jsonl"), list[dict[str, Any]])


def waveform_examples(header_reader: HeaderReader):
    repository = WaveformRepository(
        base_directory=Path("data"), options=WaveformOptions(header_reader=header_reader),
    )
    assert_type(repository.load("wave.bin"), WaveformObject)
    assert_type(repository.peek("wave.bin"), WaveformArray)
    waveform_service = WaveformFileService(repository=repository, path="wave.bin")
    assert_type(waveform_service.load(), WaveformObject)
    assert_type(waveform_service.peek(), WaveformArray)
