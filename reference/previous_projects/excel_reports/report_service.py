"""GUI・CLI共通の帳票生成窓口。PySide6への依存は持たない。"""
from typing import Sequence

from openpyxl import Workbook

from report_models import Item, Record
from report_patterns.models import CodeReportPattern, ReportPattern, TemplateReportPattern
from reporting import ReportError, ReportGenerator


def create_report(pattern: ReportPattern, records: Sequence[Record]) -> Workbook:
    """選択済みデータを、指定されたパターンでWorkbookへ変換する。

    Args:
        pattern: 登録一覧から取得した帳票パターン。
        records: GUIなどで選択・取得済みのRecord一覧。入力順を維持する。

    Returns:
        保存前のWorkbook。保存先の選択とsaveは呼び出し側が担当する。

    Raises:
        ReportError: テンプレートが存在しない、または帳票定義・入力が不正。
        TypeError: 対応していないパターン型が渡された場合。

    データの取得や画面操作は行わない。この利用側の窓口はreport_modelsの
    Record/Itemに対応する。別業務のモデルを使う場合はこの組み合わせを変更する。
    """
    generator = ReportGenerator(Record, Item)
    if isinstance(pattern, CodeReportPattern):
        # 定義を毎回生成し、別の出力処理へ設定変更が伝わることを避ける。
        return generator.code(records, pattern.spec_factory())
    if isinstance(pattern, TemplateReportPattern):
        if not pattern.template_path.is_file():
            raise ReportError(f"帳票テンプレートがありません: {pattern.template_path}")
        return generator.template(records, pattern.template_path)
    raise TypeError(f"未対応の帳票パターン型です: {type(pattern).__name__}")
