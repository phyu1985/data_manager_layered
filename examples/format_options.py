""" JSONL・KV・BlockRowsの設定を、目的別の関数から読み書きする例。
"""
import argparse
from pathlib import Path

from pydantic import BaseModel

from DataManager import (
    BlockRow, BlockRowsOptions, BlockRowsSerializer, FileService, JsonlSerializer,
    KvOptions, KvSerializer, ObjectRepository, RowsRepository,
)


class Measurement(BaseModel):
    """ 混在JSONLに入れる測定行。
    """

    id: int
    value: float


class Note(BaseModel):
    """ 混在JSONLに入れる記録行。
    """

    text: str


class Settings(BaseModel):
    """ コメントヘッダも通常の項目として受け取る。
    """

    saved_at: str
    version: int
    threshold: float


class Attribute(BaseModel):
    """ ブロック内の繰り返し属性。
    """

    name: str
    value: float


class BlockItem(BaseModel):
    """ 一つの複数行レコード。
    """

    id: int
    attrs: list[Attribute]
    length: float


def sample_jsonl(directory: Path):
    """ 通常モデルの固定tagを指定し、二種類の行を保存・追記・再読する。
    """
    serializer = JsonlSerializer.for_models(model_tags={Measurement: "measurement", Note: "note"})
    repository = RowsRepository[Measurement | Note](
        model=(Measurement, Note), base_directory=directory,
        serializers_by_extension={".jsonl": serializer},
    )
    file = FileService(repository=repository, path="mixed.jsonl")
    file.save([Measurement(id=1, value=3)])
    repository.append_jsonl("mixed.jsonl", [Note(text="checked")])
    assert file.load() == [Measurement(id=1, value=3), Note(text="checked")]


def sample_kv_values(directory: Path):
    """ 値だけのコメントをキーに対応付け、標準KVへ正規化する。
    """
    source = directory / "values_header.txt"
    source.write_text(
        "# description\n# 2026-11-10\n# 0\nthreshold: 3\n", encoding="utf-8",
    )
    options = KvOptions().with_value_header(("saved_at", "version"), skip=1)
    repository = ObjectRepository(
        model=Settings, base_directory=directory,
        serializers_by_extension={".txt": KvSerializer(options=options)},
    )
    settings = repository.load("values_header.txt")
    assert settings == Settings(saved_at="2026-11-10", version=0, threshold=3)

    normalized = ObjectRepository(model=Settings, base_directory=directory)
    normalized.save("normalized_values.txt", settings)
    assert normalized.load("normalized_values.txt") == settings


def sample_kv_pairs(directory: Path):
    """ キー付きコメントを読む。値だけのヘッダのキー一覧は指定しない。
    """
    source = directory / "pairs_header.txt"
    source.write_text(
        "# saved_at: 2026-11-10\n# version: 0\nthreshold: 3\n", encoding="utf-8",
    )
    repository = ObjectRepository(
        model=Settings, base_directory=directory,
        serializers_by_extension={".txt": KvSerializer(options=KvOptions().with_key_value_header())},
    )
    assert repository.load("pairs_header.txt") == Settings(saved_at="2026-11-10", version=0, threshold=3)


def sample_blocks(directory: Path):
    """ 列と保存見出しを、モデル直下・属性一覧ごとの行定義へまとめる。
    """
    serializer = BlockRowsSerializer(options=BlockRowsOptions(rows=(
        BlockRow.root("id"),
        BlockRow.items("attrs", "name", "value", header=("attribute_1", "value_1")),
        BlockRow.items("attrs", "name", "value", header=("attribute_2", "value_2")),
        BlockRow.root("length"),
    )))
    repository = RowsRepository(
        model=BlockItem, base_directory=directory, serializers_by_extension={".txt": serializer},
    )
    file = FileService(repository=repository, path="blocks.txt")
    rows = [BlockItem(
        id=1, attrs=[Attribute(name="a", value=1), Attribute(name="b", value=2)], length=10,
    )]
    file.save(rows)
    assert file.load() == rows


def run(directory: Path):
    directory.mkdir(parents=True, exist_ok=False)
    sample_jsonl(directory)
    sample_kv_values(directory)
    sample_kv_pairs(directory)
    sample_blocks(directory)
    print("JSONL / KV / BlockRows:", directory.resolve())


def main():
    parser = argparse.ArgumentParser(description="各形式の設定を目的別に指定する例")
    parser.add_argument("output", type=Path)
    run(parser.parse_args().output)


if __name__ == "__main__":
    main()
