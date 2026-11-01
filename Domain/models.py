""" 加工・解析が必要とする値を明示する。ファイル操作や編集ロックは持たない。
"""
from pydantic import BaseModel, ConfigDict


class Settings(BaseModel):
    """ 現在の設定ファイルで使う値。版ごとのクラスは定義しない。
    """

    model_config = ConfigDict(extra="forbid")
    threshold: float
    gain: float = 1.0


class Measurement(BaseModel):
    """ 独立して保存・手修正できる測定行。
    """

    measurement_id: str
    value: float


class ProcessingPresets(BaseModel):
    """ 加工に必要な値だけを列挙し、設定ファイルの階層に依存させない。
    """

    threshold: float
    gain: float
    raw_values: list[float]


class AnalysisPresets(BaseModel):
    """ 解析・編集が参照する値を明示する。Settingsの全体は渡さない。
    """

    threshold: float
    gain: float
    measurements: list[Measurement]
