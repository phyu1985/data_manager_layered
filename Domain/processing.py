""" Presetsから加工値を作る。保存や表示は呼出元が担当する。
"""
from collections.abc import Sequence
from math import isfinite
from Domain.models import AnalysisPresets, Measurement, ProcessingPresets


def _build_analysis_presets(
    values: Sequence[float], *, threshold: float, gain: float, generate_output: bool,
) -> AnalysisPresets:
    """ 入力順のIDを付け、解析へ渡す測定一覧を作る。
    """
    return AnalysisPresets(
        threshold=threshold,
        gain=gain,
        generate_output=generate_output,
        measurements=[
            Measurement(measurement_id=str(i), value=value)
            for i, value in enumerate(values)
        ],
    )


def process_data(presets: ProcessingPresets) -> AnalysisPresets:
    """ 値を補正せず、測定IDを付けて解析用モデルへ移す。
    """
    return _build_analysis_presets(
        presets.raw_values, threshold=presets.threshold, gain=presets.gain,
        generate_output=presets.generate_output,
    )


def process_readings(presets: ProcessingPresets) -> AnalysisPresets:
    """ 先頭値をゼロ基準にして補正し、解析へ渡すモデルを作る。
    """
    checked = ProcessingPresets.model_validate(presets.model_dump(mode="python"))
    if not checked.raw_values:
        raise ValueError("加工には一つ以上の測定値が必要です")
    if not isfinite(checked.gain) or checked.gain <= 0:
        raise ValueError("補正倍率は有限の正数が必要です")
    if not isfinite(checked.threshold):
        raise ValueError("しきい値は有限値が必要です")

    # 元の値には触れず、先頭値との差分に倍率を掛けた新しい列を作る。
    baseline = checked.raw_values[0]
    values = [(value - baseline) * checked.gain for value in checked.raw_values]
    if any(not isfinite(value) for value in values):
        raise ValueError("補正結果を有限値として保持できません")

    # 補正済みの値から新しいモデルを作り、入力と出力を共有しない。
    return _build_analysis_presets(
        values, threshold=checked.threshold, gain=checked.gain, generate_output=checked.generate_output,
    )
