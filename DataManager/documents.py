""" CSV・JSONLで共通に使う、ファイルのメタ情報と本文の受け渡し形式。
"""
from dataclasses import dataclass
from typing import Generic, TypeVar

from DataManager.model_conversion import ModelValue, SerializableValue


MetadataValue = TypeVar("MetadataValue", bound=SerializableValue)


@dataclass(frozen=True)
class RowsDocument(Generic[MetadataValue, ModelValue]):
    """ 一度の読込・保存で扱うメタ情報と行一覧。入出力処理や保存状態を持たない。

    項目は値の受け渡し用に公開する。frozenは項目の再代入だけを禁止し、
    中のモデル・辞書・リストまで読み取り専用にするものではない。
    """

    metadata: MetadataValue
    rows: list[ModelValue]
