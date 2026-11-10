""" V0のブロック形式とV1のJSONLを、メタと行モデルを揃えて相互変換する。
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


class CaptureMetadata(BaseModel):
    """ 現在版のメタ。旧版のdeviceをinstrumentとして使う。
    """

    version: int
    instrument: str


class Reading(BaseModel):
    """ 現在版の測定行。
    """

    time: int
    value: float


class Note(BaseModel):
    """ 測定行と混在する注記。
    """

    time: int
    text: str


def upcast_reading(document: dict[str, Any]) -> dict[str, Any]:
    """ メタと本文を一緒に現在版へ変える。
    """
    return {
        **document, "metadata": {"instrument": document["metadata"]["device"]},
        "rows": [{"time": row["time"], "value": row["reading"]} for row in document["rows"]],
    }


def downcast_reading(document: dict[str, Any]) -> dict[str, Any]:
    """ 旧版の保存項目だけを返す。版キーは対応表から共通処理が記録する。
    """
    return {
        **document, "metadata": {"device": document["metadata"]["instrument"]},
        "rows": [{"time": row["time"], "reading": row["value"]} for row in document["rows"]],
    }


def sample_single_model(directory: Path):
    """ ver/deviceの旧ブロックを読み、JSONLと旧ブロックへ出し分ける。
    """
    block = BlockRowsSerializer(options=BlockRowsOptions(
        rows=(BlockRow.root("time"), BlockRow.root("reading")),
        metadata=CsvHeaderOptions(fields=(CsvHeaderField.separated("ver"), CsvHeaderField.separated("device"))),
    ))
    raw = RowsRepository(
        model=dict, base_directory=directory,
        serializers_by_extension={".blocks": block, ".jsonl": JsonlSerializer()},
    )
    repository = VersionedRowsRepository.for_models(
        repository=raw,
        converter=VersionConverter(current_version=1, upcasts={0: upcast_reading}, downcasts={1: downcast_reading}),
        metadata_model=CaptureMetadata, model_tags={Reading: "reading"},
        metadata_version_fields={0: "ver"},
    )
    source = directory / "source.blocks"
    source.write_text("ver: 0\ndevice: A001\n#time\n#reading\n#\n0\n1.2\n#\n", encoding="utf-8")
    original = source.read_bytes()

    document = repository.load("source.blocks")
    assert document == RowsDocument(CaptureMetadata(version=1, instrument="A001"), [Reading(time=0, value=1.2)])
    FileService(repository=repository, path="current.jsonl").save(document)
    legacy = FileService(repository=repository.for_version(0), path="export.blocks")
    legacy.save(document)
    assert legacy.load() == document
    assert repository.load("current.jsonl") == document
    assert raw.load_document("export.blocks").metadata == {"ver": "0", "device": "A001"}
    header = json.loads((directory / "current.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert header["__meta__"]["models"] == ["reading"]
    assert header["metadata"] == {"version": 1, "instrument": "A001"}
    assert source.read_bytes() == original


def sample_unversioned_block(directory: Path):
    """ 版項目のないV0へ出力しても、不要なversionキーを追加しない。
    """
    block = BlockRowsSerializer(options=BlockRowsOptions(
        rows=(BlockRow.root("time"), BlockRow.root("reading")),
        metadata=CsvHeaderOptions(fields=(CsvHeaderField.separated("device"),)),
    ))
    raw = RowsRepository(model=dict, base_directory=directory, serializers_by_extension={".blocks": block})
    repository = VersionedRowsRepository.for_models(
        repository=raw,
        converter=VersionConverter(current_version=1, upcasts={0: upcast_reading}, downcasts={1: downcast_reading}),
        metadata_model=CaptureMetadata, model_tags={Reading: "reading"},
        metadata_version_fields={0: None},
    )
    document = RowsDocument(CaptureMetadata(version=1, instrument="A001"), [Reading(time=0, value=1.2)])
    repository.for_version(0).save("unversioned.blocks", document)
    assert repository.load("unversioned.blocks") == document
    assert raw.load_document("unversioned.blocks").metadata == {"device": "A001"}


def upcast_mixed(document: dict[str, Any]) -> dict[str, Any]:
    """ 旧kindを現在のtypeへ移し、現在のモデルに必要な値を残す。
    """
    rows: list[dict[str, Any]] = []
    for row in document["rows"]:
        if row["kind"] == "reading":
            rows.append({"type": "reading", "time": row["time"], "value": row["reading"]})
        elif row["kind"] == "note":
            rows.append({"type": "note", "time": row["time"], "text": row["message"]})
        else:
            raise ValueError("未知のkindです")
    return {**document, "metadata": {"instrument": document["metadata"]["device"]}, "rows": rows}


def downcast_mixed(document: dict[str, Any]) -> dict[str, Any]:
    """ 自動付与されたtypeもcastし、旧ブロックの固定列へ戻す。
    """
    rows: list[dict[str, Any]] = []
    for row in document["rows"]:
        if row["type"] == "reading":
            rows.append({"kind": "reading", "time": row["time"], "reading": row["value"], "message": None})
        elif row["type"] == "note":
            rows.append({"kind": "note", "time": row["time"], "reading": None, "message": row["text"]})
        else:
            raise ValueError("未知のtypeです")
    return {**document, "metadata": {"device": document["metadata"]["instrument"]}, "rows": rows}


def sample_mixed_models(directory: Path):
    """ 一つの登録表からJSONLのmodelsと各行のtype・復元先を決める。
    """
    block = BlockRowsSerializer(options=BlockRowsOptions(
        rows=(BlockRow.root("kind", "time"), BlockRow.root("reading", "message")),
        metadata=CsvHeaderOptions(fields=(CsvHeaderField.separated("ver"), CsvHeaderField.separated("device"))),
    ))
    raw = RowsRepository(
        model=dict, base_directory=directory,
        serializers_by_extension={".blocks": block, ".jsonl": JsonlSerializer()},
    )
    model_tags: dict[type[Reading | Note], str] = {Reading: "reading", Note: "note"}
    repository = VersionedRowsRepository.for_models(
        repository=raw,
        converter=VersionConverter(current_version=1, upcasts={0: upcast_mixed}, downcasts={1: downcast_mixed}),
        metadata_model=CaptureMetadata, model_tags=model_tags, metadata_version_fields={0: "ver"},
    )
    raw.save_document("mixed_source.blocks", RowsDocument(
        metadata={"ver": 0, "device": "A001"},
        rows=[
            {"kind": "reading", "time": 0, "reading": 1.2, "message": None},
            {"kind": "note", "time": 1, "reading": None, "message": "checked"},
        ],
    ))
    document = repository.load("mixed_source.blocks")
    assert document.rows == [Reading(time=0, value=1.2), Note(time=1, text="checked")]
    repository.save("mixed_current.jsonl", document)
    restored = repository.load("mixed_current.jsonl")
    assert restored == document
    assert type(restored.rows[0]) is Reading and type(restored.rows[1]) is Note
    repository.for_version(0).save("mixed_export.blocks", restored)
    assert repository.load("mixed_export.blocks") == document
    lines = (directory / "mixed_current.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["__meta__"]["models"] == ["note", "reading"]
    assert json.loads(lines[1])["type"] == "reading"
    assert json.loads(lines[2])["type"] == "note"


def main():
    parser = argparse.ArgumentParser(description="V0ブロックとV1 JSONLの版変換・モデル復元")
    parser.add_argument("output", type=Path)
    directory = parser.parse_args().output
    directory.mkdir(parents=True, exist_ok=False)
    sample_single_model(directory)
    sample_unversioned_block(directory)
    sample_mixed_models(directory)
    print(f"Versioned block rows: {directory.resolve()}")


if __name__ == "__main__":
    main()
