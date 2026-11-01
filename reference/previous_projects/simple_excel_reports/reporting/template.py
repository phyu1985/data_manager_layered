"""Excelテンプレートから論理的な帳票定義と物理的なセル位置を読み取る。

__report__の設定表と各シートのマーカーを照合し、ReportSpecとPlacementへ
分けて返す。書式はWorkbookに保持し、この段階では値の置換や複製をしない。
"""
from __future__ import annotations

import re
from typing import Literal, TypedDict

from pydantic import BaseModel, Field, ValidationError
from openpyxl import Workbook
from .models import Column, Comparison, SheetSpec, ReportSpec, PrintHeaderSpec
from .project import ReportError

# 書式を入れたセルの値に置く目印。正規表現で完全一致するものだけ扱う。
MARKER: re.Pattern[str] = re.compile(r"^\{\{(header|record|item):([A-Za-z_][A-Za-z_0-9]*)\}\}$")

# マーカーの位置は、Excelと同じ1始まりの「行・列・属性名」で保持する。
MarkerCell = tuple[int, int, str]


class SheetRule(TypedDict):
    """設定表の複数行をシート単位にまとめるための内部構造。"""

    logic: Literal["AND", "OR"]
    conditions: list[Comparison]


class Placement(BaseModel):
    """1シートのマーカー位置。行・列はすべて1始まり。

    title_rowからdata_rowまでが横へ複製するItemブロックの高さとなる。
    item_colsは連続列、record_colsはその左側の指定列を表す。
    header_cellsは同じRecord属性を複数セルに表示する場合にも対応する。
    """
    title_row: int
    data_row: int
    first_item_col: int
    record_cols: list[int]
    item_cols: list[int]
    header_cells: dict[str, list[tuple[int, int]]] = Field(default_factory=dict)


def _require(condition: bool, message: str) -> None:
    """テンプレートの前提条件を確認し、違反時はReportErrorを送出する。"""
    if not condition:
        raise ReportError(message)


