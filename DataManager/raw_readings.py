""" 外部生データの形式を選び、Domainの行モデルへ読み取る。
"""
from pathlib import Path
from DataManager import JSONLLoadOptions, JsonlSerializer, RowsRepository
from Domain.raw import RawReading


def read_raw(path: Path) -> list[RawReading]:
    """ CSVまたはメタなし外部JSONLを入力専用として読む。
    """
    path = path.resolve()
    if path.suffix.lower() == ".jsonl":
        # 外部入力用の設定を、解析データの保存用Repositoryへ流用しない。
        repository = RowsRepository(
            model=RawReading, base_directory=path.parent,
            serializers_by_extension={
                ".jsonl": JsonlSerializer(load_options=JSONLLoadOptions(metadata="absent")),
            },
        )
    elif path.suffix.lower() == ".csv":
        repository = RowsRepository(model=RawReading, base_directory=path.parent)
    else:
        raise ValueError("この例の生データはCSVか、メタなしJSONLを指定してください")

    readings = repository.load(path)
    if not readings:
        raise ValueError("生データが空です")
    return readings
