""" 確認優先順位と集計を計算する。入力の変更は呼出元で明示する。
"""
from math import isfinite
from statistics import fmean

from pydantic import TypeAdapter

from Domain.models import AnalysisPresets
from Domain.results import AnalysisResult, ReviewSummary

_threshold_adapter = TypeAdapter(float)
_measurements_adapter = TypeAdapter(tuple[tuple[str, float], ...])


def analyze_readings(presets: AnalysisPresets) -> AnalysisResult:
    """ しきい値に近い測定から確認する順序と集計を返す。入力は変更しない。
    """
    # 編集中の代入値も検証する。計算に不要な項目やモデル全体は複製しない。
    threshold = _threshold_adapter.validate_python(presets.threshold, strict=True)
    source = _measurements_adapter.validate_python(
        tuple((row.measurement_id, row.value) for row in presets.measurements), strict=True,
    )
    if not source:
        raise ValueError("解析には一つ以上の測定値が必要です")
    if not isfinite(threshold):
        raise ValueError("しきい値は有限値が必要です")
    if any(not isfinite(value) for _, value in source):
        raise ValueError("測定値は有限値が必要です")

    # IDの一意性は前提にしない。位置で指定すれば同じIDの行も失われない。
    indices = tuple(sorted(
        range(len(source)),
        key=lambda i: (abs(source[i][1] - threshold), source[i][0]),
    ))
    summary = ReviewSummary(
        threshold=threshold,
        mean_value=fmean(source[i][1] for i in indices),
        max_value=max(value for _, value in source),
        exceeded_count=sum(value > threshold for _, value in source),
        order=tuple(source[i][0] for i in indices),
    )
    return AnalysisResult(summary, indices, source)
