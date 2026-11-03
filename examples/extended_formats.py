""" 架空の旧形式から、現在モデル・標準KV/JSONL・必要ならDataFrameへつなぐ。
"""
import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from DataManager import (
    BlockRowsOptions, BlockRowsSerializer, CsvOptions, CsvSerializer, KvOptions, KvSerializer,
    FileReader, FileService, ObjectRepository, RowsDocument, RowsRepository, Storage, VersionConverter, VersionedRowsRepository,
)
from DataManager.serializers.sample_capture import CaptureCsvFileSerializer, CaptureSectionSerializer, PositionalCaptureReader

SAMPLES = Path(__file__).resolve().parents[1] / "sample_data" / "extended"


class Settings(BaseModel):
    """ コメントから抽出した値も通常の項目として受け取る。
    """

    saved_at: datetime
    version: int
    saved_path: str
    threshold: float
    gain: float
    label: str


class Measurement(BaseModel):
    """ 現在の処理で使う行。旧版のreadingという名前を持ち込まない。
    """

    time: int
    value: float


class Record(BaseModel):
    """ 複数行で一レコードとなる入力を、平坦なモデルで扱う。
    """

    name: str
    value: float
    unit: str
    status: str


def upcast(value: dict[str, Any]) -> dict[str, Any]:
    """ キャストは項目の意味の変更を担当し、空白やマーカーの解析は行わない。
    """
    return {**value, "rows": [{"time": row["time"], "value": row["reading"]} for row in value["rows"]]}


def downcast(value: dict[str, Any]) -> dict[str, Any]:
    return {**value, "rows": [{"time": row["time"], "reading": row["value"]} for row in value["rows"]]}


def upcast_capture(value: dict[str, Any]) -> dict[str, Any]:
    """ 架空の旧単位を換算する。モデル検証はキャスト連鎖の後に行う。
    """
    rows = [{"time": row["tick"], "value": float(row["reading"]) / 1000} for row in value["rows"]]
    return {**value, "rows": rows}


def decode(value: dict[str, Any]) -> RowsDocument[dict[str, Any], Measurement]:
    """ upcastの後で初めて現在モデルによる検証を行う。
    """
    return RowsDocument(metadata=value["metadata"], rows=[Measurement.model_validate(row) for row in value["rows"]])


def encode(document: RowsDocument[dict[str, Any], Measurement]) -> dict[str, Any]:
    return {"version": 1, "metadata": document.metadata, "rows": [row.model_dump() for row in document.rows]}


def run(output: Path, *, include_pandas: bool = False):
    """ 入力と出力の形式は別に選び、呼出側へ解析・版変換を散らさない。
    """
    output.mkdir(parents=True, exist_ok=False)
    if Storage.find(output) is None:
        Storage.initialize(output)

    legacy_kv = ObjectRepository(
        model=Settings, base_directory=SAMPLES,
        serializers_by_extension={".txt": KvSerializer(options=KvOptions(
            header_skip=1, header_keys=("saved_at", "version", "saved_path"),
        ))},
    )
    settings = legacy_kv.load("header_kv.txt")
    normalized = ObjectRepository(model=Settings, base_directory=output)
    normalized.save("settings.txt", settings)
    assert normalized.load("settings.txt") == settings
    assert not (output / "settings.txt").read_text(encoding="utf-8").startswith("#")

    csv = CsvSerializer(options=CsvOptions(
        boundary="blank_line", metadata_layout="values", metadata_keys=("version", "device"),
        columns=("time", "reading"),
    ))
    raw_repository = RowsRepository[dict[str, Any]](
        model=dict, base_directory=SAMPLES, serializers_by_extension={".csv": csv},
    )
    versioned_repository = VersionedRowsRepository(
        repository=raw_repository, converter=VersionConverter(current_version=1, upcasts={0: upcast}, downcasts={1: downcast}),
        decode_current=decode, encode_current=encode, read_version=lambda metadata: int(metadata.get("version", 0)),
    )
    current = FileReader(repository=versioned_repository, path="values_header.csv").load()
    # 入力先のRepositoryを流用せず、出力先の構成へ同じ版変換・モデル変換を接続する。
    destination_repository = VersionedRowsRepository(
        repository=RowsRepository[dict[str, Any]](model=dict, base_directory=output),
        converter=VersionConverter(current_version=1, upcasts={0: upcast}, downcasts={1: downcast}),
        decode_current=decode, encode_current=encode,
    )
    current_file = FileService(repository=destination_repository, path="current.jsonl")
    current_file.save(current)
    legacy_file = FileService(repository=destination_repository.for_version(0), path="legacy.jsonl")
    legacy_file.save(current)
    assert legacy_file.load() == current

    options = BlockRowsOptions(columns=(("name", "value"), ("unit", "status")))
    block_serializer = BlockRowsSerializer(options=options)
    records = RowsRepository(model=Record, base_directory=SAMPLES, serializers_by_extension={".txt": block_serializer}).load("multiline_records.txt")
    block_output = RowsRepository(model=Record, base_directory=output, serializers_by_extension={".txt": block_serializer})
    block_output.save("records.txt", records)
    assert block_output.load("records.txt") == records

    first = RowsRepository[dict[str, Any]](model=dict, base_directory=SAMPLES,
        serializers_by_extension={".csv": CaptureSectionSerializer("first")}).load_document("compound.csv")
    second = RowsRepository[dict[str, Any]](model=dict, base_directory=SAMPLES,
        serializers_by_extension={".csv": CaptureSectionSerializer("second")}).load_document("compound.csv")
    whole_file = ObjectRepository[dict[str, Any]](model=dict, base_directory=output,
        serializers_by_extension={".csv": CaptureCsvFileSerializer()})
    whole_file.save("compound.csv", {"first": {"metadata": first.metadata, "rows": first.rows},
                                     "second": {"metadata": second.metadata, "rows": second.rows}})

    positional = ObjectRepository[dict[str, Any]](model=dict, base_directory=SAMPLES,
        serializers_by_extension={".txt": PositionalCaptureReader()}).load("positional.txt")
    # 位置依存の旧入力の単位変更も、Parserではなくアプリのキャストで明示する。
    positional = VersionConverter(current_version=1, upcasts={0: upcast_capture}, downcasts={}).to_current(positional)
    positional["rows"] = [Measurement.model_validate(row).model_dump() for row in positional["rows"]]
    ObjectRepository[dict[str, Any]](model=dict, base_directory=output).save("positional.json", positional)

    if include_pandas:
        from DataManager.frames import from_frame, to_frame
        frame = to_frame(current.rows, columns=("time", "value"), dtypes={"time": "Int64", "value": "Float64"})
        assert from_frame(frame, model=Measurement) == current.rows
        channels = to_frame(second.rows, columns=tuple(second.rows[0]), dtypes={key: "Float64" for key in second.rows[0]})
        print(f"DataFrame: {frame.shape}, channels: {channels.shape}")
    print(f"KV / CSV / 複数行 / 2表 / 位置依存入力 / 版変換: {output.resolve()}")


def main():
    parser = argparse.ArgumentParser(description="合意した拡張形式の架空サンプル")
    parser.add_argument("output", type=Path)
    parser.add_argument("--pandas", action="store_true")
    arguments = parser.parse_args()
    run(arguments.output, include_pandas=arguments.pandas)


if __name__ == "__main__":
    main()
