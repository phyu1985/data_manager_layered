""" YAMLの別置きテンプレート、Rowsのmeta版変換、属性8行の入出力を追う例。
"""
import argparse
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from DataManager import (
    AttributeBlockSerializer, BlockRowsOptions, CsvOptions, CsvSerializer, FileService,
    JsonlSerializer, ObjectRepository, RowsDocument, RowsRepository, VersionConverter, VersionedRowsRepository,
)
from DataManager.settings_versions import SettingsDocument, create_settings_repository
from Domain.models import Settings
from examples.extended_formats import Attribute, BlockModel


class CaptureMetadata(BaseModel):
    """ 現在版のmeta。旧名deviceはキャストでinstrumentへ変更する。
    """

    version: int
    instrument: str


class Reading(BaseModel):
    """ 現在版の測定行。
    """

    time: int
    value: float


def upcast_capture(document: dict[str, Any]) -> dict[str, Any]:
    """ metaと本文を同じ版の構造へ変える。廃止項目は引き継がない。
    """
    return {
        **document,
        "metadata": {"instrument": document["metadata"]["device"]},
        "rows": [{"time": row["time"], "value": row["reading"]} for row in document["rows"]],
    }


def downcast_capture(document: dict[str, Any]) -> dict[str, Any]:
    """ 旧版が理解できるmeta名と本文名へ戻す。
    """
    return {
        **document,
        "metadata": {"device": document["metadata"]["instrument"]},
        "rows": [{"time": row["time"], "reading": row["value"]} for row in document["rows"]],
    }


def decode_capture(document: dict[str, Any]) -> RowsDocument[CaptureMetadata, Reading]:
    """ キャスト完了後に、metaと本文を現在のモデルで検証する。
    """
    return RowsDocument(
        metadata=CaptureMetadata.model_validate(document["metadata"]),
        rows=[Reading.model_validate(row) for row in document["rows"]],
    )


def encode_capture(document: RowsDocument[CaptureMetadata, Reading]) -> dict[str, Any]:
    """ 現在版の辞書へ戻す。出力版の選択はVersionedRowsRepositoryが担当する。
    """
    return {
        "version": 1,
        "metadata": document.metadata.model_dump(),
        "rows": [row.model_dump() for row in document.rows],
    }


def yaml_example(directory: Path):
    """ 保存先とは別のテンプレートディレクトリを構成し、同じFileServiceで扱う。
    """
    templates = directory / "templates"
    templates.mkdir(parents=True)
    (templates / "v3.yaml").write_text(
        "# Current settings\nversion: 3\nthreshold: 0  # Decision level\ngain: 1\nretained_values: {}\n",
        encoding="utf-8",
    )
    (templates / "v2.yaml").write_text(
        "# Legacy settings\nversion: 2\nthreashold: 0  # Legacy spelling\n",
        encoding="utf-8",
    )
    repository = create_settings_repository(
        directory / "data", template_directory=templates,
        templates_by_version={3: {".yaml": "v3.yaml"}, 2: {".yaml": "v2.yaml"}},
    )
    current = FileService(repository=repository, path="settings.yaml")
    document = SettingsDocument(Settings(threshold=15, gain=2), {})
    current.save(document)
    document.settings.threshold = 20
    current.save(document, overwrite=True)
    assert "Decision level" in (directory / "data/settings.yaml").read_text(encoding="utf-8")

    legacy = FileService(repository=repository.for_version(2), path="settings_v2.yaml")
    legacy.save(document)
    raw = ObjectRepository(model=dict, base_directory=directory / "data").load("settings_v2.yaml")
    assert raw == {"version": 2, "threashold": 20}
    # 同じRepositoryのJSON出力に、YAMLテンプレートは適用しない。
    current.save_as("settings.json", document)


def rows_example(directory: Path):
    """ CSVの旧meta・旧本文を読み、現在JSONLと旧版CSVへ出し分ける。
    """
    raw_repository = RowsRepository[dict[str, Any]](
        model=dict, base_directory=directory,
        serializers_by_extension={
            ".csv": CsvSerializer(options=CsvOptions(boundary="blank_line")),
            ".jsonl": JsonlSerializer(),
        },
    )
    raw_repository.save_document("source.csv", RowsDocument(
        metadata={"version": 0, "device": "A001", "unused": "discard"},
        rows=[{"time": 0, "reading": 1.2}],
    ))
    repository = VersionedRowsRepository(
        repository=raw_repository,
        converter=VersionConverter(current_version=1, upcasts={0: upcast_capture}, downcasts={1: downcast_capture}),
        decode_current=decode_capture, encode_current=encode_capture,
        read_version=lambda metadata: int(metadata.get("version", 0)),
    )
    source = FileService(repository=repository, path="source.csv")
    document = source.load()
    assert document.metadata == CaptureMetadata(version=1, instrument="A001")
    source.save_as("current.jsonl", document)
    legacy = FileService(repository=repository.for_version(0), path="legacy.csv")
    legacy.save(document)
    assert legacy.load() == document
    saved = raw_repository.load_document("legacy.csv")
    assert saved.metadata == {"device": "A001", "version": "0"}
    assert saved.rows == [{"time": "0", "reading": "1.2"}]


def blocks_example(directory: Path):
    """ 同名列を属性の所属先へ分け、8行固定のまま読み書きする。
    """
    # このモデルではaxis_mmを使う。columnsで保存先のキー名を明示できる。
    columns = (
        ("name", "ch", "start", "length"),
        *((f"info_name{i + 1}", f"info_value{i + 1}", "start", "length") for i in range(8)),
        ("axis_mm", "length_mm"),
    )
    serializer = AttributeBlockSerializer(options=BlockRowsOptions(delimiter=",", columns=columns))
    repository = RowsRepository(
        model=BlockModel, base_directory=directory, serializers_by_extension={".txt": serializer},
    )
    file = FileService(repository=repository, path="attributes.txt")
    value = BlockModel(
        name="sample", ch=1, start=100, length=200, axis_mm=10, length_mm=20,
        attrs=[Attribute(name=f"attr{i + 1}", value=i / 10, start=100 + i, length=2) for i in range(8)],
    )
    file.save([value])
    assert file.load() == [value]


def run(directory: Path):
    """ 未作成の出力先で、テンプレートと版変換・属性行の対応を確認する。
    """
    directory.mkdir(parents=True, exist_ok=False)
    yaml_example(directory / "yaml")
    rows_example(directory / "rows")
    blocks_example(directory / "blocks")
    print(f"YAML templates / metadata casts / attribute blocks: {directory.resolve()}")


def main():
    parser = argparse.ArgumentParser(description="版変換・YAMLテンプレート・属性ブロックの例")
    parser.add_argument("output", type=Path)
    run(parser.parse_args().output)


if __name__ == "__main__":
    main()
