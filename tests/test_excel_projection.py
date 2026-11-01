
import pytest
pytest.importorskip("openpyxl")
from datetime import date
import pytest
from openpyxl import load_workbook
from pydantic import BaseModel, Field
from DataManager.Excel import Column, Comparison, ReportGenerator, ReportError, ReportSpec, SheetSpec, ReportItem, ReportRecord
from tests.excel_fixtures import Item, Record, sample_records, example_spec, make_template


def test_projection_multi_sheet_sort_and_records_unchanged():
    records = sample_records()
    before = [record.model_dump() for record in records]
    data = ReportGenerator(Record, Item).prepare(records, example_spec())
    temp, volt = data.sheets
    assert [r.record_values[0] for r in temp.rows] == ["R001", "R003"]
    assert [r.record_values[0] for r in volt.rows] == ["R001", "R002", "R003", "R004"]
    assert volt.rows[3].item_values == [[None], [None]]  # Record条件でItemなしも採用
    # タイトル順に整列し、最終測定がないため右端は空欄になる。
    assert temp.rows[0].item_values == [[20, 10], [21, 11], [None, None]]
    # 電圧一覧は中間測定を表示しない。R001には最終測定がない。
    assert volt.rows[0].item_values == [[90], [None]]
    # R003には中間測定も存在するが、電圧一覧では対象外。
    assert volt.rows[2].item_values == [[105], [110]]
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
    voltage = wb["電圧一覧"]
    assert voltage["B5"].value == "初回" and voltage["C5"].value == "最終回"
    assert voltage["B7"].value == 90 and voltage["C7"].value is None
    assert voltage["B9"].value == 105 and voltage["C9"].value == 110
    assert voltage["A10"].value == "R004"  # Itemがなくても行を出す
    assert voltage["B10"].value is None and voltage["C10"].value is None
    assert load_workbook(path)["温度一覧"]["C7"].value == "{{item:temperature}}"


def test_none_comparison_does_not_match_even_not_equal():
    spec = ReportSpec(sort_field="order", sheets=[SheetSpec(
        name="欠損", conditions=[Comparison(field="temperature", op="!=", value=10)],
        item_columns=[Column(field="temperature")], item_titles=["検査1"]
    )])
    records = [Record(record_id="R", equipment="E", department="D", items=[Item(title="初期測定", order=1)])]
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
    with pytest.raises(ReportError, match="数"):
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
        Item(title="初期測定", kind="A", order=1, temperature=5),
        Item(title="中間測定", kind="B", order=2, temperature=20),
    ])]
    data = ReportGenerator(Record, Item).prepare(records, spec)
    assert len(data.sheets[0].rows) == 0  # ANDは同一Itemで判定
    assert len(data.sheets[1].rows) == 1


def test_sort_none_last_and_stable():
    records = [Record(record_id="R", equipment="E", department="製造課", items=[
        Item(title="検査0", order=None, kind="A", temperature=50),
        Item(title="検査1", order=1, kind="A", temperature=10),
        Item(title="検査2", order=1, kind="A", temperature=20),
    ])]
    # 位置順方式を明示し、ソート機能単体を確認する。
    spec = ReportSpec(sort_field="order", descending=True, sheets=[SheetSpec(
        name="温度一覧", conditions=[Comparison(field="kind", op="==", value="A")],
        item_columns=[Column(field="temperature")], item_titles=["1", "2", "3"],
    )])
    data = ReportGenerator(Record, Item).prepare(records, spec)
    assert [it[0] for it in data.sheets[0].rows[0].item_values] == [10, 20, 50]


def test_unsafe_formula_string_is_not_formula():
    records = [Record(record_id="=2+3", equipment="E", department="製造課", items=[
        Item(title="初期測定", kind="A", order=1, temperature=11),
    ])]
    wb = ReportGenerator(Record, Item).code(records, example_spec())
    cell = wb["温度一覧"]["A4"]
    assert cell.value == "=2+3" and cell.data_type == "s"


def test_date_condition_from_excel_datetime():
    # Excelの日付セルはopenpyxlでdatetimeとして読み込まれることがある。
    from datetime import datetime, date

    class DItem(ReportItem):
        seq: int
        when: date

    class DRecord(ReportRecord[DItem]):
        pass

    spec = ReportSpec(sort_field="seq", sheets=[SheetSpec(
        name="日付", conditions=[Comparison(field="when", op="<", value=datetime(2026, 11, 1))],
        item_columns=[Column(field="when")], item_titles=["予定1"]
    )])
    records = [DRecord(items=[DItem(title="予定1", seq=1, when=date(2026, 10, 29))])]
    assert len(ReportGenerator(DRecord, DItem).prepare(records, spec).sheets[0].rows) == 1


