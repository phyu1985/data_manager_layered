""" CSVの設定を、本文・可変メタ・順序付きヘッダの役割に分ける。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from DataManager.errors import ConfigurationError
from DataManager.serializers.text_header import validate_header_separator


@dataclass(frozen=True)
class CsvOptions:
    """ 一つのテーブルの規則。columnsは見出しの置換にも、列名なし入力にも使う。

    headerは列名行の有無。column_prefixはその行だけに付き、本文の値には適用しない。
    delimiterはセル、field_separatorは入れ子のキーの区切り。by_aliasは出力専用。
    """

    delimiter: str = ","
    header: bool = True
    columns: tuple[str, ...] | None = None
    column_prefix: str = ""
    strip_column_names: bool = False
    field_separator: str = "."
    empty_as_none: bool = True
    by_alias: bool = False
    allow_trailing_empty_columns: bool = False

    def __post_init__(self):
        """ 本文の文法だけを確定する。入力の列数・値は読取時に確認する。
        """
        if len(self.delimiter) != 1 or self.delimiter in '\r\n"':
            raise ConfigurationError("delimiterは引用符・改行以外の1文字で指定してください")
        if not self.field_separator:
            raise ConfigurationError("field_separatorは空にできません")

        if any(c in self.column_prefix for c in "\r\n"):
            raise ConfigurationError("column_prefixに改行は使えません")
        if not self.header and self.column_prefix:
            raise ConfigurationError("column_prefixはheader=Trueのときだけ指定してください")


@dataclass(frozen=True)
class CsvHeaderField:
    """ 固定ヘッダの一項目。nameがmetaのキーで、separatorがファイルの書式を表す。

    Noneは値だけ、空文字はversion0のような連結、半角空白はversion 0を表す。
    それ以外はcount: 1のような記号区切り。余分な区切り前後の空白は許容する。
    """

    name: str
    separator: str | None = ":"


    def __post_init__(self):
        """ 一項目の名前と書式だけを確認する。
        """
        if not self.name.strip() or any(c in self.name for c in "\r\n"):
            raise ConfigurationError("ヘッダの項目名は改行のない非空文字列です")
        if self.separator not in (None, ""):
            validate_header_separator(self.separator)

    @classmethod
    def value_only(cls, name: str) -> CsvHeaderField:
        """ 名前のない値へキーを与える。
        """
        return cls(name, separator=None)

    @classmethod
    def compact(cls, name: str) -> CsvHeaderField:
        """ version0のような連結した名前と値を読む。
        """
        return cls(name, separator="")

    @classmethod
    def whitespace(cls, name: str) -> CsvHeaderField:
        """ version 0のような空白区切りを読む。
        """
        return cls(name, separator=" ")

    @classmethod
    def separated(cls, name: str, separator: str = ":") -> CsvHeaderField:
        """ count: 2のような記号区切りを読む。
        """
        return cls(name, separator=separator)


@dataclass(frozen=True)
class CsvHeaderOptions:
    """ fieldsの順番でヘッダを読む。項目ごとの書式と、キーなしの値に対応する。

    comment_prefixesは最初の項目より前の説明行だけを飛ばす。
    allow_paddingはmeta行の末尾の空CSVセルだけを許容し、本文には作用しない。
    """

    fields: tuple[CsvHeaderField, ...]
    comment_prefixes: tuple[str, ...] = ()
    allow_padding: bool = False
    empty_as_none: bool = True

    def __post_init__(self):
        """ 各項目の検証後に、一覧としての重複と先頭コメントの規則を確認する。
        """
        names = [field.name for field in self.fields]
        if not names or len(set(names)) != len(names):
            raise ConfigurationError("ヘッダのfieldsは空でない重複のない一覧です")
        if any(not prefix or any(c in prefix for c in "\r\n") for prefix in self.comment_prefixes):
            raise ConfigurationError("コメント記号は改行のない非空文字列です")


@dataclass(frozen=True, init=False)
class CsvKeyValueHeaderOptions:
    """ 項目名が不定のメタ。通常はfixed_rowsで件数を指定して作る。

    空行・マーカーは専用の生成メソッドで選ぶ。利用者は方式と終端値を同時に組み立てない。
    テキスト固有のmultiple / prefixはas_textでまとめて設定する。
    """

    boundary: Literal["blank_line", "marker", "fixed_rows"]
    row_count: int | None
    marker: str | None
    separator: str | None
    multiple: bool
    prefix: str
    empty_as_none: bool

    def __init__(self):
        """ 読み方を確定するため、名前付きの生成メソッドからのみ作る。
        """
        raise ConfigurationError("fixed_rows / until_blank_line / until_markerで生成してください")

    @classmethod
    def fixed_rows(
        cls, row_count: int, *, separator: str | None = None, empty_as_none: bool = True,
    ) -> CsvKeyValueHeaderOptions:
        """ 先頭の指定件数を読む。separator省略時はCSVの2セルとして扱う。
        """
        if type(row_count) is not int or row_count < 0:
            raise ConfigurationError("row_countは0以上の整数です")
        return cls._create("fixed_rows", row_count=row_count, separator=separator, empty_as_none=empty_as_none)

    @classmethod
    def until_blank_line(
        cls, *, separator: str | None = None, empty_as_none: bool = True,
    ) -> CsvKeyValueHeaderOptions:
        """ 空のレコードを終端とする例外的な形式を選ぶ。
        """
        return cls._create("blank_line", separator=separator, empty_as_none=empty_as_none)

    @classmethod
    def until_marker(
        cls, marker: str, *, separator: str | None = None, empty_as_none: bool = True,
    ) -> CsvKeyValueHeaderOptions:
        """ 指定マーカーを終端とする例外的な形式を選ぶ。
        """
        if not marker or not marker.strip() or any(c in marker for c in "\r\n"):
            raise ConfigurationError("markerは改行のない非空文字列です")
        return cls._create("marker", marker=marker, separator=separator, empty_as_none=empty_as_none)

    def as_text(
        self, *, separator: str = ":", multiple: bool = False, prefix: str = "",
    ) -> CsvKeyValueHeaderOptions:
        """ テキストの文法をまとめて指定した新しい設定を返す。元の設定は変更しない。
        """
        if not separator:
            raise ConfigurationError("テキストのseparatorを指定してください")
        if any(c in prefix for c in "\r\n"):
            raise ConfigurationError("prefixに改行は使えません")
        return type(self)._create(
            self.boundary, row_count=self.row_count, marker=self.marker,
            separator=separator, multiple=multiple, prefix=prefix, empty_as_none=self.empty_as_none,
        )

    @classmethod
    def _create(
        cls, boundary: Literal["blank_line", "marker", "fixed_rows"], *,
        row_count: int | None = None, marker: str | None = None,
        separator: str | None = None, multiple: bool = False, prefix: str = "",
        empty_as_none: bool,
    ) -> CsvKeyValueHeaderOptions:
        """ 確定済みの読み方を不変の設定として保持する。方式の組合せを再検証しない。
        """
        if separator is not None:
            validate_header_separator(separator)
        instance = object.__new__(cls)
        for name, value in (
            ("boundary", boundary), ("row_count", row_count), ("marker", marker),
            ("separator", separator), ("multiple", multiple), ("prefix", prefix),
            ("empty_as_none", empty_as_none),
        ):
            object.__setattr__(instance, name, value)
        return instance
