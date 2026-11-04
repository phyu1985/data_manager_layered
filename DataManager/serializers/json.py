""" 単一モデル・dictとJSON文字列の相互変換。ファイル操作は行わない。
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from math import isfinite
from typing import Any, NoReturn, cast

from DataManager.errors import ConfigurationError, SerializationError
from DataManager.model_conversion import ModelBinding, ModelValue


@dataclass(frozen=True)
class JsonDumpOptions:
    """ JSON出力の設定。利用側が指定する公開項目で、生成後は変更できない。
    """

    by_alias: bool = False
    indent: int | None = 2
    ensure_ascii: bool = False


def parse_json_value(serialized_text: str) -> object:
    """ JSON値を解析し、重複キーや保持できない数値をエラーにする。
    """

    # Pythonのjsonが受け付けるNaN等も、標準JSONで往復できない値として拒否する。
    def reject_invalid_number(value: str) -> NoReturn:
        raise SerializationError(f"JSONの数値として不正です: {value}")

    def parse_finite_float(value: str) -> float:
        parsed_number = float(value)
        if not isfinite(parsed_number):
            raise SerializationError(f"JSONの数値を有限値として保持できません: {value}")
        return parsed_number

    def collect_unique_fields(field_pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for field_name, field_value in field_pairs:
            if field_name in data:
                raise SerializationError(f"JSONのキーが重複しています: {field_name!r}")
            data[field_name] = field_value
        return data

    try:
        # 通常のjson.loadsでは重複値の片方が消え、1e999はinfになる。変換時に検出する。
        return json.loads(
            serialized_text,
            parse_constant=reject_invalid_number,
            parse_float=parse_finite_float,
            object_pairs_hook=collect_unique_fields,
        )
    except json.JSONDecodeError as error:
        raise SerializationError(f"JSONを解析できません: {error}") from error


def parse_json_object(serialized_text: str) -> dict[str, Any]:
    """ JSON文字列を解析し、最上位が辞書であることを確認する。
    """
    parsed_value = parse_json_value(serialized_text)

    # ここでは辞書という構造までを保証し、業務フィールドの検証はModelBindingに任せる。
    if not isinstance(parsed_value, dict):
        raise SerializationError("JSONのトップレベルはオブジェクトである必要があります")

    return cast(dict[str, Any], parsed_value)


def serialize_json_object(data: dict[str, Any], *, ensure_ascii: bool, indent: int | None) -> str:
    """ 辞書をJSON文字列へ変換し、表現できない値を失敗として伝える。
    """
    # 任意のPython値を文字列へ補正すると復元不能になるため、表現できない値はエラーにする。
    try:
        return json.dumps(
            data,
            ensure_ascii=ensure_ascii,
            indent=indent,
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise SerializationError(f"JSONへ変換できません: {error}") from error


class JsonSerializer:
    """ 単一値とJSONを相互変換し、モデルの辞書化・検証はModelBindingへ委譲する。

    出力設定を保持し、Repositoryでの既定値の重複を防ぐ。
    """

    def __init__(self, *, dump_options: JsonDumpOptions | None = None):
        """ 専用の出力設定を保持し、省略時だけSerializer自身の既定値を使う。
        """
        self._dump_options = dump_options or JsonDumpOptions()

    @property
    def encoding(self) -> str:
        """ Repositoryがバイト列の入出力に使う文字コードを返す。
        """
        return "utf-8"

    @property
    def supports_document_merge(self) -> bool:
        return False

    def dumps(
        self, value: ModelValue, model_binding: ModelBinding[ModelValue], *,
        existing_text: str | None = None, template_text: str | None = None,
    ) -> str:
        """ 指定型の値を、改行付きJSON文字列へ変換する。
        """
        if existing_text is not None or template_text is not None:
            raise ConfigurationError("JSONは既存文書のマージに対応しません")

        # 型の確認とモデル固有の変換は共通処理へ任せ、JSONの規則と分ける。
        data = model_binding.to_dict(value, by_alias=self._dump_options.by_alias)

        return serialize_json_object(
            data,
            ensure_ascii=self._dump_options.ensure_ascii,
            indent=self._dump_options.indent,
        ) + "\n"

    def loads(self, serialized_text: str, model_binding: ModelBinding[ModelValue]) -> ModelValue:
        """ JSON文字列から、指定型のモデルまたはdictを復元する。
        """
        data = parse_json_object(serialized_text)

        # 解析済みの辞書で終わらず、指定モデルの検証とインスタンス生成まで行う。
        return model_binding.restore_value(data)
