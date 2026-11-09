""" a〜gをパターン別の関数で読む。各関数に設定・入出力・確認をまとめる。
"""
import argparse
from pathlib import Path
from typing import Any

from DataManager import CsvHeaderOptions, CsvHeaderField, CsvOptions, CsvSerializer, RowsRepository

SAMPLES = Path(__file__).resolve().parent / "csv_data"


def sample_a(directory: Path):
    """ 連結したversion、コロン区切りのcount、#付きカンマ見出しを読む。
    """
    serializer = CsvSerializer(
        options=CsvOptions(delimiter=",", column_prefix="#", strip_column_names=True),
        metadata=CsvHeaderOptions(
            fields=(
                CsvHeaderField.compact('version'),
                CsvHeaderField.separated('count'),
            ),
        ),
    )
    source = RowsRepository[dict[str, Any]](
        model=dict, base_directory=SAMPLES, serializers_by_extension={".csv": serializer},
    )
    destination = RowsRepository[dict[str, Any]](
        model=dict, base_directory=directory, serializers_by_extension={".csv": serializer},
    )

    document = source.load_document("a.csv")
    assert document.metadata == {"version": "0", "count": "1"}
    assert len(document.rows) == 2
    assert document.rows[0]["name"] == "taro"

    destination.save_document("a.csv", document)
    assert destination.load_document("a.csv") == document
    print("a.csv", document.metadata, document.rows[0])


def sample_b(directory: Path):
    """ 空白とコロンが混在するメタ、#付きセミコロン見出しを読む。
    """
    serializer = CsvSerializer(
        options=CsvOptions(delimiter=";", column_prefix="#"),
        metadata=CsvHeaderOptions(
            fields=(
                CsvHeaderField.whitespace('version'),
                CsvHeaderField.separated('count'),
            ),
        ),
    )
    source = RowsRepository[dict[str, Any]](
        model=dict, base_directory=SAMPLES, serializers_by_extension={".csv": serializer},
    )
    destination = RowsRepository[dict[str, Any]](
        model=dict, base_directory=directory, serializers_by_extension={".csv": serializer},
    )

    document = source.load_document("b.csv")
    assert document.metadata == {"version": "0", "count": "1"}
    assert len(document.rows) == 2
    assert document.rows[0]["name"] == "taro"

    destination.save_document("b.csv", document)
    assert destination.load_document("b.csv") == document
    print("b.csv", document.metadata, document.rows[0])


def sample_c(directory: Path):
    """ 先頭の説明コメントを飛ばし、通常の見出しを読む。
    """
    serializer = CsvSerializer(
        options=CsvOptions(delimiter=";"),
        metadata=CsvHeaderOptions(
            fields=(
                CsvHeaderField.whitespace('version'),
                CsvHeaderField.separated('count'),
            ),
            comment_prefixes=("#",),
        ),
    )
    source = RowsRepository[dict[str, Any]](
        model=dict, base_directory=SAMPLES, serializers_by_extension={".csv": serializer},
    )
    destination = RowsRepository[dict[str, Any]](
        model=dict, base_directory=directory, serializers_by_extension={".csv": serializer},
    )

    document = source.load_document("c.csv")
    assert document.metadata == {"version": "0", "count": "1"}
    assert len(document.rows) == 2
    assert document.rows[0]["name"] == "taro"

    destination.save_document("c.csv", document)
    assert destination.load_document("c.csv") == document
    print("c.csv", document.metadata, document.rows[0])


def sample_d(directory: Path):
    """ 先頭の説明コメントと、列名行の#を別々に扱う。
    """
    serializer = CsvSerializer(
        options=CsvOptions(delimiter=";", column_prefix="#"),
        metadata=CsvHeaderOptions(
            fields=(
                CsvHeaderField.whitespace('version'),
                CsvHeaderField.separated('count'),
            ),
            comment_prefixes=("#",),
        ),
    )
    source = RowsRepository[dict[str, Any]](
        model=dict, base_directory=SAMPLES, serializers_by_extension={".csv": serializer},
    )
    destination = RowsRepository[dict[str, Any]](
        model=dict, base_directory=directory, serializers_by_extension={".csv": serializer},
    )

    document = source.load_document("d.csv")
    assert document.metadata == {"version": "0", "count": "1"}
    assert len(document.rows) == 2
    assert document.rows[0]["name"] == "taro"

    destination.save_document("d.csv", document)
    assert destination.load_document("d.csv") == document
    print("d.csv", document.metadata, document.rows[0])


