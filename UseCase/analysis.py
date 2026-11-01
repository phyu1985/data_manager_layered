""" 編集の寿命と入出力の手順を管理し、処理側にはPresetsを直接渡す。

ファイルの項目対応はAnalysisFilesへ委譲する。加工・解析の計算は
Presetsを受け取る関数として分け、ロックや保存形式に依存させない。
"""
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import get_ident
from typing import Any

from DataManager import lock_directory
from DataManager.analysis_files import AnalysisDocument, AnalysisFiles
from Domain.models import AnalysisPresets, ProcessingPresets


@dataclass(frozen=True)
class _EditState:
    """ 現在の編集データと所有スレッドだけを、サービス内部で記録する。
    """

    document: AnalysisDocument
    thread_id: int


class AnalysisService:
    """ 編集権を管理し、対象別の保存をAnalysisFilesへ委譲する。

    edit()は管理用オブジェクトを公開せず、AnalysisPresetsを返す。
    保存時は同じPresetsかを確認し、終了済み・別画面の値の誤保存を防ぐ。
    """

    def __init__(self, directory: Path):
        """ 解析フォルダと保存担当を固定する。ここでは編集を開始しない。
        """
        self._directory = directory.resolve()
        self._files = AnalysisFiles(self._directory)
        self._edit: _EditState | None = None

    @property
    def directory(self) -> Path:
        return self._directory

    def exists(self) -> bool:
        """ ファイル名の知識を利用側へ持ち出さず、選択候補か確認する。
        """
        return self._files.exists()

    def load_processing(
        self, path: Path, raw_values: Sequence[float],
    ) -> tuple[ProcessingPresets, dict[str, Any]]:
        """ 加工に必要な値と、保存時に引き継ぐ維持項目を読み込む。
        """
        document = self._files.load_settings(path)
        settings = document.settings
        presets = ProcessingPresets(
            threshold=settings.threshold, gain=settings.gain, raw_values=list(raw_values),
        )
        return presets, dict(document.retained_values)

    @contextmanager
    def edit(self) -> Generator[AnalysisPresets, None, None]:
        """ 読取前に編集権を取り、終了まで同じ権利を保持する。
        """
        with lock_directory(self._directory):
            document = self._files.load()
            self._edit = _EditState(document, get_ident())

            try:
                # 呼出元はpresets.thresholdと書ける。維持項目と編集権は内部に留める。
                yield document.presets
            finally:
                # 例外終了でも編集状態を捨て、その後にwithがOSロックを解放する。
                self._edit = None

    def _require_edit(self, presets: AnalysisPresets) -> AnalysisDocument:
        """ 現在の編集で取得したPresetsだけを保存対象として認める。
        """
        state = self._edit
        if state is None or state.thread_id != get_ident() or state.document.presets is not presets:
            raise RuntimeError("同じスレッドの有効な編集セッションと、そのPresetsが必要です")
        return state.document

    def save_settings(
        self, presets: AnalysisPresets, *, path: str | Path = "settings.yaml",
        target_version: int | None = None, overwrite: bool = False,
    ):
        """ 編集中の設定だけを保存する。旧版出力では版と別名を指定する。
        """
        document = self._require_edit(presets)
        self._files.save_settings(
            presets, document.retained_values, path=path,
            target_version=target_version, overwrite=overwrite,
        )

    def save_measurements(self, presets: AnalysisPresets, *, overwrite: bool = False):
        """ 編集中の測定行だけを保存する。
        """
        self._require_edit(presets)
        self._files.save_measurements(presets, overwrite=overwrite)

    def save_initial(self, presets: AnalysisPresets, *, retained_values: dict[str, Any] | None = None):
        """ 新規保存の排他範囲を決め、保存と後始末をファイル担当へ依頼する。
        """
        with lock_directory(self._directory):
            self._files.save_initial(presets, {} if retained_values is None else retained_values)

    @contextmanager
    def saved_snapshot(self, *, presets: AnalysisPresets | None = None) -> Generator[AnalysisPresets, None, None]:
        """ 外部反映の間も排他を保ち、保存済みの値を渡す。
        """
        if presets is not None:
            # 渡されたPresetsは編集権の確認にだけ使う。未保存値は外部へ送らない。
            self._require_edit(presets)
            yield self._files.load().presets
            return

        with lock_directory(self._directory):
            yield self._files.load().presets

    def load(self) -> AnalysisPresets:
        """ 閲覧・帳票用に現在の保存内容を読む。編集状態は持ち帰らない。
        """
        with self.saved_snapshot() as presets:
            return presets

