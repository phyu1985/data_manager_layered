""" YAML一覧・メタ付き一覧と、V2/V3だけを扱う版変換の例。
"""
import argparse
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from DataManager import RowsDocument, RowsRepository, VersionConverter, VersionedRowsRepository


class Reading(BaseModel):
    """ 一覧の各要素。
    """

    name: str
    value: int


class ReportMetadata(BaseModel):
    """ 一覧全体の版と見出し。
    """

    version: int
    title: str


def sample_plain_list(directory: Path):
    """ ルートがlistのYAMLを読み、同じ一覧を.ymlへ保存する。
    """
    source = directory / "rows.yaml"
    source.write_text("- name: A\n  value: 1\n- name: B\n  value: 2\n", encoding="utf-8")
    repository = RowsRepository(model=Reading, base_directory=directory)
    rows = repository.load("rows.yaml")
    assert rows == [Reading(name="A", value=1), Reading(name="B", value=2)]
    assert repository.load_document("rows.yaml").metadata == {}

    repository.save("normalized.yml", rows)
    assert repository.load("normalized.yml") == rows
    print("YAML list:", rows)


def sample_document(directory: Path):
    """ metadata/rowsの文書を保存し、メタも型付きで読み戻す。
    """
    repository = RowsRepository(model=Reading, base_directory=directory)
    document = RowsDocument(
        metadata=ReportMetadata(version=3, title="Sample"),
        rows=[Reading(name="A", value=1)],
    )
    repository.save_document("document.yaml", document)
    assert repository.load_document("document.yaml", metadata_model=ReportMetadata) == document
    assert repository.load("document.yaml") == document.rows
    print("YAML document:", document)


def upcast_v2_to_v3(document: dict[str, Any]) -> dict[str, Any]:
    """ V2のcaptionとreadingを、現在版のtitleとvalueへ変える。
    """
    assert document["version"] == 2
    return {
        **document, "metadata": {"title": document["metadata"]["caption"]},
        "rows": [{"name": row["name"], "value": row["reading"]} for row in document["rows"]],
    }


def downcast_v3_to_v2(document: dict[str, Any]) -> dict[str, Any]:
    """ 現在版のメタ・本文をV2へ戻す。V0/V1の変換は定義しない。
    """
    assert document["version"] == 3
    return {
        **document, "metadata": {"caption": document["metadata"]["title"]},
        "rows": [{"name": row["name"], "reading": row["value"]} for row in document["rows"]],
    }


def sample_versioned_rows(directory: Path):
    """ 実在するV2/V3の経路だけを登録し、V0/V1の仮castを作らない。
    """
    raw = RowsRepository(model=dict, base_directory=directory)
    raw.save_document("v2.yaml", RowsDocument(
        metadata={"version": 2, "caption": "Sample"}, rows=[{"name": "A", "reading": 1}],
    ))
    original = (directory / "v2.yaml").read_bytes()
    repository = VersionedRowsRepository.for_models(
        repository=raw,
        converter=VersionConverter(
            current_version=3, upcasts={2: upcast_v2_to_v3}, downcasts={3: downcast_v3_to_v2},
        ),
        metadata_model=ReportMetadata, model_tags={Reading: "reading"},
    )
    document = repository.load("v2.yaml")
    assert document == RowsDocument(ReportMetadata(version=3, title="Sample"), [Reading(name="A", value=1)])
    repository.save("v3.yaml", document)
    assert repository.load("v3.yaml") == document
    repository.for_version(2).save("export_v2.yaml", document)
    assert repository.load("export_v2.yaml") == document
    assert raw.load_document("export_v2.yaml") == raw.load_document("v2.yaml")
    assert (directory / "v2.yaml").read_bytes() == original
    print("YAML V2 -> V3 -> V2:", document)


def main():
    parser = argparse.ArgumentParser(description="YAMLのRowsとV2/V3の版変換")
    parser.add_argument("output", type=Path)
    directory = parser.parse_args().output
    directory.mkdir(parents=True, exist_ok=False)
    sample_plain_list(directory)
    sample_document(directory)
    sample_versioned_rows(directory)
    print("Output:", directory.resolve())


if __name__ == "__main__":
    main()