def sample_e(directory: Path):
    """ 列名行がない本文へ、指定した3個の名前を付ける。
    """
    serializer = CsvSerializer(
        options=CsvOptions(delimiter=";", header=False, columns=("id", "name", "value")),
        metadata=CsvHeaderOptions(
            fields=(
                CsvHeaderField.whitespace('version'),
                CsvHeaderField.separated('count'),
            ),
        ),
    )
    source = RowsRepository[dict[str, Any]](
        model=dict, base_directory=SAMPLES, serializers_by_extension={".csv": serializer},
    )
    destination = RowsRepository[dict[str, Any]](
        model=dict, base_directory=directory, serializers_by_extension={".csv": serializer},
    )

    document = source.load_document("e.csv")
    assert document.metadata == {"version": "0", "count": "1"}
    assert len(document.rows) == 2
    assert document.rows[0]["name"] == "taro"

    destination.save_document("e.csv", document)
    assert destination.load_document("e.csv") == document
    print("e.csv", document.metadata, document.rows[0])


def sample_f(directory: Path):
    """ 値だけのversionへキーを付け、列名なしの本文を読む。
    """
    serializer = CsvSerializer(
        options=CsvOptions(delimiter=";", header=False, columns=("id", "name", "value")),
        metadata=CsvHeaderOptions(
            fields=(
                CsvHeaderField.value_only('version'),
            ),
        ),
    )
    source = RowsRepository[dict[str, Any]](
        model=dict, base_directory=SAMPLES, serializers_by_extension={".csv": serializer},
    )
    destination = RowsRepository[dict[str, Any]](
        model=dict, base_directory=directory, serializers_by_extension={".csv": serializer},
    )

    document = source.load_document("f.csv")
    assert document.metadata == {"version": "0"}
    assert len(document.rows) == 2
    assert document.rows[0]["name"] == "taro"

    destination.save_document("f.csv", document)
    assert destination.load_document("f.csv") == document
    print("f.csv", document.metadata, document.rows[0])


def sample_g(directory: Path):
    """ 不足する見出しを6個の指定名で置き換え、本文を全列保持する。
    """
    columns = ("id", "name", "value", "extra_1", "extra_2", "extra_3")
    serializer = CsvSerializer(
        options=CsvOptions(delimiter=";", column_prefix="#", columns=columns),
        metadata=CsvHeaderOptions(
            fields=(
                CsvHeaderField.whitespace('version'),
                CsvHeaderField.separated('count'),
            ),
            comment_prefixes=("#",),
            allow_padding=True,
        ),
    )
    source = RowsRepository[dict[str, Any]](
        model=dict, base_directory=SAMPLES, serializers_by_extension={".csv": serializer},
    )
    destination = RowsRepository[dict[str, Any]](
        model=dict, base_directory=directory, serializers_by_extension={".csv": serializer},
    )

    document = source.load_document("g.csv")
    assert document.metadata == {"version": "0", "count": "1"}
    assert len(document.rows) == 2
    assert document.rows[0]["name"] == "taro"
    assert tuple(document.rows[0]) == columns
    assert document.rows[0]["extra_3"] == "0.3"

    destination.save_document("g.csv", document)
    assert destination.load_document("g.csv") == document
    print("g.csv", document.metadata, document.rows[0])


def run(directory: Path, *, pattern: str = "all"):
    """ 指定した例だけ、または全例を実行する。入力ファイルは変更しない。
    """
    samples = {
        "a": sample_a, "b": sample_b, "c": sample_c, "d": sample_d,
        "e": sample_e, "f": sample_f, "g": sample_g,
    }
    if pattern != "all" and pattern not in samples:
        raise ValueError("patternはa〜gまたはallを指定してください")

    directory.mkdir(parents=True, exist_ok=False)
    if pattern == "all":
        for sample in samples.values():
            sample(directory)
    else:
        samples[pattern](directory)


def main():
    parser = argparse.ArgumentParser(description="CSVのa〜gをパターン別に読み書きする例")
    parser.add_argument("output", type=Path)
    parser.add_argument("--pattern", choices=("all", "a", "b", "c", "d", "e", "f", "g"), default="all")
    arguments = parser.parse_args()
    run(arguments.output, pattern=arguments.pattern)


if __name__ == "__main__":
    main()
