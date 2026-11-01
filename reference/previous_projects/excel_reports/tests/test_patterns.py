"""登録パターンを通じた生成と、既存サンプルとの互換性を確認する。"""
from io import BytesIO

import pytest
from openpyxl import load_workbook

from example import Item, Record, example_spec, make_template, sample_records
from report_models import Item as DomainItem, Record as DomainRecord
from report_patterns import CodeReportPattern, get_pattern, list_patterns
from report_patterns.registry import build_patterns
from report_service import create_report
from reporting import ReportError


def test_legacy_imports_and_fresh_definitions():
    assert Item is DomainItem and Record is DomainRecord
    pattern = get_pattern("inspection_standard")
    assert isinstance(pattern, CodeReportPattern)
    first = pattern.spec_factory()
    first.sheets[0].item_titles.clear()
    second = pattern.spec_factory()
    assert second.sheets[0].item_titles == example_spec().sheets[0].item_titles


@pytest.mark.parametrize("pattern_id,sheets", [
    ("inspection_standard", ["温度一覧", "電圧一覧"]),
    ("voltage_summary", ["電圧一覧"]),
])
def test_registered_code_patterns(pattern_id, sheets):
    records = sample_records()
    before = [record.model_dump() for record in records]
    wb = create_report(get_pattern(pattern_id), records)
    assert wb.sheetnames == sheets
    assert wb["電圧一覧"]["A3"].value == "R001"
    assert wb["電圧一覧"].oddHeader.left.text == "担当部署：製造課"
    assert [record.model_dump() for record in records] == before


def test_template_pattern_uses_configured_path_without_modifying_file(tmp_path):
    path = tmp_path / "inspection_submission.xlsx"
    make_template(path, print_headers=True)
    original = path.read_bytes()
    pattern = build_patterns(tmp_path)["inspection_submission"]
    wb = create_report(pattern, sample_records())
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    saved = load_workbook(buffer)
    assert saved.sheetnames == ["温度一覧", "電圧一覧"]
    assert saved["温度一覧"]["A7"].value == "R001"
    assert path.read_bytes() == original


def test_unknown_pattern_id():
    with pytest.raises(ReportError, match="登録されていません"):
        get_pattern("unknown")


def test_missing_template_reports_path(tmp_path):
    pattern = build_patterns(tmp_path)["inspection_submission"]
    with pytest.raises(ReportError, match="inspection_submission.xlsx"):
        create_report(pattern, [])


def test_pattern_list_order_and_empty_data():
    assert [p.id for p in list_patterns()] == [
        "inspection_standard", "inspection_submission", "voltage_summary",
    ]
    wb = create_report(get_pattern("voltage_summary"), [])
    assert wb["電圧一覧"]["B1"].value == "初回"
    assert wb["電圧一覧"]["A3"].value is None
