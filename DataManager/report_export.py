""" 従来の帳票出力名の互換窓口。新規コードはReportRepositoryとFileWriterを使う。
"""
from collections.abc import Callable, Sequence
from pathlib import Path

from DataManager.report_repository import ReportRepository
from Domain.reporting import ReportRow


class ReportExportService:
    """ 旧export呼出を新しい保存担当へ委譲する。出力処理を二重に実装しない。
    """

    def __init__(self, directory: Path, *, excel_writer: Callable[[Sequence[ReportRow]], bytes] | None = None):
        self._repository = ReportRepository(directory, excel_writer=excel_writer)

    def export(self, path: str | Path, rows: Sequence[ReportRow], *, overwrite: bool = False):
        self._repository.save(path, rows, overwrite=overwrite)
