""" 外部excel_reportsが指定された場合に、実際のWorkbookへの接続を検証する。
"""
import os
from pathlib import Path

import pytest

from examples.report_export import ReportExportService, ReportRow
from examples.excel_reports_adapter import build_voltage_excel


def test_existing_excel_report_receives_common_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    report_directory = os.environ.get("EXCEL_REPORTS_ROOT")
    if not report_directory:
        pytest.skip("EXCEL_REPORTS_ROOTで既存Excel帳票プロジェクトを指定すると実行")

    openpyxl = pytest.importorskip("openpyxl")
    monkeypatch.syspath_prepend(report_directory)
    service = ReportExportService(tmp_path, excel_writer=build_voltage_excel)
    service.export("voltage.xlsx", [
        ReportRow(measurement_id="measurement-1", value=125, exceeds_threshold=True),
    ])

    # ファイルができただけでなく、既存パターンのシートへ識別子と値が届いたことを確認する。
    workbook = openpyxl.load_workbook(tmp_path / "voltage.xlsx")
    try:
        assert workbook.sheetnames == ["電圧一覧"]
        cell_values = [cell.value for row in workbook["電圧一覧"] for cell in row]
        assert "measurement-1" in cell_values
        assert 125 in cell_values
    finally:
        workbook.close()
