""" 項目宣言型CSVで、旧版読取・メタと本文のcast・現在版と旧版の保存を追う。
"""
import argparse
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from DataManager import (
    CsvHeaderField, CsvHeaderOptions, CsvOptions, CsvSerializer, FileReader, FileService,
    JsonlSerializer, RowsDocument, RowsRepository, VersionConverter, VersionedRowsRepository,
)

SAMPLES = Path(__file__).resolve().parent / "csv_data"


class Metadata(BaseModel):
    """ 現在版のメタ。旧版のcountをgroup_countへ改名する。
    """

    version: int
    group_count: int


class Reading(BaseModel):
    """ 現在版の行。旧版のname / valueからlabel / readingへ変更する。
    """

    id: int
    label: str
    reading: float


def upcast(document: dict[str, Any]) -> dict[str, Any]:
    """ 文書の版は共通処理へ任せ、メタと本文の旧名を同時に変換する。
    """
    return {
        **document,
        "metadata": {"group_count": document["metadata"]["count"]},
        "rows": [
            {"id": row["id"], "label": row["name"], "reading": row["value"]}
            for row in document["rows"]
        ],
    }


def downcast(document: dict[str, Any]) -> dict[str, Any]:
    """ 旧版が理解できる項目だけへ戻す。
    """
    return {
        **document,
        "metadata": {"count": document["metadata"]["group_count"]},
        "rows": [
            {"id": row["id"], "name": row["label"], "value": row["reading"]}
            for row in document["rows"]
        ],
    }


def decode(document: dict[str, Any]) -> RowsDocument[Metadata, Reading]:
    """ 全castの後に、現在版のモデルを生成する。
    """
    return RowsDocument(
        metadata=Metadata.model_validate(document["metadata"]),
        rows=[Reading.model_validate(row) for row in document["rows"]],
    )


def encode(document: RowsDocument[Metadata, Reading]) -> dict[str, Any]:
    """ 現在モデルを保存用の文書辞書へ戻す。
    """
    return {
        "version": 1, "metadata": document.metadata.model_dump(),
        "rows": [row.model_dump() for row in document.rows],
    }


def run(directory: Path):
    """ b.csvを旧版の入力例とし、出力先で編集・現在版保存・旧版出力を確認する。
    """
    directory.mkdir(parents=True, exist_ok=False)
    source_bytes = (SAMPLES / "b.csv").read_bytes()
    (directory / "source_v0.csv").write_bytes(source_bytes)

    converter = VersionConverter(current_version=1, upcasts={0: upcast}, downcasts={1: downcast})
    legacy_csv = CsvSerializer(
        options=CsvOptions(delimiter=";", column_prefix="#", strip_column_names=True),
        metadata=CsvHeaderOptions(fields=(
            CsvHeaderField.whitespace("version"), CsvHeaderField.separated("count"),
        )),
    )
    current_csv = CsvSerializer(
        options=CsvOptions(delimiter=";", column_prefix="#"),
        metadata=CsvHeaderOptions(fields=(
            CsvHeaderField.whitespace("version"), CsvHeaderField.separated("group_count"),
        )),
    )

    legacy = VersionedRowsRepository(
        repository=RowsRepository[dict[str, Any]](
            model=dict, base_directory=directory, serializers_by_extension={".csv": legacy_csv},
        ),
        converter=converter, decode_current=decode, encode_current=encode,
        read_version=lambda metadata: int(metadata.get("version", 0)),
    )
    current = VersionedRowsRepository(
        repository=RowsRepository[dict[str, Any]](
            model=dict, base_directory=directory,
            serializers_by_extension={
                ".csv": current_csv, ".jsonl": JsonlSerializer.for_dict(document_models=('Reading',)),
            },
        ),
        converter=converter, decode_current=decode, encode_current=encode,
        read_version=lambda metadata: int(metadata.get("version", 0)),
    )

    document = FileReader(repository=legacy, path="source_v0.csv").load()
    assert document.metadata == Metadata(version=1, group_count=1)
    assert document.rows[0] == Reading(id=1, label="taro", reading=3)
    document.rows[0].reading = 30

    output = FileService(repository=current, path="current_v1.csv")
    output.save(document)
    assert output.load() == document
    output.save_as("current_v1.jsonl", document)

    old_output = FileService(repository=legacy.for_version(0), path="export_v0.csv")
    old_output.save(document)
    assert old_output.load() == document
    assert (directory / "source_v0.csv").read_bytes() == source_bytes
    assert (SAMPLES / "b.csv").read_bytes() == source_bytes
    print("Current CSV / JSONL and V0 CSV:", directory.resolve())


def main():
    parser = argparse.ArgumentParser(description="宣言型CSVとVersionedRowsRepositoryの例")
    parser.add_argument("output", type=Path)
    run(parser.parse_args().output)


if __name__ == "__main__":
    main()
