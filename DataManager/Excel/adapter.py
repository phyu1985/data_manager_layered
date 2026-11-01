""" Domainの共通明細を、同じDataManager内のExcelエンジンへ渡す。
"""
from collections.abc import Sequence
from io import BytesIO

from DataManager.Excel.api import ReportGenerator
from DataManager.Excel.contracts import ReportItem, ReportRecord
from DataManager.Excel.models import Column, Comparison, ReportSpec, SheetSpec
from Domain.reporting import ReportRow


class _VoltageItem(ReportItem):
    """ Excelエンジンの契約に合わせる表示用の一明細。
    """

    kind: str = "B"
    voltage: float


class _VoltageRecord(ReportRecord[_VoltageItem]):
    """ Domainのモデルを継承変更せず、帳票の行へ組み替える。
    """

    record_id: str


def build_voltage_excel(rows: Sequence[ReportRow]) -> bytes:
    """ 共通明細からWorkbookを生成し、保存担当へバイト列を返す。

    この例の測定値を電圧として表示する。実業務では項目対応とReportSpecを変える。
    """
    records = [
        _VoltageRecord(
            record_id=row.measurement_id,
            items=[_VoltageItem(title="measurement", voltage=row.value)],
        )
        for row in rows
    ]
    spec = ReportSpec(sheets=[SheetSpec(
        name="電圧一覧",
        conditions=[Comparison(field="kind", op="==", value="B")],
        record_columns=[Column(field="record_id", label="管理番号")],
        item_columns=[Column(field="voltage", label="電圧")],
        item_titles=["測定値"],
    )])

    # Excel固有の型はこの境界だけで使う。DomainにExcelの継承要件を持ち込まない。
    generator = ReportGenerator(_VoltageRecord, _VoltageItem)
    workbook = generator.code(records, spec)
    try:
        with BytesIO() as stream:
            workbook.save(stream)
            return stream.getvalue()
    finally:
        workbook.close()
