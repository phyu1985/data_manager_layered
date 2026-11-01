""" 保存済み解析データを外部へ反映し、失敗した反映だけを再試行できる窓口。
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import logging
from pathlib import Path
from typing import Any

from data_manager import ObjectRepository
from examples.analysis_models import AnalysisPresets
from examples.analysis_workflow import AnalysisService

ExternalWriter = Callable[[Path, AnalysisPresets], None]
_logger = logging.getLogger(__name__)


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


class ExternalUpdateService:
    """ 保存後の自動反映と「外部情報を更新」ボタンで同じ処理を使う。

    実DBは接続先の関数として渡す。コールバックは同じ保存物に何度実行しても
    重複登録しない更新処理にする。このクラスはDBトランザクションを推測しない。
    """

    def __init__(
        self, application: AnalysisService, *, targets: Mapping[str, ExternalWriter],
    ):
        if not targets or any(not name for name in targets):
            raise ValueError("名前付きの外部反映先を一つ以上指定してください")

        self._application = application
        self._targets = dict(targets)

    def refresh(
        self, *, presets: AnalysisPresets | None = None,
        target_names: Sequence[str] | None = None,
    ) -> ExternalUpdateResult:
        """ 保存済みの値を再反映する。失敗先だけを指定して再試行することもできる。
        """
        selected_names = tuple(self._targets) if target_names is None else tuple(target_names)
        if not selected_names or len(selected_names) != len(set(selected_names)):
            raise ValueError("反映先は重複のない一つ以上の名前で指定してください")
        if any(name not in self._targets for name in selected_names):
            raise ValueError("未登録の外部反映先です")

        # 排他と保存済み読取は解析サービスへ委譲する。
        # ここでは反映先の実行・失敗の収集だけを扱い、編集窓口の内部を参照しない。
        with self._application.saved_snapshot(presets=presets) as snapshot:
            return self._update_targets(snapshot, selected_names)

    def _update_targets(
        self, snapshot: AnalysisPresets, selected_names: Sequence[str],
    ) -> ExternalUpdateResult:
        """ 一つの失敗で他の反映を止めず、ファイル保存を巻き戻さない。
        """
        succeeded_targets: list[str] = []
        failures: list[ExternalUpdateFailure] = []

        for name in selected_names:
            try:
                # 外部処理の変更が別接続先の入力や画面の編集値へ混入するのを防ぐ。
                self._targets[name](self._application.directory, deepcopy(snapshot))
            except Exception as error:
                _logger.exception("外部情報の更新に失敗しました: %s", name)
                failures.append(ExternalUpdateFailure(target=name, error=error))
            else:
                succeeded_targets.append(name)

        return ExternalUpdateResult(tuple(succeeded_targets), tuple(failures))


def create_summary_writer(summary_directory: Path) -> ExternalWriter:
    """ 解析フォルダごとの最新情報を、集約フォルダのJSONへ更新する例。
    """
    repository = ObjectRepository[dict[str, Any]](model=dict, base_directory=summary_directory)

    def write_summary(source_directory: Path, snapshot: AnalysisPresets):
        """ 同じ解析フォルダは同じ保存先を更新し、再試行で行を増やさない。
        """
        # この例では正規化したパスを識別子にする。移動後も同一と扱う実業務では
        # 保存データ内の安定した識別子へ置き換える。
        source_identity = str(source_directory.resolve())
        file_name = sha256(source_identity.encode("utf-8")).hexdigest() + ".json"
        repository.save(file_name, {
            "source_directory": source_identity,
            "threshold": snapshot.threshold,
            "measurement_count": len(snapshot.measurements),
        }, overwrite=True)

    return write_summary
