"""実行: python example.py -> 2方式のExcel帳票と編集可能なテンプレートを作る。"""
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from reporting import ReportGenerator, ReportItem, ReportRecord, ReportSpec, SheetSpec, Column, Comparison


class Item(ReportItem):
    kind: str | None = None
    order: int | None = None
    temperature: float | None = None
    pressure: float | None = None
    voltage: float | None = None


class Record(ReportRecord[Item]):
    record_id: str
    equipment: str
    department: str


def sample_records() -> list[Record]:
    return [
        Record(record_id="R001", equipment="設備A", department="製造課", items=[
            Item(title="中間測定", kind="B", order=2, temperature=21, pressure=11, voltage=110),
            Item(title="初期測定", kind="A", order=1, temperature=20, pressure=10, voltage=90),
        ]),
        Record(record_id="R002", equipment="設備B", department="製造課", items=[
            Item(title="初期測定", kind="B", order=1, temperature=8, pressure=12, voltage=150),
        ]),
        Record(record_id="R003", equipment="設備C", department="製造課", items=[
            Item(title="最終測定", kind="A", order=3, temperature=30, pressure=13, voltage=110),
            Item(title="初期測定", kind="B", order=1, temperature=6, pressure=14, voltage=105),
            Item(title="中間測定", kind="A", order=2, temperature=25, pressure=15, voltage=80),
        ]),
        Record(record_id="R004", equipment="設備D", department="製造課", items=[]),
    ]


def example_spec() -> ReportSpec:
    return ReportSpec(
        sort_field=None, descending=False,  # タイトルで位置を決めるので並べ替え不要
        sheets=[
            SheetSpec(
                name="温度一覧", logic="AND",
                conditions=[Comparison(field="kind", op="==", value="A"),
                            Comparison(field="temperature", op=">=", value=10),
                            Comparison(source="record", field="department", op="==", value="製造課")],
                headers=[Column(field="department", label="担当部署")],
                record_columns=[Column(field="record_id", label="管理番号"),
                                Column(field="equipment", label="設備名")],
                item_columns=[Column(field="temperature", label="温度"),
                              Column(field="pressure", label="圧力")],
                item_titles=["初期測定", "中間測定", "最終測定"],
                item_keys=["初期測定", "中間測定", "最終測定"],
                item_title_field="title",
            ),
            SheetSpec(
                name="電圧一覧", logic="OR",
                conditions=[Comparison(field="kind", op="==", value="B"),
                            Comparison(field="voltage", op=">=", value=100),
                            Comparison(source="record", field="equipment", op="==", value="設備D")],
                headers=[Column(field="department", label="担当部署")],
                record_columns=[Column(field="record_id", label="管理番号")],
                item_columns=[Column(field="voltage", label="電圧")],
                item_titles=["初回", "最終回"],
                item_keys=["初期測定", "最終測定"],  # 中間測定は電圧一覧に出さない
                item_title_field="title",
            ),
        ],
    )


def make_template(path: Path) -> None:
    """実際はこのテンプレートをExcelアプリで編集・保存すればよい。"""
    wb = Workbook()
    cfg = wb.active
    cfg.title = "__report__"
    cfg["A1"] = "sort_field"
    cfg["B1"] = None  # 空欄: ソートしない
    cfg["A2"] = "descending"
    cfg["B2"] = False
    for i, value in enumerate(["sheet", "logic", "field", "operator", "value"], 1):
        cfg.cell(4, i, value)
    for i, value in enumerate(["sheet", "position", "title", "key"], 7):
        cfg.cell(4, i, value)
    conditions = [
        ("温度一覧", "AND", "kind", "==", "A"),
        ("温度一覧", "AND", "temperature", ">=", 10),
        ("温度一覧", "AND", "record.department", "==", "製造課"),
        ("電圧一覧", "OR", "kind", "==", "B"),
        ("電圧一覧", "OR", "voltage", ">=", 100),
        ("電圧一覧", "OR", "record.equipment", "==", "設備D"),
    ]
    for r, values in enumerate(conditions, 5):
        for col, value in enumerate(values, 1):
            cfg.cell(r, col, value)
    # 表示タイトルはシートごとに自由。keyにはItem.titleの値を書く。
    titles = [
        ("温度一覧", 1, "初期測定", "初期測定"),
        ("温度一覧", 2, "中間測定", "中間測定"),
        ("温度一覧", 3, "最終測定", "最終測定"),
        ("電圧一覧", 1, "初回", "初期測定"),
        ("電圧一覧", 2, "最終回", "最終測定"),
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
    cfg.column_dimensions["J"].width = 22
    cfg.freeze_panes = "A5"

    def setup(name: str, rec_fields: list[str], item_fields: list[tuple[str, str]]):
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
            from openpyxl.utils import get_column_letter
            ws.column_dimensions[get_column_letter(c)].width = 19
        ws.freeze_panes = "A7"
        ws.sheet_view.showGridLines = False
        return ws

    setup("温度一覧", ["record_id", "equipment"],
          [("temperature", "温度"), ("pressure", "圧力")])
    setup("電圧一覧", ["record_id"], [("voltage", "電圧")])
    wb.save(path)


if __name__ == "__main__":
    root = Path(__file__).parent
    records = sample_records()
    engine = ReportGenerator(Record, Item)
    template = root / "帳票テンプレート.xlsx"
    make_template(template)
    engine.code(records, example_spec()).save(root / "帳票_コード方式.xlsx")
    engine.template(records, template).save(root / "帳票_テンプレート方式.xlsx")
    print("テンプレート、コード方式の帳票、テンプレート方式の帳票を作成しました")
