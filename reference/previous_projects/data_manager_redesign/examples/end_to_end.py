""" 生データから加工・解析・再解析・帳票まで、既存モジュールをつないで使う。

加工は先頭値を基準にした補正、解析はしきい値判定と確認優先順位の決定。
実業務の計算を想定したものではなく、入出力をどこで呼ぶかを示す例である。
"""
from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from statistics import fmean
from typing import Literal

from pydantic import BaseModel, FiniteFloat

from data_manager import JSONLLoadOptions, JsonlSerializer, RowsRepository
from examples.analysis_models import AnalysisPresets, ProcessingPresets
from examples.analysis_workflow import AnalysisService, process_data
from examples.excel_reports_adapter import build_voltage_excel
from examples.report_export import ReportExportService, build_report_rows

ReportFormat = Literal["csv", "jsonl", "xlsx"]
DEFAULT_RAW = Path(__file__).parent / "data" / "raw_readings.csv"


class RawReading(BaseModel):
    """ 生データの一行。ファイルから読む段階で非有限の値を拒否する。
    """

    value: FiniteFloat


@dataclass(frozen=True)
class ReviewSummary:
    """ 解析の確認用集計。別ファイルには保存せず、画面やログへ渡す。
    """

    threshold: float
    mean_value: float
    max_value: float
    exceeded_count: int
    order: tuple[str, ...]


@dataclass(frozen=True)
class DemoResult:
    """ 実行した例の出力先と、二回の解析結果を呼出元へ返す。
    """

    analysis_directory: Path
    report_path: Path
    first: ReviewSummary
    second: ReviewSummary


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


def process_readings(presets: ProcessingPresets) -> AnalysisPresets:
    """ 先頭値をゼロ基準にして補正し、解析へ渡すモデルを作る。
    """
    checked = ProcessingPresets.model_validate(presets.model_dump(mode="python"))
    if not checked.raw_values:
        raise ValueError("加工には一つ以上の測定値が必要です")
    if not isfinite(checked.gain) or checked.gain <= 0:
        raise ValueError("補正倍率は有限の正数が必要です")
    if not isfinite(checked.threshold):
        raise ValueError("しきい値は有限値が必要です")

    baseline = checked.raw_values[0]
    values = [(value - baseline) * checked.gain for value in checked.raw_values]
    if any(not isfinite(value) for value in values):
        raise ValueError("補正結果を有限値として保持できません")

    # 既存の加工例でIDと行モデルを作り、このシナリオの補正値を反映する。
    # 元のPresetsや生データは変更しない。
    result = process_data(checked)
    for measurement, value in zip(result.measurements, values, strict=True):
        measurement.value = value
    return result


def analyze_readings(presets: AnalysisPresets) -> ReviewSummary:
    """ しきい値付近の確認優先順位を決め、集計を返す。ファイル操作はしない。
    """
    checked = AnalysisPresets.model_validate(presets.model_dump(mode="python"))
    if not checked.measurements:
        raise ValueError("解析には一つ以上の測定値が必要です")
    if not isfinite(checked.threshold):
        raise ValueError("しきい値は有限値が必要です")
    if any(not isfinite(row.value) for row in checked.measurements):
        raise ValueError("測定値は有限値が必要です")

    rows = sorted(
        checked.measurements,
        key=lambda row: (abs(row.value - checked.threshold), row.measurement_id),
    )
    summary = ReviewSummary(
        threshold=checked.threshold,
        mean_value=fmean(row.value for row in rows),
        max_value=max(row.value for row in rows),
        exceeded_count=sum(row.value > checked.threshold for row in rows),
        order=tuple(row.measurement_id for row in rows),
    )

    # 並び順を解析結果として保存する。値そのものは再補正しないので、再解析で累積しない。
    # 編集中のPresets自身へ反映し、編集権を持たない別モデルへ置き換えない。
    presets.threshold = checked.threshold
    presets.gain = checked.gain
    presets.measurements = rows
    return summary


def list_analyses(directory: Path) -> list[Path]:
    """ 必要な保存ファイルがあるフォルダを、選択画面の候補として列挙する。
    """
    return [
        path for path in sorted(directory.iterdir())
        if path.is_dir() and AnalysisService(path).exists()
    ]


def select_analysis(candidates: Sequence[Path], name: str) -> Path:
    """ ユーザーが選んだフォルダ名を確定し、未知の名前を推測で補わない。
    """
    for path in candidates:
        if path.name == name:
            return path

    names = ", ".join(path.name for path in candidates)
    raise ValueError(f"解析対象がありません: {name}（候補: {names}）")


