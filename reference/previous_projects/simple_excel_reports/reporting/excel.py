"""検証済みの論理データをopenpyxlのWorkbookへ描画する。

共通のセル設定・印刷ヘッダー、コード方式、テンプレート方式の順に配置する。
Recordの選択・ソート・共通値検証はproject.pyで完了している前提で扱う。
このモジュールはWorkbookを変更するが、ファイルへの保存は行わない。
"""
from __future__ import annotations

from copy import copy
from datetime import date, datetime
from re import Match
from typing import Any, TypedDict

from openpyxl import Workbook
from openpyxl.cell.cell import Cell, MergedCell
from openpyxl.styles import Alignment, Border, Font, GradientFill, PatternFill, Protection, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from .models import PRINT_TOKEN, WorkbookData, SheetData
from .template import Placement
from .project import ReportError


# --- コード方式の既定書式と、コピー対象セルの型 ---


BLUE = "244564"
PALE = "EAF1F6"
GRAY = "D0DBE5"
LINE = Side(style="thin", color=GRAY)
TABLE_BORDER = Border(left=LINE, right=LINE, top=LINE, bottom=LINE)


class CellSnapshot(TypedDict):
    """複製するセルの値と基本書式。数式参照・画像・コメントは複製対象外。

    valueは業務モデルの任意の属性値なのでAnyとする。
    Excelに保存できない値が渡された場合はopenpyxl側のエラーとなる。
    """

    value: Any
    font: Font
    fill: PatternFill | GradientFill
    border: Border
    alignment: Alignment
    number_format: str
    protection: Protection


# --- 2方式で共通のセル書き込み・印刷ヘッダー ---


def _set_value(cell: Cell, value: Any) -> None:
    """セルへ値を設定し、数式扱いの回避と日付の既定表示を適用する。"""
    cell.value = value
    # ユーザー提供の文字列がExcel数式にならないようにする。
    if isinstance(value, str) and value.startswith("="):
        cell.data_type = "s"
    if isinstance(value, (date, datetime)):
        cell.number_format = "yyyy/mm/dd"


def render_code(data: WorkbookData) -> Workbook:
    """定義順にシートを作成し、コード方式のレイアウトで新規ブックを返す。"""
    wb = Workbook()
    wb.remove(wb.active)
    for sheet in data.sheets:
        ws = wb.create_sheet(sheet.name)
        _render_code_sheet(ws, sheet)
    return wb


def _style_header(cell: Cell, *, dark: bool = False) -> None:
    """見出しセルの基本書式を設定する。dark=Trueは上段の濃色見出し用。"""
    cell.fill = PatternFill("solid", fgColor=BLUE if dark else PALE)
    cell.font = Font(name="Meiryo", size=10, bold=True,
                     color="FFFFFF" if dark else BLUE)
    cell.alignment = Alignment(horizontal="center", vertical="center")
    cell.border = TABLE_BORDER


def _set_print_header(ws: Worksheet, sheet: SheetData) -> None:
    """印刷ヘッダーのマーカーを置換し、全ページ共通の内容を設定する。

    ページ数はここでは計算せず、Excelが解釈する&P・&Nを埋め込む。
    設定がNoneならテンプレートの既存ヘッダーとページ別設定を保持する。
    """
    spec = sheet.print_header
    if spec is None:
        return  # テンプレートに既存のヘッダーがあれば保持する
    values = {h.field: h.value for h in sheet.headers}

    def escape(value: Any) -> str:
        """データ中の&をExcelの制御文字として解釈させない。Noneは空文字。"""
        return "" if value is None else str(value).replace("&", "&&")

    def resolve(text: str) -> str:
        """設定中のマーカーだけを一度置換する。挿入値は再解析しない。"""
        def replace(match: Match[str]) -> str:
            """検証済みの1マーカーを文字列またはページ番号コードへ変換する。"""
            token = match.group(1)
            if token == "page":
                return "&P"
            if token == "pages":
                return "&N"
            if token == "title":
                return escape(spec.title)
            return escape(values[token[7:]])
        # 固定文字と挿入値をそれぞれ一度だけエスケープする
        return PRINT_TOKEN.sub(replace, text.replace("&", "&&"))

    ws.HeaderFooter.differentFirst = False
    ws.HeaderFooter.differentOddEven = False
    for position in ("left", "center", "right"):
        part = getattr(ws.oddHeader, position)
        part.text = resolve(getattr(spec, position))
        part.font = spec.font
        part.size = spec.size


