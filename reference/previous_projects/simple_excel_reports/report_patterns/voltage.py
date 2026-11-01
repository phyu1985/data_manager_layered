"""電圧確認一覧の定義。点検帳票の電圧シート構成を再利用する。"""
from reporting import ReportSpec

from .inspection import build_inspection_spec


def build_voltage_spec() -> ReportSpec:
    """電圧一覧だけを含む、新しい帳票定義を作る。

    Returns:
        印刷ヘッダーを有効にした1シートのReportSpec。
    """
    spec = build_inspection_spec(print_headers=True)
    spec.sheets = [sheet for sheet in spec.sheets if sheet.name == "電圧一覧"]
    return spec
