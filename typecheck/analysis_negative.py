""" 誤った加工用データと更新引数を検出する。reportArgumentTypeが2件で正解。
"""
from Domain.models import ProcessingPresets
from UseCase.analysis import AnalysisService
from UseCase.external_updates import ExternalUpdateService


def invalid_calls(analysis: AnalysisService, updates: ExternalUpdateService):
    analysis.save_settings(ProcessingPresets(threshold=1, gain=1, raw_values=[]))
    updates.refresh(presets="wrong model")
