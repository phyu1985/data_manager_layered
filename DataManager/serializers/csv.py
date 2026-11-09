""" 単一種類のモデル・dict一覧を、階層付きの列名でCSVへ対応付ける。
"""
from __future__ import annotations

from collections.abc import Sequence
import csv
from datetime import date, datetime
from decimal import Decimal
from io import StringIO
from types import UnionType
from typing import Any, Union, get_args, get_origin
from uuid import UUID

from pydantic import BaseModel, ValidationError

from DataManager.documents import RowsDocument
from DataManager.errors import ConfigurationError, SerializationError
from DataManager.model_conversion import ModelBinding, ModelValue
from DataManager.serializers.field_paths import flatten_fields, unflatten_fields
from DataManager.serializers.csv_options import CsvHeaderOptions, CsvKeyValueHeaderOptions, CsvOptions
from DataManager.serializers.csv_headers import dump_header_text, split_header


class CsvSerializer:
    """ 文書のヘッダを分離し、共通のCSVテーブル変換でモデル一覧を読み書きする。

    optionsは共通の本文設定。読書きが異なる場合だけread_options / write_optionsで置き換える。
    metadataは可変メタか順序付きヘッダのどちらかを選び、未指定なら普通のCSVになる。
    """

    def __init__(
        self, *, options: CsvOptions | None = None,
        metadata: CsvHeaderOptions | CsvKeyValueHeaderOptions | None = None,
        read_options: CsvOptions | None = None, write_options: CsvOptions | None = None,
        encoding: str = "utf-8",
    ):
        # 設定値は生成時に確定済み。ここでは読書きの担当だけを接続する。
        common = options or CsvOptions()
        self._read_options = read_options or common
        self._write_options = write_options or common
        self._metadata = metadata
        self._encoding = encoding

    @property
    def encoding(self) -> str:
        return self._encoding

    def validate_model_configuration(self, model_binding: ModelBinding[ModelValue]):
        """ 型判別を持たないCSVへ混在モデルを渡していないか確認する。
        """
        if model_binding.data_mode == "mixed":
            raise ConfigurationError("CSVは単一モデルまたはdict一覧に対応します")

    def _validate_columns(self, columns: Sequence[str]):
        if not columns or any(not column.strip() for column in columns) or len(set(columns)) != len(columns):
            raise SerializationError("CSVの列名は空欄・重複のない1個以上を指定してください")

        # 値を入れる前に、親の列aと子の列a.bが共存していないか確認する。
        unflatten_fields(dict.fromkeys(columns), separator=self._write_options.field_separator)

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
            if self._write_options.by_alias:
                output_name = field_definition.serialization_alias or field_definition.alias or field_name

            field_path = prefix + output_name
            if self._write_options.field_separator in output_name:
                raise SerializationError(f"階層として曖昧なフィールド名です: {output_name!r}")
            annotation = field_definition.annotation
            # OptionalのNoneだけを外す。list[int]までintと解釈しないよう、Unionに限定する。
            if get_origin(annotation) in (UnionType, Union):
                possible_types = [item for item in get_args(annotation) if item is not type(None)]
                if len(possible_types) == 1:
                    annotation = possible_types[0]

            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                columns.extend(self._columns_for_empty_models(
                    annotation, field_path + self._write_options.field_separator,
                    ancestor_models=ancestor_models,
                ))
            elif annotation in (dict, list) or get_args(annotation):
                raise ConfigurationError("可変の階層を持つ空CSVにはcolumnsを指定してください")
            else:
                columns.append(field_path)
        return columns

    def dumps(self, rows: Sequence[ModelValue], model_binding: ModelBinding[ModelValue]) -> str:
        """ 通常のCSVを生成する。メタ付きCSVはsave_documentで明示して保存する。
        """
        if self._metadata is not None:
            raise ConfigurationError("メタ付きCSVの保存はsave_documentを使用してください")

        return self._dump_rows(rows, model_binding)

    def _dump_rows(self, rows: Sequence[ModelValue], model_binding: ModelBinding[ModelValue]) -> str:
        """ 全行から列集合を決め、見出しと本文を生成する。
        """
        self.validate_model_configuration(model_binding)
        flattened_rows: list[dict[str, Any]] = []

        # 先に全行を辞書化し、階層を列名へ展開してCSVで表せる値か確認する。
        for value in rows:
            data = model_binding.to_dict(value, by_alias=self._write_options.by_alias)
            flattened_fields = flatten_fields(data, separator=self._write_options.field_separator)
            if any(
                item is not None and not isinstance(item, (str, int, float, bool, date, datetime, Decimal, UUID))
                for item in flattened_fields.values()
            ):
                raise SerializationError("CSVの配列・空の階層・任意オブジェクトは暗黙に文字列化しません")
            flattened_rows.append(flattened_fields)

        # 1行目だけで決めると、後続行にしかない可変キーが保存されず消えてしまう。
        columns = list(self._write_options.columns or ())
        if self._write_options.columns is None:
            columns = list(dict.fromkeys(key for row in flattened_rows for key in row))
            if not rows and model_binding.data_mode == "single":
                columns = self._columns_for_empty_models(model_binding.model_classes[0])

        self._validate_columns(columns)
        if any(set(row) - set(columns) for row in flattened_rows):
            raise SerializationError("指定したCSV列に含まれない値があります")

        # 列順を確定してから、見出しと各行を同じ構成で出力する。
        output = StringIO(newline="")
        # 空白の連続は読取時に一つへまとめるため、空値のある出力では引用して区別する。
        quote_empty = self._write_options.delimiter == " " and any(
            row.get(column) is None or row.get(column) == "" for row in flattened_rows for column in columns
        )
        writer = csv.DictWriter(
            output, fieldnames=columns, lineterminator="\n", delimiter=self._write_options.delimiter,
            quoting=csv.QUOTE_ALL if quote_empty else csv.QUOTE_MINIMAL,
        )
        if self._write_options.header:
            output.write(self._write_options.column_prefix)
            writer.writeheader()
        writer.writerows(flattened_rows)
        return output.getvalue()

    def loads(self, serialized_text: str, model_binding: ModelBinding[ModelValue]) -> list[ModelValue]:
        """ 行だけを返す。メタも利用する場合はloads_documentを使う。
        """
        return self.loads_document(serialized_text, model_binding).rows

    def dumps_document(
        self, rows: Sequence[ModelValue], model_binding: ModelBinding[ModelValue], *, metadata: dict[str, Any],
    ) -> str:
        """ メタと本文を別々に生成して連結する。どちらの失敗でも保存前に止まる。
        """
        if self._metadata is None:
            if metadata:
                raise ConfigurationError("CSVメタの保存にはmetadataを構成してください")
            return self._dump_rows(rows, model_binding)
        header = dump_header_text(metadata, self._metadata, self._write_options.delimiter)
        return header + self._dump_rows(rows, model_binding)

    def loads_document(
        self, serialized_text: str, model_binding: ModelBinding[ModelValue],
    ) -> RowsDocument[dict[str, Any], ModelValue]:
        """ ヘッダの境界を決めてから表を読む。版変換や業務値の補完は扱わない。
        """
        metadata: dict[str, Any] = {}
        body = serialized_text
        if self._metadata is not None:
            metadata, body = split_header(body, self._metadata, self._read_options.delimiter)
        return RowsDocument(metadata=metadata, rows=self._load_rows(body, model_binding))

    def _load_rows(self, serialized_text: str, model_binding: ModelBinding[ModelValue]) -> list[ModelValue]:
        """ 列を階層へ戻し、各行を指定モデルまたはdictへ復元する。
        """
        self.validate_model_configuration(model_binding)
        options = self._read_options
        delimiter = options.delimiter
        # 空行の後ろに列名がある既存書式も読めるよう、先頭の空行だけを取り除く。
        stream = StringIO(serialized_text, newline="")
        first = stream.readline()
        while first and not first.strip():
            first = stream.readline()
        if options.header and first and options.column_prefix:
            if not first.startswith(options.column_prefix):
                raise SerializationError("CSVの列名行にcolumn_prefixがありません")
            first = first[len(options.column_prefix):]
        serialized_text = first + stream.read()
        reader = csv.reader(StringIO(serialized_text, newline=""), delimiter=delimiter, skipinitialspace=delimiter == " ", strict=True)
        try:
            # 列名行の有無と置換設定から、各セルの復元先を一度だけ決める。
            if options.header:
                header = next(reader, None)
                if header is None:
                    return []
                # 指定名はファイル見出しを全面的に置き換える。空欄・不足の見出しも補修できる。
                columns = list(options.columns) if options.columns is not None else header
                if options.columns is None and options.strip_column_names:
                    columns = [name.strip() for name in columns]
            else:
                columns = list(options.columns or ())

            if not columns or any(not name.strip() for name in columns) or len(set(columns)) != len(columns):
                raise SerializationError("CSVの列名が空欄・重複、または未指定です")
            unflatten_fields(dict.fromkeys(columns), separator=options.field_separator)

            # セル数を照合し、列の階層を戻してから一件ずつモデルで検証する。
            restored_values: list[ModelValue] = []
            physical_lines = StringIO(serialized_text, newline="").readlines() if delimiter == " " else []
            for cells in reader:
                if not cells or (delimiter == " " and cells == [""] and not physical_lines[reader.line_num - 1].strip()):
                    continue
                # 期待列数の内側にある空値は保持し、明示された余剰の末尾空セルだけを除く。
                if options.allow_trailing_empty_columns and len(cells) > len(columns):
                    extras = cells[len(columns):]
                    if all(value == "" for value in extras):
                        cells = cells[:len(columns)]
                if len(cells) != len(columns):
                    raise SerializationError(f"CSV行{reader.line_num}: 見出しと値の数が異なります")

                # 空白だけの物理行は飛ばすが、値がすべて空の正当なレコードは残す。
                row_values = {
                    name: None if cell == "" and options.empty_as_none else cell
                    for name, cell in zip(columns, cells)
                }
                data = unflatten_fields(row_values, separator=options.field_separator)
                try:
                    restored_values.append(model_binding.restore_value(data))
                except ValidationError as error:
                    raise SerializationError(f"CSV行{reader.line_num}: {error}") from error

            return restored_values
        except csv.Error as error:
            raise SerializationError(f"CSV行{reader.line_num}: {error}") from error
