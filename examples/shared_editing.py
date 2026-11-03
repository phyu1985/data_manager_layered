""" 別アプリ相当のサービス間で編集権を引き継ぎ、旧編集の保存を拒否する例。
"""
import argparse
from pathlib import Path

from DataManager import EditConflictError, EditRevokedError, Storage
from Domain.models import AnalysisPresets, Measurement
from UseCase.analysis import AnalysisWorkspace


def run(root: Path):
    """ ローカルでの動作例。実際のSMB・複数端末での確認を代替するものではない。
    """
    root.mkdir(parents=True, exist_ok=False)
    Storage.initialize(root)
    directory = root / "datasets" / "sample01"
    first = AnalysisWorkspace(directory)
    second = AnalysisWorkspace(directory)
    other = AnalysisWorkspace(root / "datasets" / "sample02")
    first.save_initial(AnalysisPresets(threshold=10, gain=1, measurements=[Measurement(measurement_id="a", value=20)]))

    with first.edit() as old:
        old.threshold = 99
        # 別の解析フォルダは、最初の編集が続いていても処理できる。
        other.save_initial(old)
        try:
            with second.edit():
                raise AssertionError("通常編集の重複を許可してしまいました")
        except EditConflictError:
            pass
        with second.edit(force=True) as current:
            current.threshold = 15
            second.save_settings(current, overwrite=True)
            try:
                first.save_settings(old, overwrite=True)
                raise AssertionError("失効した編集を保存してしまいました")
            except EditRevokedError:
                print("強制引継ぎ後の旧セッションからの保存を拒否しました")

    assert second.load().threshold == 15
    assert not list(directory.glob("*.lock"))
    assert not list((root / "application_control" / "editors").iterdir())
    print(f"編集終了後の所有者情報は削除済み。固定ガードは管理領域内: {root.resolve()}")


def main():
    parser = argparse.ArgumentParser(description="共有編集権の取得・強制引継ぎ")
    parser.add_argument("root", type=Path)
    run(parser.parse_args().root)


if __name__ == "__main__":
    main()
