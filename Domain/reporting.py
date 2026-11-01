""" 帳票明細のモデルと、解析値から明細への対応を定める。
"""
from collections.abc import Sequence
from typing import Literal
from pydantic import BaseModel
from Domain.models import AnalysisPresets

ReportFormat = Literal["csv", "jsonl", "xlsx"]


class ReportRow(BaseModel):
    """ 一覧帳票の共通明細。表示と外部出力に使い、解析へは読み戻さない。
    """

    measurement_id: str
    value: float
    exceeds_threshold: bool


def build_report_rows(analyses: Sequence[AnalysisPresets]) -> list[ReportRow]:
    """ 読取済みの解析結果を一覧にする。出力形式の処理を混ぜない。
    """
    return [
        ReportRow(
            measurement_id=measurement.measurement_id, value=measurement.value,
            exceeds_threshold=measurement.value > presets.threshold,
        )
        for presets in analyses
        for measurement in presets.measurements
    ]
