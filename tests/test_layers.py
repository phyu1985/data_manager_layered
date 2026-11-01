""" インストールや検索パスの細工に頼らず、レイヤの境界を守れることを確認する。
"""
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
LAYERS = {"View", "UseCase", "DataManager", "Domain"}
ALLOWED = {
    "View": {"View", "UseCase"},
    "UseCase": {"UseCase", "DataManager", "Domain"},
    "DataManager": {"DataManager", "Domain"},
    "Domain": {"Domain"},
}


@pytest.mark.parametrize("layer", sorted(LAYERS))
def test_absolute_imports_follow_layer_direction(layer: str):
    for path in (ROOT / layer).rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.level == 0, f"相対import: {path}:{node.lineno}"
                modules = [node.module or ""]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            else:
                continue

            for module in modules:
                top = module.split(".")[0]
                assert top not in {"src", "data_manager", "examples", "reporting"}, path
                if top in LAYERS:
                    assert top in ALLOWED[layer], f"レイヤ逆参照: {path} -> {module}"


def test_application_layers_do_not_edit_module_search_paths():
    for layer in LAYERS:
        for path in (ROOT / layer).rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert "sys.path" not in source, path
            assert "PYTHONPATH" not in source, path
            assert "site.addsitedir" not in source, path
            if layer != "View":
                for node in ast.walk(ast.parse(source)):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                        assert node.func.id not in {"print", "input"}, path


def test_copied_project_runs_without_old_modules_or_pythonpath(tmp_path: Path):
    copied = tmp_path / "copied_project"
    copied.mkdir()
    for directory in [*LAYERS, "sample_data"]:
        shutil.copytree(ROOT / directory, copied / directory, ignore=shutil.ignore_patterns("__pycache__"))

    script = """
import importlib.abc
import json
from pathlib import Path
import sys

class RejectOldProject(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'data_manager', 'src', 'examples', 'reporting'}:
            raise AssertionError('旧プロジェクトへの依存: ' + fullname)
        return None

sys.meta_path.insert(0, RejectOldProject())
from UseCase.end_to_end import run
import DataManager
assert Path(DataManager.__file__).resolve().is_relative_to(Path.cwd())
result = run(Path('output'))
print(json.dumps({'first': result.first.exceeded_count, 'second': result.second.exceeded_count}))
"""
    environment = {name: value for name, value in os.environ.items() if name != "PYTHONPATH"}
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=copied, env=environment,
        capture_output=True, text=True, timeout=30, check=True,
    )
    assert json.loads(completed.stdout) == {"first": 2, "second": 1}


@pytest.mark.parametrize("entrypoint", [["-m", "View.end_to_end"], ["main.py"]])
def test_view_entrypoint_calls_usecase_without_install(tmp_path: Path, entrypoint: list[str]):
    environment = {name: value for name, value in os.environ.items() if name != "PYTHONPATH"}
    output = tmp_path / "output"
    completed = subprocess.run(
        [sys.executable, *entrypoint, str(output)],
        cwd=ROOT, env=environment, capture_output=True, text=True, timeout=30, check=True,
    )
    assert (output / "report.csv").is_file()
    assert completed.stdout
    assert not (ROOT / "src").exists()
    assert not (ROOT / "setup.py").exists()
