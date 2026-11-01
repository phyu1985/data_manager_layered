""" Excelへの描画。新規生成とテンプレート流用のみを担当する。
"""
from __future__ import annotations

from copy import copy
from datetime import date, datetime
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from openpyxl.worksheet.properties import PageSetupProperties
from DataManager.Excel.models import WorkbookData, SheetData
from DataManager.Excel.template import Placement
from DataManager.Excel.project import ReportError


BLUE = "244564"
PALE = "EAF1F6"
GRAY = "D0DBE5"
LINE = Side(style="thin", color=GRAY)
TABLE_BORDER = Border(left=LINE, right=LINE, top=LINE, bottom=LINE)


def _set_value(cell, value):
    """ 出力値を書き込み、業務データの数式注入を防ぐ。
    """
    cell.value = value
    # ユーザー提供の文字列がExcel数式にならないようにする。
    if isinstance(value, str) and value.startswith("="):
        cell.data_type = "s"
    if isinstance(value, (date, datetime)):
        cell.number_format = "yyyy/mm/dd"


def render_code(data: WorkbookData) -> Workbook:
    wb = Workbook()
    default_sheet = wb.active
    if default_sheet is not None:
        wb.remove(default_sheet)
    for sheet in data.sheets:
        ws = wb.create_sheet(sheet.name)
        _render_code_sheet(ws, sheet)
    return wb


def _style_header(cell, *, dark: bool = False):
    cell.fill = PatternFill("solid", fgColor=BLUE if dark else PALE)
    cell.font = Font(name="Meiryo", size=10, bold=True,
                     color="FFFFFF" if dark else BLUE)
    cell.alignment = Alignment(horizontal="center", vertical="center")
    cell.border = TABLE_BORDER


