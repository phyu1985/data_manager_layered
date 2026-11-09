""" 辞書の隣接版変換を順に適用し、現在の処理と過去の保存仕様をつなぐ。
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any, Generic, TypeVar, cast

from DataManager.errors import ConfigurationError, SerializationError
from DataManager.repositories import ObjectRepository
from DataManager.repositories import RowsRepository
from DataManager.documents import RowsDocument

DocumentValue = TypeVar("DocumentValue")
DictionaryValue = dict[str, Any]
VersionCast = Callable[[DictionaryValue], DictionaryValue]


def _require_dict(value: object) -> DictionaryValue:
    """ 外部から渡されたキャスト関数の戻り値を、実行時にも確認する。
    """
    if not isinstance(value, dict):
        raise SerializationError("キャスト関数はdictを返す必要があります")
    return cast(DictionaryValue, value)


def _configured_target(version: int | None, current_version: int) -> int | None:
    """ 保存先の既定版を確定する。個々の保存要求はConverter側で改めて照合する。
    """
    if version is not None and (type(version) is not int or not 0 <= version <= current_version):
        raise ConfigurationError("保存版は0以上現在版以下の整数です")
    return version


class VersionConverter:
    """ 版番号を読み、必要な隣接版キャストだけを順番に実行する。

    upcastsのキーnはn→n+1、downcastsのキーnはn→n-1を表す。
    項目の改名・補完・廃止は注入した関数が担当し、このクラスは解釈しない。
    """

    def __init__(
        self, *, current_version: int, upcasts: Mapping[int, VersionCast],
        downcasts: Mapping[int, VersionCast], version_field: str = "version",
    ):
        if type(current_version) is not int or current_version < 0:
            raise ConfigurationError("current_versionは0以上の整数が必要です")
        if not version_field:
            raise ConfigurationError("version_fieldは空にできません")

        self._current_version = current_version
        self._version_field = version_field
        self._upcasts = dict(upcasts)
        self._downcasts = dict(downcasts)

        for source_version, conversion in self._upcasts.items():
            if type(source_version) is not int or not 0 <= source_version < current_version:
                raise ConfigurationError("upcastsのキーは0以上current_version未満が必要です")
            if not callable(conversion):
                raise ConfigurationError("upcastsにはキャスト関数が必要です")

        for source_version, conversion in self._downcasts.items():
            if type(source_version) is not int or not 1 <= source_version <= current_version:
                raise ConfigurationError("downcastsのキーは1以上current_version以下が必要です")
            if not callable(conversion):
                raise ConfigurationError("downcastsにはキャスト関数が必要です")

    @property
    def current_version(self) -> int:
        return self._current_version

    @property
    def version_field(self) -> str:
        return self._version_field

    def _validate_version(self, version: object) -> int:
        """ 欠損以外の不正値や、未対応の未来版を拒否する。
        """
        # boolはintの派生型だが、TrueをV1として読むのは入力ミスを隠す。
        if type(version) is not int or not 0 <= version <= self._current_version:
            raise SerializationError(f"未対応または不正な版番号です: {version!r}")
        return version

    def read_version(self, value: DictionaryValue) -> int:
        """ 版項目の欠損だけをV0として扱う。
        """
        return self._validate_version(value.get(self._version_field, 0))

    def to_current(self, value: DictionaryValue) -> DictionaryValue:
        """ 版項目がない辞書をV0とし、現在の保存仕様へ引き上げる。
        """
        return self.convert(value, target_version=self._current_version)

    def convert(self, value: DictionaryValue, *, target_version: int) -> DictionaryValue:
        """ 必要な経路を確認してから、呼出元の辞書を変更せず変換する。
        """
        source_version = self.read_version(value)
        destination_version = self._validate_version(target_version)
        direction = 1 if source_version < destination_version else -1
        conversions = self._upcasts if direction == 1 else self._downcasts
        source_versions = range(source_version, destination_version, direction)

        # 後半の関数不足を先に検出し、途中までキャストしてから失敗しないようにする。
        for step_version in source_versions:
            if step_version not in conversions:
                raise ConfigurationError(f"V{step_version}→V{step_version + direction}のキャストがありません")

        # キャストが辞書を書き換えても、呼出元の値と途中失敗の影響を切り離す。
        converted_value = deepcopy(value)
        converted_value[self._version_field] = source_version

        for step_version in source_versions:
            try:
                converted_value = _require_dict(conversions[step_version](converted_value))
            except Exception as error:
                # 元の例外を残し、どの橋渡しで失敗したかを利用側へ伝える。
                raise SerializationError(f"V{step_version}→V{step_version + direction}の変換に失敗しました") from error

            # キャスト関数は値の変換に集中し、出力版の刻印は共通処理に任せる。
            converted_value[self._version_field] = step_version + direction

        return converted_value


class VersionedObjectRepository(Generic[DocumentValue]):
    """ 辞書Repositoryへ版変換を重ね、アプリ側の型付きデータを読み書きする。

    現在版とモデルの対応はdecode_current / encode_currentへ委譲する。
    維持項目は文書と一緒に受け渡す。templates_by_versionは版→拡張子→相対名。
    テンプレートの値で出力項目を増やさず、存続キーの書式だけを使う。
    """

    def __init__(
        self, *, repository: ObjectRepository[DictionaryValue], converter: VersionConverter,
        decode_current: Callable[[DictionaryValue], DocumentValue],
        encode_current: Callable[[DocumentValue], DictionaryValue],
        target_version: int | None = None,
        templates_by_version: Mapping[int, Mapping[str, str | Path]] | None = None,
    ):
        self._repository = repository
        self._converter = converter
        self._decode_current = decode_current
        self._encode_current = encode_current
        self._target_version = _configured_target(target_version, converter.current_version)

        # 出力版ごとの雛形を拡張子で引ける形に揃え、外部の対応表から独立させる。
        self._templates_by_version: dict[int, dict[str, str | Path]] = {}
        for version, templates in (templates_by_version or {}).items():
            if type(version) is not int or not 0 <= version <= converter.current_version:
                raise ConfigurationError("テンプレートの版は0以上現在版以下の整数です")
            normalized: dict[str, str | Path] = {}
            for extension, name in templates.items():
                if not extension.startswith(".") or extension.lower() in normalized:
                    raise ConfigurationError("テンプレートの拡張子は重複のないドット付きの名前です")
                if not str(name) or Path(name).is_absolute():
                    raise ConfigurationError("テンプレート名は固定ディレクトリ内の相対パスです")
                normalized[extension.lower()] = name
            self._templates_by_version[version] = normalized

    def for_version(self, target_version: int | None) -> "VersionedObjectRepository[DocumentValue]":
        """ 通常保存先の設定を変更せず、指定版への出力用Repositoryを構成する。
        """
        return VersionedObjectRepository(
            repository=self._repository, converter=self._converter,
            decode_current=self._decode_current, encode_current=self._encode_current,
            target_version=target_version, templates_by_version=self._templates_by_version,
        )

    def load(self, path: str | Path) -> DocumentValue:
        """ 生の項目をモデル検証で除外する前に、版変換を適用する。
        """
        # 旧キーを失わず読み取り、版変換を済ませてから現在モデルを作る。
        source_value = self._repository.load(path)
        current_value = self._converter.to_current(source_value)

        return self._decode_current(current_value)

    def save(
        self, path: str | Path, value: DocumentValue, *,
        target_version: int | None = None, overwrite: bool = False,
    ):
        """ 通常は現在版で保存し、指定があれば旧版へ変換して別途出力する。
        """
        output_version = target_version if target_version is not None else self._target_version
        if output_version is None:
            output_version = self._converter.current_version

        # 現在モデルを保存辞書へ戻す。出発点の版を確認して二重変換を防ぐ。
        current_value = self._encode_current(value)
        if self._converter.read_version(current_value) != self._converter.current_version:
            raise SerializationError("encode_currentは現在版の版番号を含めてください")

        # 項目の補完・改名・廃止を終え、この版で保存する値を確定する。
        output_value = self._converter.convert(current_value, target_version=output_version)

        # 出力版と拡張子で選ぶため、旧版や別形式へ現在版の雛形を流用しない。
        extension = Path(path).suffix.lower()
        configured_extensions = {suffix for templates in self._templates_by_version.values() for suffix in templates}
        template_name = self._templates_by_version.get(output_version, {}).get(extension)
        if extension in configured_extensions and template_name is None:
            raise ConfigurationError(f"V{output_version}の{extension}用テンプレートが未指定です")

        self._repository.save(
            path, output_value, overwrite=overwrite, merge_existing=False,
            preserve_existing_comments=True, template_name=template_name,
        )


class VersionedRowsRepository(Generic[DocumentValue]):
    """ メタと本文を辞書のまま隣接版変換し、最後に現在のモデルを構築する。

    キャスト対象はversion・metadata・rowsを持つ文書。版ごとのモデルを要求しない。
    metaの改名・補完・廃止もキャストへ渡す。cast内の版は文書直下を参照する。
    read_versionはCSV等のmeta内の版表現を解釈し、保存時の版は共通処理がmetaへ記録する。
    JSONLの型情報modelsは、生のdict用Serializerのdocument_modelsで文書の固定名を構成する。
    """

    def __init__(
        self, *, repository: RowsRepository[DictionaryValue], converter: VersionConverter,
        decode_current: Callable[[DictionaryValue], DocumentValue],
        encode_current: Callable[[DocumentValue], DictionaryValue],
        target_version: int | None = None,
        read_version: Callable[[DictionaryValue], int] | None = None,
    ):
        if converter.version_field in {"metadata", "rows"}:
            raise ConfigurationError("版項目はmetadata / rows以外にしてください")
        self._repository = repository
        self._converter = converter
        self._decode_current = decode_current
        self._encode_current = encode_current
        self._target_version = _configured_target(target_version, converter.current_version)
        self._read_version = read_version or converter.read_version

    def for_version(self, target_version: int | None) -> "VersionedRowsRepository[DocumentValue]":
        """ メタ付き一覧も、保存版を構成して共通のFileServiceへ渡せるようにする。
        """
        return VersionedRowsRepository(
            repository=self._repository, converter=self._converter,
            decode_current=self._decode_current, encode_current=self._encode_current,
            read_version=self._read_version, target_version=target_version,
        )

    def _document(self, value: DictionaryValue) -> RowsDocument[DictionaryValue, DictionaryValue]:
        """ 変換後の文書構造を検証し、保存版をメタへ明示して戻す。
        """
        metadata = dict(_require_dict(value.get("metadata")))
        raw_rows = value.get("rows")
        if not isinstance(raw_rows, list):
            raise SerializationError("rowsは辞書のリストが必要です")
        rows = [_require_dict(row) for row in cast(list[object], raw_rows)]

        # castが確定した文書直下の版を正本とし、古いmetaの版値を残さない。
        metadata[self._converter.version_field] = self._converter.read_version(value)
        return RowsDocument(metadata=metadata, rows=rows)

    def load(self, path: str | Path) -> DocumentValue:
        """ 旧キーがモデル検証で消える前に、メタと行をまとめてupcastする。
        """
        # metaと本文を同時に読み、両方を一つのキャスト対象へまとめる。
        document = self._repository.load_document(path)
        payload = {
            self._converter.version_field: self._read_version(document.metadata),
            "metadata": document.metadata, "rows": document.rows,
        }

        # 全キャストの完了後に版を揃え、meta・各行を現在モデルへ復元する。
        current = self._converter.to_current(payload)
        normalized = self._document(current)
        return self._decode_current({**current, "metadata": normalized.metadata, "rows": normalized.rows})

    def save(
        self, path: str | Path, value: DocumentValue, *, target_version: int | None = None,
        overwrite: bool = False,
    ):
        """ 現在の保存辞書へ戻し、指定時だけdowncastして文書全体を出力する。
        """
        output_version = target_version if target_version is not None else self._target_version
        if output_version is None:
            output_version = self._converter.current_version

        # metaも本文も現在版の辞書へ戻し、同じ経路で出力版まで変換する。
        current = self._encode_current(value)
        if self._converter.read_version(current) != self._converter.current_version:
            raise SerializationError("encode_currentは現在版の版番号を含めてください")
        converted = self._converter.convert(current, target_version=output_version)

        # 変換後のmetaと本文を一体で保存する。版番号の刻印はここで揃える。
        self._repository.save_document(path, self._document(converted), overwrite=overwrite)


# 旧名は移行用の別名。パスを受け取る部品はRepositoryとして扱う。
VersionedObjectService = VersionedObjectRepository
VersionedRowsService = VersionedRowsRepository
