""" 外部の生データの一行を検証するモデル。
"""
from pydantic import BaseModel, FiniteFloat


class RawReading(BaseModel):
    """ 生データの一行。ファイルから読む段階で非有限の値を拒否する。
    """

    value: FiniteFloat
