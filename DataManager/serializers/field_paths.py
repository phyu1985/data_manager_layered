""" CSVと独自テキストで、辞書の階層を区切り付きフィールド名へ対応付ける。
"""
from __future__ import annotations

from typing import Any, cast

from DataManager.errors import ConfigurationError, SerializationError


def flatten_fields(data: dict[str, Any], *, separator: str) -> dict[str, Any]:
    """ 辞書の階層を展開する。空の辞書と配列は値として残す。
    """
    if not separator:
        raise ConfigurationError("階層の区切り文字は空にできません")

    flattened_fields: dict[str, Any] = {}
    ancestor_ids: set[int] = set()

    def visit_fields(nested_fields: dict[object, Any], parent_path: str):
        # 循環参照を延々と展開せず、保存前に理由の分かるエラーにする。
        if id(nested_fields) in ancestor_ids:
            raise SerializationError("辞書の循環参照は階層フィールドへ展開できません")

        ancestor_ids.add(id(nested_fields))
        try:
            for field_name, field_value in nested_fields.items():
                if not isinstance(field_name, str) or not field_name or separator in field_name:
                    raise SerializationError(f"階層として曖昧なフィールド名です: {field_name!r}")

                field_path = f"{parent_path}{separator}{field_name}" if parent_path else field_name
                if isinstance(field_value, dict) and field_value:
                    visit_fields(cast(dict[object, Any], field_value), field_path)
                else:
                    flattened_fields[field_path] = field_value
        finally:
            ancestor_ids.remove(id(nested_fields))

    visit_fields(cast(dict[object, Any], data), "")
    return flattened_fields


def unflatten_fields(flattened_fields: dict[str, Any], *, separator: str) -> dict[str, Any]:
    """ 区切り付きフィールド名を辞書へ戻し、葉と親の衝突を拒否する。
    """
    if not separator:
        raise ConfigurationError("階層の区切り文字は空にできません")

    restored_fields: dict[str, Any] = {}
    assigned_paths: set[tuple[str, ...]] = set()

    for field_path, field_value in flattened_fields.items():
        path_parts = tuple(field_path.split(separator))
        if not all(path_parts):
            raise SerializationError(f"空の階層名があります: {field_path!r}")

        # aとa.bの両方を受け入れると、値が入力順で消えるため衝突として扱う。
        if any(
            path_parts[:len(previous)] == previous
            or previous[:len(path_parts)] == path_parts
            for previous in assigned_paths
        ):
            raise SerializationError(f"階層フィールドが衝突しています: {field_path!r}")

        # 葉の手前まで辞書を用意し、最後の一段へ値を置く。
        current_fields = restored_fields
        for path_part in path_parts[:-1]:
            if path_part not in current_fields:
                current_fields[path_part] = {}
            current_fields = current_fields[path_part]

        current_fields[path_parts[-1]] = field_value
        assigned_paths.add(path_parts)

    return restored_fields
