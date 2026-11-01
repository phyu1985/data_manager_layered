"""帳票生成の公開API。

処理は「定義の取得 → 論理データの生成 → Excelへの描画」の順に進む。
ファイルへの保存は呼び出し側が ``workbook.save(path)`` で行う。
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence
from pydantic import BaseModel
from openpyxl import Workbook, load_workbook
from .models import ReportSpec, WorkbookData
from .project import project
from .excel import render_code, render_template
from .template import load_template


class ReportGenerator:
    """利用側の業務モデルを使って、2方式の帳票を生成する。

    Args:
        record_model: ``items`` フィールドを持つPydanticモデルのクラス。
        item_model: ``Record.items`` の要素となるPydanticモデルのクラス。

    モデルのクラスを受け取るため、入力が0件でも参照フィールドを検証できる。
    """

    def __init__(self, record_model: type[BaseModel], item_model: type[BaseModel]) -> None:
        self.record_model = record_model
        self.item_model = item_model

    def prepare(self, records: Sequence[BaseModel], spec: ReportSpec) -> WorkbookData:
        """定義と入力を検証し、Excel座標を含まない出力データを返す。

        入力のRecord・Itemおよびそのリストは変更しない。
        フィールド不備やシート内の共通値不一致などはReportErrorとなる。
        Excelを生成する前の値・並び順を確認する際にも利用できる。
        """
        return project(records, spec, self.record_model, self.item_model)

    def code(self, records: Sequence[BaseModel], spec: ReportSpec) -> Workbook:
        """Python定義から新しいWorkbookを生成する。保存は行わない。"""
        return render_code(self.prepare(records, spec))

    def template(self, records: Sequence[BaseModel], template_path: str | Path) -> Workbook:
        """テンプレートの定義・書式を読み、値を埋めたWorkbookを返す。

        元ファイルは変更しない。返されたWorkbookは設定用シートを除去済み。
        元テンプレートを保つ場合は、呼び出し側で別のパスへ保存する。
        """
        wb = load_workbook(template_path)
        spec, placements = load_template(wb)
        data = self.prepare(records, spec)
        return render_template(wb, data, placements)
