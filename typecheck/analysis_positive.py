""" 編集窓口を除いても、Presetsの型推論が維持されることを確認する。
"""
from typing import assert_type

from Domain.analysis import analyze_readings
from Domain.models import AnalysisPresets
from UseCase.analysis import AnalysisWorkspace, apply_analysis_result
from UseCase.external_updates import ExternalUpdater
from Domain.results import AnalysisResult, ExternalUpdateResult, ReviewSummary


def verify_types(analysis: AnalysisWorkspace, updates: ExternalUpdater):
    assert_type(analysis.load(), AnalysisPresets)

    with analysis.edit() as presets:
        assert_type(presets, AnalysisPresets)
        assert_type(presets.threshold, float)
        presets.threshold = 110
        result = analyze_readings(presets)
        assert_type(result, AnalysisResult)
        assert_type(result.summary, ReviewSummary)
        apply_analysis_result(presets, result)
        analysis.save_settings(presets, overwrite=True)
        assert_type(updates.refresh(presets=presets), ExternalUpdateResult)
