""" レビューで再現した、値の欠落・誤変換・分かりにくい例外の回帰テスト。
"""
from typing import Any

from pydantic import BaseModel
import pytest

from DataManager import BinaryWaveformSerializer, ConfigurationError, CSVDumpOptions, CsvSerializer, CustomTextSerializer, JSONLLoadOptions, JsonlSerializer, JsonSerializer, ObjectRepository, RowsRepository, SerializationError, WaveformFormatError, WaveformHeader, WaveformOptions, WaveformRepository, YamlSerializer
from DataManager.file_io import lock_file
from DataManager.model_conversion import ModelBinding


@pytest.mark.parametrize("text", [
    '{"id":1,"id":2}', '{"nested":{"id":1,"id":2}}',
    '{"items":[{"id":1,"id":2}]}',
])
def test_json_rejects_duplicate_keys_at_every_depth(text):
    with pytest.raises(SerializationError, match="重複"):
        JsonSerializer().loads(text, ModelBinding(dict))


@pytest.mark.parametrize("number", ["1e999", "-1e999", "NaN", "Infinity", "-Infinity"])
def test_json_rejects_numbers_that_cannot_be_preserved(number):
    with pytest.raises(SerializationError):
        JsonSerializer().loads('{"value":' + number + '}', ModelBinding(dict))


@pytest.mark.parametrize("value", [{"a": {1: "x"}}, {"a": [{1: "x"}]}])
@pytest.mark.parametrize("extension", ["json", "yaml", "txt"])
def test_nested_dictionary_keys_are_not_coerced_or_written(tmp_path, extension, value):
    repository = ObjectRepository[dict[str, Any]](model=dict, base_directory=tmp_path)
    with pytest.raises(SerializationError, match="キー"):
        repository.save(f"data.{extension}", value)
    assert not (tmp_path / f"data.{extension}").exists()


@pytest.mark.parametrize("text", [
    '# v1\nvalue:{"id":1,"id":2}\n', '# v1\nvalue:[{"id":1,"id":2}]\n',
    '# v1\nvalue:1e999\n',
])
def test_custom_text_uses_the_same_json_value_validation(text):
    with pytest.raises(SerializationError, match="行2"):
        CustomTextSerializer().loads(text, ModelBinding(dict))


def test_jsonl_duplicate_tag_does_not_select_last_model(tmp_path):
    class First(BaseModel):
        id: str

    class Second(BaseModel):
        id: str

    repository = RowsRepository[First | Second](model=(First, Second), base_directory=tmp_path)
    repository.save("data.jsonl", [])
    with (tmp_path / "data.jsonl").open("a") as stream:
        stream.write('{"type":"First","type":"Second","id":"x"}\n')
    with pytest.raises(SerializationError, match="重複"):
        repository.load("data.jsonl")


@pytest.mark.parametrize("text", [
    'root: &root\n  self: *root\n', 'items: &items\n  - *items\n',
])
def test_yaml_recursive_aliases_are_not_replaced_with_none(text):
    with pytest.raises(SerializationError, match="循環"):
        YamlSerializer().loads(text, ModelBinding(dict))


def test_yaml_roundtrip_preserves_aliases_scalar_values_and_mapping_boundaries():
    values = YamlSerializer().loads(
        'flag: &flag true\nother: *flag\ntext: &text "name"\ncopy: *text\n'
        'mapping: &mapping {count: 1}\nshared: *mapping\n',
        ModelBinding(dict),
    )
    assert values["flag"] is True and values["other"] is True
    assert type(values["text"]) is str and type(values["mapping"]) is dict
    assert values["shared"] == {"count": 1}

    # 同じアンカーでも、保存時に別々の項目へ更新できる。
    serializer = YamlSerializer()
    expected = {"first": {"x": 1}, "second": {"y": 2}}
    text = serializer.dumps_exact(
        expected, ModelBinding(dict),
        template_text="first: &shared {x: 0, y: 0}\nsecond: *shared\n",
    )
    assert serializer.loads(text, ModelBinding(dict)) == expected
    template = "first: 1\n\nitems:\n  - name: old\n    value: 2\n\nlast: 3\n"
    expected = {"first": 10, "items": [{"name": "new", "value": 20}], "last": 30}
    for dump in (serializer.dumps, serializer.dumps_exact):
        text = dump(expected, ModelBinding(dict), template_text=template)
        assert text.count("\n\n") == 2
        assert serializer.loads(text, ModelBinding(dict)) == expected
        assert dump(expected, ModelBinding(dict), template_text=template, existing_text=text) == text
    template = "first: 1\nitems:\n  - value: 2\n\n# Next section\nlast: 3\n"
    expected = {"first": 10, "items": [{"value": 20}], "last": 30}
    text = serializer.dumps_exact(expected, ModelBinding(dict), template_text=template)
    assert "\n\n# Next section\nlast:" in text
    assert serializer.loads(text, ModelBinding(dict)) == expected
    for indicator in ["|", "|+", "|-", ">", ">+"]:
        template = "text: " + indicator + "\n  old\n\nafter: 1\n"
        expected = {"text": "line\n\n", "after": 2}
        for dump in (serializer.dumps, serializer.dumps_exact):
            text = dump(expected, ModelBinding(dict), template_text=template)
            assert serializer.loads(text, ModelBinding(dict)) == expected


