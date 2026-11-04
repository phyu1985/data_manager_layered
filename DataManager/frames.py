""" 表への変換をファイル文法から分離する。pandasは必要なときだけ読み込む。
"""
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel

from DataManager.model_conversion import ModelBinding, ModelValue, SerializableValue

if TYPE_CHECKING:
    import pandas as pd


def to_frame(
    rows: Sequence[SerializableValue], *, columns: Sequence[str], dtypes: Mapping[str, Any] | None = None,
) -> "pd.DataFrame":
    """ 変換する列を明示する。入れ子の展開や列の暗黙の除外は行わない。
    """
    import pandas as pd

    if len(set(columns)) != len(columns) or not columns:
        raise ValueError("columnsは空でない重複のない列名リストです")

    # 列の脱落を先に検出し、指定された順序と型で表へ変換する。
    records = [
        row.model_dump(mode="python") if isinstance(row, BaseModel)
        else ModelBinding[dict[str, Any]](dict).to_dict(row, by_alias=False)
        for row in rows
    ]
    if any(set(row) - set(columns) for row in records):
        raise ValueError("指定したDataFrame列に含まれない項目があります")

    frame = pd.DataFrame.from_records(records, columns=list(columns))
    return frame.astype(dict(dtypes)) if dtypes is not None else frame


def from_frame(frame: "pd.DataFrame", *, model: type[ModelValue]) -> list[ModelValue]:
    """ 欠損をNoneへ揃えた後、各行をモデルで検証する。フレーム自体は変更しない。
    """
    if not frame.columns.is_unique or any(not isinstance(column, str) for column in list[object](frame.columns)):
        raise ValueError("DataFrameの列名は重複のない文字列が必要です")
    # pandas固有の欠損表現をNoneへ揃え、通常のモデル復元へ渡す。
    binding = ModelBinding(model)
    records = frame.astype(object).where(frame.notna(), None).to_dict(orient="records")
    # 全列名を上で実行時確認した後のcastであり、値の検証はrestore_valueが行う。
    return [binding.restore_value(cast(dict[str, Any], row)) for row in records]
