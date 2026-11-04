""" 保存済みデータを各接続先へ反映する手順と再試行を担当する。
"""
from __future__ import annotations
from collections.abc import Mapping, Sequence
from copy import deepcopy
import logging
from DataManager.summary import ExternalWriter
from Domain.models import AnalysisPresets
from Domain.results import ExternalUpdateFailure, ExternalUpdateResult
from UseCase.analysis import AnalysisWorkspace

_logger = logging.getLogger(__name__)


class ExternalUpdater:
    """ 保存済みデータを外部へ反映し、接続先ごとに成否を返す。

    再試行できるよう、接続先の関数は繰り返しても重複登録しない実装にする。
    """

    def __init__(self, workspace: AnalysisWorkspace, *, targets: Mapping[str, ExternalWriter]):
        if not targets or any(not name for name in targets):
            raise ValueError("名前付きの外部反映先を一つ以上指定してください")

        self._workspace = workspace
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

        # 未保存の編集値ではなく、Workspaceが確認した保存済みの値を送る。
        with self._workspace.saved_snapshot(presets=presets) as snapshot:
            return self._update_targets(snapshot, selected_names)

    def _update_targets(self, snapshot: AnalysisPresets, selected_names: Sequence[str]) -> ExternalUpdateResult:
        """ 一つの失敗で他の反映を止めず、ファイル保存を巻き戻さない。
        """
        succeeded_targets: list[str] = []
        failures: list[ExternalUpdateFailure] = []

        # 保存済みの一つのスナップショットを使い、接続先ごとの成否を独立して集める。
        for name in selected_names:
            try:
                # 外部処理の変更が別接続先の入力や画面の編集値へ混入するのを防ぐ。
                self._targets[name](self._workspace.directory, deepcopy(snapshot))
            except Exception as error:
                _logger.exception("外部情報の更新に失敗しました: %s", name)
                failures.append(ExternalUpdateFailure(target=name, error=error))
            else:
                succeeded_targets.append(name)

        return ExternalUpdateResult(tuple(succeeded_targets), tuple(failures))


# 旧名の移行用別名。外部への一方向の更新であり、汎用ファイル入出力ではない。
ExternalUpdateService = ExternalUpdater