# --- コード方式：共通項目 → 2段見出し → Record行 ---


def _render_code_sheet(ws: Worksheet, sheet: SheetData) -> None:
    """1シートを描画する。上部共通項目がN件ならデータ開始はN+3行目。

    Record列は左に固定し、Itemごとの列群を右へ並べる。
    表の見出しと印刷ヘッダーは別々に設定する。
    """
    # 1. セル上部に表示する共通項目だけをA/B列へ書き込む。
    table_headers = [h for h in sheet.headers if h.in_table] if sheet.show_table_headers else []
    for idx, header in enumerate(table_headers, start=1):
        title_cell, value_cell = ws.cell(idx, 1), ws.cell(idx, 2)
        _set_value(title_cell, header.label)
        _set_value(value_cell, header.value)
        _style_header(title_cell)
        value_cell.alignment = Alignment(vertical="center")
        ws.row_dimensions[idx].height = 23
    # 2. 共通項目の件数から見出し2行とデータ開始行を決める。
    top = len(table_headers) + 1
    lower = top + 1
    start_row = lower + 1
    record_column_count = len(sheet.record_headings)
    item_block_width = len(sheet.item_headings)
    total_columns = record_column_count + item_block_width * len(sheet.item_titles)

    # Record見出しは縦結合、Item見出しは位置ごとに横結合する。
    for idx, label in enumerate(sheet.record_headings, start=1):
        cell = ws.cell(top, idx)
        _set_value(cell, label)
        _style_header(cell, dark=True)
        ws.merge_cells(start_row=top, start_column=idx,
                       end_row=lower, end_column=idx)
    for k, title in enumerate(sheet.item_titles):
        first = record_column_count + k * item_block_width + 1
        last = first + item_block_width - 1
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
    # 3. 1Recordを1行へ展開し、Itemが少ない行の残り枠は空欄で埋める。
    for i, row in enumerate(sheet.rows, start=start_row):
        all_values = row.record_values + [
            value for item in row.item_values for value in item
        ]
        for col in range(1, total_columns + 1):
            cell = ws.cell(i, col)
            _set_value(cell, all_values[col-1] if col <= len(all_values) else None)
            cell.border = TABLE_BORDER
            cell.alignment = Alignment(vertical="center")
        ws.row_dimensions[i].height = 21
    # 4. 表示・印刷の設定。横幅を1ページに収め、高さ方向は制限しない。
    for col in range(1, total_columns + 1):
        ws.column_dimensions[get_column_letter(col)].width = (
            20 if col <= record_column_count else 15
        )
    ws.row_dimensions[top].height = 26
    ws.row_dimensions[lower].height = 23
    ws.freeze_panes = f"A{start_row}"
    ws.sheet_view.showGridLines = False
    ws.print_options.horizontalCentered = True
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    _set_print_header(ws, sheet)


# --- テンプレート方式：見本の保持と複製 ---


def _snapshot(cell: Cell | MergedCell) -> CellSnapshot:
    """見本の値を書き換える前に、セル値と基本書式のコピーを保持する。

    結合セルの非左上セルも書式取得の対象。結合範囲自体は別に複製する。
    openpyxlの書式は共有されるため、copyを使ってコピー先と切り離す。
    """
    return {
        "value": cell.value, "font": copy(cell.font), "fill": copy(cell.fill),
        "border": copy(cell.border), "alignment": copy(cell.alignment),
        "number_format": cell.number_format, "protection": copy(cell.protection),
    }


