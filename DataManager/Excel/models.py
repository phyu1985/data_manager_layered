""" 帳票の設定と、Excelに依存しない出力データ。
"""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator, model_validator


class Column(BaseModel):
    """ 出力する1列と、その列に表示する見出し名。
    """

    field: str
    label: str | None = None

    @property
    def heading(self) -> str:
        return self.label or self.field


class Comparison(BaseModel):
    """ RecordまたはItemに対する単一の比較条件。
    """

    # 従来のComparison(field=...)はItemを対象とする。
    source: Literal["record", "item"] = "item"
    field: str
    op: Literal["==", "!=", "<", "<=", ">", ">="]
    value: Any

    @field_validator("value")
    @classmethod
    def not_none(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("条件の比較値にはNoneを指定できません")
        return value


class SheetSpec(BaseModel):
    """ 1つの出力シートに必要な抽出条件・列構成・Item配置。
    """

    name: str
    logic: Literal["AND", "OR"] = "AND"
    conditions: list[Comparison] = Field(min_length=1)
    headers: list[Column] = Field(default_factory=list)
    record_columns: list[Column] = Field(default_factory=list)
    item_columns: list[Column] = Field(min_length=1)
    item_titles: list[str] = Field(min_length=1)  # Excelに表示する文字列
    item_keys: list[str] | None = None  # Itemを出力する位置に対応させる識別子
    # Noneなら従来どおり位置順、指定時はItemのフィールド値で見出しと対応付ける。
    item_title_field: str | None = None


class ReportSpec(BaseModel):
    """ 帳票全体の定義。ソートは全シート共通、Noneは入力順維持。
    """

    sort_field: str | None = None
    descending: bool = False
    sheets: list[SheetSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_sheets(self) -> ReportSpec:
        names = [sheet.name for sheet in self.sheets]
        if len(names) != len(set(names)):
            raise ValueError("シート名が重複しています")
        return self


class HeaderData(BaseModel):
    """ シートの上部に1回だけ置く共通項目の値。
    """

    field: str
    label: str
    value: Any = None


class RowData(BaseModel):
    """ 1 Recordの出力値。item_valuesはItem枠順・フィールド順の二重リスト。
    """

    record_values: list[Any]
    item_values: list[list[Any]]


class SheetData(BaseModel):
    """ Excelのセル座標に依存しない1シート分の出力データ。
    """

    name: str
    headers: list[HeaderData]
    record_headings: list[str]
    item_headings: list[str]
    item_titles: list[str]
    rows: list[RowData]


class WorkbookData(BaseModel):
    """ コード方式・テンプレート方式に共通の描画入力。
    """

    sheets: list[SheetData]
