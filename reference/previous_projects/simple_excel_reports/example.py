"""業務モデルと帳票定義を差し替えるための実行サンプル。

業務モデルはreport_models.py、Python定義はreport_patterns/へ分離している。
``python example.py`` で、登録済みパターンによる完成帳票3種類を保存する。
templates/の見本は初回だけ作成し、完成帳票の同名ファイルは上書きする。
"""
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet


# 業務モデルと定義の正本は専用モジュールに置く。旧import経路も維持する。
from report_models import Item, Record
from report_patterns.inspection import build_inspection_spec as example_spec
from report_patterns import get_pattern
from report_patterns.registry import TEMPLATE_DIR
from report_service import create_report


# --- 2. サンプル入力：複数シート一致・Item件数の違い・Itemなしを含む ---


def sample_records() -> list[Record]:
    """抽出・ソートの挙動を確認できる4件を、新しいインスタンスで返す。

    R001/R003は両シート、R002は電圧一覧へ出力される。
    R004はItemがないため、現在のANY抽出条件ではどのシートにも出ない。
    """
    return [
        Record(record_id="R001", equipment="設備A", department="製造課", items=[
            Item(kind="B", order=2, temperature=21, pressure=11, voltage=110),
            Item(kind="A", order=1, temperature=20, pressure=10, voltage=90),
        ]),
        Record(record_id="R002", equipment="設備B", department="製造課", items=[
            Item(kind="B", order=1, temperature=8, pressure=12, voltage=150),
        ]),
        Record(record_id="R003", equipment="設備C", department="製造課", items=[
            Item(kind="A", order=3, temperature=30, pressure=13, voltage=110),
            Item(kind="B", order=1, temperature=6, pressure=14, voltage=105),
            Item(kind="A", order=2, temperature=25, pressure=15, voltage=80),
        ]),
        Record(record_id="R004", equipment="設備D", department="製造課", items=[]),
    ]


# --- 4. Excelテンプレート：実運用では生成した見本をExcelで編集する ---


