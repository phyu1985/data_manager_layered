""" 本体・固定数の属性・寸法を持つブロック形式と、階層モデルを対応付ける。
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from pydantic import ValidationError

from DataManager.documents import RowsDocument
from DataManager.errors import ConfigurationError, SerializationError
from DataManager.model_conversion import ModelBinding, ModelValue
from DataManager.serializers.block_rows import BlockRowsFormat, BlockRowsOptions


class AttributeBlockSerializer:
    """ 属性行をattrsへまとめる。既定は8行、別の件数は構成時に指定する。
    """

    def __init__(self, *, attribute_count: int = 8, options: BlockRowsOptions | None = None):
        if type(attribute_count) is not int or attribute_count < 0:
            raise ConfigurationError("attribute_countは0以上の整数です")

        # 列の所属先を本体・属性・寸法に分ける。同名列も別の場所へ復元できる。
        self._attribute_count = attribute_count
        self._options = options or BlockRowsOptions(delimiter=",")
        self._format = BlockRowsFormat(self._options)
        self._columns = (
            ("name", "ch", "start", "length"),
            *((f"info_name{i + 1}", f"info_value{i + 1}", "start", "length") for i in range(attribute_count)),
            ("start_mm", "length_mm"),
        )

        # 列名だけの置換は許可し、固定した行数・列数は崩さない。
        if self._options.columns is not None:
            if [len(group) for group in self._options.columns] != [len(group) for group in self._columns]:
                raise ConfigurationError("columnsは本体4列・指定件数の属性4列・寸法2列の構成です")
            self._columns = self._options.columns

        self._format.validate_columns(self._columns)
        root_keys = (*self._columns[0], "attrs", *self._columns[-1])
        if len(set(root_keys)) != len(root_keys):
            raise ConfigurationError("本体・attrs・寸法の保存先キーが重複しています")

    @property
    def encoding(self) -> str:
        return "utf-8"

    def validate_model_configuration(self, model_binding: ModelBinding[ModelValue]):
        if model_binding.data_mode == "mixed":
            raise ConfigurationError("属性ブロックは単一モデルまたはdictに対応します")

    def loads_document(
        self, serialized_text: str, model_binding: ModelBinding[ModelValue],
    ) -> RowsDocument[dict[str, Any], ModelValue]:
        """ 行ごとの所属先を明示して辞書を作り、型と値の検証はモデルへ委譲する。
        """
        # 文法と行構成を先に確認し、位置の対応が確定したレコードだけを扱う。
        self.validate_model_configuration(model_binding)
        document = self._format.loads(serialized_text)
        if tuple(tuple(group) for group in document.columns) != self._columns:
            raise SerializationError("属性ブロックのヘッダが本体・指定件数の属性・寸法の構成と一致しません")

        rows: list[ModelValue] = []
        for record in document.records:
            converted = [
                [None if cell == "" and self._options.empty_as_none else cell for cell in cells]
                for cells in record
            ]

            # 本体と末尾の寸法は直下へ、間の属性行はattrsの要素へ組み立てる。
            data: dict[str, Any] = dict(zip(self._columns[0], converted[0], strict=True))
            data["attrs"] = [
                dict(zip(("name", "value", "start", "length"), cells, strict=True))
                for cells in converted[1:-1]
            ]
            data.update(zip(self._columns[-1], converted[-1], strict=True))

            # 文字列からの数値変換やAttributeの生成は、復元先モデルへ任せる。
            try:
                rows.append(model_binding.restore_value(data))
            except ValidationError as error:
                raise SerializationError(f"属性ブロックのモデル検証に失敗しました: {error}") from error

        return RowsDocument(metadata={}, rows=rows)

    def loads(self, serialized_text: str, model_binding: ModelBinding[ModelValue]) -> list[ModelValue]:
        return self.loads_document(serialized_text, model_binding).rows

    def dumps_document(
        self, rows: Sequence[ModelValue], model_binding: ModelBinding[ModelValue], *, metadata: dict[str, Any],
    ) -> str:
        if metadata:
            raise ConfigurationError("属性ブロックのファイルmetaは未対応です")
        return self.dumps(rows, model_binding)

    def dumps(self, rows: Sequence[ModelValue], model_binding: ModelBinding[ModelValue]) -> str:
        """ attrsを固定数の行へ展開する。不足・余剰を補正せず保存前に拒否する。
        """
        self.validate_model_configuration(model_binding)
        records: list[list[list[Any]]] = []
        expected = {*self._columns[0], "attrs", *self._columns[-1]}

        # 全レコードを行配列へ変換できてから、共通の文法処理で文書を作る。
        for row in rows:
            data = model_binding.to_dict(row, by_alias=self._options.by_alias)
            if set(data) != expected:
                raise SerializationError("属性ブロックの保存項目がモデルと一致しません")

            raw_attrs: object = data["attrs"]
            if not isinstance(raw_attrs, list):
                raise SerializationError("attrsはリストが必要です")
            attributes = cast(list[object], raw_attrs)
            if len(attributes) != self._attribute_count:
                raise SerializationError(f"attrsは{self._attribute_count}件必要です")

            # 読取の逆順で、本体1行・属性行・寸法1行に展開する。
            record = [[data[key] for key in self._columns[0]]]
            for raw_attribute in attributes:
                if not isinstance(raw_attribute, dict):
                    raise SerializationError("attrsの各要素は辞書またはモデルが必要です")
                attribute = cast(dict[str, Any], raw_attribute)
                if set(attribute) != {"name", "value", "start", "length"}:
                    raise SerializationError("属性の保存項目はname/value/start/lengthです")
                record.append([attribute[key] for key in ("name", "value", "start", "length")])

            record.append([data[key] for key in self._columns[-1]])
            records.append(record)

        return self._format.dumps(self._columns, records)
