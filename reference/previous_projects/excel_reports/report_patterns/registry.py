"""帳票パターンの登録場所。GUIは表示名ではなくIDでパターンを選択する。"""
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from reporting import ReportError

from .inspection import build_standard_spec
from .models import CodeReportPattern, ReportPattern, TemplateReportPattern
from .voltage import build_voltage_spec


# カレントディレクトリに依存させず、このプロジェクトの位置を基準にする。
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


def build_patterns(template_dir: Path = TEMPLATE_DIR) -> Mapping[str, ReportPattern]:
    """登録順のパターン一覧を作る。ファイルの読み書きは行わない。

    Args:
        template_dir: テンプレートの配置先。テストや配布先で差し替えられる。

    Returns:
        固定IDをキーにした読み取り専用のマッピング。
    """
    patterns: tuple[ReportPattern, ...] = (
        CodeReportPattern(
            id="inspection_standard",
            name="点検結果一覧（標準）",
            description="温度・電圧の2シートを標準レイアウトで出力します。",
            spec_factory=build_standard_spec,
        ),
        TemplateReportPattern(
            id="inspection_submission",
            name="点検結果一覧（提出用）",
            description="Excelテンプレートの配置・書式で出力します。",
            template_path=template_dir / "inspection_submission.xlsx",
        ),
        CodeReportPattern(
            id="voltage_summary",
            name="電圧確認一覧",
            description="電圧一覧シートだけを出力します。",
            spec_factory=build_voltage_spec,
        ),
    )
    return MappingProxyType({pattern.id: pattern for pattern in patterns})


PATTERNS = build_patterns()


def list_patterns() -> tuple[ReportPattern, ...]:
    """GUIの選択肢に使う、登録順のパターン一覧を返す。

    Returns:
        表示名・説明・固定IDを持つパターンのタプル。
    """
    return tuple(PATTERNS.values())


def get_pattern(pattern_id: str) -> ReportPattern:
    """画面や保存設定から取得した固定IDを、登録済みパターンへ変換する。

    Args:
        pattern_id: 表示名ではなく、登録済みの固定ID。

    Returns:
        IDに対応するパターン定義。

    Raises:
        ReportError: 未登録のIDが指定された場合。
    """
    try:
        return PATTERNS[pattern_id]
    except KeyError as exc:
        raise ReportError(f"帳票パターン '{pattern_id}' は登録されていません") from exc