def make_template(path: Path, *, print_headers: bool = False) -> None:
    """編集可能な設定シートと見本セルを持つ.xlsxを指定パスへ保存する。

    Args:
        path: テンプレートの保存先。同名ファイルは上書きする。
        print_headers: 印刷ヘッダー設定をK～P列へ追加するか。

    この関数だけがサンプルテンプレートを新規作成する。ReportGeneratorの
    templateメソッドは、ここで保存したファイルを読み取って帳票を生成する。
    """
    wb = Workbook()
    cfg = wb.active
    cfg.title = "__report__"
    cfg["A1"] = "sort_field"
    cfg["B1"] = "order"
    cfg["A2"] = "descending"
    cfg["B2"] = False
    for i, value in enumerate(["sheet", "logic", "field", "operator", "value"], 1):
        cfg.cell(4, i, value)
    for i, value in enumerate(["sheet", "position", "title"], 7):
        cfg.cell(4, i, value)
    conditions = [
        ("温度一覧", "AND", "kind", "==", "A"),
        ("温度一覧", "AND", "temperature", ">=", 10),
        ("電圧一覧", "OR", "kind", "==", "B"),
        ("電圧一覧", "OR", "voltage", ">=", 100),
    ]
    for r, values in enumerate(conditions, 5):
        for col, value in enumerate(values, 1):
            cfg.cell(r, col, value)
    titles = [
        ("温度一覧", 1, "初期測定"), ("温度一覧", 2, "中間測定"),
        ("温度一覧", 3, "最終測定"),
        ("電圧一覧", 1, "初回"), ("電圧一覧", 2, "2回目"),
        ("電圧一覧", 3, "3回目"),
    ]
    for r, values in enumerate(titles, 5):
        for col, value in enumerate(values, 7):
            cfg.cell(r, col, value)
    cfg.column_dimensions["A"].width = 19
    cfg.column_dimensions["B"].width = 15
    cfg.column_dimensions["C"].width = 18
    cfg.column_dimensions["D"].width = 13
    cfg.column_dimensions["E"].width = 18
    cfg.column_dimensions["G"].width = 18
    cfg.column_dimensions["H"].width = 12
    cfg.column_dimensions["I"].width = 22
    cfg.freeze_panes = "A5"

    def setup(
        name: str,
        rec_fields: list[str],
        item_fields: list[tuple[str, str]],
    ) -> Worksheet:
        """上部共通値と5～7行目の見本を持つシートを作る。

        item_fieldsは（属性名、表示名）の組。見出しの結合・書式を含めて、
        5行目から7行目のItemブロックが右へ複製される構成にする。
        """
        ws = wb.create_sheet(name)
        item_start = len(rec_fields) + 1
        item_end = item_start + len(item_fields) - 1
        ws["A1"] = name + "（Excelテンプレート）"
        ws["A1"].font = Font(size=15, bold=True, color="244564")
        ws["A3"] = "担当部署"
        ws["B3"] = "{{header:department}}"
        ws["B3"].fill = PatternFill("solid", fgColor="EDF5FC")
        for c, field in enumerate(rec_fields, 1):
            ws.cell(5, c, field)
            ws.merge_cells(start_row=5, start_column=c, end_row=6, end_column=c)
            ws.cell(7, c, f"{{{{record:{field}}}}}")
        ws.cell(5, item_start, "{{item_title}}")
        if item_end > item_start:
            ws.merge_cells(start_row=5, start_column=item_start,
                           end_row=5, end_column=item_end)
        for c, (field, label) in enumerate(item_fields, item_start):
            ws.cell(6, c, label)
            ws.cell(7, c, f"{{{{item:{field}}}}}")
        for row in ws.iter_rows(min_row=5, max_row=7, min_col=1, max_col=item_end):
            for cell in row:
                cell.border = Border(bottom=Side(style="thin", color="BCCAD5"))
                if cell.row <= 6:
                    cell.fill = PatternFill("solid", fgColor="DCEAF5")
                    cell.font = Font(bold=True, color="244564")
                    cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[5].height = 25
        ws.row_dimensions[6].height = 23
        ws.row_dimensions[7].height = 23
        for c in range(1, item_end+1):
            ws.column_dimensions[get_column_letter(c)].width = 19
        ws.freeze_panes = "A7"
        ws.sheet_view.showGridLines = False
        return ws

    setup("温度一覧", ["record_id", "equipment"],
          [("temperature", "温度"), ("pressure", "圧力")])
    setup("電圧一覧", ["record_id"], [("voltage", "電圧")])
    if print_headers:
        for col, label in enumerate(
            ["sheet", "title", "left", "center", "right", "show_table_headers"], 11
        ):
            cfg.cell(4, col, label)
        for row, name in enumerate(["温度一覧", "電圧一覧"], 5):
            for col, value in enumerate([
                name, name + "（設備点検結果）", "担当部署：{{header:department}}",
                "{{title}}", "（{{page}}/{{pages}}）", False,
            ], 11):
                cfg.cell(row, col, value)
            # 固定文字・行配置はテンプレート側で管理する。
            wb[name]["A1"] = None
            wb[name]["A3"] = None
    wb.save(path)


# --- 5. 実行例：Workbookの保存は呼び出し側で行う ---


if __name__ == "__main__":
    root = Path(__file__).parent
    records = sample_records()
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    template = TEMPLATE_DIR / "inspection_submission.xlsx"
    if not template.exists():
        make_template(template, print_headers=True)

    # GUIでは、画面が保持する固定IDと選択済みRecord一覧をここへ渡す。
    outputs = {
        "inspection_standard": "帳票_コード方式.xlsx",
        "inspection_submission": "帳票_テンプレート方式.xlsx",
        "voltage_summary": "帳票_電圧確認一覧.xlsx",
    }
    for pattern_id, filename in outputs.items():
        pattern = get_pattern(pattern_id)
        workbook = create_report(pattern, records)
        workbook.save(root / filename)
        print(f"{pattern.name}を作成しました: {filename}")
