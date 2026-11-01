""" 帳票明細を指定形式で保存する。解析手順や表示は担当しない。
"""
from collections.abc import Callable, Sequence
from pathlib import Path
from DataManager import RowsRepository
from DataManager.file_io import lock_file, resolve_file_path, write_file_atomically
from Domain.reporting import ReportRow


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

        if destination.suffix.lower() != ".xlsx":
            raise ValueError("この帳票の対応形式はCSV / JSONL / Excelです")

        writer = self._excel_writer
        if writer is None:
            # Excelが必要なときだけ同じレイヤ内の実装を読む。独立したreportingの登録は不要。
            from DataManager.Excel.adapter import build_voltage_excel
            writer = build_voltage_excel

        # Workbookの作成が失敗したらファイルへ触れない。保存は同じ上書き規則で行う。
        content = writer(rows)
        with lock_file(destination, timeout_seconds=10):
            if destination.exists() and not overwrite:
                raise FileExistsError(destination)
            write_file_atomically(destination, content)
