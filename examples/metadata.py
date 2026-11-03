""" CSVの3種類の境界とJSONLを、同じメタ情報APIで入出力する。
"""
import argparse
from pathlib import Path

from pydantic import BaseModel

from DataManager import (
    CsvOptions, CsvSerializer, JsonlSerializer, RowsDocument,
    FileService, RowsDocumentRepository, RowsRepository,
)


class FileMetadata(BaseModel):
    """ ファイル全体に属する値。保存形式の制御情報を混ぜない。
    """

    version: int
    device: str


class Measurement(BaseModel):
    """ テーブル本文の1行。ファイル共通の項目は持たせない。
    """

    time: int
    value: float


def run(output_directory: Path):
    """ 同じメタと本文を4形式へ保存し、読み戻したモデルを確認する。
    """
    output_directory.mkdir(parents=True, exist_ok=False)
    from DataManager.storage import Storage
    if Storage.find(output_directory) is None:
        Storage.initialize(output_directory)
    document = RowsDocument(
        metadata=FileMetadata(version=4, device="A001"),
        rows=[Measurement(time=0, value=1.2), Measurement(time=1, value=1.5)],
    )
    csv_formats = {
        "blank.csv": CsvOptions(boundary="blank_line"),
        "marker.csv": CsvOptions(boundary="marker", marker="[data]"),
        "fixed.csv": CsvOptions(boundary="fixed_rows", row_count=2),
    }

    # 区切りの差はSerializerの構成へ閉じ込める。保存・読込の呼び方は変えない。
    for filename in [*csv_formats, "metadata.jsonl"]:
        repository = RowsRepository(
            model=Measurement, base_directory=output_directory,
            serializers_by_extension={
                ".csv": CsvSerializer(options=csv_formats.get(filename)),
                ".jsonl": JsonlSerializer(),
            },
        )
        service = FileService(
            repository=RowsDocumentRepository(repository=repository, metadata_model=FileMetadata),
            path=filename,
        )
        service.save(document)
        restored = service.load()
        assert restored == document
        print(f"{filename}: version={restored.metadata.version}, device={restored.metadata.device}, rows={len(restored.rows)}")


def main():
    """ 既存データを上書きしない保存先を受け取り、比較例を実行する。
    """
    parser = argparse.ArgumentParser(description="CSV・JSONL共通のメタ情報API")
    parser.add_argument("output_directory", type=Path, nargs="?", default=Path("outputs/metadata"))
    run(parser.parse_args().output_directory)


if __name__ == "__main__":
    main()
