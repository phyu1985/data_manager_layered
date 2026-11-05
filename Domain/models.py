""" 保存用の設定と、加工・解析に必要な入力値。
"""
from pydantic import BaseModel, ConfigDict


class Settings(BaseModel):
    """ 現在版の設定値。旧版との差分は版変換で吸収する。
    """

    model_config = ConfigDict(extra="forbid")
    threshold: float
    gain: float = 1.0
    generate_output: bool = True


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
    generate_output: bool = True


class AnalysisPresets(BaseModel):
    """ 解析・編集に必要な値を、保存ファイルの構造から独立させる。
    """

    threshold: float
    gain: float
    measurements: list[Measurement]
    generate_output: bool = True
