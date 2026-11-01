""" 帳票モデルの共通I/Fと生成器の初期化時検証。
"""

import pytest
pytest.importorskip("openpyxl")
import pytest
from pydantic import BaseModel, ValidationError

from DataManager.Excel import ReportGenerator, ReportItem, ReportRecord
from tests.excel_fixtures import Item, Record


class OtherItem(ReportItem):
    value: int = 0


class OtherRecord(ReportRecord[OtherItem]):
    name: str = ""


def test_valid_models_can_create_generator():
    generator = ReportGenerator(Record, Item)
    assert generator.record_model is Record
    assert generator.item_model is Item


def test_base_model_without_report_contract_is_rejected():
    with pytest.raises(TypeError, match="ReportRecord"):
        ReportGenerator(BaseModel, Item)
    with pytest.raises(TypeError, match="ReportItem"):
        ReportGenerator(Record, BaseModel)


def test_record_and_item_type_mismatch_is_rejected():
    with pytest.raises(TypeError, match="対応していません"):
        ReportGenerator(Record, OtherItem)
    with pytest.raises(TypeError, match="対応していません"):
        ReportGenerator(OtherRecord, Item)


def test_record_declaring_wrong_items_container_is_rejected():
    class WrongRecord(ReportRecord[Item]):
        items: tuple[Item, ...] = ()

    with pytest.raises(TypeError, match="list"):
        ReportGenerator(WrongRecord, Item)


def test_title_is_required_and_nonempty():
    with pytest.raises(ValidationError):
        OtherItem()
    with pytest.raises(ValidationError):
        OtherItem(title="")


def test_missing_items_defaults_to_empty_list():
    first = OtherRecord(name="A")
    second = OtherRecord(name="B")
    first.items.append(OtherItem(title="初期測定"))
    assert second.items == []
