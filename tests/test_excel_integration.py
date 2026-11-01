""" 同じプロジェクト内のExcelエンジンと、Workbookへの接続を検証する。
"""
from pathlib import Path

import pytest

from DataManager.report_export import ReportExportService
from Domain.reporting import ReportRow


def test_existing_excel_report_receives_common_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    openpyxl = pytest.importorskip("openpyxl")
    from DataManager.Excel.adapter import build_voltage_excel
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
