""" 複数行の列定義と同じ行構成で繰り返すレコードを扱う。
"""
from __future__ import annotations

from collections.abc import Sequence
import csv
from dataclasses import dataclass
from io import StringIO
from typing import Any

from pydantic import ValidationError

from DataManager.documents import RowsDocument
from DataManager.errors import ConfigurationError, SerializationError
from DataManager.model_conversion import ModelBinding, ModelValue


@dataclass(frozen=True)
class BlockRowsOptions:
    """ 列の区切りと、レコード終端・ヘッダ行の印を指定する。

    columnsを指定するとヘッダの各行を置換する。行の数・各行の列数も一致が必要。
    セル内の改行と、単独の終端行と同じ内容を持つデータ行はこの形式では扱わない。
    """

    delimiter: str = ";"
    marker: str = "#"
    header_prefix: str = "#"
    columns: tuple[tuple[str, ...], ...] | None = None
    empty_as_none: bool = True
    by_alias: bool = False


class BlockRowsSerializer:
    """ レコード内の各行の対応を保ち、一つのモデルへ復元する。
    """

    def __init__(self, *, options: BlockRowsOptions | None = None):
        self._options = options or BlockRowsOptions()
        if len(self._options.delimiter) != 1 or not self._options.marker or not self._options.header_prefix:
            raise ConfigurationError("区切りは1文字、マーカーとヘッダ開始記号は非空です")

    @property
    def encoding(self) -> str:
        return "utf-8"

    def validate_model_configuration(self, model_binding: ModelBinding[ModelValue]):
        """ 型判別子を持たないため、レコードは同じモデルに揃える。
        """
        if model_binding.data_mode == "mixed":
            raise ConfigurationError("複数行形式は混在モデルに対応しません")

    def _validate_columns(self, groups: Sequence[Sequence[str]]):
        columns = [key for group in groups for key in group]
        if not groups or any(not group for group in groups) or any(not key.strip() for key in columns) or len(set(columns)) != len(columns):
            raise SerializationError("列定義の行・項目に空欄や重複があります")

    def loads_document(
        self, serialized_text: str, model_binding: ModelBinding[ModelValue],
    ) -> RowsDocument[dict[str, Any], ModelValue]:
        """ 最後の終端も一つのレコードの確定として扱い、空レコードを作らない。
        """
        self.validate_model_configuration(model_binding)
        options = self._options
        groups: list[list[str]] = []
        current: list[list[str]] = []
        rows: list[ModelValue] = []
        in_header = True
        try:
            for i, line in enumerate(serialized_text.splitlines(), 1):
                if not line.strip():
                    continue
                if line.strip() == options.marker:
                    if in_header:
                        in_header = False
                        if options.columns is not None:
                            if [len(g) for g in groups] != [len(g) for g in options.columns]:
                                raise SerializationError("指定列の行構成がヘッダと一致しません")
                            groups = [list(g) for g in options.columns]
                        self._validate_columns(groups)
                    elif current:
                        rows.append(self._restore(groups, current, model_binding))
                        current = []
                    continue
                if in_header:
                    if not line.startswith(options.header_prefix):
                        raise SerializationError(f"行{i}: 列定義の開始記号がありません")
                    cells = next(csv.reader([line[len(options.header_prefix):].lstrip()], delimiter=options.delimiter, strict=True))
                    groups.append(cells)
                else:
                    current.append(next(csv.reader([line], delimiter=options.delimiter, strict=True)))
        except csv.Error as error:
            raise SerializationError(f"複数行形式のCSVセルが不正です: {error}") from error
        if in_header or current:
            raise SerializationError("ヘッダまたは最終レコードの終端マーカーがありません")
        return RowsDocument(metadata={}, rows=rows)

    def _restore(
        self, groups: list[list[str]], current: list[list[str]], model_binding: ModelBinding[ModelValue],
    ) -> ModelValue:
        """ 合計数だけでなく行ごとの形を照合し、値の位置ずれを防ぐ。
        """
        if [len(g) for g in groups] != [len(g) for g in current]:
            raise SerializationError("レコードの各行の列数が列定義と一致しません")
        values = {
            key: None if value == "" and self._options.empty_as_none else value
            for keys, cells in zip(groups, current) for key, value in zip(keys, cells)
        }
        try:
            return model_binding.restore_value(values)
        except ValidationError as error:
            raise SerializationError(f"複数行レコードのモデル検証に失敗しました: {error}") from error

    def loads(self, serialized_text: str, model_binding: ModelBinding[ModelValue]) -> list[ModelValue]:
        return self.loads_document(serialized_text, model_binding).rows

    def dumps_document(
        self, rows: Sequence[ModelValue], model_binding: ModelBinding[ModelValue], *, metadata: dict[str, Any],
    ) -> str:
        """ この形式の先頭は列定義。利用者メタを黙って捨てない。
        """
        if metadata:
            raise ConfigurationError("複数行形式の利用者メタ出力は未対応です")
        return self.dumps(rows, model_binding)

    def dumps(self, rows: Sequence[ModelValue], model_binding: ModelBinding[ModelValue]) -> str:
        """ 出力の行構成はcolumnsで明示し、最後のレコードもマーカーで閉じる。
        """
        self.validate_model_configuration(model_binding)
        groups = self._options.columns
        if groups is None:
            raise ConfigurationError("複数行形式の出力には行ごとのcolumnsが必要です")
        self._validate_columns(groups)
        output = StringIO(newline="")
        writer = csv.writer(output, delimiter=self._options.delimiter, lineterminator="\n")
        for group in groups:
            line = StringIO(newline="")
            csv.writer(line, delimiter=self._options.delimiter, lineterminator="\n").writerow(group)
            output.write(self._options.header_prefix + " " + line.getvalue())
        output.write(self._options.marker + "\n")
        keys = {key for group in groups for key in group}
        for row in rows:
            values = model_binding.to_dict(row, by_alias=self._options.by_alias)
            if set(values) != keys:
                raise SerializationError("保存項目が指定された列と一致しません")
            for group in groups:
                cells = [values[key] for key in group]
                if any(isinstance(value, (dict, list, tuple)) or "\n" in str(value) or "\r" in str(value) for value in cells):
                    raise SerializationError("この複数行形式は配列・セル内改行に対応しません")
                if len(cells) == 1 and str(cells[0]).strip() == self._options.marker:
                    raise SerializationError("データ行が終端マーカーと衝突します")
                writer.writerow(cells)
            output.write(self._options.marker + "\n")
        return output.getvalue()
