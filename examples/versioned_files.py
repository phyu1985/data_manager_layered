""" YAMLの別置きテンプレート、Rowsのmeta版変換、属性8行の入出力を追う例。
"""
import argparse
from pathlib import Path


from DataManager import (
    BlockRowsSerializer, BlockRowsOptions, FileService, ObjectRepository, RowsRepository,
)
from DataManager.settings_versions import SettingsDocument, create_settings_repository
from Domain.models import Settings
from examples.extended_formats import Attribute, BlockModel
from examples.versioned_rows import rows_example


def yaml_example(directory: Path):
    """ 保存先とは別のテンプレートディレクトリを構成し、同じFileServiceで扱う。
    """
    templates = directory / "templates"
    templates.mkdir(parents=True)
    (templates / "v4.yaml").write_text(
        "# Current settings\nversion: 4\nthreshold: 0  # Decision level\ngain: 1\ngenerate_output: true\nretained_values: {}\n",
        encoding="utf-8",
    )
    (templates / "v2.yaml").write_text(
        "# Legacy settings\nversion: 2\nthreashold: 0  # Legacy spelling\n",
        encoding="utf-8",
    )
    repository = create_settings_repository(
        directory / "data", template_directory=templates,
        templates_by_version={4: {".yaml": "v4.yaml"}, 2: {".yaml": "v2.yaml"}},
    )
    current = FileService(repository=repository, path="settings.yaml")
    document = SettingsDocument(Settings(threshold=15, gain=2, generate_output=False), {})
    current.save(document)
    document.settings.threshold = 20
    current.save(document, overwrite=True)
    assert "Decision level" in (directory / "data/settings.yaml").read_text(encoding="utf-8")

    legacy = FileService(repository=repository.for_version(2), path="settings_v2.yaml")
    legacy.save(document)
    raw = ObjectRepository(model=dict, base_directory=directory / "data").load("settings_v2.yaml")
    assert raw == {"version": 2, "threashold": 20}
    # 同じRepositoryのJSON出力に、YAMLテンプレートは適用しない。
    current.save_as("settings.json", document)
    assert current.load().settings.generate_output is False
    raw_repository = ObjectRepository(model=dict, base_directory=directory / "data")
    raw_repository.save("v3.json", {"version": 3, "threshold": 20, "gain": 2})
    assert repository.load("v3.json").settings.generate_output is True
    artifact = directory / "data/optional_result.txt"
    assert not artifact.exists()
    if current.load().settings.generate_output:
        artifact.write_text("generated", encoding="utf-8")
    assert not artifact.exists()
    artifact.write_text("previous result", encoding="utf-8")
    assert current.load().settings.generate_output is False
    assert repository.load("v3.json").settings.generate_output is True


def blocks_example(directory: Path):
    """ 同名列を属性の所属先へ分け、8行固定のまま読み書きする。
    """
    # このモデルではaxis_mmを使う。columnsで保存先のキー名を明示できる。
    columns = (
        ("name", "ch", "start", "length"),
        *(("name", "value", "start", "length"),) * 8,
        ("axis_mm", "length_mm"),
    )
    header_columns = (
        columns[0],
        *((f"info_name{i + 1}", f"info_value{i + 1}", "start", "length") for i in range(8)),
        columns[-1],
    )
    serializer = BlockRowsSerializer(options=BlockRowsOptions(
        delimiter=",", columns=columns, header_columns=header_columns,
        row_targets=(None,) + ("attrs",) * 8 + (None,),
    ))
    repository = RowsRepository(
        model=BlockModel, base_directory=directory, serializers_by_extension={".txt": serializer},
    )
    file = FileService(repository=repository, path="attributes.txt")
    value = BlockModel(
        name="sample", ch=1, start=100, length=200, axis_mm=10, length_mm=20,
        attrs=[Attribute(name=f"attr{i + 1}", value=i / 10, start=100 + i, length=2) for i in range(8)],
    )
    file.save([value])
    assert file.load() == [value]


def run(directory: Path):
    """ 未作成の出力先で、テンプレートと版変換・属性行の対応を確認する。
    """
    directory.mkdir(parents=True, exist_ok=False)
    yaml_example(directory / "yaml")
    rows_example(directory / "rows")
    blocks_example(directory / "blocks")
    print(f"YAML templates / metadata casts / attribute blocks: {directory.resolve()}")


def main():
    parser = argparse.ArgumentParser(description="版変換・YAMLテンプレート・属性ブロックの例")
    parser.add_argument("output", type=Path)
    run(parser.parse_args().output)


if __name__ == "__main__":
    main()
