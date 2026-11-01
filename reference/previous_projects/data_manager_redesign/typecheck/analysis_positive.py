""" 編集窓口を除いても、Presetsの型推論が維持されることを確認する。
"""
from typing import assert_type

from examples.analysis_models import AnalysisPresets
from examples.analysis_workflow import AnalysisService
from examples.external_updates import ExternalUpdateService, ExternalUpdateResult


def verify_types(analysis: AnalysisService, updates: ExternalUpdateService):
    assert_type(analysis.load(), AnalysisPresets)

    with analysis.edit() as presets:
        assert_type(presets, AnalysisPresets)
        assert_type(presets.threshold, float)
        presets.threshold = 110
        analysis.save_settings(presets, overwrite=True)
        assert_type(updates.refresh(presets=presets), ExternalUpdateResult)
