""" ファイル入出力の入口として、形式変換と排他・保存の順序を統括する。

Repositoryがパスとロックを扱い、Serializerが形式を解釈し、
ModelBindingが辞書とモデルを相互変換する。業務フィールドの意味は扱わない。
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import os
from pathlib import Path
from typing import Generic, Protocol

from DataManager.errors import ConfigurationError, SerializationError
from DataManager.file_io import lock_file, read_last_nonblank_line, resolve_file_path, validate_lock_timeout, write_file_atomically
from DataManager.model_conversion import ModelBinding, ModelValue
from DataManager.serializers.csv import CsvSerializer
from DataManager.serializers.custom_text import CustomTextSerializer
from DataManager.serializers.json import JsonSerializer
from DataManager.serializers.jsonl import JsonlSerializer
from DataManager.serializers.yaml import YamlSerializer


class ObjectSerializer(Protocol):
    """ 単一値のRepositoryがSerializerへ要求する最小限の契約。

    Repositoryが文字コードを使ってファイルを読み書きし、
    dumps / loadsへ文字列変換とモデル復元を委譲する。
    専用設定は各実装が保持し、Repositoryは設定の内容を解釈しない。
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

    def dumps(
        self,
        rows: Sequence[ModelValue],
        model_binding: ModelBinding[ModelValue],
    ) -> str:
        ...

    def loads(
        self,
        serialized_text: str,
        model_binding: ModelBinding[ModelValue],
    ) -> list[ModelValue]:
        ...


class ObjectRepository(Generic[ModelValue]):
    """ 生成時に指定した型で、単一モデルまたはdictを保存・復元する入口。

    パスと拡張子からSerializerを選び、読み込みでは文字列からモデルを復元し、
    保存では文字列への変換を終えてからファイルを置換する。
    排他とファイル操作を担当し、形式の解析とモデルの検証は委譲する。
    組み込み形式はJSON・YAML・独自テキストv1。
    """

    def __init__(
        self,
        *,
        model: type[ModelValue],
        base_directory: Path,
        serializers_by_extension: Mapping[str, ObjectSerializer] | None = None,
        template_directory: Path | None = None,
        lock_timeout_seconds: float = 10,
    ):
        """ 使用可能なモデル、保存先の基準、形式別Serializerを固定する。
        """
        validate_lock_timeout(lock_timeout_seconds)

        self._model_binding = ModelBinding(model)
        if self._model_binding.data_mode == "mixed":
            raise ConfigurationError("ObjectRepositoryは単一モデルまたはdictを指定してください")
        self._base_directory = base_directory.resolve()
        self._lock_timeout_seconds = lock_timeout_seconds
        self._template_directory = template_directory.resolve() if template_directory is not None else None

        # 呼び出し元の対応表が変更されても、登録済みの形式が変わらないようコピーする。
        self._serializers_by_extension: dict[str, ObjectSerializer] = (
            dict(serializers_by_extension)
            if serializers_by_extension is not None
            else {
                ".json": JsonSerializer(),
                ".yaml": YamlSerializer(),
                ".yml": YamlSerializer(),
                ".txt": CustomTextSerializer(),
            }
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

    def _read_template_text(
        self, template_name: str | Path, target_path: Path, encoding: str,
    ) -> str:
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
        overwrite: bool = False, merge_existing: bool = True,
    ):
        """ 単一値を保存する。既存ファイルの更新にはoverwrite=Trueが必要。

        merge_existing=Falseは既存YAMLの合成を止める。廃止キーを戻したくない
        版変換後の保存に使うが、既存文書のコメント保持も行わなくなる。
        """
        target_path, serializer = self._resolve_path_and_serializer(path)
        template_text = None

        if template_name is not None:
            if not serializer.supports_document_merge:
                raise ConfigurationError("この形式はテンプレート合成に対応しません")
            template_text = self._read_template_text(template_name, target_path, serializer.encoding)

        # YAMLの既存読取→マージ→保存を分割せず、他の保存結果を取りこぼさないようにする。
        with lock_file(target_path, timeout_seconds=self._lock_timeout_seconds):
            # 決定版を守るため、存在確認も書き込みと同じロック内で行う。
            if target_path.exists() and not overwrite:
                raise FileExistsError(f"上書きは明示的な許可が必要です: {target_path}")

            existing_text = None
            if merge_existing and serializer.supports_document_merge and target_path.exists():
                existing_text = target_path.read_bytes().decode(serializer.encoding)

            serialized_content = serializer.dumps(
                value, self._model_binding,
                existing_text=existing_text, template_text=template_text,
            ).encode(serializer.encoding)
            write_file_atomically(target_path, serialized_content)


