""" 帳票明細の組立と、形式に応じた出力の振り分けを扱う。
"""
from collections.abc import Callable, Sequence
from pathlib import Path

from pydantic import BaseModel

from data_manager import RowsRepository
from data_manager.file_io import lock_file, resolve_file_path, write_file_atomically
from examples.analysis_models import AnalysisPresets


class ReportRow(BaseModel):
    """ 一覧帳票の共通明細。表示と外部出力に使い、解析へは読み戻さない。
    """

    measurement_id: str
    value: float
    exceeds_threshold: bool


def build_report_rows(analyses: Sequence[AnalysisPresets]) -> list[ReportRow]:
    """ 読取済みの解析結果を一覧にする。出力形式の処理を混ぜない。
    """
    return [
        ReportRow(
            measurement_id=measurement.measurement_id, value=measurement.value,
            exceeds_threshold=measurement.value > presets.threshold,
        )
        for presets in analyses
        for measurement in presets.measurements
    ]


class ReportExportService:
    """ 共通明細をCSV / JSONLへ出し、Excelは既存帳票処理へ委譲する。
    """

    def __init__(
        self, directory: Path, *, excel_writer: Callable[[Sequence[ReportRow]], bytes] | None = None,
    ):
        self._directory = directory.resolve()
        self._rows_repository = RowsRepository(model=ReportRow, base_directory=directory)
        self._excel_writer = excel_writer

    def export(self, path: str | Path, rows: Sequence[ReportRow], *, overwrite: bool = False):
        """ 同じ明細を形式別の出力先へ渡す。対応しない形式は保存前に拒否する。
        """
        destination = resolve_file_path(self._directory, path)

        if destination.suffix.lower() in {".csv", ".jsonl"}:
            self._rows_repository.save(destination, rows, overwrite=overwrite)
            return

        if destination.suffix.lower() != ".xlsx" or self._excel_writer is None:
            raise ValueError("この帳票の対応形式はCSV / JSONLと、接続済みの場合のExcelです")

        # Workbookの作成が失敗したらファイルへ触れない。保存は同じ上書き規則で行う。
        content = self._excel_writer(rows)
        with lock_file(destination, timeout_seconds=10):
            if destination.exists() and not overwrite:
                raise FileExistsError(destination)
            write_file_atomically(destination, content)
