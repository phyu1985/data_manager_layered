""" 版変換の手前が辞書でも、利用側の戻り値は指定型になることを確認する。
"""
from pathlib import Path
from typing import Any, assert_type

from pydantic import BaseModel

from DataManager import ObjectRepository, VersionConverter, VersionedObjectService


class Settings(BaseModel):
    threshold: float


def decode_current(value: dict[str, Any]) -> Settings:
    return Settings.model_validate(value)


def encode_current(value: Settings) -> dict[str, Any]:
    return {"version": 1, **value.model_dump(mode="json")}


def verify_types(directory: Path):
    service = VersionedObjectService(
        repository=ObjectRepository(model=dict, base_directory=directory),
        converter=VersionConverter(current_version=1, upcasts={}, downcasts={}),
        decode_current=decode_current, encode_current=encode_current,
    )
    assert_type(service.load("settings.yaml"), Settings)
    service.save("new.yaml", Settings(threshold=1))
