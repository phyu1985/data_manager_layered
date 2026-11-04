""" テンプレート.xlsxから帳票定義とセル位置を取得する。
"""
from __future__ import annotations

import re
from datetime import datetime, date
from pydantic import BaseModel, Field
from openpyxl import Workbook
from openpyxl.cell.cell import Cell
from DataManager.Excel.models import Column, Comparison, SheetSpec, ReportSpec
from DataManager.Excel.project import ReportError

# 書式を入れたセルの値に置く目印。正規表現で完全一致するものだけ扱う。
MARKER = re.compile(r"^\{\{(header|record|item):([A-Za-z_][A-Za-z_0-9]*)\}\}$")


class Placement(BaseModel):
    """ テンプレート上の見本セル位置。データ値や条件評価は持たない。
    """

    title_row: int
    data_row: int
    first_item_col: int
    record_cols: list[int]
    item_cols: list[int]
    header_cells: dict[str, list[tuple[int, int]]] = Field(default_factory=dict)


def _require(condition: bool, message: str):
    if not condition:
        raise ReportError(message)


def load_template(wb: Workbook) -> tuple[ReportSpec, dict[str, Placement]]:
    """ __report__のA:E・G:Jと出力シートの目印を読み、設定と座標を返す。

    B1/B2以外の固定セル設定や、K列以降の独自ヘッダ表は読まない。
    """
    if "__report__" not in wb:
        raise ReportError("テンプレートに設定シート '__report__' がありません")

    # 設定シートから抽出条件を読み、表示シートのマーカー位置と組み合わせる。
    cfg = wb["__report__"]
    sort_field = cfg["B1"].value
    descending = cfg["B2"].value
    if sort_field is not None and not isinstance(sort_field, str):
        raise ReportError("__report__!B1 はソートフィールド名または空欄にしてください")
    if isinstance(sort_field, str):
        sort_field = sort_field.strip() or None
    if not isinstance(descending, bool):
        raise ReportError("__report__!B2 はTRUE/FALSEで指定してください")

    # A5:E... にシート／AND or OR／フィールド／比較演算子／比較値。
    # C列はrecord.department / item.kindのように書ける（無指定ならItem）。
    rule_map: dict[str, dict] = {}
    for row in cfg.iter_rows(min_row=5, min_col=1, max_col=5, values_only=True):
        name, logic, field, op, value = row
        if all(cell is None for cell in row):
            continue
        if not isinstance(name, str) or name not in wb.sheetnames or name == "__report__":
            raise ReportError(f"設定シートの条件行に存在しないシートが指定されています: {name!r}")
        _require(logic in ("AND", "OR"), f"シート '{name}' の論理条件はAND/ORです")
        if not isinstance(field, str) or not field.strip():
            raise ReportError("条件のフィールド名がありません")
        raw_field = field.strip()
        if "." in raw_field:
            source, field = raw_field.split(".", 1)
            _require(source in ("record", "item") and field.isidentifier(), f"条件の対象・フィールド指定が不正です: {raw_field!r}")
        else:
            source, field = "item", raw_field  # 旧テンプレートとの互換性
        _require(field.isidentifier(), f"条件のフィールド名が不正です: {field!r}")
        _require(op in ("==", "!=", "<", "<=", ">", ">="), f"比較演算子が不正: {op}")
        _require(value is not None, f"シート '{name}' の比較値が空欄です")
        entry = rule_map.setdefault(name, {"logic": logic, "conditions": []})
        _require(entry["logic"] == logic, f"シート '{name}' 内のAND/ORが混在しています")
        entry["conditions"].append(Comparison.model_validate({"source": source, "field": field, "op": op, "value": value}))

    # G5:J... にシート／位置／表示名／照合キー。
    # J列を省略した旧テンプレートでは表示名をそのまま照合キーに使う。
    title_map: dict[str, dict[int, tuple[str, str]]] = {}
    for row in cfg.iter_rows(min_row=5, min_col=7, max_col=10, values_only=True):
        name, pos, title, key = row
        if all(cell is None for cell in row):
            continue
        if not isinstance(name, str) or name not in wb.sheetnames or name == "__report__":
            raise ReportError(f"見出し名のシート指定が不正: {name!r}")
        if type(pos) is not int or pos < 1 or not isinstance(title, str) or not title.strip():
            raise ReportError(f"シート '{name}' の位置別見出しが不正です")
        key = title if key is None else key
        if not isinstance(key, str) or not key.strip():
            raise ReportError(f"シート '{name}' の位置{pos}の照合キーが不正です")
        _require(pos not in title_map.setdefault(name, {}), f"シート '{name}' の位置{pos}が重複")
        title_map[name][pos] = (title, key)

    # 設定を読み終えてから各シートを走査し、出力定義と書込位置を同時に確定する。
    sheets = []
    placements = {}
    for ws in wb.worksheets:
        if ws.title == "__report__":
            continue
        _require(ws.title in rule_map, f"シート '{ws.title}' の条件定義がありません")
        positions = title_map.get(ws.title, {})
        _require(bool(positions) and sorted(positions) == list(range(1, len(positions) + 1)),
                 f"シート '{ws.title}' のItem見出しは1から連番で登録してください")
        markers: dict[str, list[tuple[int, int, str]]] = {"header": [], "record": [], "item": []}
        titles = []

        # マーカーの実セルから、繰り返してよいItemブロックの範囲を求める。
        for row in ws:
            for cell in row:
                # 結合従属セルには目印を置けない。実セルだけを対象に座標の型も確定する。
                if not isinstance(cell, Cell):
                    continue
                assert isinstance(cell.row, int) and isinstance(cell.column, int)
                if cell.value == "{{item_title}}":
                    titles.append((cell.row, cell.column))
                elif isinstance(cell.value, str):
                    match = MARKER.fullmatch(cell.value)
                    if match:
                        markers[match.group(1)].append((cell.row, cell.column, match.group(2)))

        _require(len(titles) == 1, f"シート '{ws.title}' に{{{{item_title}}}}を1個置いてください")
        _require(bool(markers["item"]), f"シート '{ws.title}' のItem見本セルがありません")
        data_rows = {row for row, _, _ in markers["item"] + markers["record"]}
        _require(len(data_rows) == 1, f"シート '{ws.title}' のrecord/itemは同じ見本行に置いてください")
        data_row = data_rows.pop()
        title_row, first_title_col = titles[0]
        _require(title_row < data_row, f"シート '{ws.title}' のItemタイトルは見本行より上に置いてください")
        item_cells = sorted(markers["item"], key=lambda c: c[1])
        item_cols = [col for _, col, _ in item_cells]
        _require(item_cols == list(range(min(item_cols), max(item_cols) + 1)), f"シート '{ws.title}' のItem見本列は連続させてください")
        _require(first_title_col == min(item_cols), f"シート '{ws.title}' の{{{{item_title}}}}はItem見本の左端に置いてください")
        record_cells = sorted(markers["record"], key=lambda c: c[1])
        _require(all(col < min(item_cols) for _, col, _ in record_cells), f"シート '{ws.title}' のRecord列はItemの左側に置いてください")
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

        # 描画側にはセル走査を持ち込まず、検証済みの定義と座標を渡す。
        header_map: dict[str, list[tuple[int, int]]] = {}
        for row, col, field in markers["header"]:
            _require(row < title_row, f"シート '{ws.title}' の上部情報はItem見出しより上に配置してください")
            header_map.setdefault(field, []).append((row, col))
        sheets.append(SheetSpec(
            name=ws.title, logic=rule_map[ws.title]["logic"],
            conditions=rule_map[ws.title]["conditions"],
            headers=[Column(field=field) for field in header_map],
            record_columns=[Column(field=field) for _, _, field in record_cells],
            item_columns=[Column(field=field) for _, _, field in item_cells],
            item_titles=[positions[i][0] for i in sorted(positions)],
            item_keys=[positions[i][1] for i in sorted(positions)],
            item_title_field="title",  # Item.titleをキーで照合し、表示名とは独立に配置
        ))
        placements[ws.title] = Placement(
            title_row=title_row, data_row=data_row, first_item_col=min(item_cols),
            record_cols=[col for _, col, _ in record_cells], item_cols=item_cols,
            header_cells=header_map,
        )

    return ReportSpec(sort_field=sort_field, descending=descending, sheets=sheets), placements
