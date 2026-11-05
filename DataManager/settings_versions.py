""" 設定の隣接版変換と、現在モデルへの復元規則を一か所に置く。
"""
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from DataManager.file_io import CommitGuard
from DataManager import ObjectRepository, VersionConverter, VersionedObjectRepository
from Domain.models import Settings


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


def upcast_v3_to_v4(value: dict[str, Any]) -> dict[str, Any]:
    """ 作成制御がなかったV3は常に作成扱いにする。生成物の有無では判断しない。
    """
    return {**value, "generate_output": True}


def downcast_v4_to_v3(value: dict[str, Any]) -> dict[str, Any]:
    """ 旧版が理解できない作成フラグを除く。V3での動作は常に作成となる。
    """
    return {key: item for key, item in value.items() if key != "generate_output"}


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
            "generate_output": value.get("generate_output", True),
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
        "version": 4,
        **settings.model_dump(mode="json"),
        "retained_values": dict(document.retained_values),
    }


def create_settings_repository(
    directory: Path, *, commit_guard: CommitGuard | None = None,
    template_directory: Path | None = None,
    templates_by_version: Mapping[int, Mapping[str, str | Path]] | None = None,
) -> VersionedObjectRepository[SettingsDocument]:
    """ ファイル形式の設定と業務の互換規則を、この組立箇所だけで接続する。
    """
    return VersionedObjectRepository(
        repository=ObjectRepository(
            model=dict, base_directory=directory, commit_guard=commit_guard,
            template_directory=template_directory,
        ),
        converter=VersionConverter(
            current_version=4,
            upcasts={0: upcast_v0_to_v1, 1: upcast_v1_to_v2, 2: upcast_v2_to_v3, 3: upcast_v3_to_v4},
            downcasts={4: downcast_v4_to_v3, 3: downcast_v3_to_v2},
        ),
        decode_current=decode_settings,
        encode_current=encode_settings,
        templates_by_version=templates_by_version,
    )


# 旧ファクトリー名の移行用別名。
create_settings_service = create_settings_repository
