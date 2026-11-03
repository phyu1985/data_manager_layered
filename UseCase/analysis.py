""" 解析結果の反映と、編集・保存の管理。計算はDomainへ委譲する。
"""
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import get_ident
from typing import Any

from DataManager.storage import EditConflictError, EditSession, Storage
from DataManager.analysis_files import AnalysisDocument, AnalysisFiles
from Domain.models import AnalysisPresets
from Domain.results import AnalysisResult


def apply_analysis_result(presets: AnalysisPresets, result: AnalysisResult):
    """ 計算時と同じ入力にだけ、解析で決めた並び順を反映する。保存は別操作。
    """
    current = tuple((row.measurement_id, row.value) for row in presets.measurements)
    if presets.threshold != result.summary.threshold or current != result.source_measurements:
        raise ValueError("解析後に入力が変更されています。再計算してください")

    indices = result.measurement_indices
    if (
        any(type(i) is not int for i in indices)
        or sorted(indices) != list(range(len(current)))
        or tuple(current[i][0] for i in indices) != result.summary.order
    ):
        raise ValueError("解析結果の並び順が入力と一致しません")

    # 検証を終えてから一度だけ変更する。Presetsと各測定行の同一性を保つ。
    presets.measurements = [presets.measurements[i] for i in indices]


@dataclass(frozen=True)
class _EditState:
    """ 編集値・所有スレッド・編集権を一組で保持する。
    """

    document: AnalysisDocument
    thread_id: int
    session: EditSession


class AnalysisWorkspace:
    """ 編集権を管理し、保存をAnalysisFilesへ委譲する。

    edit()で渡したPresetsだけを保存対象とし、別画面の値の誤保存を防ぐ。
    """

    def __init__(self, directory: Path):
        """ 解析フォルダと保存担当を固定する。ここでは編集を開始しない。
        """
        self._directory = directory.resolve()
        self._storage = Storage.discover(self._directory)
        self._files = AnalysisFiles(self._directory, commit_guard=self._write_guard)
        self._edit: _EditState | None = None

    @property
    def directory(self) -> Path:
        return self._directory

    def exists(self) -> bool:
        """ ファイル名の知識を利用側へ持ち出さず、選択候補か確認する。
        """
        return self._files.exists()

    @contextmanager
    def edit(self, *, force: bool = False) -> Generator[AnalysisPresets, None, None]:
        """ 読取前に編集権を取り、終了まで同じ権利を保持する。
        """
        if self._edit is not None:
            raise EditConflictError("同じ作業窓口で編集を重ねて開始できません")
        with self._storage.edit(self._directory, force=force) as session:
            document = self._files.load()
            session.check()
            self._edit = _EditState(document, get_ident(), session)

            try:
                yield document.presets
            finally:
                # 例外時も編集を閉じる。共有の所有者情報の解放はsessionへ委譲する。
                self._edit = None

    def _require_edit(self, presets: AnalysisPresets) -> AnalysisDocument:
        """ 現在の編集で取得したPresetsだけを保存対象として認める。
        """
        state = self._edit
        if state is None or state.thread_id != get_ident() or state.document.presets is not presets:
            raise RuntimeError("同じスレッドの有効な編集セッションと、そのPresetsが必要です")
        state.session.check()
        return state.document

    def save_settings(self, presets: AnalysisPresets, *, overwrite: bool = False):
        """ 編集中の設定だけを現在版で保存する。別出力はexport_settingsで明示する。
        """
        document = self._require_edit(presets)
        self._files.save_settings(presets, document.retained_values, overwrite=overwrite)

    def export_settings(
        self, path: str | Path, presets: AnalysisPresets, *, target_version: int | None = None,
        overwrite: bool = False,
    ):
        """ 現在の編集値を別ファイルへ出力する。元の一式は更新しない。
        """
        document = self._require_edit(presets)
        self._files.export_settings(path, presets, document.retained_values,
                                   target_version=target_version, overwrite=overwrite)

    def save_measurements(self, presets: AnalysisPresets, *, overwrite: bool = False):
        """ 編集中の測定行だけを保存する。
        """
        self._require_edit(presets)
        self._files.save_measurements(presets, overwrite=overwrite)

    @contextmanager
    def _write_guard(self, path: Path) -> Generator[None, None, None]:
        """ 書出し完了後の置換直前にも編集権を確認する。失効後の保存を通さない。
        """
        state = self._edit
        if state is None or state.thread_id != get_ident():
            raise RuntimeError("有効な編集セッションが必要です")
        with state.session.commit_guard(path):
            yield

    def save_initial(self, presets: AnalysisPresets, *, retained_values: dict[str, Any] | None = None):
        """ 初回保存にも同じ編集権と保存時検証を適用する。
        """
        if self._edit is not None:
            raise RuntimeError("編集中に初回保存を開始できません")
        with self._storage.edit(self._directory) as session:
            self._edit = _EditState(AnalysisDocument(presets, retained_values or {}), get_ident(), session)
            try:
                self._files.save_initial(presets, retained_values or {})
            finally:
                self._edit = None

    @contextmanager
    def saved_snapshot(self, *, presets: AnalysisPresets | None = None) -> Generator[AnalysisPresets, None, None]:
        """ 保存済みの値を編集権の確認後に渡す。外部更新との一括確定は行わない。
        """
        if presets is not None:
            # 渡されたPresetsは編集権の確認にだけ使う。未保存値は外部へ送らない。
            self._require_edit(presets)
            saved = self._files.load().presets
            self._require_edit(presets)
            yield saved
            return

        with self._storage.edit(self._directory) as session:
            saved = self._files.load().presets
            session.check()
            yield saved

    def load(self) -> AnalysisPresets:
        """ 閲覧・帳票用に現在の保存内容を読む。編集状態は持ち帰らない。
        """
        with self.saved_snapshot() as presets:
            return presets


# 既存呼出元の移行用。新規コードではAnalysisWorkspaceを使う。
AnalysisService = AnalysisWorkspace
