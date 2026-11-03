""" 単一種類のモデル・dict一覧を、階層付きの列名でCSVへ対応付ける。
"""
from __future__ import annotations

from collections.abc import Sequence
import csv
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from io import StringIO
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin
from uuid import UUID

from pydantic import BaseModel, ValidationError

from DataManager.documents import RowsDocument
from DataManager.errors import ConfigurationError, SerializationError
from DataManager.model_conversion import ModelBinding, ModelValue
from DataManager.serializers.field_paths import flatten_fields, unflatten_fields


@dataclass(frozen=True)
class CsvOptions:
    """ 一つのCSVの読書き規則。境界はメタ部分と本文の境界を表す。

    columnsは本文の列名の指定・置換に使い、metadata_keysは値だけのメタへ名前を付ける。
    読書きで異なる列・階層区切りが必要な場合だけread_columns/read_separatorを指定する。
    """

    by_alias: bool = False
    include_header: bool = True
    has_header: bool = True
    columns: tuple[str, ...] | None = None
    read_columns: tuple[str, ...] | None = None
    separator: str = "."
    read_separator: str | None = None
    empty_as_none: bool = True
    boundary: Literal["blank_line", "marker", "fixed_rows"] | None = None
    marker: str | None = None
    row_count: int | None = None
    metadata_layout: Literal["key_value", "values"] = "key_value"
    metadata_keys: tuple[str, ...] | None = None
    metadata_empty_as_none: bool = True


# 既存の呼出側の移行用。実体は同じ設定型であり、内部でも三種類を持ち続けない。
CSVDumpOptions = CsvOptions
CSVLoadOptions = CsvOptions
CSVMetadataOptions = CsvOptions