def test_invalid_comparison_value_even_without_records():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Comparison(field="order", op="==", value=None)


def test_template_item_title_alignment_with_missing_middle(tmp_path):
    """ 中間測定がないRecordでも最終測定は最終列に出力する。
    """
    path = tmp_path / "by_title.xlsx"
    make_template(path)
    from openpyxl import load_workbook
    wb = load_workbook(path)
    wb["__report__"]["B1"] = None  # 無ソートとタイトル対応の併用
    wb.save(path)

    records = [Record(record_id="R101", equipment="E", department="製造課", items=[
        Item(title="最終測定", kind="A", temperature=28, pressure=3),
        Item(title="初期測定", kind="A", temperature=18, pressure=2),
    ])]
    output = ReportGenerator(Record, Item).template(records, path)
    ws = output["温度一覧"]
    assert ws["A7"].value == "R101"
    assert ws["C7"].value == 18 and ws["D7"].value == 2
    assert ws["E7"].value is None and ws["F7"].value is None
    assert ws["G7"].value == 28 and ws["H7"].value == 3
    assert ws["C5"].value == "初期測定"
    assert ws["E5"].value == "中間測定"
    assert ws["G5"].value == "最終測定"


def test_title_match_unknown_title_is_skipped():
    spec = example_spec().model_copy(deep=True)
    spec.sheets[0].item_title_field = "title"
    records = [Record(record_id="R", equipment="E", department="製造課", items=[
        Item(title="不明な測定", kind="A", temperature=20),
    ])]
    # 照合キーにないItemは、Record条件等で採用されても表示しない。
    data = ReportGenerator(Record, Item).prepare(records, spec)
    assert data.sheets[0].rows[0].item_values == [[None, None]] * 3


def test_title_match_duplicate_title_error():
    spec = example_spec().model_copy(deep=True)
    spec.sheets[0].item_title_field = "title"
    records = [Record(record_id="R", equipment="E", department="製造課", items=[
        Item(title="初期測定", kind="A", temperature=20),
        Item(title="初期測定", kind="A", temperature=22),
    ])]
    with pytest.raises(ReportError, match="重複"):
        ReportGenerator(Record, Item).prepare(records, spec)


def test_code_defined_can_opt_in_to_title_matching():
    spec = example_spec().model_copy(deep=True)
    spec.sort_field = None
    spec.sheets[0].item_title_field = "title"
    records = [Record(record_id="R", equipment="E", department="製造課", items=[
        Item(title="最終測定", kind="A", temperature=29, pressure=3),
        Item(title="初期測定", kind="A", temperature=17, pressure=2),
    ])]
    data = ReportGenerator(Record, Item).prepare(records, spec)
    assert data.sheets[0].rows[0].item_values == [[17, 2], [None, None], [29, 3]]
    assert len(records[0].items) == 2
    assert records[0].items[0].title == "最終測定"


def test_sheet_item_keys_choose_different_titles_and_subset_without_sort():
    """ 同じItemをシートごとに異なる見出し・異なる出力数で扱える。
    """
    spec = example_spec()
    assert spec.sort_field is None
    records = [Record(record_id="RX", equipment="E", department="製造課", items=[
        Item(title="最終測定", kind="A", temperature=30, voltage=120),
        Item(title="中間測定", kind="B", temperature=25, voltage=500),
        Item(title="初期測定", kind="A", temperature=20, voltage=90),
    ])]
    data = ReportGenerator(Record, Item).prepare(records, spec)
    temp, volt = data.sheets
    assert temp.item_titles == ["初期測定", "中間測定", "最終測定"]
    assert [item[0] for item in temp.rows[0].item_values] == [20, 25, 30]
    assert volt.item_titles == ["初回", "最終回"]
    assert volt.rows[0].item_values == [[90], [120]]


def test_conditions_can_match_non_displayed_item():
    """ 条件判定はItem全件を見て、表示列の選択とは独立する。
    """
    record = Record(record_id="RX", equipment="E", department="製造課", items=[
        Item(title="中間測定", kind="B", temperature=7, voltage=500),
    ])
    data = ReportGenerator(Record, Item).prepare([record], example_spec())
    assert not data.sheets[0].rows  # 温度のAND条件不一致
    assert len(data.sheets[1].rows) == 1  # 中間測定で電圧のOR条件一致
    assert data.sheets[1].rows[0].item_values == [[None], [None]]  # ただし列には表示しない


