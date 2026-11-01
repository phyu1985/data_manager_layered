"""帳票定義（Spec）と、抽出・検証済みの出力データ（Data）。

Specは「何を出すか」、Dataは「どの値をどの順に出すか」を表す。
セル座標・罫線・結合はここに持たせず、描画処理とテンプレートに任せる。
"""
from __future__ import annotations

import re
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator, model_validator


# --- 帳票定義：利用側またはテンプレート読取処理が組み立てる ---


class Column(BaseModel):
    """出力するモデル属性と表示名。fieldは別名ではなくPythonの属性名。"""
    field: str
    label: str | None = None

    @property
    def heading(self) -> str:
        """表示名が省略・空文字の場合は属性名を見出しに使う。"""
        return self.label or self.field


class Comparison(BaseModel):
    """Itemの1フィールドに対する比較条件。複数条件の結合はSheetSpecが担う。"""
    field: str
    op: Literal["==", "!=", "<", "<=", ">", ">="]
    value: Any

    @field_validator("value")
    @classmethod
    def not_none(cls, value: Any) -> Any:
        """条件の右辺にはNoneを許可しない（Item側の欠損とは別の規則）。"""
        if value is None:
            raise ValueError("条件の比較値にはNoneを指定できません")
        return value


# 設定文字列のマーカーのみを扱う。挿入されるデータ値は再解析しない。
PRINT_TOKEN: re.Pattern[str] = re.compile(r"\{\{(.*?)\}\}")


class PrintHeaderSpec(BaseModel):
    """印刷用ヘッダーの内容と書体。セル上部の共通項目とは別の表示領域。

    left/center/rightでは ``{{title}}``、``{{header:属性名}}``、
    ``{{page}}``、``{{pages}}`` を使用できる。空文字ならその位置は非表示。
    titleはシート名と独立した任意の文字列。sizeの単位はポイント。
    """
    title: str = ""
    left: str = ""
    center: str = "{{title}}"
    right: str = "（{{page}}/{{pages}}）"
    font: str = "Meiryo"
    size: int = Field(default=10, ge=1, le=72)

    @field_validator("left", "center", "right")
    @classmethod
    def valid_tokens(cls, value: str) -> str:
        """未知のマーカーや閉じ忘れを、帳票の描画前に検出する。"""
        for token in PRINT_TOKEN.findall(value):
            if token not in ("title", "page", "pages") and not re.fullmatch(
                r"header:[A-Za-z_][A-Za-z_0-9]*", token
            ):
                raise ValueError(f"印刷ヘッダーのマーカーが不正です: {token}")
        remaining = PRINT_TOKEN.sub("", value)
        if "{{" in remaining or "}}" in remaining:
            raise ValueError("印刷ヘッダーのマーカーが閉じていません")
        return value

    def header_fields(self) -> list[str]:
        """印刷ヘッダーで参照するRecord属性を、出現順・重複なしで返す。"""
        return list(dict.fromkeys(
            token[7:] for text in (self.left, self.center, self.right)
            for token in PRINT_TOKEN.findall(text) if token.startswith("header:")
        ))


class SheetSpec(BaseModel):
    """1シートの抽出条件と列構成。

    conditionsは同一Item内でlogic（AND/OR）に従って評価する。
    条件全体を満たすItemが1件でもあれば、そのRecordと全Itemを出力する。
    headersはセル上部の共通項目、record_columnsは一覧のRecord列を表す。
    show_table_headersは共通項目のセル表示を制御し、列見出しは消さない。
    item_titlesはソート後の位置に対応する名称で、Itemの値からは生成しない。
    """
    name: str
    logic: Literal["AND", "OR"] = "AND"
    conditions: list[Comparison] = Field(min_length=1)
    headers: list[Column] = Field(default_factory=list)
    show_table_headers: bool = True
    print_header: PrintHeaderSpec | None = None
    record_columns: list[Column] = Field(default_factory=list)
    item_columns: list[Column] = Field(min_length=1)
    item_titles: list[str] = Field(min_length=1)


class ReportSpec(BaseModel):
    """ブック全体の定義。Itemのソート規則は全シートで共有する。"""
    sort_field: str
    descending: bool = False
    sheets: list[SheetSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_sheets(self) -> ReportSpec:
        """同じ名前のシートを複数定義する設定ミスを防ぐ。"""
        names = [sheet.name for sheet in self.sheets]
        if len(names) != len(set(names)):
            raise ValueError("シート名が重複しています")
        return self


# --- 出力データ：project.pyが生成し、excel.pyが描画する ---


class HeaderData(BaseModel):
    """シート内で一致を検証した共通値。

    in_table=Falseは印刷ヘッダー専用の値を示す。
    セル表示の可否は、さらにSheetData.show_table_headersで制御する。
    """
    field: str
    label: str
    value: Any = None
    in_table: bool = True


class RowData(BaseModel):
    """Record 1件分の値。item_valuesは「Item位置 → フィールド順」の二重リスト。"""
    record_values: list[Any]
    item_values: list[list[Any]]


class SheetData(BaseModel):
    """1シートの論理データ。列見出し・Item位置・行の順序は確定済み。

    rowsが空でもitem_titlesには1枠分を残す。セル配置は描画時に決める。
    """
    name: str
    headers: list[HeaderData]
    show_table_headers: bool = True
    print_header: PrintHeaderSpec | None = None
    record_headings: list[str]
    item_headings: list[str]
    item_titles: list[str]
    rows: list[RowData]


class WorkbookData(BaseModel):
    """定義順の全シートをまとめた、2方式の描画処理に共通の入力。"""
    sheets: list[SheetData]
