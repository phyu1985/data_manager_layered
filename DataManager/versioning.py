""" 辞書の隣接版変換を順に適用し、現在の処理と過去の保存仕様をつなぐ。
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any, Generic, TypeVar, cast

from DataManager.errors import ConfigurationError, SerializationError
from DataManager.repositories import ObjectRepository

DocumentValue = TypeVar("DocumentValue")
DictionaryValue = dict[str, Any]
VersionCast = Callable[[DictionaryValue], DictionaryValue]


def _require_dict(value: object) -> DictionaryValue:
    """ 外部から渡されたキャスト関数の戻り値を、実行時にも確認する。
    """
    if not isinstance(value, dict):
        raise SerializationError("キャスト関数はdictを返す必要があります")
    return cast(DictionaryValue, value)


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

        converted_value = deepcopy(value)
        converted_value[self._version_field] = source_version

        for step_version in source_versions:
            try:
                converted_value = _require_dict(conversions[step_version](converted_value))
            except Exception as error:
                # 元の例外を残し、どの橋渡しで失敗したかを利用側へ伝える。
                raise SerializationError(
                    f"V{step_version}→V{step_version + direction}の変換に失敗しました"
                ) from error

            # キャスト関数は値の変換に集中し、出力版の刻印は共通処理に任せる。
            converted_value[self._version_field] = step_version + direction

        return converted_value


class VersionedObjectService(Generic[DocumentValue]):
    """ 辞書Repositoryと版変換をつなぎ、アプリ側の型付きデータを読み書きする。

    decode_current / encode_currentにPresetsの組み立てと保持項目の方針を渡す。
    最終モデルの検証はdecode_current、出力項目の選択はencode_currentと各castの責務。
    読み込んだ文書を内部に記憶せず、並行する別データの保持値を混ぜない。
    """

    def __init__(
        self, *, repository: ObjectRepository[DictionaryValue], converter: VersionConverter,
        decode_current: Callable[[DictionaryValue], DocumentValue],
        encode_current: Callable[[DocumentValue], DictionaryValue],
    ):
        self._repository = repository
        self._converter = converter
        self._decode_current = decode_current
        self._encode_current = encode_current

    def load(self, path: str | Path) -> DocumentValue:
        """ 生の項目をモデル検証で除外する前に、版変換を適用する。
        """
        source_value = self._repository.load(path)
        current_value = self._converter.to_current(source_value)

        return self._decode_current(current_value)

    def save(
        self, path: str | Path, value: DocumentValue, *,
        target_version: int | None = None, overwrite: bool = False,
    ):
        """ 通常は現在版で保存し、指定があれば旧版へ変換して別途出力する。
        """
        current_value = self._encode_current(value)
        # encode_currentの版漏れ・誤指定で、現在の値へ再度upcastをかけない。
        if self._converter.read_version(current_value) != self._converter.current_version:
            raise SerializationError("encode_currentは現在版の版番号を含めてください")

        output_value = self._converter.convert(
            current_value,
            target_version=self._converter.current_version if target_version is None else target_version,
        )

        # 変換済みの項目が保存内容の正本。YAMLの既存キーをマージして廃止項目を戻さない。
        self._repository.save(path, output_value, overwrite=overwrite, merge_existing=False)
