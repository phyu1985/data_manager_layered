""" 収録漏れ・資料リンク切れ・公開不要ファイルの混入を確認する。
"""
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def main():
    """ 保管資料の一覧と実体、現在の説明への入口を照合する。
    """
    failures: list[str] = []
    inventory = json.loads((ROOT / "reference/inventory.json").read_text(encoding="utf-8"))
    for item in inventory:
        path = ROOT / item["path"]
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            failures.append(f"保管資料の欠損または変更: {item['path']}")

    # 過去資料を含めてファイルリンクを確認する。コード例の型引数はリンクとして数えない。
    for path in ROOT.rglob("*.md"):
        if any(part in {".venv", ".git", "outputs", "__pycache__"} for part in path.relative_to(ROOT).parts):
            continue
        text = path.read_text(encoding="utf-8-sig")
        text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        text = re.sub(r"`[^`\n]*`", "", text)
        for target in re.findall(r"\[[^\]\n]+\]\(([^)\n]+)\)", text):
            target = target.strip("<>").split("#", 1)[0]
            if not target or re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", target):
                continue
            destination = (path.parent / target).resolve()
            if not destination.is_relative_to(ROOT) or not destination.exists():
                failures.append(f"資料リンク切れ: {path.relative_to(ROOT)} -> {target}")

    # 実行に不要な秘密設定や鍵をGitHub用フォルダへ混ぜない。
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in {".venv", ".git", "outputs"} for part in path.relative_to(ROOT).parts):
            continue
        if path.name.startswith(".env") or path.suffix.lower() in {".pem", ".key", ".pfx"}:
            failures.append(f"公開対象外ファイル: {path.relative_to(ROOT)}")

    if failures:
        raise SystemExit("\n".join(failures))

    print(f"Release integrity confirmed: {len(inventory)} reference files, documentation links and file exclusions")


if __name__ == "__main__":
    main()
