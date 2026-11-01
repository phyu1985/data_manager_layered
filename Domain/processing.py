""" Presetsから加工値を作る。保存や表示は呼出元が担当する。
"""
from math import isfinite
from Domain.models import AnalysisPresets, Measurement, ProcessingPresets


def process_data(presets: ProcessingPresets) -> AnalysisPresets:
    """ 架空の加工例。必要な値だけを受け取り、ファイルや編集権を扱わない。
    """
    measurements = [
        Measurement(measurement_id=str(i), value=value)
        for i, value in enumerate(presets.raw_values)
    ]
    return AnalysisPresets(
        threshold=presets.threshold, gain=presets.gain, measurements=measurements,
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

    baseline = checked.raw_values[0]
    values = [(value - baseline) * checked.gain for value in checked.raw_values]
    if any(not isfinite(value) for value in values):
        raise ValueError("補正結果を有限値として保持できません")

    # 既存の加工例でIDと行モデルを作り、このシナリオの補正値を反映する。
    # 元のPresetsや生データは変更しない。
    result = process_data(checked)
    for measurement, value in zip(result.measurements, values, strict=True):
        measurement.value = value
    return result