def test_title_key_unknown_is_ignored_in_each_sheet():
    records = [Record(record_id="RX", equipment="E", department="製造課", items=[
        Item(title="初期測定_誤字", kind="B", voltage=200),
    ])]
    data = ReportGenerator(Record, Item).prepare(records, example_spec())
    assert not data.sheets[0].rows  # 温度一覧のItem条件には一致しない
    assert data.sheets[1].rows[0].item_values == [[None], [None]]


def test_key_validation_duplicate_and_length_mismatch():
    spec = example_spec().model_copy(deep=True)
    spec.sheets[1].item_keys = ["初期測定", "初期測定"]
    with pytest.raises(ReportError, match="キーが重複"):
        ReportGenerator(Record, Item).prepare([], spec)
    spec.sheets[1].item_keys = ["初期測定"]
    with pytest.raises(ReportError, match="数が一致"):
        ReportGenerator(Record, Item).prepare([], spec)


def test_item_keys_with_positional_mode_rejected():
    spec = example_spec().model_copy(deep=True)
    spec.sheets[1].item_title_field = None
    with pytest.raises(ReportError, match="item_title_field"):
        ReportGenerator(Record, Item).prepare([], spec)


def test_legacy_template_without_key_column_falls_back_to_title(tmp_path):
    """ J列を持たない旧式テンプレートも、表示タイトルと同じキーなら使える。
    """
    path = tmp_path / "legacy.xlsx"
    make_template(path)
    wb = load_workbook(path)
    cfg = wb["__report__"]
    for row in range(5, cfg.max_row + 1):
        cfg.cell(row, 10).value = None
    # 見出しとItem.titleが同じなら、そのまま照合できる。
    cfg["I8"] = "初期測定"
    cfg["I9"] = "最終測定"
    wb.save(path)
    data = ReportGenerator(Record, Item).template(sample_records(), path)
    assert data["電圧一覧"]["B5"].value == "初期測定"
    assert data["電圧一覧"]["C5"].value == "最終測定"


def test_duplicate_within_record_rejected_in_displayed_key():
    record = Record(record_id="RX", equipment="E", department="製造課", items=[
        Item(title="初期測定", kind="B", voltage=90),
        Item(title="初期測定", kind="B", voltage=91),
    ])
    with pytest.raises(ReportError, match="重複"):
        ReportGenerator(Record, Item).prepare([record], example_spec())


def test_template_two_columns_with_empty_middle_and_custom_heading(tmp_path):
    path = tmp_path / "new.xlsx"
    make_template(path)
    records = [Record(record_id="RX", equipment="E", department="製造課", items=[
        Item(title="最終測定", kind="B", voltage=123),
        Item(title="初期測定", kind="B", voltage=101),
    ])]
    wb = ReportGenerator(Record, Item).template(records, path)
    voltage = wb["電圧一覧"]
    assert voltage["B5"].value == "初回"
    assert voltage["C5"].value == "最終回"
    assert voltage["B7"].value == 101
    assert voltage["C7"].value == 123
    assert voltage["D5"].value is None  # 不要な3列目を作らない
    assert voltage["D7"].value is None


def test_record_condition_matches_empty_items_and_keeps_blank_columns():
    """ Record条件のみならitems=[]でも採用し、item見出し数だけ空欄を保持。
    """
    spec = ReportSpec(sheets=[SheetSpec(
        name="設備D", logic="AND",
        conditions=[Comparison(source="record", field="equipment", op="==", value="設備D")],
        record_columns=[Column(field="record_id")],
        item_columns=[Column(field="voltage")],
        item_titles=["初回", "最終回"], item_keys=["初期測定", "最終測定"],
        item_title_field="title",
    )])
    data = ReportGenerator(Record, Item).prepare(sample_records(), spec)
    assert [r.record_values[0] for r in data.sheets[0].rows] == ["R004"]
    assert data.sheets[0].rows[0].item_values == [[None], [None]]


