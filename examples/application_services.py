""" アプリ側のservicesモジュールで、用途別の入出力を一度だけ組み立てる例。
"""
import argparse
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from DataManager import FileService, ObjectRepository, RowsFileService, RowsRepository


class ApplicationSettings(BaseModel):
    """ アプリが保存する設定。ファイル形式や保存先はモデルに持たせない。
    """

    project_name: str


class MeasurementRecord(BaseModel):
    label: str
    value: float | None


class MeasurementEvent(BaseModel):
    message: str


class AuditEvent(BaseModel):
    operation: str


@dataclass(frozen=True)
class ProjectFiles:
    """ ユースケースへ公開する用途別の窓口。組み合わせ自体は変更できない。
    """

    settings: FileService[ApplicationSettings]
    measurements: FileService[list[MeasurementRecord]]
    events: RowsFileService[MeasurementEvent | AuditEvent]


def create_project_files(base_directory: Path) -> ProjectFiles:
    """ モデル・ファイル名・形式の組み合わせを、このモジュールへ集約する。
    """
    # 構成だけを作り、ここではファイルへ触れない。業務の初期値や欠損時の方針は呼び出し側が決める。
    settings = FileService(
        repository=ObjectRepository(model=ApplicationSettings, base_directory=base_directory),
        path="config/settings.yaml",
    )
    measurements = FileService(
        repository=RowsRepository(model=MeasurementRecord, base_directory=base_directory),
        path="measurements.csv",
    )
    events = RowsFileService[MeasurementEvent | AuditEvent](
        repository=RowsRepository[MeasurementEvent | AuditEvent](
            model=(MeasurementEvent, AuditEvent), base_directory=base_directory,
        ),
        path="logs/events.jsonl",
    )

    return ProjectFiles(settings=settings, measurements=measurements, events=events)


def run(output_directory: Path):
    """ 新しい出力先で共通の入出力窓口を構成し、値だけを渡して使う。
    """
    from DataManager.storage import Storage
    output_directory.mkdir(parents=True, exist_ok=False)
    if Storage.find(output_directory) is None:
        Storage.initialize(output_directory)
    files = create_project_files(output_directory)

    # ユースケースは保存先や拡張子を繰り返さず、用途と値だけで入出力できる。
    files.settings.save(ApplicationSettings(project_name="inspection"))
    files.measurements.save([
        MeasurementRecord(label="initial", value=12.5),
        MeasurementRecord(label="final", value=None),
    ])
    files.events.save([])
    files.events.append([
        MeasurementEvent(message="measurement finished"), AuditEvent(operation="saved"),
    ])

    print("設定:", files.settings.load())
    print("測定:", files.measurements.load())
    print("ログの型:", [type(event).__name__ for event in files.events.load()])


def main():
    """ 同じ例を別の保存先でも実行できる入口。
    """
    parser = argparse.ArgumentParser(description="類推できる汎用ファイル窓口")
    parser.add_argument("output_directory", nargs="?", type=Path, default=Path("outputs/services"))
    run(parser.parse_args().output_directory)


if __name__ == "__main__":
    main()


# 例の旧名から移行するための別名。
ProjectServices = ProjectFiles
create_project_services = create_project_files
