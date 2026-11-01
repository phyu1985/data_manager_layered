""" 保存済みの解析データを集約JSONへ反映する接続先の例。
"""
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from typing import Any
from DataManager import ObjectRepository
from Domain.models import AnalysisPresets

ExternalWriter = Callable[[Path, AnalysisPresets], None]


def create_summary_writer(summary_directory: Path) -> ExternalWriter:
    """ 解析フォルダごとの最新情報を、集約フォルダのJSONへ更新する例。
    """
    repository = ObjectRepository[dict[str, Any]](model=dict, base_directory=summary_directory)

    def write_summary(source_directory: Path, snapshot: AnalysisPresets):
        """ 同じ解析フォルダは同じ保存先を更新し、再試行で行を増やさない。
        """
        # この例では正規化したパスを識別子にする。移動後も同一と扱う実業務では
        # 保存データ内の安定した識別子へ置き換える。
        source_identity = str(source_directory.resolve())
        file_name = sha256(source_identity.encode("utf-8")).hexdigest() + ".json"
        repository.save(file_name, {
            "source_directory": source_identity,
            "threshold": snapshot.threshold,
            "measurement_count": len(snapshot.measurements),
        }, overwrite=True)

    return write_summary
