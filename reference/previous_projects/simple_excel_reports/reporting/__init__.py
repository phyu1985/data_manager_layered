"""帳票生成パッケージの公開窓口。

利用側はこのモジュールから設定モデルとReportGeneratorをimportする。
Excel座標や描画の補助関数は各内部モジュールへ閉じ込める。
"""

from .api import ReportGenerator
from .models import Column, Comparison, SheetSpec, ReportSpec, PrintHeaderSpec
from .project import ReportError

__all__ = [
    "ReportGenerator",
    "Column",
    "Comparison",
    "SheetSpec",
    "ReportSpec",
    "PrintHeaderSpec",
    "ReportError",
]
