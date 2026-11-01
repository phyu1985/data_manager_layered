""" 単一種類のモデル・dict一覧を、階層付きの列名でCSVへ対応付ける。
"""
from __future__ import annotations

from collections.abc import Sequence
import csv
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from io import StringIO
from types import UnionType
from typing import Any, Union, get_args, get_origin
from uuid import UUID

from pydantic import BaseModel, ValidationError

from ..errors import ConfigurationError, SerializationError
from ..model_conversion import ModelBinding, ModelValue
from .field_paths import flatten_fields, unflatten_fields


@dataclass(frozen=True)
class CSVDumpOptions:
    """ CSV出力の列・見出し・階層区切りを指定する公開設定。
    """

    by_alias: bool = False
    include_header: bool = True
    columns: tuple[str, ...] | None = None
    separator: str = "."


@dataclass(frozen=True)
class CSVLoadOptions:
    """ CSV入力の見出しと空欄の扱いを明示する公開設定。
    """

    has_header: bool = True
    columns: tuple[str, ...] | None = None
    empty_as_none: bool = True
    separator: str = "."


class CsvSerializer:
    """ 一覧とCSVを変換する。混在モデルの型判別と配列の行展開は扱わない。
    """

    def __init__(
        self, *, dump_options: CSVDumpOptions | None = None,
        load_options: CSVLoadOptions | None = None, encoding: str = "utf-8",
    ):
        self._dump_options = dump_options or CSVDumpOptions()
        self._load_options = load_options or CSVLoadOptions()
        self._encoding = encoding

        if not self._dump_options.separator or not self._load_options.separator:
            raise ConfigurationError("CSVの階層区切り文字は空にできません")

    @property
    def encoding(self) -> str:
        return self._encoding

    def validate_model_configuration(self, model_binding: ModelBinding[ModelValue]):
        """ 型判別を持たないCSVへ混在モデルを渡していないか確認する。
        """
        if model_binding.data_mode == "mixed":
            raise ConfigurationError("CSVは単一モデルまたはdict一覧に対応します")

    def _validate_columns(self, columns: Sequence[str]):
        if not columns or any(not column for column in columns) or len(set(columns)) != len(columns):
            raise SerializationError("CSVの列名は空欄・重複のない1個以上を指定してください")

        # 値を入れる前に、親の列aと子の列a.bが共存していないか確認する。
        unflatten_fields(
            dict.fromkeys(columns), separator=self._dump_options.separator,
        )

    def _columns_for_empty_models(
        self, model_class: type[Any], prefix: str = "", *,
        ancestor_models: frozenset[type[Any]] = frozenset(),
    ) -> list[str]:
        """ 空一覧でも決められる固定モデルの列だけを取り出す。
        """
        if model_class in ancestor_models:
            raise ConfigurationError("再帰モデルの空CSVには有限のcolumnsを指定してください")
        ancestor_models = ancestor_models | {model_class}

        columns: list[str] = []
        for field_name, field_definition in model_class.model_fields.items():
            if field_definition.exclude is True:
                continue
            output_name = field_name
            if self._dump_options.by_alias:
                output_name = field_definition.serialization_alias or field_definition.alias or field_name

            field_path = prefix + output_name
            if self._dump_options.separator in output_name:
                raise SerializationError(f"階層として曖昧なフィールド名です: {output_name!r}")
            annotation = field_definition.annotation
            # OptionalのNoneだけを外す。list[int]までintと解釈しないよう、Unionに限定する。
            if get_origin(annotation) in (UnionType, Union):
                possible_types = [item for item in get_args(annotation) if item is not type(None)]
                if len(possible_types) == 1:
                    annotation = possible_types[0]

            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                columns.extend(self._columns_for_empty_models(
                    annotation, field_path + self._dump_options.separator,
                    ancestor_models=ancestor_models,
                ))
            elif annotation in (dict, list) or get_args(annotation):
                raise ConfigurationError("可変の階層を持つ空CSVにはcolumnsを指定してください")
            else:
                columns.append(field_path)
        return columns

    def dumps(self, rows: Sequence[ModelValue], model_binding: ModelBinding[ModelValue]) -> str:
        """ 全行から列集合を決め、見出しと本文を生成する。
        """
        self.validate_model_configuration(model_binding)
        flattened_rows: list[dict[str, Any]] = []

        for value in rows:
            data = model_binding.to_dict(value, by_alias=self._dump_options.by_alias)
            flattened_fields = flatten_fields(
                data, separator=self._dump_options.separator,
            )
            if any(
                item is not None and not isinstance(item, (str, int, float, bool, date, datetime, Decimal, UUID))
                for item in flattened_fields.values()
            ):
                raise SerializationError("CSVの配列・空の階層・任意オブジェクトは暗黙に文字列化しません")
            flattened_rows.append(flattened_fields)

        # 1行目だけで決めると、後続行にしかない可変キーが保存されず消えてしまう。
        columns = list(self._dump_options.columns or ())
        if self._dump_options.columns is None:
            columns = list(dict.fromkeys(key for row in flattened_rows for key in row))
            if not rows and model_binding.data_mode == "single":
                columns = self._columns_for_empty_models(model_binding.model_classes[0])

        self._validate_columns(columns)
        if any(set(row) - set(columns) for row in flattened_rows):
            raise SerializationError("指定したCSV列に含まれない値があります")

        output = StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
        if self._dump_options.include_header:
            writer.writeheader()
        writer.writerows(flattened_rows)
        return output.getvalue()

    def loads(self, serialized_text: str, model_binding: ModelBinding[ModelValue]) -> list[ModelValue]:
        """ 列を階層へ戻し、各行を指定モデルまたはdictへ復元する。
        """
        self.validate_model_configuration(model_binding)
        reader = csv.reader(StringIO(serialized_text, newline=""), strict=True)
        try:
            if self._load_options.has_header:
                columns = next(reader, None)
                if columns is None:
                    return []
            else:
                columns = list(self._load_options.columns or ())

            if not columns or any(not name for name in columns) or len(set(columns)) != len(columns):
                raise SerializationError("CSVの列名が空欄・重複、または未指定です")
            unflatten_fields(dict.fromkeys(columns), separator=self._load_options.separator)

            restored_values: list[ModelValue] = []
            for cells in reader:
                if not cells:
                    continue
                if len(cells) != len(columns):
                    raise SerializationError(f"CSV行{reader.line_num}: 見出しと値の数が異なります")

                # 空白だけの物理行は飛ばすが、値がすべて空の正当なレコードは残す。
                row_values = {
                    name: None if cell == "" and self._load_options.empty_as_none else cell
                    for name, cell in zip(columns, cells)
                }
                data = unflatten_fields(
                    row_values, separator=self._load_options.separator,
                )
                try:
                    restored_values.append(model_binding.restore_value(data))
                except ValidationError as error:
                    raise SerializationError(f"CSV行{reader.line_num}: {error}") from error
            return restored_values
        except csv.Error as error:
            raise SerializationError(f"CSV行{reader.line_num}: {error}") from error
