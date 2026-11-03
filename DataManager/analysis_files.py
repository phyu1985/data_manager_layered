""" 設定・測定ファイルと、処理用モデルの対応付けをまとめる。
"""
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from DataManager.repositories import RowsRepository
from DataManager.services import FileService, FileWriter
from DataManager.file_io import CommitGuard, resolve_file_path
from Domain.models import AnalysisPresets, Measurement, Settings
from DataManager.settings_versions import SettingsDocument, create_settings_repository


@dataclass
class AnalysisDocument:
    """ 編集値と旧形式の維持項目をまとめ、維持項目を計算処理から分離する。
    """

    presets: AnalysisPresets
    retained_values: dict[str, Any]


class AnalysisFiles:
    """ 設定・測定とPresetsを対応付け、単体の入出力はRepositoryへ委譲する。

    呼出元が編集権を取得し、保存時の権限検証をcommit_guardで渡す。
    """

    _SETTINGS_NAME = "settings.yaml"
    _MEASUREMENTS_NAME = "measurements.jsonl"

    def __init__(self, directory: Path, *, commit_guard: CommitGuard | None = None):
        """ 保存対象のパスと、形式ごとのRepositoryを固定する。
        """
        self._directory = directory.resolve()
        self._commit_guard = commit_guard
        self._settings_path = self._directory / self._SETTINGS_NAME
        self._measurements_path = self._directory / self._MEASUREMENTS_NAME
        self._settings_repository = create_settings_repository(self._directory, commit_guard=commit_guard)
        self._settings = FileService(repository=self._settings_repository, path=self._settings_path)
        self._measurements = FileService(
            repository=RowsRepository(model=Measurement, base_directory=self._directory, commit_guard=commit_guard),
            path=self._measurements_path,
        )

    def exists(self) -> bool:
        """ 解析対象の候補として、必要なファイルが揃っているかを確認する。

        値の妥当性や編集中かどうかは、選択後の読み込み時に確認する。
        """
        return self.exists_at(self._directory)

    @classmethod
    def exists_at(cls, directory: Path) -> bool:
        """ 候補列挙は編集権やRepositoryを構成せず、保存一式の有無だけを見る。
        """
        return (directory / cls._SETTINGS_NAME).is_file() and (directory / cls._MEASUREMENTS_NAME).is_file()

    def load(self) -> AnalysisDocument:
        """ 保存済みの一式を読み、現在の解析用Presetsへ組み直す。
        """
        document = self._settings.load()
        settings = document.settings
        measurements = self._measurements.load()

        # どの設定値を解析で使うかをここで列挙し、各解析メソッドへ分散させない。
        presets = AnalysisPresets(
            threshold=settings.threshold, gain=settings.gain, measurements=measurements,
        )
        return AnalysisDocument(presets, dict(document.retained_values))

    @staticmethod
    def _settings_document(presets: AnalysisPresets, retained_values: dict[str, Any]) -> SettingsDocument:
        """ 処理用Presetsから保存する設定だけを明示し、対応付けを一か所へ置く。
        """
        return SettingsDocument(
            settings=Settings(threshold=presets.threshold, gain=presets.gain),
            retained_values=dict(retained_values),
        )

    def save_settings(
        self, presets: AnalysisPresets, retained_values: dict[str, Any], *, overwrite: bool = False,
    ):
        """ 現在版の設定を通常の保存先へ保存する。
        """
        self._settings.save(self._settings_document(presets, retained_values), overwrite=overwrite)

    def export_settings(
        self, path: str | Path, presets: AnalysisPresets, retained_values: dict[str, Any], *,
        target_version: int | None = None, overwrite: bool = False,
    ):
        """ 別の保存先へ出力する。現在の設定ファイルを旧版で置換しない。
        """
        target = resolve_file_path(self._directory, path)
        if target == self._settings_path.resolve():
            raise ValueError("別出力には通常のsettings.yamlと異なる保存先を指定してください")
        writer = FileWriter(repository=self._settings_repository.for_version(target_version), path=target)
        writer.save(self._settings_document(presets, retained_values), overwrite=overwrite)

    def save_measurements(self, presets: AnalysisPresets, *, overwrite: bool = False):
        """ 測定行だけを書き換え、変更していない設定ファイルに触れない。
        """
        self._measurements.save(presets.measurements, overwrite=overwrite)

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
        # フォルダ全体や管理情報は削除しない。後始末も現在の編集権に従う。
        for path in reversed(paths):
            try:
                if path.resolve().parent != self._directory:
                    raise ValueError(f"保存先外の削除を拒否しました: {path}")
                # 引継ぎ後に旧処理の後始末が新しい保存物を削除することも防ぐ。
                with self._commit_guard(path) if self._commit_guard is not None else nullcontext():
                    path.unlink(missing_ok=True)
            except Exception as error:
                error.add_note(f"削除できなかった保存先: {path}")
                errors.append(error)

        return errors
