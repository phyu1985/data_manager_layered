""" 利用側に見せる窓口はここだけ。
"""
from __future__ import annotations

from pathlib import Path
from typing import Generic, Sequence, get_args, get_origin

from openpyxl import Workbook, load_workbook

from DataManager.Excel.contracts import ReportItem, ReportRecord, TItem
from DataManager.Excel.models import ReportSpec, WorkbookData
from DataManager.Excel.project import project
from DataManager.Excel.excel import render_code, render_template
from DataManager.Excel.template import load_template


class ReportGenerator(Generic[TItem]):
    """ 指定したRecord・Itemモデルに対応する帳票生成器。
    """

    def __init__(
        self,
        record_model: type[ReportRecord[TItem]],
        item_model: type[TItem],
    ):
        # Pydantic BaseModelだけでなく、帳票用I/Fの継承を要求する。
        # これでRecord.itemsとItem.titleの存在を生成時点で保証できる。
        if not isinstance(record_model, type) or not issubclass(record_model, ReportRecord):
            raise TypeError("record_modelはReportRecordを継承したクラスにしてください")
        if not isinstance(item_model, type) or not issubclass(item_model, ReportItem):
            raise TypeError("item_modelはReportItemを継承したクラスにしてください")

        # Recordが定義するitemsの型と、渡されたitem_modelの組み合わせを検査。
        # 例: ReportRecord[TemperatureItem] に VoltageItem を渡す誤りを検出する。
        annotation = record_model.model_fields["items"].annotation
        if get_origin(annotation) is not list or len(get_args(annotation)) != 1:
            raise TypeError("Record.itemsはlist[ReportItemの派生型]で定義してください")
        declared_item_model = get_args(annotation)[0]
        if (
            not isinstance(declared_item_model, type)
            or not issubclass(declared_item_model, ReportItem)
            or not issubclass(item_model, declared_item_model)
        ):
            raise TypeError(
                "Record.itemsの要素型とitem_modelが対応していません: "
                f"{annotation!r} / {item_model.__name__}"
            )

        self._record_model = record_model
        self._item_model = item_model

    @property
    def record_model(self) -> type[ReportRecord[TItem]]:
        return self._record_model

    @property
    def item_model(self) -> type[TItem]:
        return self._item_model

    def prepare(self, records: Sequence[ReportRecord[TItem]], spec: ReportSpec) -> WorkbookData:
        """ Excelへ書き込まず、出力対象と値を確定する。
        """
        return project(records, spec, self.record_model, self.item_model)

    def code(self, records: Sequence[ReportRecord[TItem]], spec: ReportSpec) -> Workbook:
        """ Pythonの帳票定義からExcelを作成する。
        """
        return render_code(self.prepare(records, spec))

    def template(self, records: Sequence[ReportRecord[TItem]], template_path: str | Path) -> Workbook:
        """ Excelテンプレートの帳票定義に従って出力する。
        """
        # 外部ブックリンクは帳票へ引き継がない（前回の警告対策）。
        wb = load_workbook(template_path, keep_links=False)
        spec, placements = load_template(wb)
        data = self.prepare(records, spec)
        return render_template(wb, data, placements)
