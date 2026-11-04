""" 複数行レコードの文法を共有し、平坦なモデルへの対応付けを分離する。
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
    """ ブロックの文法。columnsは同じ行構成の列名を置換し、保存時の見出しにも使う。
    """

    delimiter: str = ";"
    marker: str = "#"
    header_prefix: str = "#"
    columns: tuple[tuple[str, ...], ...] | None = None
    empty_as_none: bool = True
    by_alias: bool = False


@dataclass(frozen=True)
class BlockDocument:
    """ 行の境界を保つ解析結果。キーの所属先は形式専用Serializerが決める。
    """

    columns: list[list[str]]
    records: list[list[list[str]]]


class BlockRowsFormat:
    """ マーカー・CSVセル・行構成を扱い、業務モデルの構造は解釈しない。
    """

    def __init__(self, options: BlockRowsOptions):
        if (
            len(options.delimiter) != 1 or options.delimiter in "\r\n"
            or not options.marker or not options.header_prefix
            or any(c in options.marker + options.header_prefix for c in "\r\n")
        ):
            raise ConfigurationError("区切りは改行以外の1文字、マーカーとヘッダ記号は改行のない非空文字列です")
        self._options = options

    @staticmethod
    def validate_columns(groups: Sequence[Sequence[str]]):
        """ 行内の重複を拒否する。異なる行の同名列は所属先を分けて扱える。
        """
        if not groups or any(
            not group or any(not key.strip() for key in group) or len(set(group)) != len(group)
            for group in groups
        ):
            raise SerializationError("列定義の行・項目に空欄や重複があります")

    @staticmethod
    def _validate_record(groups: Sequence[Sequence[str]], record: Sequence[Sequence[object]]):
        """ 合計数だけでなく各行の列数を照合し、位置ずれを防ぐ。
        """
        if [len(group) for group in groups] != [len(row) for row in record]:
            raise SerializationError("レコードの各行の列数が列定義と一致しません")

    def loads(self, text: str) -> BlockDocument:
        """ 終端までを一件として確定し、未完の最終レコードを拒否する。
        """
        options = self._options
        groups: list[list[str]] = []
        current: list[list[str]] = []
        records: list[list[list[str]]] = []
        in_header = True

        # 最初の終端までは列定義、それ以降は同じ行構成のレコードとして読む。
        try:
            for i, line in enumerate(text.splitlines(), 1):
                if not line.strip():
                    continue
                if line.strip() == options.marker:
                    # 終端でヘッダまたは一件を確定し、次のまとまりへ進む。
                    if in_header:
                        in_header = False
                        if options.columns is not None:
                            if [len(group) for group in groups] != [len(group) for group in options.columns]:
                                raise SerializationError("指定列の行構成がヘッダと一致しません")
                            groups = [list(group) for group in options.columns]
                        self.validate_columns(groups)
                    elif current:
                        self._validate_record(groups, current)
                        records.append(current)
                        current = []
                    continue

                if in_header:
                    if not line.startswith(options.header_prefix):
                        raise SerializationError(f"行{i}: 列定義の開始記号がありません")
                    cells = next(csv.reader([line[len(options.header_prefix):].lstrip()], delimiter=options.delimiter, strict=True))
                    groups.append([cell.strip() for cell in cells])
                else:
                    current.append(next(csv.reader([line], delimiter=options.delimiter, strict=True)))
        except csv.Error as error:
            raise SerializationError(f"複数行形式のCSVセルが不正です: {error}") from error

        if in_header or current:
            raise SerializationError("ヘッダまたは最終レコードの終端マーカーがありません")

        return BlockDocument(groups, records)

    def dumps(self, groups: Sequence[Sequence[str]], records: Sequence[Sequence[Sequence[Any]]]) -> str:
        """ 行構成を照合し、ヘッダと各レコードを終端マーカーで閉じる。
        """
        self.validate_columns(groups)
        options = self._options
        output = StringIO(newline="")
        writer = csv.writer(output, delimiter=options.delimiter, lineterminator="\n")

        # 列定義を先頭に一度だけ出し、以降の全レコードに同じ構成を使う。
        for group in groups:
            line = StringIO(newline="")
            csv.writer(line, delimiter=options.delimiter, lineterminator="\n").writerow(group)
            output.write(options.header_prefix + " " + line.getvalue())
        output.write(options.marker + "\n")

        # 各セルの表現と行構成を確認し、最後の一件も必ず終端で閉じる。
        for record in records:
            self._validate_record(groups, record)
            for cells in record:
                if any(isinstance(value, (dict, list, tuple)) or "\n" in str(value) or "\r" in str(value) for value in cells):
                    raise SerializationError("この複数行形式は配列・セル内改行に対応しません")
                if len(cells) == 1 and str(cells[0]).strip() == options.marker:
                    raise SerializationError("データ行が終端マーカーと衝突します")
                # 空の物理行は読取時にスキップするため、復元できない出力は拒否する。
                if len(cells) == 1 and isinstance(cells[0], str) and cells[0] and not cells[0].strip():
                    raise SerializationError("空白だけの単一セル行は保存できません")
                writer.writerow(cells)
            output.write(options.marker + "\n")
        return output.getvalue()


class BlockRowsSerializer:
    """ 複数行を平坦な一件へ対応付け、文法処理はBlockRowsFormatへ委譲する。
    """

    def __init__(self, *, options: BlockRowsOptions | None = None):
        self._options = options or BlockRowsOptions()
        self._format = BlockRowsFormat(self._options)

    @property
    def encoding(self) -> str:
        return "utf-8"

    def validate_model_configuration(self, model_binding: ModelBinding[ModelValue]):
        if model_binding.data_mode == "mixed":
            raise ConfigurationError("複数行形式は混在モデルに対応しません")

    def _validate_flat_columns(self, groups: Sequence[Sequence[str]]):
        """ 平坦な辞書へまとめたときに別行の値が上書きされるのを防ぐ。
        """
        columns = [key for group in groups for key in group]
        if len(set(columns)) != len(columns):
            raise SerializationError("平坦なモデルの列名に重複があります。階層を持つ形式は専用Serializerを指定してください")

    def loads_document(
        self, serialized_text: str, model_binding: ModelBinding[ModelValue],
    ) -> RowsDocument[dict[str, Any], ModelValue]:
        self.validate_model_configuration(model_binding)
        document = self._format.loads(serialized_text)
        self._validate_flat_columns(document.columns)

        # 行の境界を外すのはこの段階だけ。キーが一意なことを確認してからまとめる。
        rows: list[ModelValue] = []
        for record in document.records:
            values = {
                key: None if value == "" and self._options.empty_as_none else value
                for keys, cells in zip(document.columns, record, strict=True)
                for key, value in zip(keys, cells, strict=True)
            }
            try:
                rows.append(model_binding.restore_value(values))
            except ValidationError as error:
                raise SerializationError(f"複数行レコードのモデル検証に失敗しました: {error}") from error

        return RowsDocument(metadata={}, rows=rows)

    def loads(self, serialized_text: str, model_binding: ModelBinding[ModelValue]) -> list[ModelValue]:
        return self.loads_document(serialized_text, model_binding).rows

    def dumps_document(
        self, rows: Sequence[ModelValue], model_binding: ModelBinding[ModelValue], *, metadata: dict[str, Any],
    ) -> str:
        if metadata:
            raise ConfigurationError("複数行形式の利用者メタ出力は未対応です")
        return self.dumps(rows, model_binding)

    def dumps(self, rows: Sequence[ModelValue], model_binding: ModelBinding[ModelValue]) -> str:
        """ 一件の辞書を列定義の行へ戻す。階層構造の展開は形式専用Serializerが担当する。
        """
        self.validate_model_configuration(model_binding)
        groups = self._options.columns
        if groups is None:
            raise ConfigurationError("複数行形式の出力には行ごとのcolumnsが必要です")
        self._format.validate_columns(groups)
        self._validate_flat_columns(groups)
        keys = {key for group in groups for key in group}
        records: list[list[list[Any]]] = []

        # 列定義の順で各モデルを行へ戻し、マーカーやCSV引用は共通処理へ任せる。
        for row in rows:
            values = model_binding.to_dict(row, by_alias=self._options.by_alias)
            if set(values) != keys:
                raise SerializationError("保存項目が指定された列と一致しません")
            records.append([[values[key] for key in group] for group in groups])
        return self._format.dumps(groups, records)
