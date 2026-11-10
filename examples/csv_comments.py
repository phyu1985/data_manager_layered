""" i〜i5を独立した設定で読み、コメント由来の情報も共通のmetaへまとめる。
"""
from pathlib import Path

from pydantic import BaseModel

from DataManager import CsvHeaderField, CsvHeaderOptions, CsvKeyValueHeaderOptions, CsvOptions, CsvSerializer, RowsDocument, RowsRepository
from DataManager.serializers.sample_comment_csv import SampleCommentCsvSerializer

SAMPLES = Path(__file__).resolve().parent / "csv_data"


class Reading(BaseModel):
    """ 各サンプルで共通の本文。
    """

    name: str
    value: int


def sample_i() -> RowsDocument[dict[str, object], Reading]:
    """ 本文の空白区切りと、versionのコロン区切りを分けて指定する。
    """
    serializer = CsvSerializer(
        options=CsvOptions(delimiter=" ", column_prefix="# "),
        metadata=CsvKeyValueHeaderOptions.fixed_rows(1).as_text(),
    )
    repository = RowsRepository(
        model=Reading, base_directory=SAMPLES, serializers_by_extension={".csv": serializer},
    )
    document = repository.load_document("i.csv")
    assert document.metadata == {"version": "0"}
    assert document.rows == [Reading(name="a", value=1), Reading(name="b", value=2)]
    return document


def sample_ii() -> RowsDocument[dict[str, object], Reading]:
    """ #付きのメタも、一項目一行として読む。
    """
    serializer = CsvSerializer(
        options=CsvOptions(delimiter=" ", column_prefix="# "),
        metadata=CsvKeyValueHeaderOptions.fixed_rows(1).as_text(prefix="# "),
    )
    repository = RowsRepository(
        model=Reading, base_directory=SAMPLES, serializers_by_extension={".csv": serializer},
    )
    document = repository.load_document("ii.csv")
    assert document.metadata == {"version": "0"}
    assert document.rows == [Reading(name="a", value=1), Reading(name="b", value=2)]
    return document


def sample_iii() -> RowsDocument[dict[str, object], Reading]:
    """ #付きの説明を飛ばし、指定した列名行から本文を読む。
    """
    serializer = CsvSerializer(options=CsvOptions(
        delimiter=" ", column_prefix="# ",
        comment_prefixes=("#",), header_line="# name value",
    ))
    repository = RowsRepository(
        model=Reading, base_directory=SAMPLES, serializers_by_extension={".csv": serializer},
    )
    document = repository.load_document("iii.csv")
    assert document.metadata == {}
    assert document.rows == [Reading(name="a", value=1), Reading(name="b", value=2)]
    return document


def sample_iii_1() -> RowsDocument[dict[str, object], Reading]:
    """ 説明の後に、空白・コロンで書かれたメタと本文を読む。
    """
    serializer = CsvSerializer(
        options=CsvOptions(
            delimiter=" ", column_prefix="# ",
            comment_prefixes=("#",), header_line="# name value",
        ),
        metadata=CsvHeaderOptions(fields=(
            CsvHeaderField.whitespace("version"),
            CsvHeaderField.separated("count"),
        )),
    )
    repository = RowsRepository(
        model=Reading, base_directory=SAMPLES, serializers_by_extension={".csv": serializer},
    )
    document = repository.load_document("iii_1.csv")
    assert document.metadata == {"version": "1", "count": "2"}
    assert document.rows == [Reading(name="a", value=1), Reading(name="b", value=2)]
    return document


def sample_iiii() -> RowsDocument[dict[str, object], Reading]:
    """ 説明中から宣言したversionとsaved_atだけをmetaへ収録する。
    """
    serializer = SampleCommentCsvSerializer(required_metadata=("version", "saved_at"))
    repository = RowsRepository(
        model=Reading, base_directory=SAMPLES, serializers_by_extension={".csv": serializer},
    )
    document = repository.load_document("iiii.csv")
    assert document.metadata == {"version": "0", "saved_at": "2026-11-10"}
    assert document.rows == [Reading(name="a", value=1), Reading(name="b", value=2)]
    return document


def sample_i5() -> RowsDocument[dict[str, object], Reading]:
    """ 専用SerializerがMade by行をuser・updated_atへ読み替える。
    """
    serializer = SampleCommentCsvSerializer(
        required_metadata=("version", "saved_at", "user", "updated_at"),
    )
    repository = RowsRepository(
        model=Reading, base_directory=SAMPLES, serializers_by_extension={".csv": serializer},
    )
    document = repository.load_document("i5.csv")
    assert document.metadata == {
        "version": "0", "saved_at": "2026-11-10",
        "user": "taro yamada", "updated_at": "2026/11/10",
    }
    assert document.rows == [Reading(name="a", value=1), Reading(name="b", value=2)]
    return document


def main():
    for sample in (sample_i, sample_ii, sample_iii, sample_iii_1, sample_iiii, sample_i5):
        document = sample()
        print(sample.__name__, document.metadata, document.rows)


if __name__ == "__main__":
    main()
