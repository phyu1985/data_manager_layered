""" YAML文書を重ね、モデルの値と既存のコメント・キー順を共存させる。
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
from io import StringIO
from typing import Any, cast

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.error import YAMLError
from ruamel.yaml.nodes import MappingNode, SequenceNode
from ruamel.yaml.scalarbool import ScalarBoolean

from DataManager.errors import SerializationError
from DataManager.model_conversion import ModelBinding, ModelValue


@dataclass(frozen=True)
class YamlDumpOptions:
    """ YAMLの値の出力名と、文書の引用符・字下げを指定する公開設定。
    """

    by_alias: bool = False
    preserve_quotes: bool = True
    indent_mapping: int = 2
    indent_sequence: int = 4
    indent_offset: int = 2


class YamlSerializer:
    """ テンプレート・既存文書・値を重ね、YAMLを読み書きする。

    文書の意味とコメントの継承を担当する。既存文書をいつ読むか、
    どの範囲をロックするかはRepositoryが担当する。
    """

    def __init__(self, *, dump_options: YamlDumpOptions | None = None):
        self._dump_options = dump_options or YamlDumpOptions()

    @property
    def encoding(self) -> str:
        return "utf-8"

    @property
    def supports_document_merge(self) -> bool:
        return True

    def _create_yaml_handler(self) -> Any:
        """ 1回の操作で使うハンドラを作る。
        """
        # ruamelの状態を操作間で共有せず、異なるファイルの同時処理を干渉させない。
        handler: Any = YAML(typ="rt")
        handler.preserve_quotes = self._dump_options.preserve_quotes
        handler.indent(
            mapping=self._dump_options.indent_mapping,
            sequence=self._dump_options.indent_sequence,
            offset=self._dump_options.indent_offset,
        )
        return handler

    def _load_document(self, serialized_text: str) -> dict[str, Any]:
        """ 最上位が文字列キーのマッピングである文書だけを受け入れる。
        """
        try:
            handler = self._create_yaml_handler()

            # round-tripの値構築で循環エイリアスがNoneになる前に、構文ノードを検査する。
            syntax_tree: object = handler.compose(serialized_text)
            self._validate_yaml_aliases(syntax_tree, set())
            document: object = handler.load(serialized_text)
        except YAMLError as error:
            raise SerializationError(f"YAMLを解析できません: {error}") from error

        if document is None:
            return cast(dict[str, Any], CommentedMap())
        if not isinstance(document, Mapping):
            raise SerializationError("YAMLのトップレベルはマッピングである必要があります")
        mapping_value = cast(Mapping[object, Any], document)
        if not all(isinstance(key, str) for key in mapping_value):
            raise SerializationError("YAMLのキーはstrで指定してください")

        # 実体はCommentedMapのまま保持する。コメントAPIを使う箇所だけAnyで橋渡しする。
        self._to_plain_value(mapping_value, set())
        return cast(dict[str, Any], document)

    def _validate_yaml_aliases(self, node: object, ancestor_ids: set[int]):
        """ 値へ変換する前の構文木で、循環するエイリアスを拒否する。
        """
        if not isinstance(node, (MappingNode, SequenceNode)):
            return
        if id(node) in ancestor_ids:
            raise SerializationError("循環するYAMLエイリアスには対応していません")

        # ruamel固有のノードAPIはここで扱い、モデル復元側には持ち込まない。
        yaml_node: Any = node
        if isinstance(node, MappingNode):
            field_pairs = cast(list[tuple[object, object]], yaml_node.value)
            child_nodes = [item for field_pair in field_pairs for item in field_pair]
        else:
            child_nodes = cast(list[object], yaml_node.value)

        ancestor_ids.add(id(node))
        try:
            for child in child_nodes:
                self._validate_yaml_aliases(child, ancestor_ids)
        finally:
            ancestor_ids.remove(id(node))

    def _to_plain_value(self, value: object, ancestor_ids: set[int]) -> Any:
        """ 編集用ノードを通常の辞書・配列へ戻し、循環参照と不正なキーを拒否する。
        """
        if isinstance(value, dict):
            mapping_value = cast(dict[object, Any], value)
            if id(mapping_value) in ancestor_ids:
                raise SerializationError("循環するYAMLエイリアスには対応していません")
            ancestor_ids.add(id(mapping_value))
            try:
                result: dict[str, Any] = {}
                for key, item in mapping_value.items():
                    if not isinstance(key, str):
                        raise SerializationError("YAMLのキーはstrで指定してください")
                    result[str(key)] = self._to_plain_value(item, ancestor_ids)
                return result
            finally:
                ancestor_ids.remove(id(mapping_value))

        if isinstance(value, list):
            sequence_value = cast(list[object], value)
            if id(sequence_value) in ancestor_ids:
                raise SerializationError("循環するYAMLエイリアスには対応していません")
            ancestor_ids.add(id(sequence_value))
            try:
                return [self._to_plain_value(item, ancestor_ids) for item in sequence_value]
            finally:
                ancestor_ids.remove(id(sequence_value))

        # 編集用のスカラーも通常の型へ戻す。ScalarBooleanはintの派生なので先に判定する。
        if isinstance(value, (bool, ScalarBoolean)):
            return bool(value)
        if isinstance(value, str):
            return str(value)
        if isinstance(value, int):
            return int(value)
        if isinstance(value, float):
            return float(value)
        if value is None or isinstance(value, (bytes, date, datetime)):
            return value
        raise SerializationError(f"通常のYAML値として扱えない型です: {type(value).__name__}")

    def _merge_document(self, destination: dict[str, Any], source: dict[str, Any], *, copy_comments: bool):
        """ マッピングを再帰的に重ね、配列と単一値は全体を置き換える。
        """
        destination_node: Any = destination
        source_node: Any = source

        if copy_comments:
            # 文書冒頭とキーごとのコメントは既存文書を優先し、ない箇所はテンプレートを残す。
            if source_node.ca.comment is not None:
                destination_node.ca.comment = deepcopy(source_node.ca.comment)
            if source_node.ca.end:
                destination_node.ca.end = deepcopy(source_node.ca.end)

        for field_name, field_value in source.items():
            if isinstance(field_value, dict):
                existing_value = destination.get(field_name)
                if not isinstance(existing_value, dict):
                    destination[field_name] = CommentedMap()
                self._merge_document(
                    destination[field_name], cast(dict[str, Any], field_value), copy_comments=copy_comments,
                )
            else:
                destination[field_name] = deepcopy(field_value)

            if copy_comments and field_name in source_node.ca.items:
                destination_node.ca.items[field_name] = deepcopy(source_node.ca.items[field_name])

    def dumps(
        self, value: ModelValue, model_binding: ModelBinding[ModelValue], *,
        existing_text: str | None = None, template_text: str | None = None,
    ) -> str:
        """ テンプレート・既存文書・モデル値を重ね、未指定の既存項目も残す。
        """
        return self._dump_document(value, model_binding, existing_text, template_text, exact_fields=False)

    def dumps_exact(
        self, value: ModelValue, model_binding: ModelBinding[ModelValue], *,
        existing_text: str | None = None, template_text: str | None = None,
    ) -> str:
        """ 出力項目はモデル値に限定し、存続するキーの配置・コメントを再利用する。
        """
        return self._dump_document(value, model_binding, existing_text, template_text, exact_fields=True)

    def _keep_output_fields(self, document: dict[str, Any], values: dict[str, Any]):
        """ 全階層で廃止キーを除く。テンプレートの既定値からも復活させない。
        """
        for key in list(document):
            if key not in values:
                del document[key]
            elif isinstance(document[key], dict) and isinstance(values[key], dict):
                # YAMLアンカーで共有された辞書も、出力先ごとに独立して更新する。
                child: Any = deepcopy(document[key])
                child.yaml_set_anchor(None)
                document[key] = child
                self._keep_output_fields(document[key], values[key])

    def _dump_document(
        self, value: ModelValue, model_binding: ModelBinding[ModelValue],
        existing_text: str | None, template_text: str | None, *, exact_fields: bool,
    ) -> str:
        # まず書式の土台を作る。既存文書のコメントをテンプレートより優先する。
        document = self._load_document(template_text or "")
        if existing_text is not None:
            self._merge_document(document, self._load_document(existing_text), copy_comments=True)

        data = model_binding.to_dict(value, by_alias=self._dump_options.by_alias)
        self._to_plain_value(data, set())

        # 版変換後の辞書が保存仕様の正本。既存文書は書式だけに利用する。
        if exact_fields:
            self._keep_output_fields(document, data)
        self._merge_document(document, data, copy_comments=False)

        # 値の反映を終えた編集用文書を、最後にYAML文字列へ書き出す。
        output = StringIO()
        try:
            self._create_yaml_handler().dump(document, output)
        except YAMLError as error:
            raise SerializationError(f"YAMLへ変換できません: {error}") from error

        return output.getvalue()

    def loads(self, serialized_text: str, model_binding: ModelBinding[ModelValue]) -> ModelValue:
        """ YAMLの値から、指定型のモデルまたは通常のdictを復元する。
        """
        document = self._load_document(serialized_text)
        # コメントを持つ編集用ノードを、利用側へ返す辞書に持ち出さない。
        return model_binding.restore_value(self._to_plain_value(document, set()))
