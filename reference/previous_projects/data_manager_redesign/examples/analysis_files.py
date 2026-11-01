""" 設定・測定ファイルと、処理用モデルの対応付けをまとめる。
"""
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from data_manager import RowsRepository, lock_directory
from data_manager.file_io import resolve_file_path
from examples.analysis_models import AnalysisPresets, Measurement, Settings
from examples.settings_versions import SettingsDocument, create_settings_service


@dataclass
class AnalysisDocument:
    """ 保存境界でのみ、処理値と維持項目をひとまとめにする。

    画面や解析処理にはPresetsだけを渡す。維持項目の受け渡しはサービス側が担当する。
    """

    presets: AnalysisPresets
    retained_values: dict[str, Any]


class AnalysisFiles:
    """ 一式の読取・対象別の保存・初回失敗の後始末を担当する。

    編集期間は管理しない。呼出元がフォルダの編集ロックを取得してから使う。
    ファイル形式の解析とファイル単体の保存はRepositoryへ委譲する。
    """

    def __init__(self, directory: Path):
        """ 保存対象のパスと、形式ごとのRepositoryを固定する。
        """
        self._directory = directory.resolve()
        self._settings_path = self._directory / "settings.yaml"
        self._measurements_path = self._directory / "measurements.jsonl"
        self._settings = create_settings_service(self._directory)
        self._measurements = RowsRepository(model=Measurement, base_directory=self._directory)

    def exists(self) -> bool:
        """ 解析対象の候補として、必要なファイルが揃っているかを確認する。

        値の妥当性や編集中かどうかは、選択後の読み込み時に確認する。
        """
        return self._settings_path.is_file() and self._measurements_path.is_file()

    def load_settings(self, path: str | Path) -> SettingsDocument:
        """ 加工に使う設定を、旧版から現在の値へ変換して読む。
        """
        return self._settings.load(path)

    def load(self) -> AnalysisDocument:
        """ 保存済みの一式を読み、現在の解析用Presetsへ組み直す。
        """
        document = self._settings.load(self._settings_path)
        settings = document.settings
        measurements = self._measurements.load(self._measurements_path)

        # どの設定値を解析で使うかをここで列挙し、各解析メソッドへ分散させない。
        presets = AnalysisPresets(
            threshold=settings.threshold, gain=settings.gain, measurements=measurements,
        )
        return AnalysisDocument(presets, dict(document.retained_values))

    def save_settings(
        self, presets: AnalysisPresets, retained_values: dict[str, Any], *,
        path: str | Path = "settings.yaml", target_version: int | None = None,
        overwrite: bool = False,
    ):
        """ 処理値から保存対象だけを取り出し、指定版で設定を保存する。
        """
        document = SettingsDocument(
            settings=Settings(threshold=presets.threshold, gain=presets.gain),
            retained_values=dict(retained_values),
        )
        target = resolve_file_path(self._directory, path)

        with ExitStack() as locks:
            # 元フォルダの権利は呼出元が保持する。別フォルダへの出力では追加取得し、
            # 即時判定で使用中を拒否して、相互に待ち続ける状況を作らない。
            if target.parent != self._directory:
                locks.enter_context(lock_directory(target.parent))
            self._settings.save(target, document, target_version=target_version, overwrite=overwrite)

    def save_measurements(self, presets: AnalysisPresets, *, overwrite: bool = False):
        """ 測定行だけを書き換え、変更していない設定ファイルに触れない。
        """
        self._measurements.save(self._measurements_path, presets.measurements, overwrite=overwrite)

    def save_initial(self, presets: AnalysisPresets, retained_values: dict[str, Any]):
        """ 初回一式を保存し、失敗時は今回の新規データだけを削除する。
        """
        for target in (self._settings_path, self._measurements_path):
            if target.exists() or target.is_symlink():
                raise FileExistsError(f"初回保存先に既存データがあります: {target}")

        attempted: list[Path] = []
        try:
            # 保存直後に例外が出ても対象を追跡できるよう、実行前に記録する。
            attempted.append(self._settings_path)
            self.save_settings(presets, retained_values)
            attempted.append(self._measurements_path)
            self.save_measurements(presets)
        except BaseException as error:
            cleanup_errors = self._remove_new_files(attempted)
            if cleanup_errors:
                raise BaseExceptionGroup("初回保存と後始末に失敗しました", [error, *cleanup_errors]) from None
            raise

    def _remove_new_files(self, paths: list[Path]) -> list[Exception]:
        """ データファイルだけを片付け、削除失敗も呼出元へ報告する。
        """
        errors: list[Exception] = []

        # 初回保存前に不存在を確認した対象だけを逆順で消す。
        # フォルダ全体やsidecarは削除しない。待機中の別プロセスとの排他を保つ。
        for path in reversed(paths):
            try:
                if path.resolve().parent != self._directory:
                    raise ValueError(f"保存先外の削除を拒否しました: {path}")
                path.unlink(missing_ok=True)
            except Exception as error:
                error.add_note(f"削除できなかった保存先: {path}")
                errors.append(error)

        return errors
