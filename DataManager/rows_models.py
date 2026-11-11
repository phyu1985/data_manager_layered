""" 現在のRowsDocumentと、版変換に渡す辞書を相互変換する。
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from DataManager.documents import MetadataValue, RowsDocument
from DataManager.errors import SerializationError
from DataManager.model_conversion import ModelBinding
from DataManager.serializers.jsonl import JsonlSerializer

RowModel = TypeVar("RowModel", bound=BaseModel)


class RowsModelCodec(Generic[MetadataValue, RowModel]):
    """ 現在モデルの登録表で行を復元する。ファイル操作と版変換は担当しない。
    """

    def __init__(
        self, *, metadata_model: type[MetadataValue], model_tags: Mapping[type[RowModel], str],
        tag_field: str, version_field: str, current_version: int,
    ):
        self._rows = ModelBinding(tuple(model_tags))
        self._metadata = ModelBinding(metadata_model)
        self._tags = dict(model_tags)
        self._models = {tag: model for model, tag in model_tags.items()}
        self._tag_field = tag_field
        self._version_field = version_field
        self._current_version = current_version

        # 固定名の重複・業務フィールドとの衝突は、通常JSONLと同じ規則で確認する。
        jsonl_tags: dict[type[BaseModel], str] = {model: tag for model, tag in model_tags.items()}
        JsonlSerializer.for_models(model_tags=jsonl_tags, tag_field=tag_field).validate_model_configuration(self._rows)

    def decode(self, value: dict[str, Any]) -> RowsDocument[MetadataValue, RowModel]:
        """ upcast後の行だけをモデルへ復元する。旧項目はcastが処理するまで保持する。
        """
        # 版変換済みの文書を、メタの型と各行の型へ分けて検証する。
        try:
            metadata = self._metadata.restore_value(value["metadata"])
        except ValidationError as error:
            raise SerializationError("現在版のメタがモデルと一致しません") from error

        # 各行の復元先を決め、辞書から現在版のモデルを生成する。
        rows: list[RowModel] = []
        for row_number, raw in enumerate(value["rows"], start=1):
            data: dict[str, Any] = dict(raw)
            model: type[RowModel] | None = None
            if self._rows.data_mode == "mixed":
                # 識別キーは保存用の情報なので、モデルへ渡す業務フィールドから取り除く。
                tag = data.pop(self._tag_field, None)
                if not isinstance(tag, str) or tag not in self._models:
                    raise SerializationError(f"現在版の{row_number}件目: {self._tag_field}に登録済みの型名が必要です")
                model = self._models[tag]

            try:
                rows.append(self._rows.restore_value(data, model))
            except ValidationError as error:
                raise SerializationError(f"現在版の{row_number}件目が行モデルと一致しません") from error
        return RowsDocument(metadata=metadata, rows=rows)

    def encode(self, document: RowsDocument[MetadataValue, RowModel]) -> dict[str, Any]:
        """ 現在版の辞書を作る。混在モデルの識別情報もdowncastの対象へ含める。
        """
        # cast関数が扱うキーを一定にするため、内部辞書ではフィールド名を使う。
        # 旧版のキー名への変更は、この後のdowncastへ任せる。
        metadata = self._metadata.to_dict(document.metadata, by_alias=False)
        # 各モデルを保存用の辞書へ戻し、混在時は型識別キーも付ける。
        rows: list[dict[str, Any]] = []
        for row_number, row in enumerate(document.rows, start=1):
            data = self._rows.to_dict(row, by_alias=False)
            if self._rows.data_mode == "mixed":
                if self._tag_field in data:
                    raise SerializationError(f"現在版の{row_number}件目: {self._tag_field}が行モデルの出力と衝突します")
                data = {self._tag_field: self._tags[type(row)], **data}
            rows.append(data)

        return {self._version_field: self._current_version, "metadata": metadata, "rows": rows}
