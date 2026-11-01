""" UseCaseが呼出元へ返す結果。ファイル操作や表示は持たない。
"""
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ReviewSummary:
    """ 解析の確認用集計。別ファイルには保存せず、画面やログへ渡す。
    """

    threshold: float
    mean_value: float
    max_value: float
    exceeded_count: int
    order: tuple[str, ...]


@dataclass(frozen=True)
class DemoResult:
    """ 実行した例の出力先と、二回の解析結果を呼出元へ返す。
    """

    analysis_directory: Path
    report_path: Path
    first: ReviewSummary
    second: ReviewSummary


@dataclass(frozen=True)
class ExternalUpdateFailure:
    """ 接続先と元の例外を残し、UIの通知・ログ・再試行判断へ渡す。
    """

    target: str
    error: Exception


@dataclass(frozen=True)
class ExternalUpdateResult:
    """ 反映先ごとの成否。解析データの保存成否とは区別する。
    """

    succeeded_targets: tuple[str, ...]
    failures: tuple[ExternalUpdateFailure, ...]
