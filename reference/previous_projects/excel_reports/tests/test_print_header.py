from io import BytesIO

import pytest
from openpyxl import load_workbook
from pydantic import ValidationError

from example import Item, Record, example_spec, make_template, sample_records
from reporting import PrintHeaderSpec, ReportError, ReportGenerator


def test_code_print_header_and_body_layout_roundtrip():
    spec = example_spec(print_headers=True)
    spec.sheets[0].print_header.title = "温度検査の結果"
    wb = ReportGenerator(Record, Item).code(sample_records(), spec)
    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)
    ws = load_workbook(stream)["温度一覧"]
    assert ws.oddHeader.left.text == "担当部署：製造課"
    assert ws.oddHeader.center.text == "温度検査の結果"
    assert ws.oddHeader.right.text == "（&P/&N）"
    assert ws.oddHeader.center.font == "Meiryo"
    assert ws.oddHeader.center.size == 10
    assert ws["A1"].value == "管理番号"
    assert ws["A3"].value == "R001"


def test_print_only_fields_are_validated_without_becoming_body_headers():
    spec = example_spec()
    spec.sheets[0].headers = []
    spec.sheets[0].print_header = PrintHeaderSpec(left="{{header:department}}")
    gen = ReportGenerator(Record, Item)
    ws = gen.code(sample_records(), spec)["温度一覧"]
    assert ws["A1"].value == "管理番号"
    assert ws.oddHeader.left.text == "製造課"
    records = sample_records()
    records[2].department = "他部署"
    with pytest.raises(ReportError, match="department"):
        gen.prepare(records, spec)


def test_empty_records_and_repositioning():
    spec = example_spec(print_headers=True)
    spec.sheets[0].print_header = PrintHeaderSpec(
        title="空帳票", left="{{title}}", center="{{page}} / {{pages}}",
        right="担当部署：{{header:department}}", size=14,
    )
    ws = ReportGenerator(Record, Item).code([], spec)["温度一覧"]
    assert ws.oddHeader.left.text == "空帳票"
    assert ws.oddHeader.center.text == "&P / &N"
    assert ws.oddHeader.right.text == "担当部署："
    assert ws["C1"].value == "初期測定"
    assert ws["A3"].value is None


def test_literal_ampersands_and_markers_in_data_are_not_interpreted():
    records = sample_records()
    for record in records:
        record.department = "R&D &P {{pages}}"
    spec = example_spec(print_headers=True)
    spec.sheets[0].print_header = PrintHeaderSpec(
        title="A&B {{page}}", left="部門 & {{header:department}}",
    )
    ws = ReportGenerator(Record, Item).code(records, spec)["温度一覧"]
    assert ws.oddHeader.left.text == "部門 && R&&D &&P {{pages}}"
    assert ws.oddHeader.center.text == "A&&B {{page}}"
    assert ws.oddHeader.right.text == "（&P/&N）"


@pytest.mark.parametrize("text", ["{{unknown}}", "{{header:}}", "{{page", "page}}"])
def test_invalid_tokens(text):
    with pytest.raises(ValidationError):
        PrintHeaderSpec(left=text)


def test_missing_print_field_rejected_even_without_records():
    spec = example_spec()
    spec.sheets[0].print_header = PrintHeaderSpec(left="{{header:unknown}}")
    with pytest.raises(ReportError, match="unknown"):
        ReportGenerator(Record, Item).prepare([], spec)


def test_template_configuration_roundtrip_and_original_unchanged(tmp_path):
    path = tmp_path / "template.xlsx"
    make_template(path, print_headers=True)
    source = load_workbook(path)
    source["__report__"]["L5"] = "指定タイトル"
    source["温度一覧"].HeaderFooter.differentFirst = True
    source["温度一覧"].HeaderFooter.differentOddEven = True
    source.save(path)
    original = path.read_bytes()
    wb = ReportGenerator(Record, Item).template(sample_records(), path)
    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)
    ws = load_workbook(stream)["温度一覧"]
    assert ws.oddHeader.center.text == "指定タイトル"
    assert ws.oddHeader.left.text == "担当部署：製造課"
    assert ws.oddHeader.right.text == "（&P/&N）"
    assert ws.HeaderFooter.differentFirst is False
    assert ws.HeaderFooter.differentOddEven is False
    assert ws["B3"].value is None
    assert ws["A7"].value == "R001"
    assert path.read_bytes() == original


def test_template_existing_header_is_preserved_without_configuration(tmp_path):
    path = tmp_path / "template.xlsx"
    make_template(path)
    wb = load_workbook(path)
    wb["温度一覧"].oddHeader.center.text = "既存タイトル"
    wb.save(path)
    result = ReportGenerator(Record, Item).template([], path)
    assert result["温度一覧"].oddHeader.center.text == "既存タイトル"


@pytest.mark.parametrize("cell,value", [("P5", "FALSE"), ("M5", "{{unknown}}"), ("K6", "温度一覧")])
def test_invalid_template_configuration(tmp_path, cell, value):
    path = tmp_path / "template.xlsx"
    make_template(path, print_headers=True)
    wb = load_workbook(path)
    wb["__report__"][cell] = value
    wb.save(path)
    with pytest.raises(ReportError):
        ReportGenerator(Record, Item).template([], path)


def test_template_print_only_field_and_empty_values(tmp_path):
    path = tmp_path / "template.xlsx"
    make_template(path, print_headers=True)
    wb = load_workbook(path)
    wb["温度一覧"]["B3"] = None
    wb["__report__"]["O5"] = None  # 右欄の空欄指定でページ番号を非表示
    wb.save(path)
    gen = ReportGenerator(Record, Item)
    ws = gen.template([], path)["温度一覧"]
    assert ws.oddHeader.left.text == "担当部署："
    assert ws.oddHeader.right.text == ""
    records = sample_records()
    records[2].department = "別部署"
    with pytest.raises(ReportError, match="department"):
        gen.template(records, path)
