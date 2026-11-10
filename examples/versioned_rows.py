""" 旧CSVをupcastして現在モデルで処理し、metaごとJSONL・旧CSVへ保存する例。
"""
import argparse
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from DataManager import (
    CsvOptions, CsvSerializer, FileService, JsonlSerializer,
    RowsDocument, RowsRepository, VersionConverter, VersionedRowsRepository,
    CsvKeyValueHeaderOptions,
)


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


def rows_example(directory: Path):
    """ CSVの旧meta・旧本文を読み、現在JSONLと旧版CSVへ出し分ける。
    """
    raw_repository = RowsRepository[dict[str, Any]](
        model=dict, base_directory=directory,
        serializers_by_extension={
            ".csv": CsvSerializer(metadata=CsvKeyValueHeaderOptions.until_blank_line()),
            ".jsonl": JsonlSerializer(),
        },
    )
    raw_repository.save_document("source.csv", RowsDocument(
        metadata={"version": 0, "device": "A001", "unused": "discard"},
        rows=[{"time": 0, "reading": 1.2}],
    ))
    repository = VersionedRowsRepository.for_models(
        repository=raw_repository,
        converter=VersionConverter(current_version=1, upcasts={0: upcast_capture}, downcasts={1: downcast_capture}),
        metadata_model=CaptureMetadata, model_tags={Reading: "Reading"},
    )
    source = FileService(repository=repository, path="source.csv")
    document = source.load()
    assert document.metadata == CaptureMetadata(version=1, instrument="A001")
    source.save_as("current.jsonl", document)
    legacy = FileService(repository=repository.for_version(0), path="legacy.csv")
    legacy.save(document)
    assert legacy.load() == document
    import json
    meta = json.loads((directory / "current.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert meta["__meta__"]["models"] == ["Reading"]
    assert meta["metadata"] == {"instrument": "A001", "version": 1}
    saved = raw_repository.load_document("legacy.csv")
    assert saved.metadata == {"device": "A001", "version": "0"}
    assert saved.rows == [{"time": "0", "reading": "1.2"}]


def main():
    parser = argparse.ArgumentParser(description="VersionedRowsRepositoryの単独例")
    parser.add_argument("output", type=Path)
    directory = parser.parse_args().output
    directory.mkdir(parents=True, exist_ok=False)
    rows_example(directory)
    print(f"Versioned rows: {directory.resolve()}")


if __name__ == "__main__":
    main()
