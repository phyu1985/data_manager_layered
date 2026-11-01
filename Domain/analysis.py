""" 保存先や画面を知らずに、解析用Presetsを計算する。
"""
from math import isfinite
from statistics import fmean
from Domain.models import AnalysisPresets
from Domain.results import ReviewSummary


def analyze_readings(presets: AnalysisPresets) -> ReviewSummary:
    """ しきい値付近の確認優先順位を決め、集計を返す。ファイル操作はしない。
    """
    checked = AnalysisPresets.model_validate(presets.model_dump(mode="python"))
    if not checked.measurements:
        raise ValueError("解析には一つ以上の測定値が必要です")
    if not isfinite(checked.threshold):
        raise ValueError("しきい値は有限値が必要です")
    if any(not isfinite(row.value) for row in checked.measurements):
        raise ValueError("測定値は有限値が必要です")

    rows = sorted(
        checked.measurements,
        key=lambda row: (abs(row.value - checked.threshold), row.measurement_id),
    )
    summary = ReviewSummary(
        threshold=checked.threshold,
        mean_value=fmean(row.value for row in rows),
        max_value=max(row.value for row in rows),
        exceeded_count=sum(row.value > checked.threshold for row in rows),
        order=tuple(row.measurement_id for row in rows),
    )

    # 並び順を解析結果として保存する。値そのものは再補正しないので、再解析で累積しない。
    # 編集中のPresets自身へ反映し、編集権を持たない別モデルへ置き換えない。
    presets.threshold = checked.threshold
    presets.gain = checked.gain
    presets.measurements = rows
    return summary