def test_yaml_rejects_cyclic_existing_document_without_overwriting(tmp_path):
    target = tmp_path / "data.yaml"
    original = b"root: &root\n  self: *root\n"
    target.write_bytes(original)
    with pytest.raises(SerializationError, match="循環"):
        ObjectRepository[dict[str, Any]](model=dict, base_directory=tmp_path).save("data.yaml", {"a": 1}, overwrite=True)
    assert target.read_bytes() == original


def test_empty_recursive_csv_requires_explicit_columns(tmp_path):
    class Node(BaseModel):
        name: str = ""
        child: "Node | None" = None

    repository = RowsRepository(model=Node, base_directory=tmp_path)
    with pytest.raises(ConfigurationError, match="再帰"):
        repository.save("recursive.csv", [])

    configured = RowsRepository(
        model=Node, base_directory=tmp_path,
        serializers_by_extension={".csv": CsvSerializer(dump_options=CSVDumpOptions(columns=("name",)))},
    )
    configured.save("recursive.csv", [])
    assert configured.load("recursive.csv") == []


@pytest.mark.parametrize("model", [42, [], (dict, []), (), (dict, dict), str])
def test_invalid_model_configuration_has_domain_error(model):
    with pytest.raises(ConfigurationError):
        ModelBinding(model)


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), float("-inf"), -1.0])
@pytest.mark.parametrize("repository_type", [ObjectRepository, RowsRepository, WaveformRepository])
def test_invalid_lock_timeouts_are_rejected_without_io(tmp_path, timeout, repository_type):
    arguments = {"base_directory": tmp_path / "not_created", "lock_timeout_seconds": timeout}
    if repository_type is not WaveformRepository:
        arguments["model"] = dict
    with pytest.raises(ConfigurationError, match="有限"):
        repository_type(**arguments)
    assert not (tmp_path / "not_created").exists()


def test_direct_lock_also_rejects_invalid_timeout_before_mkdir(tmp_path):
    with pytest.raises(ConfigurationError):
        with lock_file(tmp_path / "not_created/data.json", timeout_seconds=float("nan")):
            pytest.fail("the lock must not be entered")
    assert not (tmp_path / "not_created").exists()


@pytest.mark.parametrize("result", [
    None, {"channels": [0]}, WaveformHeader(values=None, data_offset=0),
    WaveformHeader(values={1: "invalid"}, data_offset=0),
])
def test_invalid_header_results_have_waveform_error(result):
    options = WaveformOptions(header_reader=lambda stream: result)
    with pytest.raises(WaveformFormatError):
        BinaryWaveformSerializer(options=options).load(b"\x00" * 4)


def test_mixed_model_binding_requires_an_explicit_selected_class():
    class First(BaseModel):
        id: str

    class Second(BaseModel):
        id: str

    with pytest.raises(ConfigurationError, match="選択済み"):
        ModelBinding[First | Second]((First, Second)).restore_value({"id": "x"})


def test_object_repository_does_not_accept_mixed_types_from_untyped_configuration(tmp_path):
    class First(BaseModel):
        id: str

    class Second(BaseModel):
        id: str

    with pytest.raises(ConfigurationError, match="単一"):
        ObjectRepository(model=(First, Second), base_directory=tmp_path)


@pytest.mark.parametrize("metadata", ["optional", None])
def test_unknown_metadata_mode_is_not_silently_ignored(metadata):
    with pytest.raises(ConfigurationError, match="metadata"):
        JsonlSerializer(load_options=JSONLLoadOptions(metadata=metadata))
