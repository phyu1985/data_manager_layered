""" ファイル名と入出力方針を固定し、ユースケースへ小さな操作を提供する。
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Generic

from .model_conversion import ModelValue
from .repositories import ObjectRepository, RowsRepository
from .waveform import WaveformArray, WaveformObject, WaveformRepository

__all__ = ["ObjectFileService", "RowsFileService", "WaveformFileService"]


class ObjectFileService(Generic[ModelValue]):
    """ 単一ファイルの入出力を、保存先とテンプレートを意識せず呼び出す窓口。

    利用側のservicesモジュールでRepositoryとファイル名を組み合わせて作る。
    型変換・文書合成・排他・例外処理はRepositoryへ委譲する。
    """

    def __init__(
        self, *, repository: ObjectRepository[ModelValue], path: str | Path,
        template_name: str | Path | None = None,
    ):
        self._repository = repository
        self._path = Path(path)
        self._template_name = template_name

    def load(self) -> ModelValue:
        """ 設定済みのファイルから、指定型の値を復元する。
        """
        return self._repository.load(self._path)

    def save(self, value: ModelValue, *, overwrite: bool = False):
        """ 設定済みの保存先へ保存する。既存更新はoverwrite=Trueで許可する。
        """
        self._repository.save(
            self._path, value, template_name=self._template_name, overwrite=overwrite,
        )


class RowsFileService(Generic[ModelValue]):
    """ 一覧ファイルの全件入出力とJSONL追記を、固定した保存先へ提供する窓口。
    """

    def __init__(self, *, repository: RowsRepository[ModelValue], path: str | Path):
        self._repository = repository
        self._path = Path(path)

    def load(self) -> list[ModelValue]:
        """ 設定済みのファイルから、指定型の一覧を復元する。
        """
        return self._repository.load(self._path)

    def save(self, rows: Sequence[ModelValue], *, overwrite: bool = False):
        """ 一覧を全件保存する。既存更新はoverwrite=Trueで許可する。
        """
        self._repository.save(self._path, rows, overwrite=overwrite)

    def append(self, rows: Iterable[ModelValue]):
        """ JSONLへ追記する。CSVなどの未対応形式ではRepositoryのエラーを返す。
        """
        # 形式の推測や全件書き直しで代用せず、追記の保証はRepositoryと同じにする。
        self._repository.append_jsonl(self._path, rows)


class WaveformFileService:
    """ ヘッダー解析・復号設定を持つRepositoryと、波形の保存先を組み合わせる窓口。
    """

    def __init__(self, *, repository: WaveformRepository, path: str | Path):
        self._repository = repository
        self._path = Path(path)

    def load(self) -> WaveformObject:
        """ 設定済みの波形ファイル全体を復元する。
        """
        return self._repository.load(self._path)

    def peek(self) -> WaveformArray:
        """ 設定済みの波形ファイルから先頭1サンプルを復元する。
        """
        return self._repository.peek(self._path)
