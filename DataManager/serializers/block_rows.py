""" 複数行レコードの文法を共有し、平坦なモデルへの対応付けを分離する。
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
import csv
from dataclasses import dataclass
from io import StringIO
from typing import Any, cast

from pydantic import ValidationError

from DataManager.documents import RowsDocument
from DataManager.errors import ConfigurationError, SerializationError
from DataManager.model_conversion import ModelBinding, ModelValue
from DataManager.serializers.csv_headers import HeaderOptions, dump_header_text, split_header


def _valid_column_names(columns: Sequence[str]) -> bool:
    """ 物理一行に収まる列名の文法。設定とファイルの列定義で同じ規則を使う。
    """
    return (
        bool(columns)
        and all(name.strip() and "\n" not in name and "\r" not in name for name in columns)
        and len(set(columns)) == len(columns)
    )


@dataclass(frozen=True)
class BlockRow:
    """ 一行の復元先列・所属先・保存見出し。対応する情報を同じ定義へまとめる。
    """

    columns: tuple[str, ...]
    target: str | None = None
    header: tuple[str, ...] | None = None

    def __post_init__(self):
        """ 一行の中で確定する形と名前を確認する。
        """
        if not _valid_column_names(self.columns):
            raise ConfigurationError("行の列名は空欄・改行・重複のない一覧です")
        if self.target is not None and (not self.target.strip() or self.target != self.target.strip()):
            raise ConfigurationError("所属先は空白を除いた非空の一覧名です")
        if self.header is not None:
            if len(self.header) != len(self.columns) or not _valid_column_names(self.header):
                raise ConfigurationError("保存見出しは列数に合う空欄・改行・重複のない一覧です")

    @classmethod
    def root(cls, *columns: str, header: tuple[str, ...] | None = None) -> BlockRow:
        """ モデル直下へ対応付ける行を宣言する。
        """
        return cls(columns, header=header)

    @classmethod
    def items(cls, target: str, *columns: str, header: tuple[str, ...] | None = None) -> BlockRow:
        """ 指定したモデル内の一覧へ、一要素を追加する行を宣言する。
        """
        if not target:
            raise ConfigurationError("itemsには所属先の一覧名を指定してください")
        return cls(columns, target=target, header=header)


@dataclass(frozen=True)
class BlockRowsOptions:
    """ ブロックの文法と行定義。列・所属先・保存見出しはrowsの各BlockRowへまとめる。

    metadataはCSVと同じヘッダ設定。列名ヘッダとファイル全体のメタを別の塊として宣言する。
    """

    delimiter: str = ";"
    marker: str = "#"
    header_prefix: str = "#"
    rows: tuple[BlockRow, ...] | None = None
    empty_as_none: bool = True
    by_alias: bool = False
    metadata: HeaderOptions | None = None

    def __post_init__(self):
        """ 文法と行の対応先を確定する。メタはヘッダ設定自身で検証済み。
        """
        self._check_grammar()
        self._check_targets()

    def _check_grammar(self):
        """ ブロックとCSVセルを区切る記号を確認する。
        """
        if len(self.delimiter) != 1 or self.delimiter in "\r\n":
            raise ConfigurationError("セルの区切りは改行以外の1文字です")
        symbols = (self.marker, self.header_prefix)
        if any(not symbol or any(c in symbol for c in "\r\n") for symbol in symbols):
            raise ConfigurationError("マーカーとヘッダ記号は改行のない非空文字列です")

    def _check_targets(self):
        """ 全行を通して、モデル直下のキーと一覧の名前の衝突だけを確認する。
        """
        if self.rows is None:
            return
        if not self.rows:
            raise ConfigurationError("rowsには一行以上の定義が必要です")
        root_keys = [name for row in self.rows if row.target is None for name in row.columns]
        list_names = {row.target for row in self.rows if row.target is not None}
        if len(set(root_keys)) != len(root_keys) or set(root_keys) & list_names:
            raise ConfigurationError("モデル直下の列名または一覧名が重複しています")

    @property
    def columns(self) -> tuple[tuple[str, ...], ...] | None:
        """ 文法処理へ渡す列構成を、行定義から取り出す。
        """
        return None if self.rows is None else tuple(row.columns for row in self.rows)

    @property
    def row_targets(self) -> tuple[str | None, ...] | None:
        """ モデルへの対応先を、列と同じ行定義から取り出す。
        """
        return None if self.rows is None else tuple(row.target for row in self.rows)

    @property
    def header_columns(self) -> tuple[tuple[str, ...], ...] | None:
        """ 別の見出しを指定した行だけを置き換える。
        """
        if self.rows is None or all(row.header is None for row in self.rows):
            return None
        return tuple(row.header if row.header is not None else row.columns for row in self.rows)


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
        self._options = options

    @staticmethod
    def validate_columns(groups: Sequence[Sequence[str]]):
        """ 行内の重複を拒否する。異なる行の同名列は所属先を分けて扱える。
        """
        if not groups or any(not _valid_column_names(group) for group in groups):
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
                    cells = next(csv.reader([line[len(options.header_prefix):].lstrip()], delimiter=options.delimiter, skipinitialspace=options.delimiter == " ", strict=True))
                    groups.append([cell.strip() for cell in cells])
                else:
                    current.append(next(csv.reader([line], delimiter=options.delimiter, skipinitialspace=options.delimiter == " ", strict=True)))
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
        writer = csv.writer(output, delimiter=options.delimiter, lineterminator="\n", quoting=csv.QUOTE_ALL if options.delimiter == " " else csv.QUOTE_MINIMAL)

        # 復元先のキーとファイル上の見出しが違う形式も、位置の対応を保って保存する。
        headers = options.header_columns if options.header_columns is not None else groups
        self.validate_columns(headers)
        if [len(group) for group in headers] != [len(group) for group in groups]:
            raise SerializationError("header_columnsとcolumnsの行・列数が一致しません")
        for group in headers:
            line = StringIO(newline="")
            csv.writer(line, delimiter=options.delimiter, lineterminator="\n", quoting=csv.QUOTE_ALL if options.delimiter == " " else csv.QUOTE_MINIMAL).writerow(group)
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
    """ 各行をモデル直下または指定の一覧へまとめ、文法処理はBlockRowsFormatへ委譲する。
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

    def _row_targets(self, groups: Sequence[Sequence[str]]) -> tuple[str | None, ...]:
        """ 行と所属先を照合し、同じ辞書へ入るキーの衝突を拒否する。
        """
        # 宣言した行は設定生成時に整合済み。ファイル由来の列だけをここで対応付ける。
        targets = self._options.row_targets
        if targets is not None:
            return targets
        targets = (None,) * len(groups)

        root_keys = [key for group, target in zip(groups, targets, strict=True) if target is None for key in group]
        list_keys = {target for target in targets if target is not None}
        if len(set(root_keys)) != len(root_keys) or set(root_keys) & list_keys:
            raise SerializationError("モデル直下の列名または一覧名が重複しています")
        return targets

    def loads_document(
        self, serialized_text: str, model_binding: ModelBinding[ModelValue],
    ) -> RowsDocument[dict[str, Any], ModelValue]:
        """ 行構成を確認してから所属先の辞書を作り、モデルの型・値を検証する。
        """
        self.validate_model_configuration(model_binding)
        metadata: dict[str, Any] = {}
        if self._options.metadata is not None:
            # CSVと同じ規則で先頭メタを切り出し、残りをブロックの列定義・本文へ渡す。
            metadata, serialized_text = split_header(
                serialized_text, self._options.metadata, self._options.delimiter,
            )
        # 列定義とレコードを読み取り、各行の値を入れる場所を決める。
        document = self._format.loads(serialized_text)
        targets = self._row_targets(document.columns)

        # Noneの行は直下へ統合し、同じ一覧名の行は入力順で一要素ずつ追加する。
        rows: list[ModelValue] = []
        for record in document.records:
            data: dict[str, Any] = {}
            for keys, cells, target in zip(document.columns, record, targets, strict=True):
                values = {
                    key: None if value == "" and self._options.empty_as_none else value
                    for key, value in zip(keys, cells, strict=True)
                }
                if target is None:
                    data.update(values)
                else:
                    data.setdefault(target, []).append(values)

            # 入れ子のAttribute等もPydanticに生成させ、Serializerにモデル型を固定しない。
            try:
                rows.append(model_binding.restore_value(data))
            except ValidationError as error:
                raise SerializationError(f"複数行レコードのモデル検証に失敗しました: {error}") from error

        return RowsDocument(metadata=metadata, rows=rows)

    def loads(self, serialized_text: str, model_binding: ModelBinding[ModelValue]) -> list[ModelValue]:
        return self.loads_document(serialized_text, model_binding).rows

    def dumps_document(
        self, rows: Sequence[ModelValue], model_binding: ModelBinding[ModelValue], *, metadata: dict[str, Any],
    ) -> str:
        """ metaを列定義の前へ置き、本文のレコード構成は従来の処理へ委譲する。
        """
        if self._options.metadata is None:
            if metadata:
                raise ConfigurationError("metaの出力にはmetadataを構成してください")
            return self._dump_rows(rows, model_binding)
        header = dump_header_text(metadata, self._options.metadata, self._options.delimiter)
        return header + self._dump_rows(rows, model_binding)

    def _list_values(self, values: dict[str, Any], counts: Counter[str]) -> dict[str, list[object]]:
        """ 一覧の要素数を行定義と照合し、不足や余剰を黙って補正しない。
        """
        lists: dict[str, list[object]] = {}
        for target, count in counts.items():
            raw: object = values[target]
            if not isinstance(raw, list):
                raise SerializationError(f"{target}はリストが必要です")
            items = cast(list[object], raw)
            if len(items) != count:
                raise SerializationError(f"{target}は{count}件必要です")
            lists[target] = items
        return lists

    def dumps(self, rows: Sequence[ModelValue], model_binding: ModelBinding[ModelValue]) -> str:
        return self.dumps_document(rows, model_binding, metadata={})

    def _dump_rows(self, rows: Sequence[ModelValue], model_binding: ModelBinding[ModelValue]) -> str:
        """ 直下の値と一覧要素を列定義の順へ展開し、文書全体を生成する。
        """
        self.validate_model_configuration(model_binding)
        groups = self._options.columns
        if groups is None:
            raise ConfigurationError("複数行形式の出力には行ごとのcolumnsが必要です")
        # 行定義から、モデル直下の項目と一覧要素に必要な件数を整理する。
        targets = self._row_targets(groups)
        counts = Counter(target for target in targets if target is not None)
        root_keys = {key for group, target in zip(groups, targets, strict=True) if target is None for key in group}
        expected = root_keys | set(counts)

        # 全件の対応付けを終えてから文法処理へ渡し、失敗時はファイルへ触れない。
        records: list[list[list[Any]]] = []
        for row in rows:
            values = model_binding.to_dict(row, by_alias=self._options.by_alias)
            if set(values) != expected:
                raise SerializationError("保存項目が指定された列・一覧名と一致しません")
            # 一件のモデルを、行定義の順に並ぶセルのまとまりへ変換する。
            lists = self._list_values(values, counts)
            positions = dict.fromkeys(counts, 0)
            record: list[list[Any]] = []
            for keys, target in zip(groups, targets, strict=True):
                if target is None:
                    source = values
                else:
                    item = lists[target][positions[target]]
                    positions[target] += 1
                    if not isinstance(item, dict):
                        raise SerializationError(f"{target}の各要素は辞書またはモデルが必要です")
                    source = cast(dict[str, Any], item)
                    if set(source) != set(keys):
                        raise SerializationError(f"{target}の要素と列定義が一致しません")
                record.append([source[key] for key in keys])
            records.append(record)

        # 列定義と組み立てた全レコードを、ブロック形式のテキストへ書き出す。
        return self._format.dumps(groups, records)
