""" 辞書の隣接版変換を順に適用し、現在の処理と過去の保存仕様をつなぐ。
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any, Generic, TypeVar, cast, overload

from pydantic import BaseModel, ValidationError

from DataManager.errors import ConfigurationError, SerializationError
from DataManager.repositories import ObjectRepository
from DataManager.repositories import RowsRepository
from DataManager.documents import MetadataValue, RowsDocument
from DataManager.model_conversion import ModelBinding, ModelValue, SerializableValue
from DataManager.rows_models import RowModel, RowsModelCodec

DocumentValue = TypeVar("DocumentValue")
ObjectModel = TypeVar("ObjectModel", bound=BaseModel)
OtherMetadata = TypeVar("OtherMetadata", bound=SerializableValue)
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

    登録するcastは実際に通る経路だけでよい。現在版V3でV2/V3のみを扱うなら、
    upcasts={2: V2→V3の関数}、downcasts={3: V3→V2の関数}だけを指定する。
    未対応のV0/V1のために仮のcastを作る必要はない。

    版キーの欠損はV0として扱うが、値の形からV2/V3などを推測する機能はない。
    版を確定できない入力は呼出側で拒否し、辻褄合わせのcastで通さない。
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
        # ファイル拡張子から版を推測しない。版番号で、隣接する版の変換経路を決める。
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

    @classmethod
    def for_model(
        cls, *, repository: ObjectRepository[DictionaryValue], converter: VersionConverter,
        model: type[ObjectModel], target_version: int | None = None,
        templates_by_version: Mapping[int, Mapping[str, str | Path]] | None = None,
    ) -> VersionedObjectRepository[ObjectModel]:
        """ 現在モデル一つの入出力を構成する。維持項目を別に持つ文書は通常の構成を使う。
        """
        binding = ModelBinding(model)

        def decode(value: DictionaryValue) -> ObjectModel:
            """ 現在版の辞書から業務モデルを復元する。
            """
            # 版を業務フィールドに持たないモデルにも、保存用の版キーを渡さない。
            data = dict(value)
            if converter.version_field not in model.model_fields:
                data.pop(converter.version_field, None)
            return binding.restore_value(data)

        def encode(value: ObjectModel) -> DictionaryValue:
            """ モデルをフィールド名の辞書へ戻し、現在版を記録する。
            """
            return {**binding.to_dict(value, by_alias=False), converter.version_field: converter.current_version}

        return VersionedObjectRepository(
            repository=repository, converter=converter, decode_current=decode, encode_current=encode,
            target_version=target_version, templates_by_version=templates_by_version,
        )

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

        # ここから先は現在版の構造だけを扱う。過去のキーをモデル側へ持ち込まない。
        try:
            return self._decode_current(current_value)
        except ValidationError as error:
            raise SerializationError("現在版のモデル検証に失敗しました") from error

    def save(
        self, path: str | Path, value: DocumentValue, *,
        target_version: int | None = None, overwrite: bool = False,
    ):
        """ 通常は現在版で保存し、指定があれば旧版へ変換して別途出力する。
        """
        # 出力版を決める。呼出時の指定、構成時の指定、現在版の順で選ぶ。
        output_version = target_version if target_version is not None else self._target_version
        if output_version is None:
            output_version = self._converter.current_version

        # 現在モデルを保存辞書へ戻す。出発点の版を確認して二重変換を防ぐ。
        try:
            current_value = self._encode_current(value)
        except ValidationError as error:
            raise SerializationError("保存するモデルの検証に失敗しました") from error
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

        # 変換済みの値と選択したテンプレートを、実際のファイル保存へ渡す。
        self._repository.save(
            path, output_value, overwrite=overwrite, merge_existing=False,
            preserve_existing_comments=True, template_name=template_name,
        )


class VersionedRowsRepository(Generic[MetadataValue, ModelValue]):
    """ メタと本文を辞書のまま隣接版変換し、最後に現在のモデルを構築する。

    キャスト対象はversion・metadata・rowsを持つ文書。版ごとのモデルを要求しない。
    metaの改名・補完・廃止もキャストへ渡す。cast内の版は文書直下を参照する。
    metadata_version_fieldsは版ごとのメタ内の版キー。Noneは版を記載しない旧形式。
    for_modelsは現在モデルの対応表から、復元・辞書化とJSONLの型名を一括構成する。
    load/saveは行一覧、load_document/save_documentはメタ付き文書を扱う。
    metadata_modelはメタ省略時の既定値と辞書入力の正規化に使い、for_modelsが自動で指定する。
    """

    def __init__(
        self, *, repository: RowsRepository[DictionaryValue], converter: VersionConverter,
        decode_current: Callable[[DictionaryValue], RowsDocument[MetadataValue, ModelValue]],
        encode_current: Callable[[RowsDocument[MetadataValue, ModelValue]], DictionaryValue],
        target_version: int | None = None,
        read_version: Callable[[DictionaryValue], int] | None = None,
        metadata_version_fields: Mapping[int, str | None] | None = None,
        metadata_model: type[MetadataValue] | None = None,
    ):
        if converter.version_field in {"metadata", "rows"}:
            raise ConfigurationError("版項目はmetadata / rows以外にしてください")
        self._repository = repository
        self._converter = converter
        self._decode_current = decode_current
        self._encode_current = encode_current
        self._metadata_binding = ModelBinding(metadata_model) if metadata_model is not None else None
        self._target_version = _configured_target(target_version, converter.current_version)

        # 版キーだけはRepositoryが管理する。通常メタの改名・廃止はcastへ任せる。
        self._metadata_version_fields: dict[int, str | None] = {
            version: converter.version_field for version in range(converter.current_version + 1)
        }
        for version, field in (metadata_version_fields or {}).items():
            if type(version) is not int or not 0 <= version <= converter.current_version:
                raise ConfigurationError("メタの版キーの対応表は0以上現在版以下の版を指定してください")
            if field is None and version != 0 and read_version is None:
                raise ConfigurationError("V1以降で版キーを省く場合はread_versionを指定してください")
            if field is not None and not field.strip():
                raise ConfigurationError("メタの版キーは非空文字列かNoneを指定してください")
            self._metadata_version_fields[version] = field
        self._version_keys = {field for field in self._metadata_version_fields.values() if field is not None}
        self._version_keys.add(converter.version_field)
        self._read_version = read_version or self._read_metadata_version

    @classmethod
    def for_models(
        cls, *, repository: RowsRepository[DictionaryValue], converter: VersionConverter,
        metadata_model: type[OtherMetadata], model_tags: Mapping[type[RowModel], str],
        tag_field: str = "type", target_version: int | None = None,
        read_version: Callable[[DictionaryValue], int] | None = None,
        metadata_version_fields: Mapping[int, str | None] | None = None,
    ) -> VersionedRowsRepository[OtherMetadata, RowModel]:
        """ 現在モデルを一度登録し、型付き文書とJSONLのmodelsを同じ表から構成する。
        """
        codec = RowsModelCodec(
            metadata_model=metadata_model, model_tags=model_tags, tag_field=tag_field,
            version_field=converter.version_field, current_version=converter.current_version,
        )
        # コピーへ接続するため、呼出元のSerializerやRepositoryの設定は変わらない。
        configured = repository.with_jsonl_models(tuple(model_tags.values()))
        return VersionedRowsRepository(
            repository=configured, converter=converter,
            decode_current=codec.decode, encode_current=codec.encode,
            target_version=target_version, read_version=read_version,
            metadata_version_fields=metadata_version_fields, metadata_model=metadata_model,
        )

    def _read_metadata_version(self, metadata: DictionaryValue) -> int:
        """ 対応表にある版キーを読む。欠損だけをV0とし、矛盾したキーは拒否する。
        """
        present = self._version_keys & metadata.keys()
        if not present:
            return 0
        if len(present) != 1:
            raise SerializationError("メタに複数の版キーがあります")
        field = next(iter(present))
        raw = metadata[field]
        version = int(raw) if isinstance(raw, str) and raw.isdecimal() else raw
        version = self._converter.read_version({self._converter.version_field: version})
        if self._metadata_version_fields[version] != field:
            raise SerializationError(f"V{version}のメタの版キーが対応表と一致しません")
        return version

    def for_version(self, target_version: int | None) -> "VersionedRowsRepository[MetadataValue, ModelValue]":
        """ メタ付き一覧も、保存版を構成して共通のFileServiceへ渡せるようにする。
        """
        return VersionedRowsRepository(
            repository=self._repository, converter=self._converter,
            decode_current=self._decode_current, encode_current=self._encode_current,
            read_version=self._read_version, target_version=target_version,
            metadata_version_fields=self._metadata_version_fields,
            metadata_model=self._metadata_binding.model_classes[0] if self._metadata_binding is not None else None,
        )

    def _document(self, value: DictionaryValue) -> RowsDocument[DictionaryValue, DictionaryValue]:
        """ 文書構造を確認し、出力版に合う名前でメタの版を記録する。
        """
        # 変換結果からメタと行を取り出し、保存用の文書へ組み直す。
        metadata = dict(_require_dict(value.get("metadata")))
        raw_rows = value.get("rows")
        if not isinstance(raw_rows, list):
            raise SerializationError("rowsは辞書のリストが必要です")
        rows = [_require_dict(row) for row in cast(list[object], raw_rows)]

        # 内部の版と、旧ファイルに書く版キーは別物。管理対象の版キーだけを置き換える。
        version = self._converter.read_version(value)
        for field in self._version_keys:
            metadata.pop(field, None)
        output_field = self._metadata_version_fields[version]
        if output_field is not None:
            metadata[output_field] = version
        return RowsDocument(metadata=metadata, rows=rows)

    def load(self, path: str | Path) -> list[ModelValue]:
        """ 版変換を済ませた行一覧を返す。メタも必要ならload_documentを使う。
        """
        return self.load_document(path).rows

    @overload
    def load_document(
        self, path: str | Path, *, metadata_model: type[OtherMetadata],
    ) -> RowsDocument[OtherMetadata, ModelValue]:
        ...

    @overload
    def load_document(self, path: str | Path) -> RowsDocument[MetadataValue, ModelValue]:
        ...

    def load_document(
        self, path: str | Path, *, metadata_model: type[OtherMetadata] | None = None,
    ) -> RowsDocument[MetadataValue, ModelValue] | RowsDocument[OtherMetadata, ModelValue]:
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
        # ファイル上の型名はcodecが行モデルへ対応付ける。Repositoryは具体的な型を選ばない。
        try:
            document = self._decode_current({**current, "metadata": normalized.metadata, "rows": normalized.rows})
        except ValidationError as error:
            raise SerializationError("現在版の文書のモデル検証に失敗しました") from error
        if metadata_model is None:
            return document

        # アダプターが指定したメタ型へ揃える。版変換は既に完了している。
        metadata = ModelBinding(type(document.metadata)).to_dict(document.metadata, by_alias=False)
        return RowsDocument(metadata=ModelBinding(metadata_model).restore_value(metadata), rows=document.rows)

    def _restore_metadata(self, value: DictionaryValue) -> MetadataValue:
        """ 現在版のメタを復元し、省略時も同じモデルの既定値・必須項目を適用する。
        """
        if self._metadata_binding is None:
            raise ConfigurationError("metadataを指定してください。省略時の復元にはmetadata_modelの構成が必要です")

        # メタだけを検証する。行数とメタが関連する独自decodeを空行で呼び出さない。
        metadata = dict(value)
        for field in self._version_keys:
            metadata.pop(field, None)
        field = self._metadata_version_fields[self._converter.current_version]
        if field is not None:
            metadata[field] = self._converter.current_version
        return self._metadata_binding.restore_value(metadata)

    def save(
        self, path: str | Path, rows: Sequence[ModelValue], *, overwrite: bool = False,
        target_version: int | None = None, metadata: MetadataValue | None = None,
    ):
        """ 行一覧を全件保存する。必須メタや維持するメタがある場合は明示して渡す。
        """
        # メタを推測して既存ファイルから引き継がない。省略時は現在モデルの既定値を使う。
        if metadata is None:
            try:
                metadata = self._restore_metadata({})
            except SerializationError as error:
                raise SerializationError("メタ情報が必要です。metadataを指定するかsave_documentを使ってください") from error
        self.save_document(
            path, RowsDocument(metadata=metadata, rows=list(rows)), overwrite=overwrite, target_version=target_version,
        )

    def save_document(
        self, path: str | Path, document: RowsDocument[OtherMetadata, ModelValue], *,
        target_version: int | None = None, overwrite: bool = False, metadata_by_alias: bool = False,
    ):
        """ 現在の保存辞書へ戻し、指定時だけdowncastして文書全体を出力する。
        """
        # 版変換の内部キーはフィールド名に固定する。保存先の別名はcastで表現する。
        if metadata_by_alias:
            raise ConfigurationError("版付きメタの出力名変更はcastで指定してください。metadata_by_aliasはFalseです")

        # 出力版を決める。呼出時の指定、構成時の指定、現在版の順で選ぶ。
        output_version = target_version if target_version is not None else self._target_version
        if output_version is None:
            output_version = self._converter.current_version

        # metaも本文も現在版の辞書へ戻し、同じ経路で出力版まで変換する。
        # 登録済みのメタ型があれば辞書入力も正規化する。独自codecには元の文書を渡す。
        current_document = cast(RowsDocument[MetadataValue, ModelValue], document)
        if self._metadata_binding is not None:
            raw_metadata = ModelBinding(type(document.metadata)).to_dict(document.metadata, by_alias=False)
            metadata = self._restore_metadata(raw_metadata)
            current_document = RowsDocument(metadata=metadata, rows=document.rows)
        try:
            current = self._encode_current(current_document)
        except ValidationError as error:
            raise SerializationError("保存する文書のモデル検証に失敗しました") from error
        if self._converter.read_version(current) != self._converter.current_version:
            raise SerializationError("encode_currentは現在版の版番号を含めてください")
        converted = self._converter.convert(current, target_version=output_version)

        # 変換後のmetaと本文を一体で保存する。版番号の刻印はここで揃える。
        self._repository.save_document(path, self._document(converted), overwrite=overwrite)


# 旧名は移行用の別名。パスを受け取る部品はRepositoryとして扱う。
VersionedObjectService = VersionedObjectRepository
VersionedRowsService = VersionedRowsRepository