def _render_code_sheet(ws: Worksheet, sheet: SheetData):
    for idx, header in enumerate(sheet.headers, start=1):
        title_cell, value_cell = ws.cell(idx, 1), ws.cell(idx, 2)
        _set_value(title_cell, header.label)
        _set_value(value_cell, header.value)
        _style_header(title_cell)
        value_cell.alignment = Alignment(vertical="center")
        ws.row_dimensions[idx].height = 23
    top = len(sheet.headers) + 1
    lower = top + 1
    start_row = lower + 1
    n_rec = len(sheet.record_headings)
    n_item = len(sheet.item_headings)

    for idx, label in enumerate(sheet.record_headings, start=1):
        cell = ws.cell(top, idx)
        _set_value(cell, label)
        _style_header(cell, dark=True)
        ws.merge_cells(start_row=top, start_column=idx,
                       end_row=lower, end_column=idx)
    for k, title in enumerate(sheet.item_titles):
        first = n_rec + k*n_item + 1
        last = first + n_item - 1
        cell = ws.cell(top, first)
        _set_value(cell, title)
        _style_header(cell, dark=True)
        if first < last:
            ws.merge_cells(start_row=top, start_column=first,
                           end_row=top, end_column=last)
        for offset, heading in enumerate(sheet.item_headings):
            c = ws.cell(lower, first + offset)
            _set_value(c, heading)
            _style_header(c)
    for i, row in enumerate(sheet.rows, start=start_row):
        all_values = row.record_values + [
            value for item in row.item_values for value in item
        ]
        for col in range(1, n_rec + n_item*len(sheet.item_titles) + 1):
            cell = ws.cell(i, col)
            _set_value(cell, all_values[col-1] if col <= len(all_values) else None)
            cell.border = TABLE_BORDER
            cell.alignment = Alignment(vertical="center")
        ws.row_dimensions[i].height = 21
    for col in range(1, n_rec + n_item*len(sheet.item_titles) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 20 if col <= n_rec else 15
    ws.row_dimensions[top].height = 26
    ws.row_dimensions[lower].height = 23
    ws.freeze_panes = f"A{start_row}"
    ws.sheet_view.showGridLines = False
    ws.print_options.horizontalCentered = True
    page_settings = ws.sheet_properties.pageSetUpPr
    if page_settings is None:
        ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    else:
        page_settings.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0


def _snapshot(cell) -> dict:
    """ セル値と表示書式のコピー用。見本の値を書き換える前に取得する。
    """
    return {
        # テンプレート自身の数式と、業務データに含まれる文字列を区別する。
        "value": cell.value, "data_type": cell.data_type,
        "font": copy(cell.font), "fill": copy(cell.fill),
        "border": copy(cell.border), "alignment": copy(cell.alignment),
        "number_format": cell.number_format, "protection": copy(cell.protection),
    }


def _paste(ws: Worksheet, row: int, col: int, snap: dict):
    """ 見本セルの値・書式を複製する。数式は信頼するテンプレートだけで許可。
    """
    cell = ws.cell(row, col)
    if snap["data_type"] == "f":
        # =ROW()-6 などのテンプレート数式を複製時も数式として残す。
        # _set_value()は業務データの数式注入対策で文字列に変換するため通さない。
        cell.value = snap["value"]
    else:
        _set_value(cell, snap["value"])
    cell.font = copy(snap["font"])
    cell.fill = copy(snap["fill"])
    cell.border = copy(snap["border"])
    cell.alignment = copy(snap["alignment"])
    cell.number_format = snap["number_format"]
    cell.protection = copy(snap["protection"])


def _check_empty(ws: Worksheet, start_row: int, end_row: int,
                 start_col: int, end_col: int):
    # 既存値や結合セルを上書きしない。書式のみ設定済みの空セルは許容。
    for row in ws.iter_rows(min_row=start_row, max_row=end_row,
                            min_col=start_col, max_col=end_col):
        for cell in row:
            if cell.value is not None:
                raise ReportError(f"シート '{ws.title}' の拡張先 {cell.coordinate} に既存の値があります")
    for merged in ws.merged_cells.ranges:
        overlaps = not (
            merged.max_col < start_col or merged.min_col > end_col or
            merged.max_row < start_row or merged.min_row > end_row
        )
        if overlaps:
            raise ReportError(f"シート '{ws.title}' の拡張先にセル結合があります: {merged}")


def _render_template_sheet(ws: Worksheet, sheet: SheetData, place: Placement):
    """ Item見本を横に、Record見本を下に展開してから値を上書きする。
    """
    block_width = len(place.item_cols)
    first = place.first_item_col
    count = len(sheet.item_titles)
    last_col = first + block_width*count - 1
    title_row, data_row = place.title_row, place.data_row

    # 横方向: Itemの見本ブロック（見出しからデータ行まで）を繰り返す。
    block = {
        (r, offset): _snapshot(ws.cell(r, first + offset))
        for r in range(title_row, data_row + 1)
        for offset in range(block_width)
    }
    original_merges = list(ws.merged_cells.ranges)
    block_merges = [
        (m.min_row, m.max_row, m.min_col - first, m.max_col - first)
        for m in original_merges
        if (m.min_col >= first and m.max_col < first+block_width and
            m.min_row >= title_row and m.max_row <= data_row)
    ]
    for item_index in range(1, count):
        target_col = first + item_index*block_width
        _check_empty(ws, title_row, data_row, target_col, target_col+block_width-1)
        for (r, offset), snap in block.items():
            _paste(ws, r, target_col+offset, snap)
        for r1, r2, c1, c2 in block_merges:
            ws.merge_cells(start_row=r1, end_row=r2,
                           start_column=target_col+c1, end_column=target_col+c2)
        for offset in range(block_width):
            src = ws.column_dimensions[get_column_letter(first+offset)]
            dst = ws.column_dimensions[get_column_letter(target_col+offset)]
            dst.width = src.width
            dst.hidden = src.hidden

    # 横へ展開した見本行を、Record件数分下へコピーする。
    row_snapshot = [_snapshot(ws.cell(data_row, col)) for col in range(1, last_col+1)]
    row_merges = [m for m in ws.merged_cells.ranges
                  if m.min_row == data_row and m.max_row == data_row]
    for i in range(1, len(sheet.rows)):
        target_row = data_row + i
        _check_empty(ws, target_row, target_row, 1, last_col)
        for col, snap in enumerate(row_snapshot, start=1):
            _paste(ws, target_row, col, snap)
        ws.row_dimensions[target_row].height = ws.row_dimensions[data_row].height
        for m in row_merges:
            ws.merge_cells(start_row=target_row, end_row=target_row,
                           start_column=m.min_col, end_column=m.max_col)

    # タイトルと上部の共通値
    for index, title in enumerate(sheet.item_titles):
        _set_value(ws.cell(title_row, first+index*block_width), title)
    headers_by_field = {header.field: header.value for header in sheet.headers}
    for field, positions in place.header_cells.items():
        for row, col in positions:
            _set_value(ws.cell(row, col), headers_by_field[field])
    # 一覧の値。Item数が少ないRecordの残り枠は空欄にする。
    record_width = len(place.record_cols)
    for index, row in enumerate(sheet.rows):
        target = data_row + index
        for col, value in zip(place.record_cols, row.record_values):
            _set_value(ws.cell(target, col), value)
        for block_index in range(count):
            for offset in range(block_width):
                value = (row.item_values[block_index][offset]
                         if block_index < len(row.item_values) else None)
                _set_value(ws.cell(target, first + block_index*block_width + offset), value)

    # 0件でも空の見本1行は書式として保持し、未処理マーカーを消す。
    if not sheet.rows:
        for col in place.record_cols:
            _set_value(ws.cell(data_row, col), None)
        for col in range(first, last_col+1):
            _set_value(ws.cell(data_row, col), None)
    ws.sheet_view.showGridLines = False


def render_template(wb: Workbook, data: WorkbookData,
                    placements: dict[str, Placement]) -> Workbook:
    for sheet in data.sheets:
        _render_template_sheet(wb[sheet.name], sheet, placements[sheet.name])
    wb.remove(wb["__report__"])
    return wb