class RowsRepository(Generic[ModelValue]):
    """ 型を固定した一覧を、全件保存・読み込み・JSONL追記する入口。

    load / saveはファイル全体を扱い、append_jsonlは既存内容を残して追加する。
    混在するモデルの判別はSerializerへ委譲し、Repositoryは行の項目を解釈しない。
    全件保存は一時ファイルの置換、既存への追記は排他中の直接書き込みを使うため、
    障害時の保証は同じではない。組み込み形式はCSV・JSONL。
    """

    def __init__(
        self,
        *,
        model: type[ModelValue] | tuple[type[ModelValue], ...],
        base_directory: Path,
        serializers_by_extension: Mapping[str, RowsSerializer] | None = None,
        lock_timeout_seconds: float = 10,
    ):
        """ 使用可能なモデル、保存先の基準、形式別Serializerを固定する。
        """
        validate_lock_timeout(lock_timeout_seconds)

        self._model_binding = ModelBinding(model)
        self._base_directory = base_directory.resolve()
        self._lock_timeout_seconds = lock_timeout_seconds

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
        serialized_content = serializer.dumps(rows, self._model_binding).encode(
            serializer.encoding
        )

        with lock_file(target_path, timeout_seconds=self._lock_timeout_seconds):
            if target_path.exists() and not overwrite:
                raise FileExistsError(f"上書きは明示的な許可が必要です: {target_path}")

            write_file_atomically(target_path, serialized_content)

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
        serialized_data_lines = serializer.serialize_data_lines(
            rows_to_append,
            self._model_binding,
        ).encode(serializer.encoding)
        serialized_metadata_line = serializer.serialize_metadata_line(
            self._model_binding
        ).encode(serializer.encoding)

        # 存在判定から書き込みまで同じロックを保持し、同時作成による上書きを防ぐ。
        with lock_file(target_path, timeout_seconds=self._lock_timeout_seconds):
            # 新規ファイルはメタと本文を一体で保存し、メタだけの作成途中を見せない。
            if not target_path.exists():
                write_file_atomically(
                    target_path,
                    serialized_metadata_line + serialized_data_lines,
                )
                return

            needs_separator_newline = self._validate_existing_jsonl_file(
                target_path,
                serializer,
            )

            # 完全な最終行でも改行がない場合がある。次のJSONと連結しないよう補う。
            with target_path.open("ab") as stream:
                separator_newline = b"\n" if needs_separator_newline else b""
                stream.write(separator_newline + serialized_data_lines)
                stream.flush()
                os.fsync(stream.fileno())

    def _validate_existing_jsonl_file(
        self,
        target_path: Path,
        serializer: JsonlSerializer,
    ) -> bool:
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
            serializer.validate_metadata_line(
                metadata_line.decode(serializer.encoding),
                self._model_binding,
            )

            # 全行の再読み込みを避け、最後の非空行だけを検証する。
            last_data_line, last_line_offset = read_last_nonblank_line(stream)

            # 開始位置がメタ行の範囲内なら本文はまだなく、モデルとして復元する必要がない。
            if last_line_offset >= metadata_end_offset:
                try:
                    serializer.deserialize_data_line(
                        last_data_line.decode(serializer.encoding),
                        self._model_binding,
                    )
                except (ValueError, UnicodeError) as error:
                    raise SerializationError(f"JSONLの末尾行が不正です: {error}") from error

            stream.seek(-1, os.SEEK_END)

            return stream.read(1) != b"\n"
