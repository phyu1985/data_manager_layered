""" j.csvをV0として読み、型付きV1 JSONLと旧CSVへ出力する。
"""
import argparse
import csv
from io import StringIO
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from DataManager import (
    FileService, JsonlSerializer, NumberCountCsvSerializer, RowsDocument, RowsRepository,
    VersionConverter, VersionedRowsRepository,
)

SOURCE = Path(__file__).resolve().parent / "csv_data" / "j.csv"
CURRENT_VERSION = 1


class NumberModel(BaseModel):
    """ NUMBER TABLEの現在モデル。
    """

    index: int
    id: int
    name: str


class CountModel(BaseModel):
    """ COUNT TABLEの現在モデル。indexもファイル内の実データを使う。
    """

    index: int
    order: int
    value: int


type TableRow = NumberModel | CountModel


class TableMetadata(BaseModel):
    """ 現在版の共通メタ。NoneのflagはV0出力で省略する。
    """

    version: int
    number: int
    count: int
    flag: int | None = None


def upcast_v0_to_v1(document: dict[str, Any]) -> dict[str, Any]:
    """ 旧列名とFlagを現在名へ変える。表の分類はSerializerが確定済み。
    """
    metadata = document["metadata"]
    rows: list[dict[str, Any]] = []
    for row in document["rows"]:
        if row["type"] == "number":
            rows.append({"type": "number", "index": row["NUMBERINDEX"], "id": row["NUMBERID"], "name": row["NAME"]})
        elif row["type"] == "count":
            rows.append({"type": "count", "index": row["index"], "order": row["order"], "value": row["value"]})
        else:
            raise ValueError("未知の表の種類です")
    return {
        **document,
        "metadata": {"number": metadata["number"], "count": metadata["count"], "flag": metadata.get("Flag")},
        "rows": rows,
    }


def downcast_v1_to_v0(document: dict[str, Any]) -> dict[str, Any]:
    """ 現在名をV0の列名へ戻し、NoneのFlagは保存対象に入れない。
    """
    current = document["metadata"]
    metadata = {"number": current["number"], "count": current["count"]}
    if current["flag"] is not None:
        metadata["Flag"] = current["flag"]
    rows: list[dict[str, Any]] = []
    for row in document["rows"]:
        if row["type"] == "number":
            rows.append({"type": "number", "NUMBERINDEX": row["index"], "NUMBERID": row["id"], "NAME": row["name"]})
        elif row["type"] == "count":
            rows.append({"type": "count", "index": row["index"], "order": row["order"], "value": row["value"]})
        else:
            raise ValueError("未知の表の種類です")
    return {**document, "metadata": metadata, "rows": rows}


def create_repository(directory: Path) -> VersionedRowsRepository[RowsDocument[TableMetadata, TableRow]]:
    """ V0の専用CSVとV1 JSONLを、同じモデル登録・版変換へ接続する。
    """
    raw = RowsRepository(
        model=dict, base_directory=directory,
        serializers_by_extension={".csv": NumberCountCsvSerializer(), ".jsonl": JsonlSerializer()},
    )
    model_tags: dict[type[TableRow], str] = {NumberModel: "number", CountModel: "count"}
    return VersionedRowsRepository.for_models(
        repository=raw,
        converter=VersionConverter(
            current_version=CURRENT_VERSION, upcasts={0: upcast_v0_to_v1}, downcasts={1: downcast_v1_to_v0},
        ),
        metadata_model=TableMetadata, model_tags=model_tags,
    )


def make_document(rows: list[TableRow], *, flag: int | None) -> RowsDocument[TableMetadata, TableRow]:
    """ 編集後の件数を一か所で揃え、どの形式にも同じメタで保存する。
    """
    metadata = TableMetadata(
        version=CURRENT_VERSION,
        number=sum(isinstance(row, NumberModel) for row in rows),
        count=sum(isinstance(row, CountModel) for row in rows), flag=flag,
    )
    return RowsDocument(metadata=metadata, rows=rows)


def sample_roundtrip(directory: Path):
    """ 実際のj.csv→型付きV1→JSONL再読→V0別名出力を確認する。
    """
    original = SOURCE.read_bytes()
    repository = create_repository(directory)
    document = FileService(repository=repository, path=SOURCE).load()
    assert document.metadata == TableMetadata(version=1, number=1, count=2, flag=1)
    assert document.rows == [
        NumberModel(index=0, id=1, name="taro yamada"),
        CountModel(index=1, order=1, value=2), CountModel(index=2, order=3, value=4),
    ]

    FileService(repository=repository, path="current.jsonl").save(document)
    restored = repository.load("current.jsonl")
    assert restored == document
    assert type(restored.rows[0]) is NumberModel and type(restored.rows[1]) is CountModel
    legacy = FileService(repository=repository.for_version(0), path="export_v0.csv")
    legacy.save(restored)
    assert legacy.load() == document
    assert (directory / "export_v0.csv").read_text(encoding="utf-8").splitlines()[-1] == "Flag: 1"
    header = json.loads((directory / "current.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert header["__meta__"]["models"] == ["count", "number"]
    assert header["metadata"] == {"number": 1, "count": 2, "flag": 1, "version": 1}
    assert SOURCE.read_bytes() == original
    print("V0 -> V1 -> V0:", document)


def sample_optional_flag(directory: Path):
    """ FlagなしとFlag=0を区別し、元のj.csvを変更せず保存する。
    """
    repository = create_repository(directory)
    original = repository.load(SOURCE)
    for flag, filename in ((None, "without_flag.csv"), (0, "flag_zero.csv")):
        document = make_document(original.rows, flag=flag)
        repository.for_version(0).save(filename, document)
        assert repository.load(filename) == document
        text = (directory / filename).read_text(encoding="utf-8")
        records = [record for record in csv.reader(StringIO(text), skipinitialspace=True) if record]
        if flag is None:
            assert not (len(records[-1]) == 1 and records[-1][0].startswith("Flag:"))
        else:
            assert records[-1] == ["Flag: 0"]
    print("Optional Flag: None is omitted; 0 is written")


def sample_edited_counts(directory: Path):
    """ COUNTを追加した後、件数を揃えた一文書から両形式へ保存する。
    """
    repository = create_repository(directory)
    original = repository.load(SOURCE)
    document = make_document(
        [*original.rows, CountModel(index=3, order=5, value=6)], flag=original.metadata.flag,
    )
    assert document.metadata.count == 3
    repository.save("edited.jsonl", document)
    repository.for_version(0).save("edited_v0.csv", document)
    assert repository.load("edited.jsonl") == document
    assert repository.load("edited_v0.csv") == document
    assert original.metadata.count == 2
    print("Edited counts:", document.metadata)


def main():
    parser = argparse.ArgumentParser(description="NUMBER/COUNTのCSVと混在JSONLの版変換")
    parser.add_argument("output", type=Path)
    directory = parser.parse_args().output
    directory.mkdir(parents=True, exist_ok=False)
    sample_roundtrip(directory)
    sample_optional_flag(directory)
    sample_edited_counts(directory)
    print("Output:", directory.resolve())


if __name__ == "__main__":
    main()
