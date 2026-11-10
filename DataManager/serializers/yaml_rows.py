""" YAMLのレコード一覧を、RowsRepositoryの共通I/Fで読み書きする。
"""
from __future__ import annotations

from collections.abc import Sequence
from io import StringIO
from typing import Any, cast

from pydantic import ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from DataManager.documents import RowsDocument
from DataManager.errors import ConfigurationError, SerializationError
from DataManager.model_conversion import ModelBinding, ModelValue
from DataManager.serializers.yaml_values import load_yaml_value, to_plain_yaml_value


class YamlRowsSerializer:
    """ 一覧はlist、メタ付き一覧はmetadata/rowsを持つ一文書として保存する。

    単一種類のモデルまたはdictを扱い、全件を置き換える。ロックと保存はRepositoryへ任せる。
    Object用YAMLのテンプレート合成・既存コメントの継承は行わない。
    """

    def __init__(self, *, by_alias: bool = False):
        self._by_alias = by_alias

    @property
    def encoding(self) -> str:
        return "utf-8"

    def validate_model_configuration(self, model_binding: ModelBinding[ModelValue]):
        """ 型情報を持たない一覧で、行の復元先を推測しない。
        """
        if model_binding.data_mode == "mixed":
            raise ConfigurationError(
                "YAMLの一覧は単一モデルまたはdictを指定してください。"
                "混在型の版管理にはVersionedRowsRepository.for_modelsを使用できます"
            )

    def _create_yaml_handler(self) -> Any:
        """ 操作ごとに状態を分離し、文書内の配列を読みやすく字下げする。
        """
        handler: Any = YAML(typ="rt")
        handler.indent(mapping=2, sequence=4, offset=2)
        return handler

    def _encode_rows(
        self, rows: Sequence[ModelValue], model_binding: ModelBinding[ModelValue],
    ) -> list[dict[str, Any]]:
        """ 行の型と辞書のキーを共通処理で確認し、保存用の値へ変換する。
        """
        self.validate_model_configuration(model_binding)
        records: list[dict[str, Any]] = []
        for row_number, row in enumerate(rows, start=1):
            data = cast(object, model_binding.to_dict(row, by_alias=self._by_alias))
            # RootModelや独自のmodel_serializerでも、保存結果を行のdictに限定する。
            if not isinstance(data, dict):
                raise SerializationError(f"YAMLの{row_number}件目のモデル出力はdictが必要です")
            records.append(cast(dict[str, Any], data))
        return records

    def _dump_value(self, value: object) -> str:
        """ 書き戻せるYAML値かを確認してから文字列を生成する。
        """
        plain_value = to_plain_yaml_value(value, set())
        output = StringIO()
        handler = self._create_yaml_handler()
        if isinstance(plain_value, list):
            # ルートの一覧は行頭から書き、文書内のrows配列とは字下げを分ける。
            handler.indent(mapping=2, sequence=2, offset=0)
        try:
            handler.dump(plain_value, output)
        except YAMLError as error:
            raise SerializationError(f"YAMLへ変換できません: {error}") from error
        return output.getvalue()

    def dumps(self, rows: Sequence[ModelValue], model_binding: ModelBinding[ModelValue]) -> str:
        """ レコードだけをトップレベルのlistへ保存する。空一覧は[]になる。
        """
        return self._dump_value(self._encode_rows(rows, model_binding))

    def dumps_document(
        self, rows: Sequence[ModelValue], model_binding: ModelBinding[ModelValue], *, metadata: dict[str, Any],
    ) -> str:
        """ メタが空でもmetadata/rowsの形を保ち、文書保存の意図を明示する。
        """
        if not isinstance(cast(object, metadata), dict):
            raise SerializationError("YAMLのmetadataはdictが必要です")
        return self._dump_value({"metadata": metadata, "rows": self._encode_rows(rows, model_binding)})

    def loads(self, serialized_text: str, model_binding: ModelBinding[ModelValue]) -> list[ModelValue]:
        """ listとメタ付き文書のどちらからも、本文のレコードだけを返す。
        """
        return self.loads_document(serialized_text, model_binding).rows

    def loads_document(
        self, serialized_text: str, model_binding: ModelBinding[ModelValue],
    ) -> RowsDocument[dict[str, Any], ModelValue]:
        """ 文書の形を確定し、各行を指定モデルまたはdictへ復元する。
        """
        self.validate_model_configuration(model_binding)
        value = to_plain_yaml_value(load_yaml_value(serialized_text, self._create_yaml_handler()), set())

        # listはメタなし、マッピングは明示したmetadata/rowsだけを受け入れる。
        # 通常のObject文書や余分な項目を、一覧と誤認して読み捨てない。
        metadata: dict[str, Any] = {}
        raw_rows: list[object]
        if isinstance(value, list):
            raw_rows = cast(list[object], value)
        elif isinstance(value, dict) and set(cast(dict[str, Any], value)) == {"metadata", "rows"}:
            document = cast(dict[str, Any], value)
            if not isinstance(document["metadata"], dict) or not isinstance(document["rows"], list):
                raise SerializationError("YAMLのmetadataはdict、rowsはlistが必要です")
            metadata = cast(dict[str, Any], document["metadata"])
            raw_rows = cast(list[object], document["rows"])
        else:
            raise SerializationError(
                "YAMLの一覧はlist、メタ付き一覧はmetadata/rowsの文書が必要です。"
                "空一覧は[]と記載してください"
            )

        # 値の型変換はModelBinding/Pydanticへ任せ、Serializerにモデル固有の規則を持ち込まない。
        rows: list[ModelValue] = []
        for row_number, row in enumerate(raw_rows, start=1):
            if not isinstance(row, dict):
                raise SerializationError(f"YAMLの{row_number}件目はdictが必要です")
            try:
                rows.append(model_binding.restore_value(cast(dict[str, Any], row)))
            except ValidationError as error:
                raise SerializationError(f"YAMLの{row_number}件目が行モデルと一致しません: {error}") from error
        return RowsDocument(metadata=metadata, rows=rows)
