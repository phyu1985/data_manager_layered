""" 既存のアプリ回帰ケースに、明示初期化済みの保存領域を用意する。
"""
from pathlib import Path

import pytest

from DataManager.storage import Storage


@pytest.fixture(autouse=True)
def initialized_storage_for_application_tests(request: pytest.FixtureRequest, tmp_path: Path):
    """ 単独Serializerのケースには管理領域を持ち込まない。
    """
    if request.module.__name__.rsplit(".", 1)[-1] in {
        "test_edit_sessions", "test_external_updates", "test_versioning_workflow", "test_end_to_end",
    }:
        Storage.initialize(tmp_path)
