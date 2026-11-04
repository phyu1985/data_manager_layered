""" 生データから帳票までの手順。画面表示は通知用関数へ委譲する。
"""
from collections.abc import Callable, Sequence
from math import isfinite
from pathlib import Path
from DataManager.storage import Storage
from DataManager.analysis_files import AnalysisFiles
from DataManager.raw_readings import read_raw
from DataManager.report_repository import ReportRepository
from DataManager.services import FileWriter
from Domain.models import ProcessingPresets
from Domain.processing import process_readings
from Domain.analysis import analyze_readings
from Domain.reporting import ReportFormat, build_report_rows
from Domain.results import DemoResult, ReviewSummary as ReviewSummary
from UseCase.analysis import AnalysisWorkspace, apply_analysis_result

DEFAULT_RAW = Path(__file__).resolve().parents[1] / "sample_data" / "raw_readings.csv"


def list_analyses(directory: Path) -> list[Path]:
    """ 必要な保存ファイルがあるフォルダを、選択画面の候補として列挙する。
    """
    return [
        path for path in sorted(directory.iterdir())
        if path.is_dir() and AnalysisFiles.exists_at(path)
    ]


def select_analysis(candidates: Sequence[Path], name: str) -> Path:
    """ ユーザーが選んだフォルダ名を確定し、未知の名前を推測で補わない。
    """
    for path in candidates:
        if path.name == name:
            return path

    names = ", ".join(path.name for path in candidates)
    raise ValueError(f"解析対象がありません: {name}（候補: {names}）")


def run(
    output_directory: Path, *, raw_path: Path = DEFAULT_RAW, dataset: str = "sample01",
    first_threshold: float = 10, second_threshold: float = 18, gain: float = 1,
    report_format: ReportFormat = "csv", on_progress: Callable[[str], None] | None = None,
) -> DemoResult:
    """ 新しい保存先で全工程を実行し、帳票は指定形式の一つだけを出力する。
    """
    # 表示方法をView側で選べるよう、進捗だけを通知する。
    def notify(message: str):
        if on_progress is not None:
            on_progress(message)

    if output_directory.exists():
        raise FileExistsError(f"まだ存在しない出力先を指定してください: {output_directory}")
    if dataset in {"", ".", ".."} or Path(dataset).name != dataset:
        raise ValueError("datasetはパスではなく、フォルダ名で指定してください")
    if report_format not in {"csv", "jsonl", "xlsx"}:
        raise ValueError("帳票形式はcsv / jsonl / xlsxから選んでください")
    if not isfinite(second_threshold):
        raise ValueError("再解析のしきい値は有限値が必要です")

    # 1. Repositoryで実ファイルを読み、処理に必要な値をPresetsへ集める。
    raw = read_raw(raw_path)
    notify(f"生データ読取: {raw_path.resolve()}（{len(raw)}件）")
    processing = ProcessingPresets(
        raw_values=[row.value for row in raw], gain=gain, threshold=first_threshold,
    )
    processed = process_readings(processing)
    notify(f"加工: 先頭値={processing.raw_values[0]:g}を基準に、倍率={gain:g}で補正")

    # 2. 加工済みの設定と測定を一式で新規保存する。
    output_directory.mkdir(parents=True, exist_ok=False)
    if Storage.find(output_directory) is None:
        Storage.initialize(output_directory)
    data_directory = output_directory / "datasets"
    analysis = AnalysisWorkspace(data_directory / dataset)
    analysis.save_initial(processed)
    notify(f"加工済み保存: {analysis.directory}")

    # 3. 保存フォルダを列挙して選ぶ。選択後はメモリ上のprocessedを流用せず再読する。
    candidates = list_analyses(data_directory)
    notify("解析候補: " + ", ".join(path.name for path in candidates))
    selected = select_analysis(candidates, dataset)
    analysis = AnalysisWorkspace(selected)

    # 4. 計算結果を明示的に反映し、変更した測定JSONLだけを保存する。
    with analysis.edit() as presets:
        first_result = analyze_readings(presets)
        apply_analysis_result(presets, first_result)
        analysis.save_measurements(presets, overwrite=True)
    notify("初回解析を保存しました")

    # 5. 一度閉じて、保存済みデータから再解析する。今回は条件も変えたので両方を更新する。
    with analysis.edit() as presets:
        presets.threshold = second_threshold
        second_result = analyze_readings(presets)
        apply_analysis_result(presets, second_result)
        analysis.save_settings(presets, overwrite=True)
        analysis.save_measurements(presets, overwrite=True)
    notify("再解析を保存しました")

    # 6. 再読した最新状態から明細を作る。Excel等の出力処理へ解析ロジックを持ち込まない。
    rows = build_report_rows([analysis.load()])
    report_path = output_directory / f"report.{report_format}"
    reports = FileWriter(repository=ReportRepository(output_directory), path=report_path.resolve())
    reports.save(rows)
    notify(f"帳票: {report_path.resolve()}")

    return DemoResult(analysis.directory, report_path.resolve(), first_result.summary, second_result.summary)