def _paste(ws: Worksheet, row: int, col: int, snap: CellSnapshot) -> None:
    """保存済みの値と基本書式を、1始まりの行・列座標へ復元する。

    数式の参照先は変換しない。見本の表示形式は_set_valueの既定値より優先する。
    """
    cell = ws.cell(row, col)
    _set_value(cell, snap["value"])
    cell.font = copy(snap["font"])
    cell.fill = copy(snap["fill"])
    cell.border = copy(snap["border"])
    cell.alignment = copy(snap["alignment"])
    cell.number_format = snap["number_format"]
    cell.protection = copy(snap["protection"])


def _check_empty(ws: Worksheet, start_row: int, end_row: int,
                 start_col: int, end_col: int) -> None:
    """両端を含む矩形領域に既存値・結合があればReportErrorで中止する。

    書式のみが設定済みの空セルは許可する。検査範囲は実際の複製先に限る。
    """
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


def _render_template_sheet(ws: Worksheet, sheet: SheetData, place: Placement) -> None:
    """Item見本を横へ、Record見本行を下へ複製してから値を埋める。

    複製中はマーカーを残し、横・縦の展開が終わってから実値へ置換する。
    元の見本を先に書き換えると、その値が複製先へ混入するため順序を守る。
    画像・グラフ・数式参照・印刷範囲の自動拡張は行わない。
    """
    block_width = len(place.item_cols)
    first = place.first_item_col
    count = len(sheet.item_titles)
    last_col = first + block_width*count - 1
    title_row, data_row = place.title_row, place.data_row

    # 1. 横方向：Item見本を、見出しからデータ行までひとまとめに保存する。
    block = {
        (r, offset): _snapshot(ws.cell(r, first + offset))
        for r in range(title_row, data_row + 1)
        for offset in range(block_width)
    }
    original_merges = list(ws.merged_cells.ranges)
    # 列座標はブロック左端からの相対位置にして、横の複製先でも使う。
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

    # 2. 縦方向：横へ展開済みの見本行をRecord件数分コピーする。
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

    # 3. 複製完了後に、位置別タイトルと上部共通値を設定する。
    for index, title in enumerate(sheet.item_titles):
        _set_value(ws.cell(title_row, first+index*block_width), title)
    headers_by_field = {header.field: header.value for header in sheet.headers}
    for field, positions in place.header_cells.items():
        for row, col in positions:
            _set_value(ws.cell(row, col), headers_by_field[field] if sheet.show_table_headers else None)
    # 4. 一覧の値を設定する。Item数が少ないRecordの残り枠は空欄にする。
    for index, row in enumerate(sheet.rows):
        target = data_row + index
        for col, value in zip(place.record_cols, row.record_values):
            _set_value(ws.cell(target, col), value)
        for block_index in range(count):
            for offset in range(block_width):
                value = (row.item_values[block_index][offset]
                         if block_index < len(row.item_values) else None)
                _set_value(ws.cell(target, first + block_index*block_width + offset), value)

    # 5. 0件時は見本行の書式を保持し、データ用マーカーだけを消す。
    if not sheet.rows:
        for col in place.record_cols:
            _set_value(ws.cell(data_row, col), None)
        for col in range(first, last_col+1):
            _set_value(ws.cell(data_row, col), None)
    ws.sheet_view.showGridLines = False
    _set_print_header(ws, sheet)


def render_template(wb: Workbook, data: WorkbookData,
                    placements: dict[str, Placement]) -> Workbook:
    """読み込み済みのブックを直接変更し、設定シートを除いて返す。

    placementsのキーとdataのシート名はload_templateで対応付け済み。
    元ファイルへの書き込みは行わず、渡されたWorkbookと同じオブジェクトを返す。
    """
    for sheet in data.sheets:
        _render_template_sheet(wb[sheet.name], sheet, placements[sheet.name])
    wb.remove(wb["__report__"])
    return wb
