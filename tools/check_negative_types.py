""" 誤ったモデル型の入力がPyrightで拒否されることを確認する。
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_COUNTS = {
    "negative.py": 3,
    "services_negative.py": 3,
    "versioning_negative.py": 2,
    "analysis_negative.py": 2,
    "documents_negative.py": 2,
}


def main():
    """ 正常終了ではなく、想定した箇所・種類の型エラーだけが出ることを検証する。
    """
    # PATHが未設定でも、実行中の仮想環境に入ったPyrightを優先して見つける。
    executable = Path(sys.executable).parent / ("pyright.exe" if sys.platform == "win32" else "pyright")
    command = str(executable) if executable.is_file() else shutil.which("pyright")
    if command is None:
        raise SystemExit("requirements-dev.txtをインストールしてください: pyrightがありません")

    for filename, expected in EXPECTED_COUNTS.items():
        completed = subprocess.run(
            [command, "--pythonpath", sys.executable, "--outputjson", f"typecheck/{filename}"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False,
        )
        if completed.returncode not in {0, 1}:
            raise SystemExit(f"Pyrightの実行に失敗しました: {filename}\n{completed.stderr}")

        result = json.loads(completed.stdout)
        diagnostics = result["generalDiagnostics"]
        errors = [item for item in diagnostics if item["severity"] == "error"]
        # 別ファイルのエラーや警告を、期待した型エラーの件数に混ぜない。
        valid = (
            len(errors) == expected and len(diagnostics) == expected
            and all(item.get("rule") == "reportArgumentType" for item in errors)
            and all(Path(item["file"]).name == filename for item in errors)
        )
        if not valid:
            raise SystemExit(f"想定と異なる型診断です: {filename}\n{completed.stdout}")

        print(f"{filename}: expected {expected} argument type errors confirmed")


if __name__ == "__main__":
    main()
