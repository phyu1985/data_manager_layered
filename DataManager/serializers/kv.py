""" コメントヘッダとkey/valueを、一つのオブジェクトへ対応付ける。
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Literal

from DataManager.errors import ConfigurationError, SerializationError
from DataManager.model_conversion import ModelBinding, ModelValue
from DataManager.serializers.field_paths import flatten_fields, unflatten_fields
from DataManager.serializers.json import parse_json_value


@dataclass(frozen=True)
class KvOptions:
    """ ヘッダと本文の文法。出力は識別行のないkey:JSON値へ揃える。

    header_skipは先頭コメント群で説明として飛ばす件数。
    separatorは項目の階層、key_value_separatorはキーと値の区切りである。
    """

    by_alias: bool = False
    separator: str = "."
    key_value_separator: str = ":"
    comment_prefixes: tuple[str, ...] = ("#", ";")
    header_keys: tuple[str, ...] = ()
    header_layout: Literal["values", "key_value"] = "values"
    header_skip: int = 0
    inline_comments: bool = True


def strip_inline_comment(text: str, prefixes: tuple[str, ...]) -> str:
    """ 引用符の外で、空白の後にある記号だけを行末コメントとする。
    """
    quoted = False
    escaped = False
    for i, character in enumerate(text):
        if escaped:
            escaped = False
            continue
        if quoted and character == "\\":
            escaped = True
            continue
        if character == '"':
            quoted = not quoted
        if not quoted and i > 0 and text[i - 1].isspace() and any(text.startswith(prefix, i) for prefix in prefixes):
            return text[:i].rstrip()
    return text


def parse_text_value(text: str) -> Any:
    """ JSON値は型を復元し、引用符なしの通常テキストは文字列として保持する。
    """
    try:
        return parse_json_value(text)
    except SerializationError:
        if text[:1] in ('"', "[", "{") or text in {"NaN", "Infinity", "-Infinity"}:
            raise
        try:
            number = float(text)
        except ValueError:
            return text
        if number in (float("inf"), float("-inf")):
            raise SerializationError("非有限数は受け付けません") from None
        return text


class KvSerializer:
    """ ヘッダ由来の値も通常のキーへ収録する。元の配置・説明コメントは保持しない。

    保存文法の識別行は要求・出力しない。指定した既存書式を読み、
    標準書式へ正規化して保存する。正規化した出力は既定設定で読み込める。
    """

    def __init__(self, *, options: KvOptions | None = None):
        self._options = options or KvOptions()
        options = self._options
        if not options.separator or any(c in options.separator for c in ":\r\n"):
            raise ConfigurationError("キーの階層区切りが不正です")
        if not options.key_value_separator or any(c in options.key_value_separator for c in "\r\n"):
            raise ConfigurationError("キーと値の区切りが不正です")
        if any(not prefix or "\n" in prefix or "\r" in prefix for prefix in options.comment_prefixes):
            raise ConfigurationError("コメントの開始記号が不正です")
        if type(options.header_skip) is not int or options.header_skip < 0:
            raise ConfigurationError("header_skipは0以上の整数です")
        if any(not key.strip() for key in options.header_keys) or len(set(options.header_keys)) != len(options.header_keys):
            raise ConfigurationError("header_keysに空欄・重複は指定できません")
        if options.header_layout not in {"values", "key_value"} or (options.header_layout == "key_value" and options.header_keys):
            raise ConfigurationError("ヘッダはvaluesとキーリスト、またはkey_valueで指定してください")

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
        """ コメント配置に依存せず、項目と型を標準書式で保存する。
        """
        if existing_text is not None or template_text is not None:
            raise ConfigurationError("KV形式は元の文書のマージに対応しません")
        if self._options.header_keys or self._options.header_layout != "values" or self._options.key_value_separator != ":":
            raise ConfigurationError("既存入力用の設定です。標準出力には既定のKvSerializerを指定してください")
        data = model_binding.to_dict(value, by_alias=self._options.by_alias)
        lines: list[str] = []
        for key, item in flatten_fields(data, separator=self._options.separator).items():
            if not key or key != key.strip() or any(c in key for c in ":\r\n") or any(key.startswith(p) for p in self._options.comment_prefixes):
                raise SerializationError(f"KVのキーとして保存できません: {key!r}")
            try:
                lines.append(f"{key}:{json.dumps(item, ensure_ascii=False, allow_nan=False)}")
            except (ValueError, TypeError) as error:
                raise SerializationError(f"KVへ保存できません: {error}") from error
        return "\n".join(lines) + ("\n" if lines else "")

    def loads(self, serialized_text: str, model_binding: ModelBinding[ModelValue]) -> ModelValue:
        """ ヘッダ値は区切りで分解せず、指定されたキーで本文と合わせる。
        """
        options = self._options
        fields: dict[str, Any] = {}
        header_values: list[str] = []
        in_header = True
        for line_number, original in enumerate(serialized_text.splitlines(), 1):
            line = original.strip()
            if not line:
                continue
            prefix = next((p for p in options.comment_prefixes if line.startswith(p)), None)
            if prefix is not None:
                if in_header:
                    header_values.append(line[len(prefix):].strip())
                continue
            in_header = False
            key, value = self._read_pair(line, f"KV行{line_number}")
            if key in fields:
                raise SerializationError(f"KV行{line_number}: キーが重複しています: {key}")
            fields[key] = value

        if options.header_layout == "key_value":
            selected = header_values[options.header_skip:]
            if not selected:
                raise SerializationError("キー付きのコメントヘッダがありません")
            pairs = [self._read_pair(value, f"KVヘッダ項目{i + 1}") for i, value in enumerate(selected)]
        else:
            selected = header_values[options.header_skip:options.header_skip + len(options.header_keys)]
            if len(selected) != len(options.header_keys):
                raise SerializationError("ヘッダ項目に対応するコメント値がありません")
            pairs = [(key, parse_text_value(value)) for key, value in zip(options.header_keys, selected)]
        for key, value in pairs:
            if key in fields:
                raise SerializationError(f"ヘッダと本文でキーが重複しています: {key}")
            fields[key] = value

        return model_binding.restore_value(unflatten_fields(fields, separator=options.separator))

    def _read_pair(self, line: str, location: str) -> tuple[str, Any]:
        """ 先にキーと値を分け、値の中の行末コメントだけを取り除く。
        """
        options = self._options
        if options.key_value_separator.isspace():
            cells = line.split(None, 1)
            if len(cells) == 2:
                cells[1] = " " + cells[1]
        else:
            key, found, value = line.partition(options.key_value_separator)
            cells = [key, value] if found else []
        if len(cells) != 2 or not cells[0].strip():
            raise SerializationError(f"{location}: キーと値を分割できません")
        key, raw = cells
        raw = strip_inline_comment(raw, options.comment_prefixes) if options.inline_comments else raw
        try:
            return key.strip(), parse_text_value(raw.strip())
        except SerializationError as error:
            raise SerializationError(f"{location}: {error}") from error
