""" テンプレートでの連番数式と、業務データの数式注入対策を確認する。
"""

import pytest
pytest.importorskip("openpyxl")

from pathlib import Path

from openpyxl import Workbook, load_workbook

from tests.excel_fixtures import Item, Record
from DataManager.Excel import ReportGenerator


def _numbered_template(path: Path):
    """ A列が連番、B列がRecord、C列以降がItemの最小テンプレートを作る。
    """
    workbook = Workbook()
    config = workbook.active
    config.title = "__report__"
    config["B1"] = None
    config["B2"] = False
    # Record条件だけで抽出するので、items=[]のRecordも採用される。
    for column, value in enumerate(
        ("検査表", "AND", "record.department", "==", "製造課"), start=1
    ):
        config.cell(5, column, value)

    for row, key in enumerate(("初期測定", "最終測定"), start=5):
        for column, value in enumerate(("検査表", row - 4, key, key), start=7):
            config.cell(row, column, value)

    sheet = workbook.create_sheet("検査表")
    sheet["A5"] = "No."
    sheet["B5"] = "Record ID"
    sheet["C5"] = "{{item_title}}"
    sheet["C6"] = "電圧"
    # 固定座標を使わず、現在行のB列が空欄なら番号を表示しない。
    # 複製後も同じ式で正しい行番号を参照できる。
    sheet["A7"] = '=IF(INDEX(B:B,ROW())="","",ROW()-6)'
    sheet["B7"] = "{{record:record_id}}"
    sheet["C7"] = "{{item:voltage}}"
    workbook.save(path)


def test_numbering_formula_is_preserved_across_rows(tmp_path: Path):
    """ 見本行の数式を複製しても文字列化せず、各行の数式として保存する。
    """
    template = tmp_path / "numbered.xlsx"
    _numbered_template(template)
    records = [
        Record(record_id="R001", equipment="A", department="製造課", items=[
            Item(title="初期測定", voltage=100)
        ]),
        Record(record_id="R002", equipment="B", department="製造課", items=[]),
        Record(record_id="R003", equipment="C", department="製造課", items=[
            Item(title="最終測定", voltage=120)
        ]),
    ]
    output = ReportGenerator(Record, Item).template(records, template)
    report = output["検査表"]
    formula = '=IF(INDEX(B:B,ROW())="","",ROW()-6)'
    for row_index in range(7, 10):
        cell = report[f"A{row_index}"]
        assert cell.value == formula
        assert cell.data_type == "f"

    assert report["B7"].value == "R001"
    assert report["B8"].value == "R002"
    assert report["B9"].value == "R003"
    assert report["C8"].value is None  # R002はItemがない
    assert report["D8"].value is None
    assert report["C9"].value is None  # 最終測定しかないR003は初期列が空欄
    assert report["D9"].value == 120
    assert "__report__" not in output.sheetnames

    # 書き込み→再読込しても式として保持されていることを確認。
    exported = tmp_path / "output.xlsx"
    output.save(exported)
    reopened = load_workbook(exported)
    assert reopened["検査表"]["A8"].data_type == "f"
    assert reopened["検査表"]["A8"].value == formula


def test_template_with_zero_records_does_not_write_record_values(tmp_path: Path):
    """ 0件でも見出しは維持し、Record欄は空欄のままとする。
    """
    template = tmp_path / "numbered.xlsx"
    _numbered_template(template)
    result = ReportGenerator(Record, Item).template([], template)
    report = result["検査表"]
    assert report["B7"].value is None
    assert report["C7"].value is None
    assert report["D7"].value is None
    # A7のIF式は残るが、Excelで再計算すると空文字を返す。
    assert report["A7"].data_type == "f"
