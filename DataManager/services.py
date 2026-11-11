""" ファイル名と入出力方針を固定し、ユースケースへ小さな操作を提供する。
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Generic, Protocol, TypeVar, overload

from DataManager.documents import MetadataValue, RowsDocument
from DataManager.model_conversion import ModelValue
from DataManager.repositories import ObjectRepository, RowsRepository
from DataManager.waveform import WaveformArray, WaveformObject, WaveformRepository

Value = TypeVar("Value")
ReadValue = TypeVar("ReadValue", covariant=True)
WriteValue = TypeVar("WriteValue", contravariant=True)

__all__ = ["FileReader", "FileWriter", "FileService",
           "ObjectFileService", "RowsFileService", "WaveformFileService"]


class _ReadableFile(Protocol[ReadValue]):
    """ 読取の最小契約。モデルの構造や版変換の有無を要求しない。
    """

    def load(self, path: str | Path, /) -> ReadValue:
        ...


class _WritableFile(Protocol[WriteValue]):
    """ 出力の最小契約。形式専用の設定は構成済みRepositoryが保持する。
    """

    def save(self, path: str | Path, value: WriteValue, /, *, overwrite: bool = False):
        ...


class _FileRepository(_ReadableFile[Value], _WritableFile[Value], Protocol[Value]):
    """ 同じ型の値を読み書きできる契約。実装の継承を要求しない。
    """


class FileReader(Generic[ReadValue]):
    """ 一つの入力先を固定する読取窓口。未対応の保存メソッドを持たない。
    """

    def __init__(self, *, repository: _ReadableFile[ReadValue], path: str | Path):
        self._repository = repository
        self._path = Path(path)

    def load(self) -> ReadValue:
        """ 構成済みの読取先から、宣言した型の値を返す。
        """
        return self._repository.load(self._path)


class FileWriter(Generic[WriteValue]):
    """ 一つの出力先を固定する書込窓口。帳票など読取を提供しない用途にも使う。
    """

    def __init__(self, *, repository: _WritableFile[WriteValue], path: str | Path):
        self._repository = repository
        self._path = Path(path)

    def save(self, value: WriteValue, *, overwrite: bool = False):
        """ 通常の出力先へ保存する。既存ファイルの上書きは明示する。
        """
        self.save_as(self._path, value, overwrite=overwrite)

    def save_as(self, path: str | Path, value: WriteValue, *, overwrite: bool = False):
        """ 別の出力先へ保存する。通常の出力先は変更しない。
        """
        self._repository.save(path, value, overwrite=overwrite)


class FileService(Generic[Value]):
    """ 保存先を固定し、Repositoryの種類によらずload / save / save_asを提供する。

    値の型と変換規則はRepositoryが決め、操作はFileReader / FileWriterへ委譲する。
    """

    def __init__(self, *, repository: _FileRepository[Value], path: str | Path):
        # 呼出側は保存先を毎回渡さずに済む。形式・版変換・排他は渡されたRepositoryが担う。
        self._reader = FileReader(repository=repository, path=path)
        self._writer = FileWriter(repository=repository, path=path)

    def load(self) -> Value:
        return self._reader.load()

    def save(self, value: Value, *, overwrite: bool = False):
        self._writer.save(value, overwrite=overwrite)

    def save_as(self, path: str | Path, value: Value, *, overwrite: bool = False):
        self._writer.save_as(path, value, overwrite=overwrite)


class ObjectFileService(Generic[ModelValue]):
    """ 固定テンプレート用の従来窓口。新規構成はFileServiceを使う。
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
        self.save_as(self._path, value, overwrite=overwrite)

    def save_as(self, path: str | Path, value: ModelValue, *, overwrite: bool = False):
        """ 固定テンプレートを使って別の出力先へ保存する。
        """
        self._repository.save(path, value, template_name=self._template_name, overwrite=overwrite)


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
        self.save_as(self._path, rows, overwrite=overwrite)

    def save_as(self, path: str | Path, rows: Sequence[ModelValue], *, overwrite: bool = False):
        """ 一覧を別の出力先へ全件保存する。
        """
        self._repository.save(path, rows, overwrite=overwrite)

    @overload
    def load_document(self, *, metadata_model: type[MetadataValue]) -> RowsDocument[MetadataValue, ModelValue]:
        ...

    @overload
    def load_document(self) -> RowsDocument[dict[str, Any], ModelValue]:
        ...

    def load_document(
        self, *, metadata_model: type[MetadataValue] | None = None,
    ) -> RowsDocument[MetadataValue, ModelValue] | RowsDocument[dict[str, Any], ModelValue]:
        """ CSV・JSONL共通の入口で、メタ情報と本文を一度に取得する。
        """
        if metadata_model is None:
            return self._repository.load_document(self._path)
        return self._repository.load_document(self._path, metadata_model=metadata_model)

    def save_document(
        self, document: RowsDocument[MetadataValue, ModelValue], *,
        overwrite: bool = False, metadata_by_alias: bool = False,
    ):
        """ ファイル名を意識せず、メタと本文を一体で保存する。
        """
        self._repository.save_document(self._path, document, overwrite=overwrite, metadata_by_alias=metadata_by_alias)

    def append(self, rows: Iterable[ModelValue]):
        """ JSONLへ追記する。CSVなどの未対応形式ではRepositoryのエラーを返す。
        """
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
