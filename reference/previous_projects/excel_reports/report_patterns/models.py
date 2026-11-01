"""GUIで選ぶ帳票パターンの型。1パターンは1ブック全体を表す。"""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from reporting import ReportSpec


@dataclass(frozen=True)
class CodeReportPattern:
    """Python定義を使用するパターン。

    Args:
        id: 設定保存や画面選択で使う固定ID。表示名を変えても変更しない。
        name: 利用者に表示する名前。
        description: 選択画面に表示する用途の説明。
        spec_factory: 呼び出すたびに新しいReportSpecを返す関数。
    """

    id: str
    name: str
    description: str
    spec_factory: Callable[[], ReportSpec]


@dataclass(frozen=True)
class TemplateReportPattern:
    """Excel定義を使用するパターン。条件・列・書式は.xlsx内で管理する。

    Args:
        id: プログラムで識別する固定ID。
        name: 利用者に表示する名前。
        description: 選択画面に表示する用途の説明。
        template_path: 使用する.xlsxの場所。存在確認は出力時に行う。
    """

    id: str
    name: str
    description: str
    template_path: Path


ReportPattern = CodeReportPattern | TemplateReportPattern
