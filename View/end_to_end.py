""" コマンドライン入力と表示を担当し、処理をUseCaseへ依頼する。
"""
import argparse
from pathlib import Path
from UseCase.end_to_end import DEFAULT_RAW, ReviewSummary, run


def show_summary(label: str, summary: ReviewSummary):
    """ ファイルを増やさず、二回の判定の違いを表示する。
    """
    print(
        f"{label}: しきい値={summary.threshold:g}, 超過={summary.exceeded_count}件, "
        f"平均={summary.mean_value:g}, 最大={summary.max_value:g}, "
        f"確認順={','.join(summary.order)}"
    )


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

    result = run(
        arguments.output_directory, raw_path=arguments.raw, dataset=arguments.dataset,
        first_threshold=arguments.first_threshold, second_threshold=arguments.second_threshold,
        gain=arguments.gain, report_format=arguments.report_format, on_progress=print,
    )
    show_summary("初回解析", result.first)
    show_summary("再解析", result.second)



if __name__ == "__main__":
    main()
