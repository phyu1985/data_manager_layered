""" ObjectとRowsで共用するYAMLの読取・値検証。文書の合成や行モデルは扱わない。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, cast

from ruamel.yaml.error import YAMLError
from ruamel.yaml.nodes import MappingNode, SequenceNode
from ruamel.yaml.scalarbool import ScalarBoolean

from DataManager.errors import SerializationError


def load_yaml_value(serialized_text: str, handler: Any) -> Any:
    """ 編集用ノードを構築する前に循環エイリアスを検出し、YAMLを読み取る。
    """
    try:
        # ruamelが循環エイリアスをNoneへ変える前に、元の構文で検出する。
        syntax_tree: object = handler.compose(serialized_text)
        _validate_yaml_aliases(syntax_tree, set())
        return handler.load(serialized_text)
    except YAMLError as error:
        raise SerializationError(f"YAMLを解析できません: {error}") from error


def _validate_yaml_aliases(node: object, ancestor_ids: set[int]):
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
            _validate_yaml_aliases(child, ancestor_ids)
    finally:
        ancestor_ids.remove(id(node))


def to_plain_yaml_value(value: object, ancestor_ids: set[int]) -> Any:
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
                result[str(key)] = to_plain_yaml_value(item, ancestor_ids)
            return result
        finally:
            ancestor_ids.remove(id(mapping_value))

    if isinstance(value, list):
        sequence_value = cast(list[object], value)
        if id(sequence_value) in ancestor_ids:
            raise SerializationError("循環するYAMLエイリアスには対応していません")
        ancestor_ids.add(id(sequence_value))
        try:
            return [to_plain_yaml_value(item, ancestor_ids) for item in sequence_value]
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

