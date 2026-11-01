""" 既存excel_reportsの電圧一覧へ、架空の共通明細を接続する例。
"""
from collections.abc import Sequence
from importlib import import_module
from io import BytesIO

from pydantic import create_model

from examples.report_export import ReportRow


def build_voltage_excel(rows: Sequence[ReportRow]) -> bytes:
    """ 現在のReportRecord / ReportItem契約に合わせ、Workbookをバイト列へ変換する。

    excel_reportsのルートをPYTHONPATHへ加え、openpyxlを用意して実行する。
    この例では測定値を電圧として扱う。実業務では項目対応を置き換える。
    """
    # Excelを選んだ場合だけ任意の外部プロジェクトを読み込む。
    # 汎用RepositoryやCSV利用者にopenpyxlへの依存を持ち込まない。
    reporting = import_module("reporting")

    # 旧report_models.Record / Itemは現在の基底契約を満たさない。
    # 任意依存を遅延読込した後で、接続例に必要な最小モデルだけを作る。
    item_model = create_model(
        "VoltageItem", __base__=reporting.ReportItem,
        kind=(str, "B"), voltage=(float, ...),
    )
    record_model = create_model(
        "VoltageRecord", __base__=reporting.ReportRecord[item_model],
        record_id=(str, ...),
    )

    records = [
        record_model(
            record_id=row.measurement_id,
            items=[item_model(title="measurement", kind="B", voltage=row.value)],
        )
        for row in rows
    ]
    # 現在の登録パターンにはPrintHeaderSpecの参照不整合があるため、
    # 接続例専用の定義を現在の公開APIで作る。既存プロジェクトは変更しない。
    specification = reporting.ReportSpec(sheets=[reporting.SheetSpec(
        name="電圧一覧",
        conditions=[reporting.Comparison(field="kind", op="==", value="B")],
        record_columns=[reporting.Column(field="record_id", label="管理番号")],
        item_columns=[reporting.Column(field="voltage", label="電圧")],
        item_titles=["測定値"],
    )])
    generator = reporting.ReportGenerator(record_model, item_model)
    workbook = generator.code(records, specification)

    try:
        with BytesIO() as stream:
            workbook.save(stream)
            return stream.getvalue()
    finally:
        workbook.close()
