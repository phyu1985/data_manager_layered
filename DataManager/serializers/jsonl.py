""" 単一・混在モデルとdict一覧のJSONL。型識別は本文と同じ階層に置く。
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from pydantic import BaseModel, ValidationError

from DataManager.errors import ConfigurationError, SerializationError
from DataManager.model_conversion import ModelBinding, ModelValue
from DataManager.serializers.json import parse_json_object, serialize_json_object


@dataclass(frozen=True)
class JSONLDumpOptions:
    """ JSONL出力の設定。利用側が指定する公開項目で、生成後は変更できない。
    """

    by_alias: bool = False
    ensure_ascii: bool = False


@dataclass(frozen=True)
class JSONLLoadOptions:
    """ 内部形式と、メタなしの外部JSONLの読み方を明示する設定。

    requiredは先頭のメタ行を検証する。absentは全行を本文として読む。
    形式の推測はせず、混在モデルにはrequiredを要求する。
    """

    metadata: Literal["required", "absent"] = "required"


class JsonlSerializer:
    """ 一覧をJSONLへ変換し、メタ情報とtagに基づいてモデルを復元する。

    保存時は先頭のメタ行と本文を作り、混在モデルにだけ平坦なtagキーを加える。
    読み込み時はメタの一致を確認し、各行のtagから許可済みのクラスを選んで検証する。
    本文だけの変換とメタ行の操作を分け、Repositoryが追記でも再利用できるようにする。
    ファイルの読み書きやロックは扱わない。
    """

    def __init__(
        self,
        *,
        tag_field: str = "type",
        model_tags: Mapping[type[BaseModel], str] | None = None,
        dump_options: JSONLDumpOptions | None = None,
        load_options: JSONLLoadOptions | None = None,
    ):
        """ tagのキー名・固定名と、形式専用の読み書き設定を保持する。
        """
        # 具体的なモデルはRepositoryから後で渡される。ここではキー名だけを確認する。
        if not tag_field.strip():
            raise ConfigurationError("tag_fieldは空白以外の文字を含む必要があります")

        self._tag_field = tag_field
        self._model_tags: dict[type[object], str] = {
            model_class: tag for model_class, tag in (model_tags or {}).items()
        }
        self._dump_options = dump_options or JSONLDumpOptions()
        self._load_options = load_options or JSONLLoadOptions()
        if self._load_options.metadata not in ("required", "absent"):
            raise ConfigurationError("metadataはrequiredまたはabsentを指定してください")

    @property
    def encoding(self) -> str:
        """ Repositoryがバイト列の入出力に使う文字コードを返す。
        """
        return "utf-8"

    def validate_model_configuration(self, model_binding: ModelBinding[ModelValue]):
        """ 指定されたモデルで、このSerializerの設定を使えるか確認する。
        """
        # 対応表の構築で未指定の型・重複・衝突を検出する。共有状態へのキャッシュはしない。
        self._build_models_by_tag(model_binding)

    def _build_models_by_tag(
        self,
        model_binding: ModelBinding[ModelValue],
    ) -> dict[str, type[ModelValue]]:
        """ 型名から許可済みクラスを選ぶための対応表を返す。
        """
        # 固定tagの指定が、Repositoryで許可していないクラスを持ち込まないようにする。
        if any(
            model_class not in model_binding.model_classes
            for model_class in self._model_tags
        ):
            raise ConfigurationError("model_tagsに未指定のモデルが含まれています")

        models_by_tag: dict[str, type[ModelValue]] = {}

        if model_binding.data_mode == "dict":
            return models_by_tag

        # 長期保存用の固定名を優先し、省略された型だけクラス名を使う。
        for model_class in model_binding.model_classes:
            tag = self._model_tags.get(model_class, model_class.__name__)

            if not tag.strip() or tag in models_by_tag:
                raise ConfigurationError(f"型名が空白または重複しています: {tag!r}")

            models_by_tag[tag] = model_class

        if model_binding.data_mode == "mixed":
            self._validate_tag_field_collisions(model_binding)

        return models_by_tag

    def _validate_tag_field_collisions(self, model_binding: ModelBinding[ModelValue]):
        """ tagの追加・除去で業務データを上書きしたり失ったりしないようにする。
        """
        # 静的なフィールドを先に確認し、計算フィールド等は実際の出力時にも確認する。
        for model_class in model_binding.model_classes:
            if not issubclass(model_class, BaseModel):
                continue

            for field_name, field_definition in model_class.model_fields.items():
                output_name = field_name

                # 別名で出力するときも、tagの追加・除去で業務フィールドを失わないようにする。
                if self._dump_options.by_alias:
                    output_name = (
                        field_definition.serialization_alias
                        or field_definition.alias
                        or field_name
                    )

                if self._tag_field in (field_name, output_name):
                    raise ConfigurationError(
                        f"{model_class.__name__}.{field_name}と"
                        f"tagキー{self._tag_field!r}が衝突します"
                    )

    def _build_metadata(self, model_binding: ModelBinding[ModelValue]) -> dict[str, Any]:
        """ ファイルの用途を照合するためのメタ情報を作る。
        """
        # 型を指定した順序だけでメタの不一致にならないよう、型名は並べ替えて記録する。
        metadata: dict[str, Any] = {
            "schema_version": 1,
            "mode": model_binding.data_mode,
            "models": sorted(self._build_models_by_tag(model_binding)),
        }

        if model_binding.data_mode == "mixed":
            metadata["tag_field"] = self._tag_field

        return metadata

    def serialize_metadata_line(self, model_binding: ModelBinding[ModelValue]) -> str:
        """ 全件保存と新規追記に使う、改行付きのメタ行を返す。
        """
        metadata_record = {"__meta__": self._build_metadata(model_binding)}

        return serialize_json_object(
            metadata_record,
            ensure_ascii=False,
            indent=None,
        ) + "\n"

    def validate_metadata_line(
        self,
        serialized_text: str,
        model_binding: ModelBinding[ModelValue],
    ):
        """ メタ行の構造と内容が、指定モデル・形式に一致するか確認する。
        """
        metadata_record = parse_json_object(serialized_text)
        expected_metadata = self._build_metadata(model_binding)
        parsed_metadata = metadata_record.get("__meta__")

        # まずメタ専用行の構造を確認し、その後で設定との一致を調べる。
        if set(metadata_record) != {"__meta__"} or not isinstance(parsed_metadata, dict):
            raise SerializationError("JSONLのメタ情報がRepositoryの型・形式と一致しません")

        actual_metadata = cast(dict[str, Any], parsed_metadata)

        # True == 1となるため、バージョンは等値だけでなくint型であることも確認する。
        if (
            type(actual_metadata.get("schema_version")) is not int
            or actual_metadata != expected_metadata
        ):
            raise SerializationError("JSONLのメタ情報がRepositoryの型・形式と一致しません")

    def serialize_data_lines(
        self,
        rows: Sequence[ModelValue],
        model_binding: ModelBinding[ModelValue],
    ) -> str:
        """ 全件保存・追記に使う、メタ行を含まない本文を返す。
        """
        models_by_tag = self._build_models_by_tag(model_binding)
        # 読み込み用のtag→モデル表を、保存時に必要なモデル→tag表へ反転する。
        tags_by_model = {
            model_class: tag for tag, model_class in models_by_tag.items()
        }
        serialized_lines: list[str] = []

        for row_number, value in enumerate(rows, 1):
            data = model_binding.to_dict(
                value,
                by_alias=self._dump_options.by_alias,
            )

            # 実際の出力も確認し、計算フィールド等のtagキーを黙って上書きしない。
            if model_binding.data_mode == "mixed":
                if self._tag_field in data:
                    raise SerializationError(f"JSONL行{row_number}: tagキーが本文と衝突します")

                data = {
                    self._tag_field: tags_by_model[type(value)],
                    **data,
                }

            serialized_line = serialize_json_object(
                data,
                ensure_ascii=self._dump_options.ensure_ascii,
                indent=None,
            )
            serialized_lines.append(serialized_line + "\n")

        return "".join(serialized_lines)

    def dumps(
        self,
        rows: Sequence[ModelValue],
        model_binding: ModelBinding[ModelValue],
    ) -> str:
        """ メタ行を含むJSONL全体を、改行付き文字列として返す。
        """
        # 全件置換では古いメタ行も消えるため、ファイルの有無によらず毎回生成する。
        metadata_line = self.serialize_metadata_line(model_binding)
        data_lines = self.serialize_data_lines(rows, model_binding)

        return metadata_line + data_lines

    def deserialize_data_line(
        self,
        serialized_text: str,
        model_binding: ModelBinding[ModelValue],
    ) -> ModelValue:
        """ 本文1行から、指定型のモデルまたはdictを復元する。
        """
        data = parse_json_object(serialized_text)

        if model_binding.data_mode != "mixed":
            return model_binding.restore_value(data)

        # tagは保存形式の情報なので、モデルのフィールド検証へ渡す前に取り除く。
        tag = data.pop(self._tag_field, None)
        models_by_tag = self._build_models_by_tag(model_binding)

        if not isinstance(tag, str) or tag not in models_by_tag:
            raise SerializationError(f"JSONLの型名が未指定または未登録です: {tag!r}")

        # 許可済みのクラスを選んで検証・生成する。ファイルの型名から任意のクラスは探さない。
        return model_binding.restore_value(data, models_by_tag[tag])

    def loads(
        self,
        serialized_text: str,
        model_binding: ModelBinding[ModelValue],
    ) -> list[ModelValue]:
        """ JSONL文字列から、指定型の値のリストを復元する。
        """
        if self._load_options.metadata == "absent" and model_binding.data_mode == "mixed":
            raise ConfigurationError("混在JSONLはメタ行が必要です")

        # 空白行を除いても、検証エラーにファイル上の行番号を付けられるよう元の番号を残す。
        numbered_lines = (
            (line_number, line)
            for line_number, line in enumerate(serialized_text.splitlines(), 1)
            if line.strip()
        )

        # absentでは先頭から全行を本文として扱い、業務行をメタと推測して捨てない。
        if self._load_options.metadata == "required":
            first_line = next(numbered_lines, None)

            if first_line is None:
                raise SerializationError("JSONLにメタ行がありません")

            self.validate_metadata_line(first_line[1], model_binding)

        restored_values: list[ModelValue] = []

        for line_number, line in numbered_lines:
            try:
                restored_values.append(self.deserialize_data_line(line, model_binding))
            except (SerializationError, ValidationError) as error:
                raise SerializationError(f"JSONL行{line_number}: {error}") from error

        return restored_values