class CsvSerializer:
    """ 一覧とCSVを変換する。混在モデルの型判別と配列の行展開は扱わない。
    """

    def __init__(
        self, *, options: CsvOptions | None = None, encoding: str = "utf-8",
        dump_options: CsvOptions | None = None, load_options: CsvOptions | None = None,
        metadata_options: CsvOptions | None = None,
    ):
        """ 新規コードはoptions一つで構成する。旧引数は移行のため受け付ける。
        """
        if options is not None and any(value is not None for value in (dump_options, load_options, metadata_options)):
            raise ConfigurationError("optionsと旧形式のオプション引数は併用できません")

        configured = options or CsvOptions()
        if dump_options is not None:
            configured = replace(configured, by_alias=dump_options.by_alias,
                                 include_header=dump_options.include_header, columns=dump_options.columns,
                                 separator=dump_options.separator)
        if load_options is not None:
            configured = replace(configured, has_header=load_options.has_header,
                                 read_columns=load_options.columns, read_separator=load_options.separator,
                                 empty_as_none=load_options.empty_as_none)
        if metadata_options is not None:
            configured = replace(configured, boundary=metadata_options.boundary or "blank_line",
                                 marker=metadata_options.marker, row_count=metadata_options.row_count,
                                 metadata_layout=metadata_options.metadata_layout,
                                 metadata_keys=metadata_options.metadata_keys,
                                 metadata_empty_as_none=metadata_options.empty_as_none)

        if configured.boundary == "fixed_rows" and configured.row_count is None and configured.metadata_layout == "values" and configured.metadata_keys is not None:
            configured = replace(configured, row_count=len(configured.metadata_keys))
        self._options = configured
        self._encoding = encoding
        if not configured.separator or configured.read_separator == "":
            raise ConfigurationError("CSVの階層区切り文字は空にできません")
        if configured.boundary is not None:
            self._validate_metadata_options(configured)
        elif configured.marker is not None or configured.row_count is not None or configured.metadata_keys is not None or configured.metadata_layout != "key_value":
            raise ConfigurationError("メタの設定にはboundaryを指定してください")

    @staticmethod
    def _validate_metadata_options(options: CsvOptions):
        """ 設定の曖昧さを、ファイルを読む前に検出する。
        """
        if options.metadata_layout not in {"key_value", "values"}:
            raise ConfigurationError("metadata_layoutはkey_value / valuesです")
        if options.metadata_layout == "values":
            keys = options.metadata_keys
            if not keys or any(not key.strip() for key in keys) or len(set(keys)) != len(keys):
                raise ConfigurationError("値だけのメタには重複・空欄のないmetadata_keysが必要です")
            if options.boundary == "fixed_rows" and options.row_count != len(keys):
                raise ConfigurationError("row_countとmetadata_keysの件数を一致させてください")
        elif options.metadata_keys is not None:
            raise ConfigurationError("metadata_keysは値だけのメタで指定してください")

        if options.boundary not in {"blank_line", "marker", "fixed_rows"}:
            raise ConfigurationError("CSVメタのboundaryはblank_line / marker / fixed_rowsです")
        if options.boundary == "marker":
            if not isinstance(options.marker, str) or not options.marker.strip():
                raise ConfigurationError("marker境界には空白以外のマーカー文字列が必要です")
            if "\n" in options.marker or "\r" in options.marker:
                raise ConfigurationError("マーカーには改行を含められません")
        elif options.marker is not None:
            raise ConfigurationError("markerはmarker境界だけで指定してください")

        if options.boundary == "fixed_rows":
            if type(options.row_count) is not int or options.row_count < 0:
                raise ConfigurationError("fixed_rowsには0以上の整数のrow_countが必要です")
        elif options.row_count is not None:
            raise ConfigurationError("row_countはfixed_rows境界だけで指定してください")

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
            dict.fromkeys(columns), separator=self._options.separator,
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
            if self._options.by_alias:
                output_name = field_definition.serialization_alias or field_definition.alias or field_name

            field_path = prefix + output_name
            if self._options.separator in output_name:
                raise SerializationError(f"階層として曖昧なフィールド名です: {output_name!r}")
            annotation = field_definition.annotation
            # OptionalのNoneだけを外す。list[int]までintと解釈しないよう、Unionに限定する。
            if get_origin(annotation) in (UnionType, Union):
                possible_types = [item for item in get_args(annotation) if item is not type(None)]
                if len(possible_types) == 1:
                    annotation = possible_types[0]

            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                columns.extend(self._columns_for_empty_models(
                    annotation, field_path + self._options.separator,
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
        if self._options.boundary is not None:
            raise ConfigurationError("メタ付きCSVの保存はsave_documentを使用してください")

        return self._dump_rows(rows, model_binding)

    def _dump_rows(self, rows: Sequence[ModelValue], model_binding: ModelBinding[ModelValue]) -> str:
        """ 全行から列集合を決め、見出しと本文を生成する。
        """
        self.validate_model_configuration(model_binding)
        flattened_rows: list[dict[str, Any]] = []

        for value in rows:
            data = model_binding.to_dict(value, by_alias=self._options.by_alias)
            flattened_fields = flatten_fields(
                data, separator=self._options.separator,
            )
            if any(
                item is not None and not isinstance(item, (str, int, float, bool, date, datetime, Decimal, UUID))
                for item in flattened_fields.values()
            ):
                raise SerializationError("CSVの配列・空の階層・任意オブジェクトは暗黙に文字列化しません")
            flattened_rows.append(flattened_fields)

        # 1行目だけで決めると、後続行にしかない可変キーが保存されず消えてしまう。
        columns = list(self._options.columns or ())
        if self._options.columns is None:
            columns = list(dict.fromkeys(key for row in flattened_rows for key in row))
            if not rows and model_binding.data_mode == "single":
                columns = self._columns_for_empty_models(model_binding.model_classes[0])

        self._validate_columns(columns)
        if any(set(row) - set(columns) for row in flattened_rows):
            raise SerializationError("指定したCSV列に含まれない値があります")

        output = StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
        if self._options.include_header:
            writer.writeheader()
        writer.writerows(flattened_rows)
        return output.getvalue()

    def loads(self, serialized_text: str, model_binding: ModelBinding[ModelValue]) -> list[ModelValue]:
        """ 本文だけを返す。メタも必要な場合はload_documentを使う。
        """
        return self.loads_document(serialized_text, model_binding).rows

    def dumps_document(
        self, rows: Sequence[ModelValue], model_binding: ModelBinding[ModelValue], *,
        metadata: dict[str, Any],
    ) -> str:
        """ メタと本文を一体で生成する。既存の本文変換へ委譲し、文法を二重化しない。
        """
        options = self._options if self._options.boundary is not None else None
        if options is None:
            if metadata:
                raise ConfigurationError("CSVメタを保存するにはCsvOptionsのboundaryを指定してください（旧metadata_optionsにも対応）")
            return self._dump_rows(rows, model_binding)

        # 固定件数を合わせるための補完・切捨てはしない。別の値を保存してしまうのを防ぐ。
        if options.boundary == "fixed_rows" and len(metadata) != options.row_count:
            raise SerializationError("CSVメタの件数がrow_countと一致しません")

        keys = options.metadata_keys if options.metadata_layout == "values" else tuple(metadata)
        if keys is None or set(keys) != set(metadata):
            raise SerializationError("値だけのメタはmetadata_keysと保存項目が一致する必要があります")
        output = StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        for key in keys:
            value = metadata[key]
            if not key.strip():
                raise SerializationError("CSVメタのキーは空白以外の文字列が必要です")
            if value is not None and not isinstance(value, (str, int, float, bool, date, datetime, Decimal, UUID)):
                raise SerializationError("CSVメタの値は単一値が必要です。辞書・配列は保存できません")
            writer.writerow([value] if options.metadata_layout == "values" else [key, value])

        if options.boundary == "blank_line":
            writer.writerow([])
        elif options.boundary == "marker":
            writer.writerow([options.marker])

        return output.getvalue() + self._dump_rows(rows, model_binding)

    def loads_document(
        self, serialized_text: str, model_binding: ModelBinding[ModelValue],
    ) -> RowsDocument[dict[str, Any], ModelValue]:
        """ 指定規則で先頭のメタを分離し、本文は通常のCSVとして復元する。
        """
        options = self._options if self._options.boundary is not None else None
        if options is None:
            return RowsDocument(metadata={}, rows=self._load_rows(serialized_text, model_binding))

        reader = csv.reader(StringIO(serialized_text, newline=""), strict=True)
        metadata: dict[str, Any] = {}
        try:
            # splitlinesでは引用符内の改行も境界になってしまう。CSVパーサーのレコードで数える。
            while True:
                if options.boundary == "fixed_rows" and len(metadata) == options.row_count:
                    break
                cells = next(reader, None)
                if cells is None:
                    raise SerializationError("CSVメタの境界、または指定件数のメタがありません")
                if options.boundary == "blank_line" and not cells:
                    break
                if options.boundary == "marker" and cells == [options.marker]:
                    break

                if options.metadata_layout == "values":
                    keys = options.metadata_keys or ()
                    if len(cells) != 1 or len(metadata) >= len(keys):
                        raise SerializationError(f"CSV行{reader.line_num}: メタ値とキーリストが対応しません")
                    cells = [keys[len(metadata)], cells[0]]

                if len(cells) != 2 or not cells[0].strip():
                    raise SerializationError(f"CSV行{reader.line_num}: メタは空でないkeyとvalueの2列が必要です")
                key, value = cells
                if key in metadata:
                    raise SerializationError(f"CSV行{reader.line_num}: メタのキーが重複しています: {key!r}")
                metadata[key] = None if value == "" and options.metadata_empty_as_none else value

            if options.metadata_layout == "values" and len(metadata) != len(options.metadata_keys or ()):
                raise SerializationError("メタ値の数がmetadata_keysと一致しません")

            # 残りもcsv.writerで受け渡し、引用符・区切り文字・セル内改行を失わないようにする。
            body = StringIO(newline="")
            csv.writer(body, lineterminator="\n").writerows(reader)
        except csv.Error as error:
            raise SerializationError(f"CSV行{reader.line_num}: {error}") from error

        return RowsDocument(metadata=metadata, rows=self._load_rows(body.getvalue(), model_binding))

    def _load_rows(self, serialized_text: str, model_binding: ModelBinding[ModelValue]) -> list[ModelValue]:
        """ 列を階層へ戻し、各行を指定モデルまたはdictへ復元する。
        """
        self.validate_model_configuration(model_binding)
        reader = csv.reader(StringIO(serialized_text, newline=""), strict=True)
        try:
            if self._options.has_header:
                header = next(reader, None)
                if header is None:
                    return []
                supplied = self._options.read_columns if self._options.read_columns is not None else self._options.columns
                columns = list(supplied) if supplied is not None else header
                if len(columns) != len(header):
                    raise SerializationError("指定した列名の数がCSVの列名行と一致しません")
            else:
                columns = list((self._options.read_columns if self._options.read_columns is not None else self._options.columns) or ())

            if not columns or any(not name for name in columns) or len(set(columns)) != len(columns):
                raise SerializationError("CSVの列名が空欄・重複、または未指定です")
            unflatten_fields(dict.fromkeys(columns), separator=(self._options.read_separator or self._options.separator))

            restored_values: list[ModelValue] = []
            for cells in reader:
                if not cells:
                    continue
                if len(cells) != len(columns):
                    raise SerializationError(f"CSV行{reader.line_num}: 見出しと値の数が異なります")

                # 空白だけの物理行は飛ばすが、値がすべて空の正当なレコードは残す。
                row_values = {
                    name: None if cell == "" and self._options.empty_as_none else cell
                    for name, cell in zip(columns, cells)
                }
                data = unflatten_fields(
                    row_values, separator=(self._options.read_separator or self._options.separator),
                )
                try:
                    restored_values.append(model_binding.restore_value(data))
                except ValidationError as error:
                    raise SerializationError(f"CSV行{reader.line_num}: {error}") from error
            return restored_values
        except csv.Error as error:
            raise SerializationError(f"CSV行{reader.line_num}: {error}") from error
