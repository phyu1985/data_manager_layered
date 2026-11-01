""" アプリ側のservicesモジュールで、用途別の入出力を一度だけ組み立てる例。
"""
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from DataManager import ObjectFileService, ObjectRepository, RowsFileService, RowsRepository


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
class ProjectServices:
    """ ユースケースへ公開する用途別の窓口。組み合わせ自体は変更できない。
    """

    settings: ObjectFileService[ApplicationSettings]
    measurements: RowsFileService[MeasurementRecord]
    events: RowsFileService[MeasurementEvent | AuditEvent]


def create_project_services(base_directory: Path) -> ProjectServices:
    """ モデル・ファイル名・形式の組み合わせを、このモジュールへ集約する。
    """
    # 構成だけを作り、ここではファイルへ触れない。業務の初期値や欠損時の方針は呼び出し側が決める。
    settings = ObjectFileService(
        repository=ObjectRepository(model=ApplicationSettings, base_directory=base_directory),
        path="config/settings.yaml",
    )
    measurements = RowsFileService(
        repository=RowsRepository(model=MeasurementRecord, base_directory=base_directory),
        path="measurements.csv",
    )
    events = RowsFileService[MeasurementEvent | AuditEvent](
        repository=RowsRepository[MeasurementEvent | AuditEvent](
            model=(MeasurementEvent, AuditEvent), base_directory=base_directory,
        ),
        path="logs/events.jsonl",
    )

    return ProjectServices(settings=settings, measurements=measurements, events=events)


def main():
    services = create_project_services(Path("outputs/services"))

    # ユースケースは保存先や拡張子を繰り返さず、用途と値だけで入出力できる。
    services.settings.save(ApplicationSettings(project_name="inspection"))
    services.measurements.save([
        MeasurementRecord(label="initial", value=12.5),
        MeasurementRecord(label="final", value=None),
    ])
    services.events.save([])
    services.events.append([
        MeasurementEvent(message="measurement finished"), AuditEvent(operation="saved"),
    ])

    print("設定:", services.settings.load())
    print("測定:", services.measurements.load())
    print("ログの型:", [type(event).__name__ for event in services.events.load()])


if __name__ == "__main__":
    main()