def show_summary(label: str, summary: ReviewSummary):
    """ ファイルを増やさず、二回の判定の違いを表示する。
    """
    print(
        f"{label}: しきい値={summary.threshold:g}, 超過={summary.exceeded_count}件, "
        f"平均={summary.mean_value:g}, 最大={summary.max_value:g}, "
        f"確認順={','.join(summary.order)}"
    )


def run(
    output_directory: Path, *, raw_path: Path = DEFAULT_RAW, dataset: str = "sample01",
    first_threshold: float = 10, second_threshold: float = 18, gain: float = 1,
    report_format: ReportFormat = "csv",
) -> DemoResult:
    """ 新しい保存先で全工程を実行し、帳票は指定形式の一つだけを出力する。
    """
    if output_directory.exists():
        raise FileExistsError(f"まだ存在しない出力先を指定してください: {output_directory}")
    if dataset in {"", ".", ".."} or Path(dataset).name != dataset:
        raise ValueError("datasetはパスではなく、フォルダ名で指定してください")
    if report_format not in {"csv", "jsonl", "xlsx"}:
        raise ValueError("帳票形式はcsv / jsonl / xlsxから選んでください")
    if not isfinite(second_threshold):
        raise ValueError("再解析のしきい値は有限値が必要です")

    # 1. Repositoryで実ファイルを読み、処理に必要な値をPresetsへ集める。
    # 本例の条件は画面で指定した想定。外部設定を読む場合はAnalysisService.load_processingを使える。
    raw = read_raw(raw_path)
    print(f"生データ読取: {raw_path.resolve()}（{len(raw)}件）")
    processing = ProcessingPresets(
        raw_values=[row.value for row in raw], gain=gain, threshold=first_threshold,
    )
    processed = process_readings(processing)
    print(f"加工: 先頭値={processing.raw_values[0]:g}を基準に、倍率={gain:g}で補正")

    # 2. 加工済みの一式を新規保存する。失敗時の後始末は既存サービスへ委譲する。
    output_directory.mkdir(parents=True, exist_ok=False)
    data_directory = output_directory / "datasets"
    analysis = AnalysisService(data_directory / dataset)
    analysis.save_initial(processed)
    print(f"加工済み保存: {analysis.directory}")

    # 3. 保存フォルダを列挙して選ぶ。選択後はメモリ上のprocessedを流用せず再読する。
    candidates = list_analyses(data_directory)
    print("解析候補: " + ", ".join(path.name for path in candidates))
    selected = select_analysis(candidates, dataset)
    analysis = AnalysisService(selected)

    # 4. 解析結果は確認順として測定JSONLへ保存する。条件は変えていないのでYAMLには触れない。
    with analysis.edit() as presets:
        first = analyze_readings(presets)
        analysis.save_measurements(presets, overwrite=True)
    show_summary("初回解析", first)

    # 5. 一度閉じて、保存済みデータから再解析する。今回は条件も変えたので両方を更新する。
    # 別名の結果ファイルは作らず、同じ一式へ最新の条件と確認順を保存する。
    with analysis.edit() as presets:
        presets.threshold = second_threshold
        second = analyze_readings(presets)
        analysis.save_settings(presets, overwrite=True)
        analysis.save_measurements(presets, overwrite=True)
    show_summary("再解析", second)

    # 6. 再読した最新状態から明細を作る。Excel等の出力処理へ解析ロジックを持ち込まない。
    rows = build_report_rows([analysis.load()])
    reports = ReportExportService(
        output_directory, excel_writer=build_voltage_excel if report_format == "xlsx" else None,
    )
    report_path = output_directory / f"report.{report_format}"
    reports.export(report_path.resolve(), rows)
    print(f"帳票: {report_path.resolve()}")

    return DemoResult(analysis.directory, report_path.resolve(), first, second)


def main():
    """ 入力と帳票形式を選び、存在しない出力先へ一連の例を実行する。
    """
    parser = argparse.ArgumentParser(description="生データから再解析・帳票までの利用例")
    parser.add_argument("output_directory", type=Path)
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--dataset", default="sample01")
    parser.add_argument("--first-threshold", type=float, default=10)
    parser.add_argument("--second-threshold", type=float, default=18)
    parser.add_argument("--gain", type=float, default=1)
    parser.add_argument("--report-format", choices=("csv", "jsonl", "xlsx"), default="csv")
    arguments = parser.parse_args()

    run(
        arguments.output_directory, raw_path=arguments.raw, dataset=arguments.dataset,
        first_threshold=arguments.first_threshold, second_threshold=arguments.second_threshold,
        gain=arguments.gain, report_format=arguments.report_format,
    )


if __name__ == "__main__":
    main()
