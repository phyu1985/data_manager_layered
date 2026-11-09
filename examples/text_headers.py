""" 空白本文・複数key:valueのmeta・ブロックの追加ヘッダを同じ文書APIで扱う例。
"""
import argparse
from pathlib import Path

from pydantic import BaseModel

from DataManager import BlockRow, BlockRowsOptions, BlockRowsSerializer, CsvOptions, CsvSerializer, RowsDocument, RowsRepository, CsvKeyValueHeaderOptions


class Reading(BaseModel):
    """ サンプルの測定行。
    """

    name: str
    value: float


def run(directory: Path):
    directory.mkdir(parents=True, exist_ok=False)
    csv = CsvSerializer(
        options=CsvOptions(delimiter=" "),
        metadata=CsvKeyValueHeaderOptions.until_marker("[data]").as_text(multiple=True),
    )
    blocks = BlockRowsSerializer(options=BlockRowsOptions(
        delimiter=" ", rows=(BlockRow.root("name", "value"),),
        metadata=CsvKeyValueHeaderOptions.until_marker("[columns]").as_text(multiple=True),
    ))
    repository = RowsRepository(
        model=Reading, base_directory=directory,
        serializers_by_extension={".csv": csv, ".blocks": blocks},
    )
    (directory / "source.csv").write_text(
        'version: 1    device: A001\n[data]\nname    value\nA    1.25\n', encoding="utf-8",
    )
    document = repository.load_document("source.csv")
    assert document.metadata == {"version": "1", "device": "A001"}
    assert document.rows == [Reading(name="A", value=1.25)]
    repository.save_document("export.blocks", document)
    assert repository.load_document("export.blocks") == document
    repository.save_document("export.csv", RowsDocument(metadata=document.metadata, rows=document.rows))
    assert repository.load_document("export.csv") == document
    print(f"Text headers: {directory.resolve()}")


def main():
    parser = argparse.ArgumentParser(description="テキストヘッダと空白本文の例")
    parser.add_argument("output", type=Path)
    run(parser.parse_args().output)


if __name__ == "__main__":
    main()
