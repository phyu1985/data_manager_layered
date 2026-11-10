""" iiii・i5の前置コメントを読む実例。汎用CSVの設定には固有の文法を持ち込まない。
"""
from __future__ import annotations

from collections.abc import Sequence
from io import StringIO
import re
from typing import Any

from DataManager.documents import RowsDocument
from DataManager.errors import ConfigurationError, SerializationError
from DataManager.model_conversion import ModelBinding, ModelValue
from DataManager.serializers.csv import CsvSerializer
from DataManager.serializers.csv_options import CsvOptions


class SampleCommentCsvSerializer:
    """ サンプル固有のコメントをメタへ変換し、本文の復元はCSVへ委譲する。

    # name valueを表の開始とし、version・saved_at・Made by行を解釈する。
    読取専用。実際の独自形式を実装するときは、この文法部分を書き換える。
    """

    def __init__(self, *, required_metadata: tuple[str, ...] = ()):
        self._required_metadata = required_metadata
        self._table = CsvSerializer(options=CsvOptions(delimiter=" ", column_prefix="# "))

    @property
    def encoding(self) -> str:
        return self._table.encoding

    def validate_model_configuration(self, model_binding: ModelBinding[ModelValue]):
        """ 本文の対応モデルは委譲先のCSVと同じ条件に揃える。
        """
        self._table.validate_model_configuration(model_binding)

    @staticmethod
    def _read_metadata(comment: str) -> dict[str, str]:
        """ この形式が持つ二種類のメタ行を読む。それ以外は説明コメントとして扱う。
        """
        if comment.startswith("Made by "):
            match = re.fullmatch(r"Made by (?P<user>.+?) at (?P<updated_at>\d{4}/\d{2}/\d{2})", comment)
            if match is None:
                raise SerializationError("Made by行はMade by 名前 at YYYY/MM/DDの形式が必要です")
            return match.groupdict()

        name, separator, value = comment.partition(":")
        if name.strip() in {"version", "saved_at"}:
            if not separator or not value.strip():
                raise SerializationError(f"{name.strip()}にはコロンと値が必要です")
            return {name.strip(): value.strip()}
        words = comment.split(maxsplit=1)
        if words and words[0] in {"version", "saved_at"}:
            raise SerializationError("version・saved_atはkey: valueの形式が必要です")
        return {}

    def loads_document(
        self, serialized_text: str, model_binding: ModelBinding[ModelValue],
    ) -> RowsDocument[dict[str, Any], ModelValue]:
        """ 列名までメタを集め、列名以降の文字列をそのままCSVへ渡す。
        """
        self.validate_model_configuration(model_binding)
        stream = StringIO(serialized_text, newline="")
        metadata: dict[str, Any] = {}

        # 説明とメタは前置部分だけで解釈する。本文の#や引用符内改行には触れない。
        while True:
            start = stream.tell()
            line = stream.readline()
            if not line:
                raise SerializationError("列名行 # name value がありません")
            if not line.strip():
                continue
            if not line.startswith("#"):
                raise SerializationError("列名より前には#で始まるコメントを記載してください")

            comment = line[1:].strip()
            if comment == "name value":
                break
            values = self._read_metadata(comment)
            if metadata.keys() & values.keys():
                raise SerializationError("コメント中のメタが重複しています")
            metadata.update(values)

        # 必須項目だけをここで確認し、列数・値・モデルの検証はCSVへ任せる。
        missing = [name for name in self._required_metadata if name not in metadata]
        if missing:
            raise SerializationError(f"コメント中のメタが不足しています: {', '.join(missing)}")
        rows = self._table.loads(serialized_text[start:], model_binding)
        return RowsDocument(metadata=metadata, rows=rows)

    def loads(self, serialized_text: str, model_binding: ModelBinding[ModelValue]) -> list[ModelValue]:
        """ Repositoryの通常読み込みにも同じ文書の本文を返す。
        """
        return self.loads_document(serialized_text, model_binding).rows

    def dumps(self, rows: Sequence[ModelValue], model_binding: ModelBinding[ModelValue]) -> str:
        """ 元形式の書式を推測して保存しない。出力先に合うSerializerを別に選ぶ。
        """
        raise ConfigurationError("SampleCommentCsvSerializerは読取専用です。出力用Serializerを別に構成してください")

    def dumps_document(
        self, rows: Sequence[ModelValue], model_binding: ModelBinding[ModelValue], *, metadata: dict[str, Any],
    ) -> str:
        """ メタ付き保存も、通常保存と同じ読取専用の扱いに揃える。
        """
        return self.dumps(rows, model_binding)
