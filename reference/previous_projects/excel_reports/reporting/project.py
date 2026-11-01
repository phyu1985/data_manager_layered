"""振り分けと値の整列。ここではopenpyxlを使わない。"""
from __future__ import annotations

from datetime import date, datetime, time
from numbers import Number
from operator import eq, ne, lt, le, gt, ge
from typing import Any, Sequence
from pydantic import BaseModel
from .models import Comparison, ReportSpec, WorkbookData, SheetData, RowData, HeaderData


class ReportError(ValueError):
    """不正な帳票定義・入力データを検出した場合。"""


OPERATORS = {"==": eq, "!=": ne, "<": lt, "<=": le, ">": gt, ">=": ge}


def _get(model: BaseModel, field: str) -> Any:
    """正式なPydanticフィールドのみを参照し、存在しない名前は明示的にエラー。"""
    if field not in type(model).model_fields:
        raise ReportError(f"{type(model).__name__}にフィールド '{field}' がありません")
    return getattr(model, field)


def _check_type(a: Any, b: Any) -> None:
    """None以外の比較値について、型の誤指定を静かに見逃さない。"""
    if isinstance(a, bool) or isinstance(b, bool):
        ok = type(a) is type(b)
    elif isinstance(a, Number) and isinstance(b, Number):
        ok = True
    elif isinstance(a, str) and isinstance(b, str):
        ok = True
    elif isinstance(a, datetime) or isinstance(b, datetime):
        ok = isinstance(a, datetime) and isinstance(b, datetime)
    elif isinstance(a, date) or isinstance(b, date):
        ok = type(a) is date and type(b) is date
    else:
        ok = type(a) is type(b)
    if not ok:
        raise ReportError(f"比較する型が異なります: {type(a).__name__} / {type(b).__name__}")


def _matches(model: BaseModel, conditions: list[Comparison], logic: str) -> bool:
    """同じ対象（Recordまたは同一Item）に対する条件を評価する。"""
    checks = []
    for condition in conditions:
        value = _get(model, condition.field)
        if value is None:  # != であっても不一致
            checks.append(False)
            continue
        expected = condition.value
        # Excelで日付だけを指定しても、読み取り結果はdatetimeになることがある。
        if (type(value) is date and isinstance(expected, datetime)
                and expected.time() == time.min):
            expected = expected.date()
        _check_type(value, expected)
        try:
            checks.append(bool(OPERATORS[condition.op](value, expected)))
        except (TypeError, ValueError) as exc:
            raise ReportError(f"'{condition.field}' の比較に失敗: {exc}") from exc
    return all(checks) if logic == "AND" else any(checks)


def _record_matches(
    record: BaseModel,
    items: list[BaseModel],
    record_conditions: list[Comparison],
    item_conditions: list[Comparison],
    logic: str,
) -> bool:
    """Record条件とItem条件を評価。Item条件のANDは必ず同じItem内で成立する。"""
    if logic == "AND":
        # 条件が設定されていない側は、AND判定を妨げない。
        record_ok = (not record_conditions or _matches(record, record_conditions, "AND"))
        item_ok = (not item_conditions or any(
            _matches(item, item_conditions, "AND") for item in items
        ))
        return record_ok and item_ok

    # OR: Itemが0件でもRecord条件を満たせば採用される。
    record_ok = bool(record_conditions) and _matches(record, record_conditions, "OR")
    item_ok = bool(item_conditions) and any(
        _matches(item, item_conditions, "OR") for item in items
    )
    return record_ok or item_ok


def _sorted_items(record: BaseModel, sort_field: str, descending: bool) -> list[BaseModel]:
    """元のRecord.itemsに触れず、安定ソートした新しいリストを返す。"""
    items = list(_get(record, "items"))  # 元のリストを変更しない
    if not all(isinstance(item, BaseModel) for item in items):
        raise ReportError("Record.items はBaseModelのリストである必要があります")
    available = [(i, _get(item, sort_field)) for i, item in enumerate(items)]
    filled = [(i, value) for i, value in available if value is not None]
    try:
        filled.sort(key=lambda x: x[1], reverse=descending)  # 安定ソート
    except TypeError as exc:
        raise ReportError(f"Itemの並べ替えに失敗 ({sort_field}): {exc}") from exc
    # Noneは昇順・降順に関係なく最後、同値は元の順序を維持
    return [items[i] for i, _ in filled] + [items[i] for i, value in available if value is None]


