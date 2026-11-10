""" V0のconfig 0とV1のversionを、現在のConfig.versionへ揃える例。
"""
import argparse
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from DataManager import (
    BlockRow, BlockRowsOptions, BlockRowsSerializer, CsvHeaderField, CsvHeaderOptions,
    FileService, JsonlSerializer, RowsDocument, RowsRepository, VersionConverter, VersionedRowsRepository,
)


class Config(BaseModel):
    """ 現在版のメタ。古いconfigというフィールドは持たせない。
    """

    version: int
    threshold: float


class Reading(BaseModel):
    """ 本文の測定行。この例では版をまたいでも構造を変えない。
    """

    time: int
    value: float


def upcast_config(document: dict[str, Any]) -> dict[str, Any]:
    """ 内部の版はversionで参照し、業務項目limitだけをthresholdへ変える。
    """
    assert document["version"] == 0
    return {**document, "metadata": {"threshold": document["metadata"]["limit"]}}


def downcast_config(document: dict[str, Any]) -> dict[str, Any]:
    """ 業務項目を旧名へ戻す。ファイルの版キーの書換えは共通処理へ任せる。
    """
    assert document["version"] == 1
    return {**document, "metadata": {"limit": document["metadata"]["threshold"]}}


def create_repository(directory: Path) -> VersionedRowsRepository[RowsDocument[Config, Reading]]:
    """ 旧ファイルの文法、内部の版、保存時の版キー、現在モデルを接続する。
    """
    legacy = BlockRowsSerializer(options=BlockRowsOptions(
        rows=(BlockRow.root("time", "value"),),
        metadata=CsvHeaderOptions(fields=(
            CsvHeaderField.whitespace("config"),
            CsvHeaderField.separated("limit"),
        )),
    ))
    raw = RowsRepository(
        model=dict, base_directory=directory,
        serializers_by_extension={".blocks": legacy, ".jsonl": JsonlSerializer()},
    )
    converter = VersionConverter(
        current_version=1, version_field="version",
        upcasts={0: upcast_config}, downcasts={1: downcast_config},
    )
    return VersionedRowsRepository.for_models(
        repository=raw, converter=converter,
        metadata_model=Config, model_tags={Reading: "reading"},
        metadata_version_fields={0: "config", 1: "version"},
    )


def sample_version_key_names(directory: Path):
    """ V0読込→Config復元→V1保存→V0別名保存と再読を確認する。
    """
    directory.mkdir(parents=True, exist_ok=False)
    source = directory / "source_v0.blocks"
    source.write_text("config 0\nlimit: 2.5\n#time;value\n#\n0;1.2\n#\n", encoding="utf-8")
    original = source.read_bytes()
    repository = create_repository(directory)

    document = FileService(repository=repository, path="source_v0.blocks").load()
    assert document.metadata == Config(version=1, threshold=2.5)
    assert document.rows == [Reading(time=0, value=1.2)]

    FileService(repository=repository, path="current_v1.jsonl").save(document)
    legacy = FileService(repository=repository.for_version(0), path="export_v0.blocks")
    legacy.save(document)
    assert legacy.load() == document
    assert repository.load("current_v1.jsonl") == document
    assert source.read_bytes() == original

    header = json.loads((directory / "current_v1.jsonl").read_text(encoding="utf-8").splitlines()[0])
    exported = (directory / "export_v0.blocks").read_text(encoding="utf-8").splitlines()
    assert header["metadata"] == {"version": 1, "threshold": 2.5}
    assert header["__meta__"]["models"] == ["reading"]
    assert exported[:2] == ["config 0", "limit: 2.5"]

    print("V0 input: config 0 / limit: 2.5")
    print("Current Config:", document.metadata.model_dump())
    print("V1 JSONL metadata:", header["metadata"])
    print("V0 export:", " / ".join(exported[:2]))
    print("Output:", directory.resolve())


def main():
    parser = argparse.ArgumentParser(description="V0のconfigとV1のversionの対応")
    parser.add_argument("output", type=Path)
    sample_version_key_names(parser.parse_args().output)


if __name__ == "__main__":
    main()
