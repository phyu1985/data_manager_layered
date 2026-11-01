""" モデル固有の項目を知らずに、辞書化・検証する内部処理。

aliasの逆引き、空文字の置換、未知キーの削除は行わない。
入力の受け入れ方はモデルのPydantic設定に従う。
"""
from __future__ import annotations

from typing import Any, Generic, Literal, TypeVar, cast

from pydantic import BaseModel

from .errors import ConfigurationError, SerializationError

SerializableValue = BaseModel | dict[str, Any]
ModelValue = TypeVar("ModelValue", bound=SerializableValue)
DataMode = Literal["single", "mixed", "dict"]


class ModelBinding(Generic[ModelValue]):
    """ 保存・復元に使える型と、共通のモデル変換規則を保持する。

    生成時に単一モデル・混在モデル・dictのどれを扱うか確定する。
    保存時は指定型の値を辞書化し、復元時はSerializerが選んだクラスで検証する。
    ファイル形式やtagの名前は扱わず、公開APIではこのクラスを利用側へ要求しない。
    """

    def __init__(self, model: type[ModelValue] | tuple[type[ModelValue], ...]):
        """ 保存・復元に使えるモデル型を検証し、保持する。
        """
        # 単一指定もタプルへ揃え、以降の型確認とSerializerからの参照を共通化する。
        model_classes: tuple[type[ModelValue], ...] = (
            model if isinstance(model, tuple) else (model,)
        )

        if not model_classes:
            raise ConfigurationError("モデルは重複のない1個以上のクラスを指定してください")

        # 外部設定の誤りもConfigurationErrorに揃え、setやissubclassのTypeErrorを漏らさない。
        for model_candidate in list[object](model_classes):
            if not isinstance(model_candidate, type):
                raise ConfigurationError("モデルにはクラスを指定してください")
            if model_candidate is not dict and not issubclass(model_candidate, BaseModel):
                raise ConfigurationError("モデルはBaseModelの派生クラス、またはdictです")

        if len(set(model_classes)) != len(model_classes):
            raise ConfigurationError("モデルは重複のない1個以上のクラスを指定してください")

        # dictには復元先のモデルがないため、型判別が必要なモデルとの混在は受け付けない。
        if dict in model_classes and len(model_classes) != 1:
            raise ConfigurationError("dictと他のモデルの混在には対応していません")

        self._model_classes: tuple[type[ModelValue], ...] = model_classes
        self._data_mode: DataMode

        # このモードをJSONLのメタ情報と、各行にtagが必要かの判断に使う。
        if model_classes == (dict,):
            self._data_mode = "dict"
        elif len(model_classes) > 1:
            self._data_mode = "mixed"
        else:
            self._data_mode = "single"

    @property
    def model_classes(self) -> tuple[type[ModelValue], ...]:
        """ Serializerが型判別に使うモデルクラスを読み取り専用で返す。
        """
        return self._model_classes

    @property
    def data_mode(self) -> DataMode:
        """ メタ行と型判別に使うデータの構成を返す。
        """
        return self._data_mode

    def to_dict(self, value: ModelValue, *, by_alias: bool) -> dict[str, Any]:
        """ 保存対象の型を確認し、形式別Serializerが使える辞書へ変換する。
        """
        # 派生型を親型として保存すると型情報が失われるため、指定された具体型だけを許可する。
        if type(value) not in self._model_classes:
            raise SerializationError(f"保存対象の型が設定と異なります: {type(value).__name__}")

        # モデルの型変換とaliasはPydanticへ任せ、形式ごとの独自補正を持ち込まない。
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json", by_alias=by_alias)

        self._validate_keys_and_cycles(value, set())

        return dict(value)

    def _validate_keys_and_cycles(self, value: object, ancestor_ids: set[int]):
        """ 辞書のキーを全階層で確認し、循環参照を拒否する。
        """
        if not isinstance(value, (dict, list, tuple)):
            return

        container = cast(dict[object, Any] | list[object] | tuple[object, ...], value)
        if id(container) in ancestor_ids:
            raise SerializationError("辞書・配列の循環参照は保存できません")

        ancestor_ids.add(id(container))
        try:
            if isinstance(container, dict):
                for key, item in container.items():
                    # JSONが整数キー等を文字列へ変えてしまう前に、元の構造を確認する。
                    if not isinstance(key, str):
                        raise SerializationError("辞書のキーは全階層でstrを指定してください")
                    self._validate_keys_and_cycles(item, ancestor_ids)
            else:
                for item in container:
                    self._validate_keys_and_cycles(item, ancestor_ids)
        finally:
            ancestor_ids.remove(id(container))

    def restore_value(
        self,
        data: dict[str, Any],
        model_class: type[ModelValue] | None = None,
    ) -> ModelValue:
        """ 辞書から、指定された型のモデルまたはdictを復元する。

        単一型は復元先を省略できる。混在時は選択済みのクラスを渡す。
        """
        if model_class is None and self._data_mode == "mixed":
            raise ConfigurationError("混在モデルの復元には、選択済みのクラスを指定してください")

        selected_model_class = model_class or self._model_classes[0]

        if selected_model_class not in self._model_classes:
            raise SerializationError("指定されていない復元先です")

        if selected_model_class is dict:
            # 復元先と辞書の構造は確認済み。castは生成や検証の代用ではない。
            return cast(ModelValue, dict(data))

        if issubclass(selected_model_class, BaseModel):
            # 実体の生成と値の検証はmodel_validateが行う。castだけで型を取り繕わない。
            return cast(ModelValue, selected_model_class.model_validate(data))

        raise ConfigurationError("復元先はBaseModelまたはdictです")
