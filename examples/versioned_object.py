""" VersionedObjectRepositoryを組み立て、別置き雛形・現在版・旧版保存を確認する例。
"""
import argparse
from pathlib import Path

from DataManager import FileService, ObjectRepository, VersionConverter, VersionedObjectRepository
from DataManager.serializers.yaml import YamlDumpOptions, YamlSerializer
from DataManager.settings_versions import (
    SettingsDocument, decode_settings, encode_settings,
    upcast_v0_to_v1, upcast_v1_to_v2, upcast_v2_to_v3, upcast_v3_to_v4,
    downcast_v4_to_v3, downcast_v3_to_v2,
)
from Domain.models import Settings


def run(directory: Path):
    """ 形式変換・版変換・パス固定の三段を接続する。元の旧版ファイルは変更しない。
    """
    directory.mkdir(parents=True, exist_ok=False)
    templates = directory / "templates"
    templates.mkdir()
    (templates / "v4.yaml").write_text(
        "# Settings template\nretained_values: {}\nversion: 4\nthreshold: 0  # Decision level\ngain: 1\ngenerate_output: true\n",
        encoding="utf-8",
    )
    (templates / "v2.yaml").write_text("# Legacy settings\nversion: 2\nthreashold: 0\n", encoding="utf-8")
    raw = ObjectRepository(
        model=dict, base_directory=directory / "data", template_directory=templates,
        serializers_by_extension={".yaml": YamlSerializer(
            dump_options=YamlDumpOptions(footer_fields=("retained_values",)),
        )},
    )
    repository = VersionedObjectRepository(
        repository=raw,
        converter=VersionConverter(
            current_version=4,
            upcasts={0: upcast_v0_to_v1, 1: upcast_v1_to_v2, 2: upcast_v2_to_v3, 3: upcast_v3_to_v4},
            downcasts={4: downcast_v4_to_v3, 3: downcast_v3_to_v2},
        ),
        decode_current=decode_settings, encode_current=encode_settings,
        templates_by_version={4: {".yaml": "v4.yaml"}, 2: {".yaml": "v2.yaml"}},
    )
    raw.save("source_v2.yaml", {"version": 2, "threashold": 10, "operator_note": "keep"})
    source = FileService(repository=repository, path="source_v2.yaml")
    document = source.load()
    assert document.settings.threshold == 10
    document.settings.threshold = 15
    document.settings.generate_output = False
    current = FileService(repository=repository, path="current.yaml")
    current.save(document)
    current.save(document, overwrite=True)
    assert current.load() == document
    text = (directory / "data/current.yaml").read_text(encoding="utf-8")
    assert "\n\nretained_values:" in text
    assert list(raw.load("current.yaml"))[-1] == "retained_values"
    legacy = FileService(repository=repository.for_version(2), path="export_v2.yaml")
    legacy.save(document)
    assert raw.load("source_v2.yaml")["threashold"] == 10
    assert raw.load("export_v2.yaml")["threashold"] == 15
    assert isinstance(document, SettingsDocument) and isinstance(document.settings, Settings)
    print(f"Versioned object: {directory.resolve()}")


def main():
    parser = argparse.ArgumentParser(description="VersionedObjectRepositoryの単独例")
    parser.add_argument("output", type=Path)
    run(parser.parse_args().output)


if __name__ == "__main__":
    main()
