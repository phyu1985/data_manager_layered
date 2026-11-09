""" AA・AAAを別々の関数で読み、異なる行モデルを持つ文書として保存・再読する。
"""
import argparse
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from DataManager import (
    CsvHeaderOptions, CsvHeaderField, CsvOptions, FileService,
    ObjectRepository, TwoTableCsvSerializer,
)

SAMPLES = Path(__file__).resolve().parent / "csv_data"


class UpperRow(BaseModel):
    """ 上段の一行。列名と値の検証をモデルへ集約する。
    """

    model_config = ConfigDict(extra="forbid")
    id: int
    name: str
    value: float


class LowerRow(BaseModel):
    """ 下段の一行。
    """

    model_config = ConfigDict(extra="forbid")
    index: int
    name: str
    position: int


class TablesDocument(BaseModel):
    """ ファイル全体のメタと二種類の行一覧。AAAにはmax_indexがなくてもよい。
    """

    model_config = ConfigDict(extra="forbid")
    metadata: dict[str, int]
    upper: list[UpperRow]
    lower: list[LowerRow]


def sample_aa(directory: Path):
    """ AAの三つの先頭メタと、下段直前のnumberをまとめて読む。
    """
    serializer = TwoTableCsvSerializer(
        upper_header=CsvHeaderOptions(fields=(
            CsvHeaderField.compact('version'),
            CsvHeaderField.separated('count'), CsvHeaderField.separated('max_index'),
        )),
        lower_header=CsvHeaderOptions(fields=(CsvHeaderField.separated('number'),)),
        upper_options=CsvOptions(column_prefix="#", strip_column_names=True),
        lower_options=CsvOptions(column_prefix="#", strip_column_names=True),
    )
    source = ObjectRepository(
        model=TablesDocument, base_directory=SAMPLES, serializers_by_extension={".csv": serializer},
    )
    destination = ObjectRepository(
        model=TablesDocument, base_directory=directory, serializers_by_extension={".csv": serializer},
    )

    document = FileService(repository=source, path="AA.csv").load()
    assert document.metadata == {"version": 0, "count": 2, "max_index": 4, "number": 5}
    assert document.upper[0] == UpperRow(id=1, name="taro", value=3)
    assert document.lower[0] == LowerRow(index=0, name=" hoge", position=32)

    output = FileService(repository=destination, path="AA.csv")
    output.save(document)
    assert output.load() == document
    print("AA.csv:", document.metadata, len(document.upper), len(document.lower))


def sample_aaa(directory: Path):
    """ AAAの両段で余分な末尾空セルを許容し、二つのモデルへ復元する。
    """
    serializer = TwoTableCsvSerializer(
        upper_header=CsvHeaderOptions(fields=(
            CsvHeaderField.compact('version'), CsvHeaderField.separated('count'),
        )),
        lower_header=CsvHeaderOptions(fields=(CsvHeaderField.separated('number'),)),
        upper_options=CsvOptions(
            column_prefix="#", strip_column_names=True, allow_trailing_empty_columns=True,
        ),
        lower_options=CsvOptions(
            column_prefix="#", strip_column_names=True, allow_trailing_empty_columns=True,
        ),
    )
    source = ObjectRepository(
        model=TablesDocument, base_directory=SAMPLES, serializers_by_extension={".csv": serializer},
    )
    destination = ObjectRepository(
        model=TablesDocument, base_directory=directory, serializers_by_extension={".csv": serializer},
    )

    document = FileService(repository=source, path="AAA.csv").load()
    assert document.metadata == {"version": 0, "count": 2, "number": 5}
    assert document.upper[1] == UpperRow(id=2, name="jiro", value=4)
    assert document.lower[-1] == LowerRow(index=4, name=" bar", position=99)

    output = FileService(repository=destination, path="AAA.csv")
    output.save(document)
    assert output.load() == document
    print("AAA.csv:", document.metadata, len(document.upper), len(document.lower))


def run(directory: Path, *, pattern: str = "all"):
    """ 入力を変更せず、指定したパターンを未作成の出力先で実行する。
    """
    if pattern not in {"all", "AA", "AAA"}:
        raise ValueError("patternはall / AA / AAAです")
    directory.mkdir(parents=True, exist_ok=False)
    if pattern in {"all", "AA"}:
        sample_aa(directory)
    if pattern in {"all", "AAA"}:
        sample_aaa(directory)


def main():
    parser = argparse.ArgumentParser(description="二段CSVのAA・AAAを型付き文書で読み書きする例")
    parser.add_argument("output", type=Path)
    parser.add_argument("--pattern", choices=("all", "AA", "AAA"), default="all")
    arguments = parser.parse_args()
    run(arguments.output, pattern=arguments.pattern)


if __name__ == "__main__":
    main()
