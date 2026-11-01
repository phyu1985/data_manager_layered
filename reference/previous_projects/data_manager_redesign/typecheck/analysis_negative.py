""" 誤った加工用データと更新引数を検出する。reportArgumentTypeが2件で正解。
"""
from examples.analysis_models import ProcessingPresets
from examples.analysis_workflow import AnalysisService
from examples.external_updates import ExternalUpdateService


def invalid_calls(analysis: AnalysisService, updates: ExternalUpdateService):
    analysis.save_settings(ProcessingPresets(threshold=1, gain=1, raw_values=[]))
    updates.refresh(presets="wrong model")
