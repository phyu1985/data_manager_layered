""" 新しい出力先で、旧設定読取から再解析・互換出力・帳票出力までを実行する。
"""
import argparse
from pathlib import Path
from typing import Any

from DataManager.storage import Storage
from DataManager import ObjectRepository
from UseCase.processing import load_processing_presets
from UseCase.analysis import AnalysisWorkspace
from Domain.processing import process_data
from DataManager.report_repository import ReportRepository
from DataManager.services import FileWriter
from Domain.reporting import build_report_rows
from UseCase.external_updates import ExternalUpdater
from DataManager.summary import create_summary_writer


def run(output_directory: Path, *, include_excel: bool = False):
    """ 実ファイルを残し、各段階の保存内容を読んで確認できるようにする。
    """
    # 例の再実行で以前の結果を壊さない。利用者が新しい保存先を選ぶ。
    output_directory.mkdir(parents=True, exist_ok=False)
    if Storage.find(output_directory) is None:
        Storage.initialize(output_directory)
    source_repository = ObjectRepository[dict[str, Any]](model=dict, base_directory=output_directory)
    source_repository.save("legacy.json", {
        "version": 2, "threashold": 100,
        "operator_note": "以前は使用していたので維持", "draft_flag": "未使用なので廃止",
    })

    analysis = AnalysisWorkspace(output_directory / "analysis")
    processing, retained_values = load_processing_presets(
        (output_directory / "legacy.json").resolve(), [80, 120, 150],
    )
    presets = process_data(processing)
    analysis.save_initial(presets, retained_values=retained_values)
    external_updates = ExternalUpdater(analysis, targets={
        "summary": create_summary_writer(output_directory / "latest_status"),
    })
    initial_update = external_updates.refresh()
    if initial_update.failures:
        print("解析データは保存済みです。外部情報の更新に失敗しました。")

    # 再読した解析用Presetsを編集し、設定ファイルだけを更新する。
    # 測定行は編集していないので、save_measurementsは呼ばない。
    with analysis.edit() as presets:
        presets.threshold = 110
        analysis.save_settings(presets, overwrite=True)

        # 旧形式は別の保存先へ出す。gainはV2にないためdowncastで除外される。
        analysis.export_settings("settings_v2.json", presets, target_version=2)
        result = external_updates.refresh(presets=presets)
        if result.failures:
            print("外部反映だけ失敗しました。「外部情報を更新」で再試行できます。")

    # ボタンを押したときもこの呼び出しを使う。解析処理を再実行しない。
    # 最新情報は同じ保存先を更新するため、繰り返してもファイルは増えない。
    external_updates.refresh()

    # 帳票の明細は一度だけ組み立て、選んだ形式の出力担当へ渡す。
    rows = build_report_rows([analysis.load()])
    if include_excel:
        from DataManager.Excel.adapter import build_voltage_excel

    report_repository = ReportRepository(
        output_directory / "reports", excel_writer=build_voltage_excel if include_excel else None,
    )
    reports = FileWriter(repository=report_repository, path="summary.csv")
    reports.save(rows)
    reports.save_as("summary.jsonl", rows)
    if include_excel:
        reports.save_as("summary.xlsx", rows)

    print(f"出力先: {output_directory.resolve()}")
    print("analysis: 最新設定・独立した測定行・V2互換出力")
    print("latest_status: 保存済み解析データから再更新できる集約情報")
    print("reports: 同じ明細から作成したCSV / JSONL" + (" / Excel" if include_excel else ""))


def main():
    parser = argparse.ArgumentParser(description="加工・解析・帳票の接続例")
    parser.add_argument("output_directory", type=Path, help="まだ存在しない出力フォルダ")
    parser.add_argument("--excel", action="store_true", help="同梱のDataManager.Excelで出力する")
    arguments = parser.parse_args()

    run(arguments.output_directory, include_excel=arguments.excel)


if __name__ == "__main__":
    main()
