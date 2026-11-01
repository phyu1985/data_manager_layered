""" 設定の隣接版変換と、現在モデルへの復元規則を一か所に置く。
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from data_manager import ObjectRepository, VersionConverter, VersionedObjectService
from examples.analysis_models import Settings


@dataclass
class SettingsDocument:
    """ 設定値と、処理には使わない維持対象を読み書きの間だけまとめる。
    """

    settings: Settings
    retained_values: dict[str, Any]


def upcast_v0_to_v1(value: dict[str, Any]) -> dict[str, Any]:
    """ この例の版なし形式に、最初の設定名を与える。
    """
    return {**value, "threashold": value.get("threashold", 0.0)}


def upcast_v1_to_v2(value: dict[str, Any]) -> dict[str, Any]:
    """ この例では同じ構造を引き継ぐ。版番号の更新は共通処理が行う。
    """
    return dict(value)


def upcast_v2_to_v3(value: dict[str, Any]) -> dict[str, Any]:
    """ 誤記を直し、維持対象だけを救出する。draft_flagは意図して廃止する。
    """
    retained_values: dict[str, Any] = {}

    # operator_noteは以前使っていた値。空文字やNoneも、存在するならそのまま維持する。
    if "operator_note" in value:
        retained_values["operator_note"] = value["operator_note"]

    # 出力項目を列挙し、見ても使ってもいなかったdraft_flagを持ち越さない。
    return {
        "threshold": value["threashold"],
        "gain": 1.0,
        "retained_values": retained_values,
    }


def downcast_v3_to_v2(value: dict[str, Any]) -> dict[str, Any]:
    """ V2の項目だけを出し、V3のgainと廃止したdraft_flagは出さない。
    """
    output_value = {"threashold": value["threshold"]}
    retained_values = value.get("retained_values", {})

    if "operator_note" in retained_values:
        output_value["operator_note"] = retained_values["operator_note"]

    return output_value


def decode_settings(value: dict[str, Any]) -> SettingsDocument:
    """ 現在の値を検証し、維持情報と分ける。
    """
    raw_retained_values: object = value.get("retained_values", {})
    if not isinstance(raw_retained_values, dict):
        raise ValueError("retained_valuesは辞書が必要です")
    retained_values = cast(dict[str, Any], raw_retained_values)
    if set(retained_values) - {"operator_note"}:
        raise ValueError("retained_valuesにはoperator_noteだけを指定できます")

    return SettingsDocument(
        settings=Settings.model_validate({
            "threshold": value["threshold"], "gain": value.get("gain", 1.0),
        }),
        retained_values=dict(retained_values),
    )


def encode_settings(document: SettingsDocument) -> dict[str, Any]:
    """ 編集後の値を検証し、最新仕様の辞書へ戻す。
    """
    # BaseModelの内部が編集済みでも、保存時の必須条件をここで再確認する。
    settings = Settings.model_validate(document.settings.model_dump())
    if set(document.retained_values) - {"operator_note"}:
        raise ValueError("維持対象でない項目が含まれています")

    return {
        "version": 3,
        **settings.model_dump(mode="json"),
        "retained_values": dict(document.retained_values),
    }


def create_settings_service(directory: Path) -> VersionedObjectService[SettingsDocument]:
    """ ファイル形式の設定と業務の互換規則を、この組立箇所だけで接続する。
    """
    return VersionedObjectService(
        repository=ObjectRepository(model=dict, base_directory=directory),
        converter=VersionConverter(
            current_version=3,
            upcasts={0: upcast_v0_to_v1, 1: upcast_v1_to_v2, 2: upcast_v2_to_v3},
            downcasts={3: downcast_v3_to_v2},
        ),
        decode_current=decode_settings,
        encode_current=encode_settings,
    )
