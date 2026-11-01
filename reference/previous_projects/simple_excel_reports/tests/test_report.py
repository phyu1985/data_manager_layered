from datetime import date
import pytest
from openpyxl import load_workbook
from pydantic import BaseModel, Field
from reporting import Column, Comparison, ReportGenerator, ReportError, ReportSpec, SheetSpec
from example import Item, Record, sample_records, example_spec, make_template


def test_projection_multi_sheet_sort_and_records_unchanged():
    records = sample_records()
    before = [record.model_dump() for record in records]
    data = ReportGenerator(Record, Item).prepare(records, example_spec())
    temp, volt = data.sheets
    assert [r.record_values[0] for r in temp.rows] == ["R001", "R003"]
    assert [r.record_values[0] for r in volt.rows] == ["R001", "R002", "R003"]
    # R001: order=1 → order=2; 一致しなかったItemも出力される
    assert temp.rows[0].item_values == [[20, 10], [21, 11]]
    assert records[0].items[0].order == 2
    assert [record.model_dump() for record in records] == before


def test_code_renderer_merges_and_header_position():
    wb = ReportGenerator(Record, Item).code(sample_records(), example_spec())
    ws = wb["温度一覧"]
    assert ws["A1"].value == "担当部署" and ws["B1"].value == "製造課"
    assert ws["A2"].value == "管理番号"
    assert ws["C2"].value == "初期測定"
    assert ws["C3"].value == "温度"
    assert "C2:D2" in [str(x) for x in ws.merged_cells.ranges]
    assert ws["A4"].value == "R001"
    assert ws["C4"].value == 20
    assert ws["E4"].value == 21


def test_template_renderer_parity_and_styles(tmp_path):
    path = tmp_path / "template.xlsx"
    make_template(path)
    wb = ReportGenerator(Record, Item).template(sample_records(), path)
    assert set(wb.sheetnames) == {"温度一覧", "電圧一覧"}
    ws = wb["温度一覧"]
    assert ws["B3"].value == "製造課"
    assert ws["C5"].value == "初期測定" and ws["E5"].value == "中間測定"
    assert ws["G5"].value == "最終測定"
    assert ws["C7"].value == 20 and ws["E7"].value == 21
    assert ws["A8"].value == "R003"
    assert "E5:F5" in [str(x) for x in ws.merged_cells.ranges]
    assert ws["E6"].value == "温度"  # コピーした見本の列見出し
    assert ws["E6"].font.bold is True
    assert ws["E7"].border.bottom.style == ws["C7"].border.bottom.style
    assert load_workbook(path)["温度一覧"]["C7"].value == "{{item:temperature}}"


def test_none_comparison_does_not_match_even_not_equal():
    spec = ReportSpec(sort_field="order", sheets=[SheetSpec(
        name="欠損", conditions=[Comparison(field="temperature", op="!=", value=10)],
        item_columns=[Column(field="temperature")], item_titles=["検査1"]
    )])
    records = [Record(record_id="R", equipment="E", department="D", items=[Item(order=1)])]
    assert not ReportGenerator(Record, Item).prepare(records, spec).sheets[0].rows


def test_empty_records_still_create_1_item_block(tmp_path):
    gen = ReportGenerator(Record, Item)
    wb = gen.code([], example_spec())
    assert wb["温度一覧"]["C2"].value == "初期測定"
    assert wb["温度一覧"]["A4"].value is None
    path = tmp_path / "template.xlsx"
    make_template(path)
    wb2 = gen.template([], path)
    assert wb2["温度一覧"]["C5"].value == "初期測定"
    assert wb2["温度一覧"]["C7"].value is None
    assert wb2["温度一覧"]["B3"].value is None


def test_item_titles_short_error():
    spec = example_spec().model_copy(deep=True)
    spec.sheets[0].item_titles = ["初期測定"]
    with pytest.raises(ReportError, match="見出し名"):
        ReportGenerator(Record, Item).prepare(sample_records(), spec)


def test_headers_mismatch_error():
    records = sample_records()
    records[2].department = "他部署"
    with pytest.raises(ReportError, match="department"):
        ReportGenerator(Record, Item).prepare(records, example_spec())


def test_type_mismatch_error():
    spec = ReportSpec(sort_field="order", sheets=[SheetSpec(
        name="不正", conditions=[Comparison(field="temperature", op=">=", value="10")],
        item_columns=[Column(field="temperature")], item_titles=["初回"]
    )])
    with pytest.raises(ReportError, match="型が異なります"):
        ReportGenerator(Record, Item).prepare(sample_records(), spec)


def test_rightside_collision_fails(tmp_path):
    path = tmp_path / "template.xlsx"
    make_template(path)
    from openpyxl import load_workbook
    wb = load_workbook(path)
    wb["温度一覧"]["E5"].value = "上書き不可"
    wb.save(path)
    with pytest.raises(ReportError, match="既存の値"):
        ReportGenerator(Record, Item).template(sample_records(), path)


def test_template_missing_field_error(tmp_path):
    path = tmp_path / "template.xlsx"
    make_template(path)
    wb = load_workbook(path)
    wb["温度一覧"]["C7"].value = "{{item:unknown}}"
    wb.save(path)
    with pytest.raises(ReportError, match="Itemフィールド"):
        ReportGenerator(Record, Item).template(sample_records(), path)


def test_and_requires_same_item():
    spec = example_spec()
    records = [Record(record_id="R", equipment="E", department="製造課", items=[
        Item(kind="A", order=1, temperature=5),
        Item(kind="B", order=2, temperature=20),
    ])]
    data = ReportGenerator(Record, Item).prepare(records, spec)
    assert len(data.sheets[0].rows) == 0  # ANDは同一Itemで判定
    assert len(data.sheets[1].rows) == 1


def test_sort_none_last_and_stable():
    records = [Record(record_id="R", equipment="E", department="製造課", items=[
        Item(order=None, kind="A", temperature=50),
        Item(order=1, kind="A", temperature=10),
        Item(order=1, kind="A", temperature=20),
    ])]
    spec = example_spec().model_copy(deep=True)
    spec.descending = True
    data = ReportGenerator(Record, Item).prepare(records, spec)
    assert [it[0] for it in data.sheets[0].rows[0].item_values] == [10, 20, 50]


def test_unsafe_formula_string_is_not_formula():
    records = [Record(record_id="=2+3", equipment="E", department="製造課", items=[
        Item(kind="A", order=1, temperature=11),
    ])]
    wb = ReportGenerator(Record, Item).code(records, example_spec())
    cell = wb["温度一覧"]["A4"]
    assert cell.value == "=2+3" and cell.data_type == "s"


def test_date_condition_from_excel_datetime():
    # Excelの日付セルはopenpyxlでdatetimeとして読み込まれることがある。
    from datetime import datetime, date

    class DItem(BaseModel):
        seq: int
        when: date

    class DRecord(BaseModel):
        items: list[DItem] = Field(default_factory=list)

    spec = ReportSpec(sort_field="seq", sheets=[SheetSpec(
        name="日付", conditions=[Comparison(field="when", op="<", value=datetime(2026, 11, 1))],
        item_columns=[Column(field="when")], item_titles=["予定1"]
    )])
    records = [DRecord(items=[DItem(seq=1, when=date(2026, 10, 29))])]
    assert len(ReportGenerator(DRecord, DItem).prepare(records, spec).sheets[0].rows) == 1


def test_invalid_comparison_value_even_without_records():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Comparison(field="order", op="==", value=None)