def test_mixed_AND_requires_both_sides_even_with_empty_items():
    """ Recordが一致しても、ANDのItem条件があるならItemがない行は不採用。
    """
    records = [
        Record(record_id="R1", equipment="設備D", department="製造課", items=[]),
        Record(record_id="R2", equipment="設備D", department="製造課", items=[
            Item(title="初期測定", kind="B", temperature=10),
        ]),
        Record(record_id="R3", equipment="設備A", department="製造課", items=[
            Item(title="初期測定", kind="B", temperature=10),
        ]),
    ]
    spec = ReportSpec(sheets=[SheetSpec(
        name="AND", logic="AND", conditions=[
            Comparison(source="record", field="equipment", op="==", value="設備D"),
            Comparison(source="item", field="kind", op="==", value="B"),
        ], record_columns=[Column(field="record_id")],
        item_columns=[Column(field="temperature")], item_titles=["初期測定"],
        item_title_field="title",
    )])
    rows = ReportGenerator(Record, Item).prepare(records, spec).sheets[0].rows
    assert [r.record_values[0] for r in rows] == ["R2"]


def test_mixed_OR_keeps_record_if_items_empty():
    spec = ReportSpec(sheets=[SheetSpec(
        name="OR", logic="OR", conditions=[
            Comparison(source="record", field="equipment", op="==", value="設備D"),
            Comparison(field="voltage", op=">=", value=100),
        ], record_columns=[Column(field="record_id")],
        item_columns=[Column(field="voltage")], item_titles=["初回", "最終回"],
        item_keys=["初期測定", "最終測定"], item_title_field="title",
    )])
    records = [
        Record(record_id="R1", equipment="設備D", department="D", items=[]),
        Record(record_id="R2", equipment="設備X", department="D", items=[
            Item(title="初期測定", voltage=150),
        ]),
        Record(record_id="R3", equipment="設備X", department="D", items=[]),
    ]
    rows = ReportGenerator(Record, Item).prepare(records, spec).sheets[0].rows
    assert [r.record_values[0] for r in rows] == ["R1", "R2"]
    assert rows[0].item_values == [[None], [None]]
    assert rows[1].item_values == [[150], [None]]


def test_mixed_AND_item_conditions_require_same_item():
    spec = ReportSpec(sheets=[SheetSpec(
        name="AND", logic="AND", conditions=[
            Comparison(source="record", field="department", op="==", value="製造課"),
            Comparison(field="kind", op="==", value="A"),
            Comparison(field="temperature", op=">", value=10),
        ], record_columns=[Column(field="record_id")],
        item_columns=[Column(field="temperature")], item_titles=["初期測定", "中間測定"],
        item_keys=["初期測定", "中間測定"], item_title_field="title",
    )])
    records = [Record(record_id="R1", equipment="E", department="製造課", items=[
        Item(title="初期測定", kind="A", temperature=4),
        Item(title="中間測定", kind="B", temperature=20),
    ])]
    assert not ReportGenerator(Record, Item).prepare(records, spec).sheets[0].rows


def test_template_record_condition_and_blank_record_row(tmp_path):
    """ テンプレートC列record.* と旧式Item指定を両立し、R004を表示。
    """
    path = tmp_path / "record_conditions.xlsx"
    make_template(path)
    from DataManager.Excel.template import load_template
    wb = load_workbook(path)
    spec, _ = load_template(wb)
    assert [(c.source, c.field) for c in spec.sheets[0].conditions] == [
        ("item", "kind"), ("item", "temperature"), ("record", "department")
    ]
    assert [(c.source, c.field) for c in spec.sheets[1].conditions] == [
        ("item", "kind"), ("item", "voltage"), ("record", "equipment")
    ]
    result = ReportGenerator(Record, Item).template(sample_records(), path)
    ws = result["電圧一覧"]
    assert ws["A10"].value == "R004"
    assert ws["B10"].value is None and ws["C10"].value is None


def test_invalid_record_field_and_bad_source():
    spec = ReportSpec(sheets=[SheetSpec(
        name="不正", conditions=[Comparison(source="record", field="missing", op="==", value="x")],
        item_columns=[Column(field="voltage")], item_titles=["初期測定"],
    )])
    with pytest.raises(ReportError, match="record条件フィールド"):
        ReportGenerator(Record, Item).prepare([], spec)
    spec.sheets[0].conditions = [Comparison(source="record", field="items", op="==", value="x")]
    with pytest.raises(ReportError, match="record条件フィールド"):
        ReportGenerator(Record, Item).prepare([], spec)


def test_invalid_template_prefix_rejected(tmp_path):
    path = tmp_path / "bad_prefix.xlsx"
    make_template(path)
    wb = load_workbook(path)
    wb["__report__"]["C5"] = "unknown.kind"
    wb.save(path)
    with pytest.raises(ReportError, match="対象・フィールド指定が不正"):
        ReportGenerator(Record, Item).template(sample_records(), path)
