""" 編集窓口を除いても、Presetsの型推論が維持されることを確認する。
"""
from typing import assert_type

from Domain.models import AnalysisPresets
from UseCase.analysis import AnalysisService
from UseCase.external_updates import ExternalUpdateService
from Domain.results import ExternalUpdateResult


def verify_types(analysis: AnalysisService, updates: ExternalUpdateService):
    assert_type(analysis.load(), AnalysisPresets)

    with analysis.edit() as presets:
        assert_type(presets, AnalysisPresets)
        assert_type(presets.threshold, float)
        presets.threshold = 110
        analysis.save_settings(presets, overwrite=True)
        assert_type(updates.refresh(presets=presets), ExternalUpdateResult)