def load_template(wb: Workbook) -> tuple[ReportSpec, dict[str, Placement]]:
    """読み込み済みブックを検証し、帳票定義とシート別の配置情報を返す。

    設定シートの構成:
        B1/B2: 全シート共通のItemソート属性と降順フラグ。
        A5:E: シート別の抽出条件（1条件1行）。
        G5:I: Item位置別の見出し名（1位置1行）。
        K5:P: 任意の印刷ヘッダー設定（1シート1行）。

    Returns:
        共通処理に渡すReportSpecと、シート名をキーにしたPlacement。

    Raises:
        ReportError: 設定の不足・重複、マーカー位置や結合範囲が不正な場合。
        pydantic.ValidationError: 正規化した値が設定モデルの制約に違反する場合。
    """
    # 1. 設定シートから、ブック全体のソート規則を読み取る。
    if "__report__" not in wb:
        raise ReportError("テンプレートに設定シート '__report__' がありません")
    cfg = wb["__report__"]
    sort_field = cfg["B1"].value
    descending = cfg["B2"].value
    _require(isinstance(sort_field, str) and bool(sort_field.strip()),
             "__report__!B1 にソートフィールド名を指定してください")
    _require(isinstance(descending, bool), "__report__!B2 はTRUE/FALSEで指定してください")
    # 2. A5:Eの条件行をシート単位にまとめる。同じシートでAND/ORは混在不可。
    rule_map: dict[str, SheetRule] = {}
    for row in cfg.iter_rows(min_row=5, min_col=1, max_col=5, values_only=True):
        name, logic, field, op, value = row
        if all(cell is None for cell in row):
            continue
        _require(isinstance(name, str) and name in wb.sheetnames and name != "__report__",
                 f"設定シートの条件行に存在しないシートが指定されています: {name!r}")
        _require(logic in ("AND", "OR"), f"シート '{name}' の論理条件はAND/ORです")
        _require(isinstance(field, str) and field != "", "条件のフィールド名がありません")
        _require(op in ("==", "!=", "<", "<=", ">", ">="), f"比較演算子が不正: {op}")
        _require(value is not None, f"シート '{name}' の比較値が空欄です")
        entry = rule_map.setdefault(name, {"logic": logic, "conditions": []})
        _require(entry["logic"] == logic, f"シート '{name}' 内のAND/ORが混在しています")
        entry["conditions"].append(Comparison(field=field, op=op, value=value))
    # 3. G5:Iから位置別名称を読む。位置の欠番は各シートの構築時に検証する。
    title_map: dict[str, dict[int, str]] = {}
    for row in cfg.iter_rows(min_row=5, min_col=7, max_col=9, values_only=True):
        name, pos, title = row
        if all(cell is None for cell in row):
            continue
        _require(isinstance(name, str) and name in wb.sheetnames and name != "__report__",
                 f"見出し名のシート指定が不正: {name!r}")
        _require(type(pos) is int and pos >= 1 and isinstance(title, str) and title != "",
                 f"シート '{name}' の位置別見出しが不正です")
        _require(pos not in title_map.setdefault(name, {}), f"シート '{name}' の位置{pos}が重複")
        title_map[name][pos] = title

    # 4. K5:Pは任意設定。未登録シートの既存印刷ヘッダーは描画側で保持する。
    print_map: dict[str, tuple[PrintHeaderSpec, bool]] = {}
    for row in cfg.iter_rows(min_row=5, min_col=11, max_col=16, values_only=True):
        name, title, left, center, right, show = row
        if all(cell is None for cell in row):
            continue
        _require(isinstance(name, str) and name in wb.sheetnames and name != "__report__",
                 f"印刷ヘッダーのシート指定が不正: {name!r}")
        _require(name not in print_map, f"シート '{name}' の印刷ヘッダーが重複しています")
        _require(show is None or type(show) is bool,
                 f"シート '{name}' のセル共通値の表示はTRUE/FALSEで指定してください")
        try:
            # Excelの空セルはNone。表示文字列の空欄は明示的な非表示として扱う。
            header = PrintHeaderSpec(**{
                key: value if value is not None else ""
                for key, value in zip(("title", "left", "center", "right"),
                                      (title, left, center, right))
            })
        except ValidationError as exc:
            raise ReportError(f"シート '{name}' の印刷ヘッダーが不正です: {exc}") from exc
        print_map[name] = (header, True if show is None else show)

    # 5. 帳票シートを走査し、マーカーの位置と見本ブロックの制約を検証する。
    sheets: list[SheetSpec] = []
    placements: dict[str, Placement] = {}
    for ws in wb.worksheets:
        if ws.title == "__report__":
            continue
        _require(ws.title in rule_map, f"シート '{ws.title}' の条件定義がありません")
        positions = title_map.get(ws.title, {})
        _require(positions and sorted(positions) == list(range(1, len(positions) + 1)),
                 f"シート '{ws.title}' のItem見出しは1から連番で登録してください")
        markers: dict[str, list[MarkerCell]] = {"header": [], "record": [], "item": []}
        titles: list[tuple[int, int]] = []
        for row in ws:
            for cell in row:
                if cell.value == "{{item_title}}":
                    titles.append((cell.row, cell.column))
                elif isinstance(cell.value, str):
                    match = MARKER.fullmatch(cell.value)
                    if match:
                        markers[match.group(1)].append((cell.row, cell.column, match.group(2)))
        _require(len(titles) == 1, f"シート '{ws.title}' に{{{{item_title}}}}を1個置いてください")
        _require(bool(markers["item"]), f"シート '{ws.title}' のItem見本セルがありません")
        # 1Record=1行なので、RecordとItemのデータマーカーは同じ行に限定する。
        data_rows = {row for row, _, _ in markers["item"] + markers["record"]}
        _require(len(data_rows) == 1, f"シート '{ws.title}' のrecord/itemは同じ見本行に置いてください")
        data_row = data_rows.pop()
        title_row, first_title_col = titles[0]
        _require(title_row < data_row, f"シート '{ws.title}' のItemタイトルは見本行より上に置いてください")
        # シートの走査順ではなく列番号で並べ、列順を論理定義へ引き継ぐ。
        item_cells = sorted(markers["item"], key=lambda c: c[1])
        item_cols = [col for _, col, _ in item_cells]
        _require(item_cols == list(range(min(item_cols), max(item_cols) + 1)),
                 f"シート '{ws.title}' のItem見本列は連続させてください")
        _require(first_title_col == min(item_cols),
                 f"シート '{ws.title}' の{{{{item_title}}}}はItem見本の左端に置いてください")
        record_cells = sorted(markers["record"], key=lambda c: c[1])
        _require(all(col < min(item_cols) for _, col, _ in record_cells),
                 f"シート '{ws.title}' のRecord列はItemの左側に置いてください")
        _require(len({field for _, _, field in item_cells}) == len(item_cells),
                 f"シート '{ws.title}' で同一Itemフィールドが重複しています")
        # 複製対象のItemブロックをまたぐセル結合は事故の元なので禁止。
        for merged in ws.merged_cells.ranges:
            if merged.max_col < min(item_cols) or merged.min_col > max(item_cols):
                continue
            if merged.max_row < title_row or merged.min_row > data_row:
                continue
            _require(merged.min_col >= min(item_cols) and merged.max_col <= max(item_cols),
                     f"シート '{ws.title}' にItemブロックを横断する結合があります: {merged}")
            _require(merged.min_row >= title_row and merged.max_row <= data_row,
                     f"シート '{ws.title}' にItemブロックを縦断する結合があります: {merged}")
        header_map: dict[str, list[tuple[int, int]]] = {}
        for row, col, field in markers["header"]:
            _require(row < title_row, f"シート '{ws.title}' の上部情報はItem見出しより上に配置してください")
            header_map.setdefault(field, []).append((row, col))
        # 6. 値の意味を持つSheetSpecと、座標だけのPlacementへ分ける。
        sheets.append(SheetSpec(
            name=ws.title, logic=rule_map[ws.title]["logic"],
            print_header=print_map[ws.title][0] if ws.title in print_map else None,
            show_table_headers=print_map[ws.title][1] if ws.title in print_map else True,
            conditions=rule_map[ws.title]["conditions"],
            headers=[Column(field=field) for field in header_map],
            record_columns=[Column(field=field) for _, _, field in record_cells],
            item_columns=[Column(field=field) for _, _, field in item_cells],
            item_titles=[positions[i] for i in sorted(positions)],
        ))
        placements[ws.title] = Placement(
            title_row=title_row, data_row=data_row, first_item_col=min(item_cols),
            record_cols=[col for _, col, _ in record_cells], item_cols=item_cols,
            header_cells=header_map,
        )
    return ReportSpec(sort_field=sort_field, descending=descending, sheets=sheets), placements
