""" 文書・一覧形式の往復と、保存時のデータ欠落・競合を検証する。
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
import pytest

from data_manager import (
    ConfigurationError, CSVDumpOptions, CSVLoadOptions, CsvSerializer,
    CustomTextOptions, CustomTextSerializer, ObjectRepository, RowsRepository,
    SerializationError,
)


class Details(BaseModel):
    count: int
    enabled: bool


class Settings(BaseModel):
    name: str
    details: Details
    optional: str | None = None
    created: date = date(2026, 10, 31)


@pytest.mark.parametrize("extension", ["json", "yaml", "yml", "txt"])
def test_object_formats_restore_real_nested_models(tmp_path, extension):
    repository = ObjectRepository(model=Settings, base_directory=tmp_path)
    value = Settings(name="日本語:テスト", details=Details(count=3, enabled=True))
    repository.save(f"settings.{extension}", value)
    restored = repository.load(f"settings.{extension}")
    assert restored == value
    assert type(restored.details) is Details


@pytest.mark.parametrize("extension", ["json", "yaml", "txt"])
def test_document_datas_keep_types(tmp_path, extension):
    repository = ObjectRepository[dict[str, Any]](model=dict, base_directory=tmp_path)
    value = {"empty": "", "number_text": "001", "null": None, "flag": False,
             "array": [1, "x\ny", None], "nested": {"empty_map": {}}}
    repository.save(f"values.{extension}", value)
    assert repository.load(f"values.{extension}") == value


def test_yaml_merge_preserves_comments_quotes_and_key_order(tmp_path):
    template_directory = tmp_path / "templates"
    template_directory.mkdir()
    template = template_directory / "base.yaml"
    template.write_text('# template heading\nname: "template" # template name\n'
                        'details:\n  count: 1 # template count\n  enabled: true\n'
                        'template_only: keep # template extra\n', encoding="utf-8")
    target = tmp_path / "settings.yaml"
    target.write_text('# existing heading\nname: "existing" # existing name\n'
                      'details:\n  count: 2 # existing count\n  enabled: false\n'
                      'existing_only: keep # existing extra\n', encoding="utf-8")
    original_template = template.read_bytes()
    repository = ObjectRepository(model=Settings, base_directory=tmp_path, template_directory=template_directory)
    value = Settings(name="model", details=Details(count=9, enabled=True))
    repository.save("settings.yaml", value, template_name="base.yaml", overwrite=True)

    text = target.read_text(encoding="utf-8")
    assert '# existing heading' in text and '# existing name' in text
    assert '# existing count' in text and '# template extra' in text and '# existing extra' in text
    assert 'name: "model"' in text
    assert text.index("name:") < text.index("details:") < text.index("template_only:") < text.index("existing_only:")
    assert repository.load("settings.yaml") == value
    assert template.read_bytes() == original_template


def test_yaml_concurrent_merges_do_not_lose_independent_keys(tmp_path):
    repository = ObjectRepository[dict[str, Any]](model=dict, base_directory=tmp_path)
    with ThreadPoolExecutor(max_workers=4) as workers:
        list(workers.map(lambda index: repository.save("shared.yaml", {f"key{index}": index}, overwrite=True), range(16)))
    assert repository.load("shared.yaml") == {f"key{index}": index for index in range(16)}


@pytest.mark.parametrize("template_name", ["../outside.yaml", "/outside.yaml"])
def test_template_directory_rejects_escape(tmp_path, template_name):
    repository = ObjectRepository[dict[str, Any]](
        model=dict, base_directory=tmp_path, template_directory=tmp_path / "templates",
    )
    with pytest.raises(ConfigurationError):
        repository.save("data.yaml", {}, template_name=template_name)


def test_template_cannot_be_overwritten_or_used_for_json(tmp_path):
    repository = ObjectRepository[dict[str, Any]](
        model=dict, base_directory=tmp_path, template_directory=tmp_path,
    )
    with pytest.raises(ConfigurationError, match="別のパス"):
        repository.save("same.yaml", {}, template_name="same.yaml")
    with pytest.raises(ConfigurationError, match="合成"):
        repository.save("data.json", {}, template_name="base.yaml")


@pytest.mark.parametrize("text", ["- 1\n- 2\n", "a: 1\na: 2\n", "1: value\n", "a: [\n"])
def test_invalid_yaml_is_not_silently_accepted(tmp_path, text):
    (tmp_path / "invalid.yaml").write_text(text)
    with pytest.raises(SerializationError):
        ObjectRepository[dict[str, Any]](model=dict, base_directory=tmp_path).load("invalid.yaml")


def test_invalid_yaml_save_preserves_original(tmp_path):
    repository = ObjectRepository[dict[str, Any]](model=dict, base_directory=tmp_path)
    repository.save("data.yaml", {"a": 1})
    path = tmp_path / "data.yaml"
    original = path.read_bytes()
    with pytest.raises(SerializationError):
        repository.save("data.yaml", {"a": object()}, overwrite=True)
    assert path.read_bytes() == original


def test_yaml_dictionary_does_not_return_editing_nodes(tmp_path):
    (tmp_path / "data.yaml").write_text('a:\n  b: [1, 2]\n')
    value = ObjectRepository[dict[str, Any]](model=dict, base_directory=tmp_path).load("data.yaml")
    assert type(value) is dict and type(value["a"]) is dict and type(value["a"]["b"]) is list


def test_csv_nested_model_and_nullable_fields(tmp_path):
    repository = RowsRepository(model=Settings, base_directory=tmp_path)
    value = Settings(name="A,\"B\"\nC", details=Details(count=3, enabled=False))
    repository.save("settings.csv", [value])
    assert repository.load("settings.csv") == [value]
    assert "details.count" in (tmp_path / "settings.csv").read_text()


def test_csv_collects_columns_from_all_rows(tmp_path):
    repository = RowsRepository[dict[str, Any]](model=dict, base_directory=tmp_path)
    repository.save("dicts.csv", [{"a": "first"}, {"b": "second"}])
    assert repository.load("dicts.csv") == [{"a": "first", "b": None}, {"a": None, "b": "second"}]


def test_empty_typed_csv_has_header(tmp_path):
    repository = RowsRepository(model=Settings, base_directory=tmp_path)
    repository.save("empty.csv", [])
    assert (tmp_path / "empty.csv").read_text().splitlines() == ["name,details.count,details.enabled,optional,created"]
    assert repository.load("empty.csv") == []


def test_empty_dict_csv_requires_columns(tmp_path):
    repository = RowsRepository[dict[str, Any]](model=dict, base_directory=tmp_path)
    with pytest.raises(SerializationError):
        repository.save("empty.csv", [])
    configured = RowsRepository[dict[str, Any]](
        model=dict, base_directory=tmp_path,
        serializers_by_extension={".csv": CsvSerializer(dump_options=CSVDumpOptions(columns=("id", "count")))},
    )
    configured.save("empty.csv", [])
    assert (tmp_path / "empty.csv").read_text() == "id,count\n"


def test_csv_can_keep_empty_string_and_headerless_columns(tmp_path):
    serializer = CsvSerializer(
        dump_options=CSVDumpOptions(include_header=False, columns=("name", "value")),
        load_options=CSVLoadOptions(has_header=False, columns=("name", "value"), empty_as_none=False),
        encoding="utf-8-sig",
    )
    repository = RowsRepository[dict[str, Any]](
        model=dict, base_directory=tmp_path, serializers_by_extension={".csv": serializer},
    )
    repository.save("no_header.csv", [{"name": "日本語", "value": ""}])
    assert repository.load("no_header.csv") == [{"name": "日本語", "value": ""}]
    assert (tmp_path / "no_header.csv").read_bytes().startswith(b"\xef\xbb\xbf")


@pytest.mark.parametrize("text", ["a,a\n1,2\n", "a,a.b\n1,2\n", "a,b\n1,2,3\n", 'a\n"unclosed\n', ",a\n1,2\n"])
def test_csv_invalid_columns_and_records_are_errors(tmp_path, text):
    (tmp_path / "bad.csv").write_text(text)
    repository = RowsRepository[dict[str, Any]](model=dict, base_directory=tmp_path)
    with pytest.raises(SerializationError):
        repository.load("bad.csv")


@pytest.mark.parametrize("value", [{"items": [1, 2]}, {"nested": {}}, {"a.b": 1}, {"a": 1, "a.b": 2}])
def test_csv_does_not_stringify_or_drop_unsupported_structures(tmp_path, value):
    repository = RowsRepository[dict[str, Any]](model=dict, base_directory=tmp_path)
    with pytest.raises(SerializationError):
        repository.save("bad.csv", [value])
    assert not (tmp_path / "bad.csv").exists()


def test_csv_explicit_columns_do_not_silently_drop_values(tmp_path):
    repository = RowsRepository[dict[str, Any]](
        model=dict, base_directory=tmp_path,
        serializers_by_extension={".csv": CsvSerializer(dump_options=CSVDumpOptions(columns=("a",)))},
    )
    with pytest.raises(SerializationError, match="含まれない"):
        repository.save("bad.csv", [{"a": 1, "b": 2}])


def test_csv_has_no_tag_even_for_business_type_field(tmp_path):
    class Business(BaseModel):
        type: str

    repository = RowsRepository(model=Business, base_directory=tmp_path)
    repository.save("business.csv", [Business(type="business")])
    assert repository.load("business.csv") == [Business(type="business")]


def test_csv_mixed_model_configuration_is_rejected(tmp_path):
    with pytest.raises(ConfigurationError, match="単一"):
        RowsRepository[Settings | Details](
            model=(Settings, Details), base_directory=tmp_path,
            serializers_by_extension={".csv": CsvSerializer()},
        )


def test_custom_text_separator_is_shared_by_dump_and_load(tmp_path):
    repository = ObjectRepository[dict[str, Any]](
        model=dict, base_directory=tmp_path,
        serializers_by_extension={".txt": CustomTextSerializer(options=CustomTextOptions(separator="/"))},
    )
    value = {"nested": {"count": 3}, "text": "a:b\nc", "empty": {}}
    repository.save("value.txt", value, overwrite=True)
    assert 'nested/count:3' in (tmp_path / "value.txt").read_text()
    assert repository.load("value.txt") == value


@pytest.mark.parametrize("text", ["# v0\na:1\n", "# v1\na:1\na:2\n", "# v1\na:bare\n", "# v1\na:1\na.b:2\n", "# v1\na:NaN\n", "# v1\nbad\n"])
def test_custom_text_rejects_ambiguous_or_invalid_records(tmp_path, text):
    (tmp_path / "bad.txt").write_text(text)
    with pytest.raises(SerializationError):
        ObjectRepository[dict[str, Any]](model=dict, base_directory=tmp_path).load("bad.txt")


def test_custom_empty_dict_and_nested_arrays(tmp_path):
    repository = ObjectRepository[dict[str, Any]](model=dict, base_directory=tmp_path)
    for value in ({}, {"items": [{"name": "a"}, None], "flag": True}):
        repository.save("value.txt", value, overwrite=True)
        assert repository.load("value.txt") == value


def test_csv_alias_follows_model_input_rules(tmp_path):
    class Aliased(BaseModel):
        model_config = ConfigDict(populate_by_name=True)
        identifier: int = Field(alias="id")

    repository = RowsRepository(
        model=Aliased, base_directory=tmp_path,
        serializers_by_extension={".csv": CsvSerializer(dump_options=CSVDumpOptions(by_alias=True))},
    )
    repository.save("alias.csv", [Aliased(identifier=1)])
    assert (tmp_path / "alias.csv").read_text().startswith("id\n")
    assert repository.load("alias.csv") == [Aliased(identifier=1)]


@pytest.mark.parametrize("value", [object(), {1, 2}])
def test_csv_rejects_arbitrary_object_cells(tmp_path, value):
    repository = RowsRepository[dict[str, Any]](model=dict, base_directory=tmp_path)
    with pytest.raises(SerializationError, match="オブジェクト"):
        repository.save("bad.csv", [{"value": value}])


def test_csv_nullable_empty_column_inference_and_explicit_list_error(tmp_path):
    class Nullable(BaseModel):
        value: int | None

    repository = RowsRepository(model=Nullable, base_directory=tmp_path)
    repository.save("empty.csv", [])
    assert (tmp_path / "empty.csv").read_text() == "value\n"

    class ArrayModel(BaseModel):
        values: list[int]

    with pytest.raises(ConfigurationError, match="columns"):
        RowsRepository(model=ArrayModel, base_directory=tmp_path).save("array.csv", [])


@pytest.mark.parametrize("extension", ["txt", "yaml"])
def test_cyclic_dictionary_is_rejected_before_file_creation(tmp_path, extension):
    value = {}
    value["cycle"] = value
    repository = ObjectRepository[dict[str, Any]](model=dict, base_directory=tmp_path)
    with pytest.raises(SerializationError, match="循環"):
        repository.save(f"cycle.{extension}", value)
    assert not (tmp_path / f"cycle.{extension}").exists()


def test_yaml_does_not_return_tagged_editing_values(tmp_path):
    (tmp_path / "tag.yaml").write_text("value: !custom text\n")
    with pytest.raises(SerializationError, match="型"):
        ObjectRepository[dict[str, Any]](model=dict, base_directory=tmp_path).load("tag.yaml")
