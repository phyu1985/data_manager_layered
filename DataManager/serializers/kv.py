""" コメントヘッダとkey/valueを、一つのオブジェクトへ対応付ける。
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
import json
from typing import Any, Literal

from DataManager.errors import ConfigurationError, SerializationError
from DataManager.model_conversion import ModelBinding, ModelValue
from DataManager.serializers.field_paths import flatten_fields, unflatten_fields
from DataManager.serializers.json import parse_json_value


@dataclass(frozen=True)
class KvOptions:
    """ ヘッダと本文の文法。出力は識別行のないkey:JSON値へ揃える。

    separatorは項目の階層、key_value_separatorはキーと値の区切り。
    コメントの取り込み方はwith_value_header / with_key_value_headerで選ぶ。
    """

    by_alias: bool = False
    separator: str = "."
    key_value_separator: str = ":"
    comment_prefixes: tuple[str, ...] = ("#", ";")
    _header_keys: tuple[str, ...] | None = ()
    _header_skip: int = 0
    inline_comments: bool = True

    def __post_init__(self):
        """ 本文とコメントの記号を確定する。ヘッダ方式は名前付きメソッドで選ぶ。
        """
        if not self.separator or any(c in self.separator for c in ":\r\n"):
            raise ConfigurationError("キーの階層区切りが不正です")
        if not self.key_value_separator or any(c in self.key_value_separator for c in "\r\n"):
            raise ConfigurationError("キーと値の区切りが不正です")
        if any(not prefix or "\n" in prefix or "\r" in prefix for prefix in self.comment_prefixes):
            raise ConfigurationError("コメントの開始記号が不正です")

    def with_value_header(self, keys: Sequence[str], *, skip: int = 0) -> KvOptions:
        """ 値だけのコメントへ、指定した順にキーを与える新しい設定を返す。
        """
        if isinstance(keys, str):
            raise ConfigurationError("keysは文字列一つではなく、キーの一覧で指定してください")
        names = tuple(keys)
        if not names or any(not key.strip() for key in names) or len(set(names)) != len(names):
            raise ConfigurationError("値ヘッダには空欄・重複のないキー一覧が必要です")
        return self._with_header(names, skip)

    def with_key_value_header(self, *, skip: int = 0) -> KvOptions:
        """ コメント自身のキーを使う新しい設定を返す。外部のキー一覧は不要。
        """
        return self._with_header(None, skip)

    def _with_header(self, keys: tuple[str, ...] | None, skip: int) -> KvOptions:
        """ 選択したヘッダ規則を保持する。モードとキー一覧の組合せは生成側で確定済み。
        """
        if type(skip) is not int or skip < 0:
            raise ConfigurationError("skipは0以上の整数です")
        return replace(self, _header_keys=keys, _header_skip=skip)

    @property
    def header_keys(self) -> tuple[str, ...]:
        """ 値だけのヘッダへ与えるキーを返す。
        """
        return self._header_keys or ()

    @property
    def header_layout(self) -> Literal["values", "key_value"]:
        """ キーの外部指定の有無から方式を求め、別のモード指定との矛盾をなくす。
        """
        return "key_value" if self._header_keys is None else "values"

    @property
    def header_skip(self) -> int:
        """ 先頭説明として飛ばすコメント件数を返す。
        """
        return self._header_skip


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
        # 標準書式で保存できる設定か確認する。入力専用の配置はそのまま書き戻さない。
        if existing_text is not None or template_text is not None:
            raise ConfigurationError("KV形式は元の文書のマージに対応しません")
        if self._options.header_keys or self._options.header_layout != "values" or self._options.key_value_separator != ":":
            raise ConfigurationError("既存入力用の設定です。標準出力には既定のKvSerializerを指定してください")

        # 階層付きキーへ展開し、値だけをJSON化して型を保つ標準書式へ揃える。
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

        # 先頭のコメント群はヘッダ候補として集め、本文のkey/valueとは分けて読む。
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

        # 本文を読み終えた後にヘッダを解釈し、同じ辞書へ合流させる。
        pairs = self._header_pairs(header_values)

        for key, value in pairs:
            if key in fields:
                raise SerializationError(f"ヘッダと本文でキーが重複しています: {key}")
            fields[key] = value

        # 形式由来の配置をここで解消し、モデルには通常の階層辞書を渡す。
        return model_binding.restore_value(unflatten_fields(fields, separator=options.separator))

    def _header_pairs(self, values: list[str]) -> list[tuple[str, Any]]:
        """ 確定したヘッダ方式に沿って、位置またはキーから値を取り出す。
        """
        options = self._options
        selected = values[options.header_skip:]
        if options.header_layout == "key_value":
            if not selected:
                raise SerializationError("キー付きのコメントヘッダがありません")
            return [self._read_pair(value, f"KVヘッダ項目{i + 1}") for i, value in enumerate(selected)]

        selected = selected[:len(options.header_keys)]
        if len(selected) != len(options.header_keys):
            raise SerializationError("ヘッダ項目に対応するコメント値がありません")
        return [(key, parse_text_value(value)) for key, value in zip(options.header_keys, selected)]

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
