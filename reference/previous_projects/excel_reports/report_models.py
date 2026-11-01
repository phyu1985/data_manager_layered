"""利用側の業務モデル。帳票の配置や書式には依存しない。"""
from pydantic import BaseModel, Field


class Item(BaseModel):
    """1回分の測定。kindは抽出条件、orderは全シート共通のソートに使う。"""
    kind: str | None = None
    order: int | None = None
    temperature: float | None = None
    pressure: float | None = None
    voltage: float | None = None


class Record(BaseModel):
    """帳票の1行に対応する設備情報と、その設備が持つ測定一覧。"""
    record_id: str
    equipment: str
    department: str
    items: list[Item] = Field(default_factory=list)
