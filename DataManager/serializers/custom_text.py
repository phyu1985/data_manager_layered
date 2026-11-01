""" 階層フィールド:JSON値の行を使う、型を保持する独自テキストv1。
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from DataManager.errors import ConfigurationError, SerializationError
from DataManager.model_conversion import ModelBinding, ModelValue
from DataManager.serializers.field_paths import flatten_fields, unflatten_fields
from DataManager.serializers.json import parse_json_value


@dataclass(frozen=True)
class CustomTextOptions:
    """ v1の出力名と、読み書きで共有する階層区切りを指定する公開設定。
    """

    by_alias: bool = False
    separator: str = "."


class CustomTextSerializer:
    """ 階層名と値を行へ対応付ける。v0の曖昧な文字列化は引き継がない。
    """

    def __init__(self, *, options: CustomTextOptions | None = None):
        self._options = options or CustomTextOptions()
        if not self._options.separator or any(character in self._options.separator for character in ":\r\n"):
            raise ConfigurationError("独自テキストの階層区切りが不正です")

    @property
    def encoding(self) -> str:
        return "utf-8"

    @property
    def supports_document_merge(self) -> bool:
        return False

    def dumps(
        self, value: ModelValue, model_binding: ModelBinding[ModelValue], *,
        existing_text: str | None = None, template_text: str | None = None,
    ) -> str:
        """ 値の型をJSONリテラルで保持し、v1のテキストを生成する。
        """
        if existing_text is not None or template_text is not None:
            raise ConfigurationError("独自テキストは既存文書のマージに対応しません")

        data = model_binding.to_dict(value, by_alias=self._options.by_alias)
        flattened_fields = flatten_fields(data, separator=self._options.separator)
        lines = ["# v1"]

        for field_path, field_value in flattened_fields.items():
            if any(character in field_path for character in ":\r\n"):
                raise SerializationError(f"独自テキストのキーとして使えません: {field_path!r}")
            try:
                # JSON値にすることで、空文字・文字列の数字・None・配列を混同しない。
                serialized_value = json.dumps(field_value, ensure_ascii=False, allow_nan=False)
            except (TypeError, ValueError) as error:
                raise SerializationError(f"独自テキストへ変換できません: {error}") from error
            lines.append(f"{field_path}:{serialized_value}")

        return "\n".join(lines) + "\n"

    def loads(self, serialized_text: str, model_binding: ModelBinding[ModelValue]) -> ModelValue:
        """ v1の各行を解析し、階層を戻してから指定型を検証する。
        """
        numbered_lines = (
            (line_number, line)
            for line_number, line in enumerate(serialized_text.splitlines(), 1)
            if line.strip()
        )
        first_line = next(numbered_lines, None)
        if first_line is None or first_line[1].strip() != "# v1":
            raise SerializationError("独自テキストv1のヘッダーがありません。v0は別途変換が必要です")

        flattened_fields: dict[str, Any] = {}
        for line_number, line in numbered_lines:
            if ":" not in line:
                raise SerializationError(f"独自テキスト行{line_number}: キーと値の区切りがありません")
            field_path, serialized_value = line.split(":", 1)
            if not field_path or field_path in flattened_fields:
                raise SerializationError(f"独自テキスト行{line_number}: キーが空または重複しています")
            try:
                # JSON・JSONLと同じ規則で、値の中の重複キーや不正な数値も拒否する。
                flattened_fields[field_path] = parse_json_value(serialized_value)
            except SerializationError as error:
                raise SerializationError(f"独自テキスト行{line_number}: {error}") from error

        data = unflatten_fields(flattened_fields, separator=self._options.separator)
        return model_binding.restore_value(data)
