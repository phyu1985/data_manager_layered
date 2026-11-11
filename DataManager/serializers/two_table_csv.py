""" 空行で区切られた二つのCSV表を、一つの型付き文書として扱う。
"""
from __future__ import annotations

import csv
from io import StringIO
from typing import Any, cast

from pydantic import ValidationError

from DataManager.errors import ConfigurationError, SerializationError
from DataManager.model_conversion import ModelBinding, ModelValue
from DataManager.serializers.csv import CsvSerializer
from DataManager.serializers.csv_options import CsvHeaderOptions, CsvOptions


class TwoTableCsvSerializer:
    """ 二段の配置・メタの所属・件数を管理し、各表の変換はCsvSerializerへ委譲する。

    文書はmetadata・upper・lowerを持つモデルまたはdict。metadataは一か所へ集めるが、
    保存位置は各ヘッダのfieldsから復元する。行モデルは文書モデルの型定義で指定する。
    """

    def __init__(
        self, *, upper_header: CsvHeaderOptions, lower_header: CsvHeaderOptions,
        upper_options: CsvOptions | None = None, lower_options: CsvOptions | None = None,
        upper_count_field: str = "count", lower_count_field: str = "number",
    ):
        self._upper_options = upper_options or CsvOptions()
        self._upper_keys = tuple(field.name for field in upper_header.fields)
        self._lower_keys = tuple(field.name for field in lower_header.fields)
        self._upper_count_field = upper_count_field
        self._lower_count_field = lower_count_field
        if set(self._upper_keys) & set(self._lower_keys):
            raise ConfigurationError("二段のメタ項目名は重複できません")
        if upper_count_field not in self._upper_keys or lower_count_field not in self._lower_keys:
            raise ConfigurationError("件数項目をそれぞれのヘッダfieldsへ含めてください")

        self._upper = CsvSerializer(options=self._upper_options, metadata=upper_header)
        self._lower = CsvSerializer(options=lower_options, metadata=lower_header)
        self._raw_binding = ModelBinding[dict[str, Any]](dict)

    @property
    def encoding(self) -> str:
        return "utf-8"

    @property
    def supports_document_merge(self) -> bool:
        return False

    def _split_tables(self, text: str) -> tuple[str, str]:
        """ 引用符内の空行を境界とせず、最初の空CSVレコードで二段を分ける。
        """
        stream = StringIO(text, newline="")
        reader = csv.reader(
            stream, delimiter=self._upper_options.delimiter,
            skipinitialspace=self._upper_options.delimiter == " ", strict=True,
        )
        try:
            while True:
                start = stream.tell()
                cells = next(reader, None)
                if cells is None:
                    raise SerializationError("上段と下段の間に空行の境界がありません")
                if not cells:
                    return text[:start], stream.read()
        except csv.Error as error:
            raise SerializationError(f"上段のCSVレコードが不正です: {error}") from error

    @staticmethod
    def _check_count(metadata: dict[str, Any], field: str, actual: int):
        """ 件数を推測で補正せず、メタと復元した行数の一致を確認する。
        """
        value: object = metadata.get(field)
        if isinstance(value, str) and value.isdecimal():
            expected = int(value)
        elif type(value) is int:
            expected = value
        else:
            raise SerializationError(f"{field}は0以上の整数である必要があります")
        if expected < 0 or expected != actual:
            raise SerializationError(f"{field}={expected}と本文の件数{actual}が一致しません")

    def loads(self, serialized_text: str, model_binding: ModelBinding[ModelValue]) -> ModelValue:
        """ 両段の変換と件数照合が完了してから、文書・各行を現在のモデルへ復元する。
        """
        upper_text, lower_text = self._split_tables(serialized_text)
        upper = self._upper.loads_document(upper_text, self._raw_binding)
        lower = self._lower.loads_document(lower_text, self._raw_binding)

        # 記載位置を残すのはSerializerの責務。利用側はメタをまとめて参照できる。
        metadata = {**upper.metadata, **lower.metadata}
        self._check_count(metadata, self._upper_count_field, len(upper.rows))
        self._check_count(metadata, self._lower_count_field, len(lower.rows))

        # 入れ子の行もPydanticへ渡すため、上段・下段のモデルを別々に検証できる。
        try:
            return model_binding.restore_value({
                "metadata": metadata, "upper": upper.rows, "lower": lower.rows,
            })
        except (ValidationError, SerializationError) as error:
            raise SerializationError(f"二段CSVの文書・行モデルの検証に失敗しました: {error}") from error

    @staticmethod
    def _mapping(value: object, name: str) -> dict[str, Any]:
        """ 保存文書の形を確認し、欠損や不正な値を保存前に検出する。
        """
        if not isinstance(value, dict):
            raise SerializationError(f"{name}は辞書である必要があります")
        return cast(dict[str, Any], value)

    def _rows(self, value: object, name: str) -> list[dict[str, Any]]:
        """ 文書モデルの辞書化後に、各段が行辞書の一覧になっていることを確認する。
        """
        if not isinstance(value, list):
            raise SerializationError(f"{name}は行の一覧である必要があります")
        return [self._mapping(row, name) for row in cast(list[object], value)]

    def dumps(
        self, value: ModelValue, model_binding: ModelBinding[ModelValue], *,
        existing_text: str | None = None, template_text: str | None = None,
    ) -> str:
        """ メタを所定位置へ戻して全体を生成する。件数更新と保存対象の選択は呼出側で行う。
        """
        if existing_text is not None or template_text is not None:
            raise ConfigurationError("二段CSVの部分マージ・テンプレートは未対応です")
        data = model_binding.to_dict(value, by_alias=False)
        if set(data) != {"metadata", "upper", "lower"}:
            raise SerializationError("二段CSVの文書はmetadata・upper・lowerが必要です")
        metadata = self._mapping(data["metadata"], "metadata")
        if set(metadata) != set(self._upper_keys) | set(self._lower_keys):
            raise SerializationError("保存するメタ項目と上下段のfieldsが一致しません")
        upper = self._rows(data["upper"], "upper")
        lower = self._rows(data["lower"], "lower")

        # 両段を文字列へ変換し終えてから連結する。Repositoryはこの後に一度だけ保存する。
        upper_text = self._upper.dumps_document(
            upper, self._raw_binding, metadata={key: metadata[key] for key in self._upper_keys},
        )
        lower_text = self._lower.dumps_document(
            lower, self._raw_binding, metadata={key: metadata[key] for key in self._lower_keys},
        )
        text = upper_text + "\n" + lower_text
        # 編集後のモデル値と生成した文法を、読取経路で一度だけ検証する。件数照合もここで行う。
        self.loads(text, model_binding)
        return text
