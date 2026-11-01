""" 帳票エンジンへ渡すRecord・Itemの最小I/F。
"""
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field


class ReportItem(BaseModel):
    """ 帳票用Itemの共通基底クラス。

    titleはExcelの表示名ではなく、__report__のkeyと一致させる照合キー。
    """

    title: str = Field(min_length=1)


TItem = TypeVar("TItem", bound=ReportItem)


class ReportRecord(BaseModel, Generic[TItem]):
    """ 帳票用Recordの共通基底クラス。

    items=[]でもRecord側の条件で出力できる。
    """

    items: list[TItem] = Field(default_factory=list)
