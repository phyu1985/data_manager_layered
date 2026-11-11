""" 加工入力の組立て。解析フォルダの編集管理へ依存させない。
"""
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from DataManager.services import FileReader
from DataManager.settings_versions import create_settings_repository
from Domain.models import ProcessingPresets


def load_processing_presets(path: Path, raw_values: Sequence[float]) -> tuple[ProcessingPresets, dict[str, Any]]:
    """ 設定を現在版で読み、加工に必要な値と維持項目を組み立てる。
    """
    # 旧版設定を現在モデルで読み、加工用の値と維持項目を分けて受け渡す。
    source = path.resolve()
    document = FileReader(repository=create_settings_repository(source.parent), path=source.name).load()

    # 設定と生データから、加工処理へ渡す入力を組み立てる。
    presets = ProcessingPresets(
        threshold=document.settings.threshold, gain=document.settings.gain, raw_values=list(raw_values),
        generate_output=document.settings.generate_output,
    )
    return presets, dict(document.retained_values)