def _validate_fields(spec: ReportSpec, record_model: type[BaseModel], item_model: type[BaseModel]) -> None:
    """帳票定義のフィールド参照・キーの構成を、値の出力前に検証する。"""
    rec_fields = record_model.model_fields
    item_fields = item_model.model_fields
    if "items" not in rec_fields:
        raise ReportError("Recordモデルにitemsフィールドが必要です")
    if spec.sort_field is not None and spec.sort_field not in item_fields:
        raise ReportError(f"Itemのソート項目 '{spec.sort_field}' がありません")
    for sheet in spec.sheets:
        # タイトル一致方式では「照合キー」と「表示名」は別々に扱う。
        if sheet.item_keys is not None and sheet.item_title_field is None:
            raise ReportError(f"シート '{sheet.name}' のitem_keysにはitem_title_fieldが必要です")
        if sheet.item_title_field is not None:
            if sheet.item_title_field not in item_fields:
                raise ReportError(
                    f"シート '{sheet.name}' のタイトル項目 '{sheet.item_title_field}' がありません"
                )
            keys = sheet.item_keys if sheet.item_keys is not None else sheet.item_titles
            if len(keys) != len(sheet.item_titles):
                raise ReportError(f"シート '{sheet.name}' のItemキーと見出し名の数が一致しません")
            if any(not isinstance(key, str) or not key.strip() for key in keys):
                raise ReportError(f"シート '{sheet.name}' に空欄または不正なItemキーがあります")
            if len(keys) != len(set(keys)):
                raise ReportError(f"シート '{sheet.name}' のItemキーが重複しています")
        for col in sheet.headers + sheet.record_columns:
            if col.field not in rec_fields or col.field == "items":
                raise ReportError(f"シート '{sheet.name}' のRecordフィールド '{col.field}' が不正です")
        for col in sheet.item_columns:
            if col.field not in item_fields:
                raise ReportError(f"シート '{sheet.name}' のItemフィールド '{col.field}' がありません")
        for condition in sheet.conditions:
            fields = rec_fields if condition.source == "record" else item_fields
            if condition.field not in fields or (condition.source == "record" and condition.field == "items"):
                raise ReportError(
                    f"シート '{sheet.name}' の{condition.source}条件フィールド "
                    f"'{condition.field}' が不正です"
                )


def project(
    records: Sequence[BaseModel], spec: ReportSpec,
    record_model: type[BaseModel], item_model: type[BaseModel],
) -> WorkbookData:
    """Excel操作なしでデータを確定。何か不正なら出力前に停止。"""
    _validate_fields(spec, record_model, item_model)
    for record in records:
        if not isinstance(record, record_model):
            raise ReportError(f"Recordの型が異なります: {type(record).__name__}")
        for item in _get(record, "items"):
            if not isinstance(item, item_model):
                raise ReportError(f"Itemの型が異なります: {type(item).__name__}")

    # 1Record内で共通の並び。複数シートでもソートを再実行しない。
    ordered_items = [
        _sorted_items(record, spec.sort_field, spec.descending)
        if spec.sort_field is not None else list(_get(record, "items"))
        for record in records
    ]
    sheets = []
    for sheet in spec.sheets:
        record_conditions = [c for c in sheet.conditions if c.source == "record"]
        item_conditions = [c for c in sheet.conditions if c.source == "item"]
        chosen = [
            (record, items)
            for record, items in zip(records, ordered_items)
            if _record_matches(record, items, record_conditions, item_conditions, sheet.logic)
        ]
        headers = []
        for col in sheet.headers:
            values = [_get(record, col.field) for record, _ in chosen]
            if values and any(value != values[0] for value in values[1:]):
                raise ReportError(f"シート '{sheet.name}' の共通項目 '{col.field}' の値が一致しません")
            headers.append(HeaderData(field=col.field, label=col.heading,
                                      value=values[0] if values else None))

        item_count = max((len(items) for _, items in chosen), default=0)
        # title一致を使うときは、途中のItemが欠けても列位置を固定する。
        count = (len(sheet.item_titles) if sheet.item_title_field is not None
                 else max(1, item_count))
        if count > len(sheet.item_titles):
            raise ReportError(
                f"シート '{sheet.name}' はItemが最大{count}件ですが、"
                f"見出し名が{len(sheet.item_titles)}件分しかありません"
            )
        keys = sheet.item_keys if sheet.item_keys is not None else sheet.item_titles
        key_positions = {key: index for index, key in enumerate(keys)}
        rows = []
        for record, items in chosen:
            if sheet.item_title_field is None:
                # 従来方式: ソート済みItemを左から順に置く。
                item_values = [
                    [_get(item, col.field) for col in sheet.item_columns]
                    for item in items
                ]
            else:
                # 全見出し分の空欄を確保。欠けたItemは空欄として残る。
                item_values = [[None] * len(sheet.item_columns) for _ in sheet.item_titles]
                occupied: set[int] = set()
                for item in items:
                    key = _get(item, sheet.item_title_field)
                    if not isinstance(key, str):
                        raise ReportError(
                            f"シート '{sheet.name}' のItemキーが文字列ではありません: {key!r}"
                        )
                    # 他のシートで使うキーは、このシートでは出力しない。
                    if key not in key_positions:
                        continue
                    index = key_positions[key]
                    if index in occupied:
                        raise ReportError(
                            f"シート '{sheet.name}' の同一Record内でItemキー '{key}' が重複しています"
                        )
                    occupied.add(index)
                    item_values[index] = [
                        _get(item, col.field) for col in sheet.item_columns
                    ]
            rows.append(RowData(
                record_values=[_get(record, col.field) for col in sheet.record_columns],
                item_values=item_values,
            ))
        sheets.append(SheetData(
            name=sheet.name, headers=headers,
            record_headings=[col.heading for col in sheet.record_columns],
            item_headings=[col.heading for col in sheet.item_columns],
            item_titles=sheet.item_titles[:count], rows=rows,
        ))
    return WorkbookData(sheets=sheets)
