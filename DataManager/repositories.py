""" ファイル入出力の入口として、形式変換と排他・保存の順序を統括する。

Repositoryがパスとロックを扱い、Serializerが形式を解釈し、
ModelBindingが辞書とモデルを相互変換する。業務フィールドの意味は扱わない。
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from contextlib import nullcontext
import os
from pathlib import Path
from typing import Any, Generic, Protocol, overload, runtime_checkable

from pydantic import ValidationError

from DataManager.documents import MetadataValue, RowsDocument
from DataManager.errors import ConfigurationError, SerializationError
from DataManager.file_io import CommitGuard, lock_file, read_last_nonblank_line, resolve_file_path, validate_lock_timeout, write_file_atomically
from DataManager.model_conversion import ModelBinding, ModelValue
from DataManager.serializers.csv import CsvSerializer
from DataManager.serializers.kv import KvSerializer
from DataManager.serializers.json import JsonSerializer
from DataManager.serializers.jsonl import JsonlSerializer
from DataManager.serializers.yaml import YamlSerializer


class ObjectSerializer(Protocol):
    """ 単一値と文字列の変換契約。専用設定はSerializer自身が保持する。
    """

    @property
    def encoding(self) -> str:
        ...

    @property
    def supports_document_merge(self) -> bool:
        ...

    def dumps(
        self, value: ModelValue, model_binding: ModelBinding[ModelValue], *,
        existing_text: str | None = None, template_text: str | None = None,
    ) -> str:
        ...

    def loads(self, serialized_text: str, model_binding: ModelBinding[ModelValue]) -> ModelValue:
        ...


@runtime_checkable
class ExactObjectSerializer(Protocol):
    """ 保存項目を増やさず、既存文書・テンプレートの書式を再利用する追加契約。
    """

    def dumps_exact(
        self, value: ModelValue, model_binding: ModelBinding[ModelValue], *,
        existing_text: str | None = None, template_text: str | None = None,
    ) -> str:
        ...


class RowsSerializer(Protocol):
    """ 一覧の全件保存・読み込みを形式に依存せず呼び出すための契約。

    メタ情報や行ごとの型判別はSerializerが扱い、Repositoryはその仕様を組み立てない。
    JSONLへの追記は、この共通契約とは別にJsonlSerializerの操作を使う。
    """

    @property
    def encoding(self) -> str:
        ...

    def validate_model_configuration(self, model_binding: ModelBinding[ModelValue]):
        ...

    def dumps(self, rows: Sequence[ModelValue], model_binding: ModelBinding[ModelValue]) -> str:
        ...

    def loads(self, serialized_text: str, model_binding: ModelBinding[ModelValue]) -> list[ModelValue]:
        ...


@runtime_checkable
class RowsDocumentSerializer(Protocol):
    """ メタ付き一覧を扱うSerializerの追加契約。ファイル操作はRepositoryが担当する。
    """

    def dumps_document(
        self, rows: Sequence[ModelValue], model_binding: ModelBinding[ModelValue], *,
        metadata: dict[str, Any],
    ) -> str:
        ...

    def loads_document(
        self, serialized_text: str, model_binding: ModelBinding[ModelValue],
    ) -> RowsDocument[dict[str, Any], ModelValue]:
        ...


def default_object_serializers() -> dict[str, ObjectSerializer]:
    """ 標準の対応表を新しく作る。用途別の構成もここから必要な形式だけ差し替える。
    """
    return {
        ".json": JsonSerializer(), ".yaml": YamlSerializer(),
        ".yml": YamlSerializer(), ".txt": KvSerializer(),
    }


class ObjectRepository(Generic[ModelValue]):
    """ パスと拡張子でSerializerを選び、指定型の単一値を読み書きする。

    排他とアトミック保存を担当し、形式の解釈・モデル検証はSerializerへ委譲する。
    """

    def __init__(
        self, *, model: type[ModelValue], base_directory: Path,
        serializers_by_extension: Mapping[str, ObjectSerializer] | None = None,
        template_directory: Path | None = None, template_name: str | Path | None = None,
        lock_timeout_seconds: float = 10, commit_guard: CommitGuard | None = None,
    ):
        """ 使用可能なモデル、保存先の基準、形式別Serializerを固定する。
        """
        validate_lock_timeout(lock_timeout_seconds)

        self._model_binding = ModelBinding(model)
        if self._model_binding.data_mode == "mixed":
            raise ConfigurationError("ObjectRepositoryは単一モデルまたはdictを指定してください")

        # 保存場所・排他・テンプレートを固定し、操作中に設定が変わらないようにする。
        self._base_directory = base_directory.resolve()
        self._lock_timeout_seconds = lock_timeout_seconds
        self._commit_guard = commit_guard
        self._template_directory = template_directory.resolve() if template_directory is not None else None
        self._template_name = template_name
        if template_name is not None and template_directory is None:
            raise ConfigurationError("template_nameにはtemplate_directoryが必要です")

        # 呼び出し元の対応表が変更されても、登録済みの形式が変わらないようコピーする。
        self._serializers_by_extension: dict[str, ObjectSerializer] = (
            dict(serializers_by_extension)
            if serializers_by_extension is not None
            else default_object_serializers()
        )

    def _resolve_path_and_serializer(self, path: str | Path) -> tuple[Path, ObjectSerializer]:
        """ 基準ディレクトリと拡張子から、保存先と変換担当を決める。
        """
        target_path = resolve_file_path(self._base_directory, path)
        serializer = self._serializers_by_extension.get(target_path.suffix.lower())

        if serializer is None:
            raise ConfigurationError(f"未対応の拡張子です: {target_path.suffix}")

        return target_path, serializer

    def load(self, path: str | Path) -> ModelValue:
        """ ファイル内容を一度読み取り、生成時に指定した型の値へ復元する。
        """
        target_path, serializer = self._resolve_path_and_serializer(path)

        with lock_file(target_path, timeout_seconds=self._lock_timeout_seconds):
            serialized_text = target_path.read_bytes().decode(serializer.encoding)

        # 読み取った内容は固定されているため、時間のかかる解析・検証はロック解放後に行う。
        return serializer.loads(serialized_text, self._model_binding)

    def _read_template_text(self, template_name: str | Path, target_path: Path, encoding: str) -> str:
        """ 固定ディレクトリ内のテンプレートを、一貫したスナップショットとして読む。
        """
        if self._template_directory is None:
            raise ConfigurationError("template_directoryを指定してください")
        if Path(template_name).is_absolute():
            raise ConfigurationError("template_nameはテンプレート内の相対パスで指定してください")

        template_path = (self._template_directory / template_name).resolve()
        if not template_path.is_relative_to(self._template_directory):
            raise ConfigurationError("テンプレートディレクトリ外は指定できません")
        if template_path == target_path:
            raise ConfigurationError("テンプレートと保存先には別のパスを指定してください")

        # テンプレートのロックを先に解放し、保存先との相互ロックを作らない。
        with lock_file(template_path, timeout_seconds=self._lock_timeout_seconds):
            return template_path.read_bytes().decode(encoding)

    def save(
        self, path: str | Path, value: ModelValue, *, template_name: str | Path | None = None,
        overwrite: bool = False, merge_existing: bool = True, preserve_existing_comments: bool = False,
    ):
        """ 単一値を保存する。既存ファイルの更新にはoverwrite=Trueが必要。

        merge_existing=Falseは保存項目をvalueに限定する。
        preserve_existing_comments=Trueなら、存続キーの既存コメントも引き継ぐ。
        """
        # 先に雛形を読み終え、保存先とは別のスナップショットとして扱う。
        target_path, serializer = self._resolve_path_and_serializer(path)
        template_text = None

        selected_template = template_name if template_name is not None else self._template_name
        if selected_template is not None:
            if serializer.supports_document_merge:
                template_text = self._read_template_text(selected_template, target_path, serializer.encoding)
            elif template_name is not None:
                raise ConfigurationError("この形式はテンプレート合成に対応しません")
            # 構成時の既定テンプレートは、合成対応形式だけに適用する。

        if (
            not merge_existing
            and serializer.supports_document_merge
            and not isinstance(serializer, ExactObjectSerializer)
        ):
            raise ConfigurationError("このSerializerは保存項目を限定した文書出力に対応しません")

        # YAMLの既存読取→マージ→保存を分割せず、他の保存結果を取りこぼさないようにする。
        with lock_file(target_path, timeout_seconds=self._lock_timeout_seconds):
            # 決定版を守るため、存在確認も書き込みと同じロック内で行う。
            if target_path.exists() and not overwrite:
                raise FileExistsError(f"上書きは明示的な許可が必要です: {target_path}")

            # 保存先の既存内容は、上書き可否の確認から置換まで同じ排他内で扱う。
            existing_text = None
            if (
                (merge_existing or preserve_existing_comments)
                and serializer.supports_document_merge
                and target_path.exists()
            ):
                existing_text = target_path.read_bytes().decode(serializer.encoding)

            # 通常保存は値を合成し、版変換後は指定された項目だけで文書を作る。
            if not merge_existing and isinstance(serializer, ExactObjectSerializer):
                serialized_text = serializer.dumps_exact(
                    value, self._model_binding, existing_text=existing_text, template_text=template_text,
                )
            else:
                serialized_text = serializer.dumps(
                    value, self._model_binding, existing_text=existing_text, template_text=template_text,
                )

            # 文書全体を作れた場合だけ切り替え、変換途中の内容を保存先へ見せない。
            serialized_content = serialized_text.encode(serializer.encoding)
            write_file_atomically(target_path, serialized_content, commit_guard=self._commit_guard)


class RowsRepository(Generic[ModelValue]):
    """ 指定型の一覧を読み書きし、行の解釈はSerializerへ委譲する。

    全件保存はアトミック置換、JSONL追記は排他中の直接書込み。
    追記の途中停止では末尾が不完全になる場合がある。
    """

    def __init__(
        self, *, model: type[ModelValue] | tuple[type[ModelValue], ...], base_directory: Path,
        serializers_by_extension: Mapping[str, RowsSerializer] | None = None,
        lock_timeout_seconds: float = 10, commit_guard: CommitGuard | None = None,
    ):
        """ 使用可能なモデル、保存先の基準、形式別Serializerを固定する。
        """
        validate_lock_timeout(lock_timeout_seconds)

        self._model_binding = ModelBinding(model)
        self._base_directory = base_directory.resolve()
        self._lock_timeout_seconds = lock_timeout_seconds
        self._commit_guard = commit_guard

        # 呼び出し元の対応表が変更されても、登録済みの形式が変わらないようコピーする。
        self._serializers_by_extension: dict[str, RowsSerializer] = (
            dict(serializers_by_extension)
            if serializers_by_extension is not None
            else {
                ".jsonl": JsonlSerializer(),
                **({".csv": CsvSerializer()} if self._model_binding.data_mode != "mixed" else {}),
            }
        )

        # tagの重複や業務フィールドとの衝突は、最初の保存を待たずに検出する。
        for serializer in self._serializers_by_extension.values():
            serializer.validate_model_configuration(self._model_binding)

    def _resolve_path_and_serializer(self, path: str | Path) -> tuple[Path, RowsSerializer]:
        """ 基準ディレクトリと拡張子から、保存先と変換担当を決める。
        """
        target_path = resolve_file_path(self._base_directory, path)
        serializer = self._serializers_by_extension.get(target_path.suffix.lower())

        if serializer is None:
            raise ConfigurationError(f"未対応の拡張子です: {target_path.suffix}")

        return target_path, serializer

    def load(self, path: str | Path) -> list[ModelValue]:
        """ 一覧ファイルを読み、指定モデルまたはdictのリストへ復元する。
        """
        target_path, serializer = self._resolve_path_and_serializer(path)

        with lock_file(target_path, timeout_seconds=self._lock_timeout_seconds):
            serialized_text = target_path.read_bytes().decode(serializer.encoding)

        # 読み取った内容は固定されているため、時間のかかる解析・検証はロック解放後に行う。
        return serializer.loads(serialized_text, self._model_binding)

    def save(self, path: str | Path, rows: Sequence[ModelValue], *, overwrite: bool = False):
        """ メタ情報を含む一覧全体を保存する。既存更新はoverwrite=Trueで許可する。
        """
        target_path, serializer = self._resolve_path_and_serializer(path)

        # 現在の形式は既存内容を参照しない。変換エラーでは保存先へ触れないよう先に済ませる。
        serialized_content = serializer.dumps(rows, self._model_binding).encode(serializer.encoding)

        with lock_file(target_path, timeout_seconds=self._lock_timeout_seconds):
            if target_path.exists() and not overwrite:
                raise FileExistsError(f"上書きは明示的な許可が必要です: {target_path}")

            write_file_atomically(target_path, serialized_content, commit_guard=self._commit_guard)

    @overload
    def load_document(
        self, path: str | Path, *, metadata_model: type[MetadataValue],
    ) -> RowsDocument[MetadataValue, ModelValue]:
        ...

    @overload
    def load_document(self, path: str | Path) -> RowsDocument[dict[str, Any], ModelValue]:
        ...

    def load_document(
        self, path: str | Path, *, metadata_model: type[MetadataValue] | None = None,
    ) -> RowsDocument[MetadataValue, ModelValue] | RowsDocument[dict[str, Any], ModelValue]:
        """ メタと本文を同じ読込結果から返す。指定時だけメタもモデルとして検証する。
        """
        target_path, serializer = self._resolve_path_and_serializer(path)
        if not isinstance(serializer, RowsDocumentSerializer):
            raise ConfigurationError("このSerializerはメタ付き文書の入出力に対応していません")

        with lock_file(target_path, timeout_seconds=self._lock_timeout_seconds):
            serialized_text = target_path.read_bytes().decode(serializer.encoding)

        # メタと本文を別々に読み直すと、途中の更新により異なる版の値が混ざってしまう。
        document = serializer.loads_document(serialized_text, self._model_binding)
        if metadata_model is None:
            return document

        # 本文の復元は完了している。指定がある場合だけmetaもモデルで検証する。
        try:
            metadata = ModelBinding(metadata_model).restore_value(document.metadata)
        except ValidationError as error:
            raise SerializationError(f"メタ情報のモデル検証に失敗しました: {error}") from error

        return RowsDocument(metadata=metadata, rows=document.rows)

    def save_document(
        self, path: str | Path, document: RowsDocument[MetadataValue, ModelValue], *,
        overwrite: bool = False, metadata_by_alias: bool = False,
    ):
        """ メタと本文を一体で保存する。変換失敗時には既存ファイルへ触れない。
        """
        target_path, serializer = self._resolve_path_and_serializer(path)
        if not isinstance(serializer, RowsDocumentSerializer):
            raise ConfigurationError("このSerializerはメタ付き文書の入出力に対応していません")

        # 本文と同じ変換担当へ委譲し、Repositoryにdictとモデルの分岐を増やさない。
        metadata = ModelBinding(type(document.metadata)).to_dict(document.metadata, by_alias=metadata_by_alias)
        serialized_content = serializer.dumps_document(
            document.rows, self._model_binding, metadata=metadata,
        ).encode(serializer.encoding)

        with lock_file(target_path, timeout_seconds=self._lock_timeout_seconds):
            if target_path.exists() and not overwrite:
                raise FileExistsError(f"上書きは明示的な許可が必要です: {target_path}")
            write_file_atomically(target_path, serialized_content, commit_guard=self._commit_guard)

    def append_jsonl(self, path: str | Path, rows: Iterable[ModelValue]):
        """ 既存のJSONLへ、指定型の行を末尾追加する。

        型・値のエラーでは追記しないが、直接書き込み中のI/O障害では一部が残り得る。
        """
        target_path, serializer = self._resolve_path_and_serializer(path)

        if target_path.suffix.lower() != ".jsonl" or not isinstance(serializer, JsonlSerializer):
            raise ConfigurationError("append_jsonlはJsonlSerializerを登録した.jsonl専用です")

        rows_to_append = list(rows)

        if not rows_to_append:
            return

        # バッチ全体を変換し、型・値のエラーで途中まで追記しないようにする。
        serialized_data_lines = serializer.serialize_data_lines(rows_to_append, self._model_binding).encode(serializer.encoding)
        serialized_metadata_line = serializer.serialize_metadata_line(self._model_binding).encode(serializer.encoding)

        # 存在判定から書き込みまで同じロックを保持し、同時作成による上書きを防ぐ。
        with lock_file(target_path, timeout_seconds=self._lock_timeout_seconds):
            # 新規ファイルはメタと本文を一体で保存し、メタだけの作成途中を見せない。
            if not target_path.exists():
                write_file_atomically(
                    target_path, serialized_metadata_line + serialized_data_lines, commit_guard=self._commit_guard,
                )
                return

            needs_separator_newline = self._validate_existing_jsonl_file(target_path, serializer)

            # 完全な最終行でも改行がない場合がある。次のJSONと連結しないよう補う。
            with self._commit_guard(target_path) if self._commit_guard is not None else nullcontext():
                self._append_bytes(target_path, serialized_data_lines, needs_separator_newline)

    @staticmethod
    def _append_bytes(target_path: Path, serialized_data_lines: bytes, needs_separator_newline: bool):
        """ 所有権を確保した区間内でのみ追記する。I/O中の強制割込はしない。
        """
        with target_path.open("ab") as stream:
            separator_newline = b"\n" if needs_separator_newline else b""
            stream.write(separator_newline + serialized_data_lines)
            stream.flush()
            os.fsync(stream.fileno())

    def _validate_existing_jsonl_file(self, target_path: Path, serializer: JsonlSerializer) -> bool:
        """ 既存JSONLへ追記できるか確認し、区切り改行の要否を返す。

        呼び出し元が保存先のロックを保持していることが前提。
        """
        with target_path.open("rb") as stream:
            # メタなし外部JSONLには追記しない。既存形式を黙って変更しない。
            metadata_line = stream.readline()

            while metadata_line and not metadata_line.strip():
                metadata_line = stream.readline()

            if not metadata_line:
                raise SerializationError("既存JSONLにメタ行がありません")

            metadata_end_offset = stream.tell()

            # 別のモデル構成で作られたファイルへ追記しないよう、先頭の設定を照合する。
            serializer.validate_metadata_line(metadata_line.decode(serializer.encoding), self._model_binding)

            # 全行の再読み込みを避け、最後の非空行だけを検証する。
            last_data_line, last_line_offset = read_last_nonblank_line(stream)

            # 開始位置がメタ行の範囲内なら本文はまだなく、モデルとして復元する必要がない。
            if last_line_offset >= metadata_end_offset:
                try:
                    serializer.deserialize_data_line(last_data_line.decode(serializer.encoding), self._model_binding)
                except (ValueError, UnicodeError) as error:
                    raise SerializationError(f"JSONLの末尾行が不正です: {error}") from error

            stream.seek(-1, os.SEEK_END)

            return stream.read(1) != b"\n"


class RowsDocumentRepository(Generic[MetadataValue, ModelValue]):
    """ メタの復元型を構成時に固定し、通常のload/save契約へ合わせるアダプター。

    メタ付きファイルを扱うFileServiceも、利用側でload_documentへ切り替える必要がない。
    実際の文法、ファイル排他、モデルの検証は元のRepositoryへ委譲する。
    """

    def __init__(
        self, *, repository: RowsRepository[ModelValue], metadata_model: type[MetadataValue],
        metadata_by_alias: bool = False,
    ):
        self._repository = repository
        self._metadata_binding = ModelBinding(metadata_model)
        self._metadata_by_alias = metadata_by_alias

    def load(self, path: str | Path) -> RowsDocument[MetadataValue, ModelValue]:
        return self._repository.load_document(path, metadata_model=self._metadata_binding.model_classes[0])

    def save(self, path: str | Path, value: RowsDocument[MetadataValue, ModelValue], *, overwrite: bool = False):
        # 構成した型以外のメタを、実行時にも受け付けない。モデルの辞書化も一度で済ませる。
        metadata = self._metadata_binding.to_dict(value.metadata, by_alias=self._metadata_by_alias)
        self._repository.save_document(path, RowsDocument(metadata=metadata, rows=value.rows), overwrite=overwrite)


