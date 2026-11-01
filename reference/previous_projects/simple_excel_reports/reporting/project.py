"""業務データをExcelに依存しない帳票データへ変換する。

定義・入力の検証、Itemの共通ソート、シート別のRecord選択、共通値の
一致検証、列順に沿った値の抽出を行う。セル操作・ファイル保存は行わない。
"""
from __future__ import annotations

from datetime import date, datetime, time
from numbers import Number
from operator import eq, ne, lt, le, gt, ge
from typing import Any, Callable, Sequence
from pydantic import BaseModel
from .models import Column, Comparison, ReportSpec, WorkbookData, SheetData, RowData, HeaderData


class ReportError(ValueError):
    """不正な帳票定義・入力データを検出した場合。"""


OPERATORS: dict[str, Callable[[Any, Any], bool]] = {
    "==": eq, "!=": ne, "<": lt, "<=": le, ">": gt, ">=": ge,
}


def _get(model: BaseModel, field: str) -> Any:
    """宣言済みフィールドの値を取得し、属性名の誤りをReportErrorにそろえる。"""
    if field not in type(model).model_fields:
        raise ReportError(f"{type(model).__name__}にフィールド '{field}' がありません")
    return getattr(model, field)


def _check_type(a: Any, b: Any) -> None:
    """比較値の型の整合性を確認する。実際の演算可否は_matchesで確認する。

    数値同士は許可するが、boolはintの派生型なので先に区別する。
    同様にdatetimeをdateより先に判定し、日付と日時を混同しない。
    """
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


def _matches(item: BaseModel, conditions: list[Comparison], logic: str) -> bool:
    """1つのItemに対する条件全体の結果を返す。Record全体のANY判定はしない。

    Noneは!=を含む全比較で不成立。それ以外の型不整合はエラーにする。
    Item内の全条件を評価するため、AND/ORの短絡で比較エラーを隠さない。
    """
    checks: list[bool] = []
    for condition in conditions:
        value = _get(item, condition.field)
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


def _sorted_items(record: BaseModel, sort_field: str, descending: bool) -> list[BaseModel]:
    """入力リストを変えずに並べたItem参照を返す。モデル自体は複製しない。

    同値は元順を保つ。Noneを別に保持し、昇順・降順とも末尾へ置く。
    """
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
    """モデルの定義に対して参照先を検証する。入力0件でも検証を省略しない。"""
    rec_fields = record_model.model_fields
    item_fields = item_model.model_fields
    if "items" not in rec_fields:
        raise ReportError("Recordモデルにitemsフィールドが必要です")
    if spec.sort_field not in item_fields:
        raise ReportError(f"Itemのソート項目 '{spec.sort_field}' がありません")
    for sheet in spec.sheets:
        print_columns = ([Column(field=f) for f in sheet.print_header.header_fields()]
                         if sheet.print_header else [])
        for col in sheet.headers + sheet.record_columns + print_columns:
            if col.field not in rec_fields or col.field == "items":
                raise ReportError(f"シート '{sheet.name}' のRecordフィールド '{col.field}' が不正です")
        for col in sheet.item_columns:
            if col.field not in item_fields:
                raise ReportError(f"シート '{sheet.name}' のItemフィールド '{col.field}' がありません")
        for condition in sheet.conditions:
            if condition.field not in item_fields:
                raise ReportError(f"シート '{sheet.name}' の条件フィールド '{condition.field}' がありません")


def project(
    records: Sequence[BaseModel], spec: ReportSpec,
    record_model: type[BaseModel], item_model: type[BaseModel],
) -> WorkbookData:
    """定義と入力を検証し、シート順・行順・列順が確定した値を返す。

    Args:
        records: 入力順で出力するRecord一覧。Itemやリストを書き換えない。
        spec: 共通ソート規則と各シートの抽出条件・表示項目。
        record_model: Recordの期待するPydanticモデルクラス。
        item_model: Itemの期待するPydanticモデルクラス。

    Returns:
        対象0件のシートも含む論理データ。空シートの共通値はNoneとなる。

    Raises:
        ReportError: 参照フィールド・入力型・比較・ソート・共通値・見出し数が不正。
    """
    # 1. モデル定義と入力の型を検証する。
    _validate_fields(spec, record_model, item_model)
    for record in records:
        if not isinstance(record, record_model):
            raise ReportError(f"Recordの型が異なります: {type(record).__name__}")
        for item in _get(record, "items"):
            if not isinstance(item, item_model):
                raise ReportError(f"Itemの型が異なります: {type(item).__name__}")

    # 2. 各RecordのItem順を一度だけ作り、全シートで共有する。
    # 条件は順序に依存しないため、ここで先にソートしても選択結果は変わらない。
    ordered_items = [_sorted_items(record, spec.sort_field, spec.descending) for record in records]
    sheets: list[SheetData] = []
    for sheet in spec.sheets:
        # 3. シートごとに独立してRecordを選ぶ。一致しないItemも出力には含める。
        chosen = [
            (record, items)
            for record, items in zip(records, ordered_items)
            if any(_matches(item, sheet.conditions, sheet.logic) for item in items)
        ]
        # 4. セル用・印刷用の共通項目を合わせ、選択済みRecord内だけで一致を検証。
        headers: list[HeaderData] = []
        table_fields = {col.field for col in sheet.headers}
        extra_columns = ([Column(field=f) for f in sheet.print_header.header_fields()
                          if f not in table_fields] if sheet.print_header else [])
        for col in sheet.headers + extra_columns:
            values = [_get(record, col.field) for record, _ in chosen]
            if values and any(value != values[0] for value in values[1:]):
                raise ReportError(f"シート '{sheet.name}' の共通項目 '{col.field}' の値が一致しません")
            headers.append(HeaderData(field=col.field, label=col.heading,
                                      value=values[0] if values else None,
                                      in_table=col.field in table_fields))

        # 5. シート内の最大Item数に合わせて枠数を決め、位置別名称を割り当てる。
        item_count = max((len(items) for _, items in chosen), default=0)
        count = max(1, item_count)  # 0件でも1つの見出し枠は保持
        if count > len(sheet.item_titles):
            raise ReportError(
                f"シート '{sheet.name}' はItemが最大{count}件ですが、"
                f"見出し名が{len(sheet.item_titles)}件分しかありません"
            )
        # 6. モデル属性を定義の列順で取り出す。Excel座標への変換は描画側が担う。
        rows = [
            RowData(
                record_values=[_get(record, col.field) for col in sheet.record_columns],
                item_values=[[_get(item, col.field) for col in sheet.item_columns] for item in items],
            )
            for record, items in chosen
        ]
        sheets.append(SheetData(
            name=sheet.name, headers=headers,
            show_table_headers=sheet.show_table_headers,
            print_header=sheet.print_header,
            record_headings=[col.heading for col in sheet.record_columns],
            item_headings=[col.heading for col in sheet.item_columns],
            item_titles=sheet.item_titles[:count], rows=rows,
        ))
    return WorkbookData(sheets=sheets)
