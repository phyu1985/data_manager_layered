from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, computed_field, create_model
import portalocker
import pytest

from DataManager import (
    ConfigurationError, JSONLDumpOptions, JSONLLoadOptions, JsonDumpOptions,
    JsonlSerializer, JsonSerializer, ObjectRepository, RowsRepository,
    SerializationError,
)
from DataManager.file_io import lock_file


class User(BaseModel):
    id: str
    name: str = ""


class Event(BaseModel):
    id: str
    message: str


def create_mixed_repository(base_directory: Path, **repository_options: Any) -> RowsRepository[User | Event]:
    return RowsRepository[User | Event](model=(User, Event), base_directory=base_directory, **repository_options)


def test_object_roundtrip_preserves_nested_values(tmp_path):
    class Nested(BaseModel):
        users: list[User]
        optional: str | None

    repository = ObjectRepository(model=Nested, base_directory=tmp_path)
    value = Nested(users=[User(id="日本語")], optional=None)
    repository.save("nested/user.JSON", value)
    result = repository.load("nested/user.JSON")
    assert result == value and type(result.users[0]) is User
    assert "日本語" in (tmp_path / "nested/user.JSON").read_text(encoding="utf-8")


def test_object_dict_mode_and_top_level_validation(tmp_path):
    repository = ObjectRepository[dict[str, Any]](model=dict, base_directory=tmp_path)
    value = {"type": "business", "items": [{"x": 1}], "empty": "", "none": None}
    repository.save("data.json", value)
    assert repository.load("data.json") == value
    (tmp_path / "data.json").write_text("[]", encoding="utf-8")
    with pytest.raises(SerializationError, match="トップレベル"):
        repository.load("data.json")


def test_mixed_roundtrip_builds_real_instances_and_flat_tag(tmp_path):
    repository = create_mixed_repository(tmp_path)
    values = [User(id="u1"), Event(id="e1", message="start")]
    before = [value.model_dump() for value in values]
    repository.save("mixed.jsonl", values)
    raw = [json.loads(line) for line in (tmp_path / "mixed.jsonl").read_text().splitlines()]
    assert raw[1] == {"type": "User", "id": "u1", "name": ""}
    assert raw[2] == {"type": "Event", "id": "e1", "message": "start"}
    result = repository.load("mixed.jsonl")
    assert result == values
    assert [type(row) for row in result] == [User, Event]
    assert all("type" not in row.model_dump() for row in result)
    assert [value.model_dump() for value in values] == before


def test_single_model_has_no_row_tag(tmp_path):
    repository = RowsRepository(model=User, base_directory=tmp_path)
    repository.save("single.jsonl", [User(id="u")])
    body = json.loads((tmp_path / "single.jsonl").read_text().splitlines()[1])
    assert body == {"id": "u", "name": ""}
    assert type(repository.load("single.jsonl")[0]) is User


def test_dict_rows_preserve_empty_objects_and_business_meta_keys(tmp_path):
    repository = RowsRepository[dict[str, Any]](model=dict, base_directory=tmp_path)
    values = [{}, {"blank": "", "none": None}, {"__meta__": {"a": 1}}]
    repository.save("dicts.jsonl", values)
    assert repository.load("dicts.jsonl") == values


def test_dict_mode_rejects_mixed_file_without_losing_tags(tmp_path):
    create_mixed_repository(tmp_path).save("mixed.jsonl", [User(id="u")])
    repository = RowsRepository[dict[str, Any]](model=dict, base_directory=tmp_path)
    with pytest.raises(SerializationError, match="メタ情報"):
        repository.load("mixed.jsonl")


def test_tag_collision_is_rejected_and_key_can_be_changed(tmp_path):
    class Business(BaseModel):
        type: str

    with pytest.raises(ConfigurationError, match="衝突"):
        RowsRepository[Business | Event](model=(Business, Event), base_directory=tmp_path)
    repository = RowsRepository[Business | Event](
        model=(Business, Event), base_directory=tmp_path,
        serializers_by_extension={".jsonl": JsonlSerializer(tag_field="record_kind")},
    )
    values = [Business(type="business"), Event(id="e", message="ok")]
    repository.save("business.jsonl", values)
    assert repository.load("business.jsonl") == values
    # 単一モデルではtagを追加しないのでtypeを業務フィールドとして使える。
    single = RowsRepository(model=Business, base_directory=tmp_path)
    single.save("single.jsonl", [values[0]])
    assert single.load("single.jsonl")[0].type == "business"


def test_alias_collision_is_rejected(tmp_path):
    class Aliased(BaseModel):
        code: str = Field(serialization_alias="type")

    with pytest.raises(ConfigurationError, match="衝突"):
        RowsRepository[Aliased | Event](
            model=(Aliased, Event), base_directory=tmp_path,
            serializers_by_extension={".jsonl": JsonlSerializer(
                dump_options=JSONLDumpOptions(by_alias=True),
            )},
        )


def test_computed_tag_key_is_rejected_before_overwrite(tmp_path):
    class Computed(BaseModel):
        @computed_field
        @property
        def type(self) -> str:
            return "business"

    repository = RowsRepository[Computed | Event](model=(Computed, Event), base_directory=tmp_path)
    with pytest.raises(SerializationError, match="衝突"):
        repository.save("collision.jsonl", [Computed()])
    assert not (tmp_path / "collision.jsonl").exists()


def test_external_dictionary_meta_key_is_not_guessed_as_header(tmp_path):
    path = tmp_path / "external.jsonl"
    path.write_text('{"__meta__":{"business":true}}\n', encoding="utf-8")
    repository = RowsRepository[dict[str, Any]](
        model=dict, base_directory=tmp_path,
        serializers_by_extension={".jsonl": JsonlSerializer(load_options=JSONLLoadOptions(metadata="absent"))},
    )
    assert repository.load("external.jsonl") == [{"__meta__": {"business": True}}]


def test_bool_schema_version_is_not_accepted_as_one(tmp_path):
    repository = RowsRepository(model=User, base_directory=tmp_path)
    repository.save("version.jsonl", [])
    path = tmp_path / "version.jsonl"
    header = json.loads(path.read_text())
    header["__meta__"]["schema_version"] = True
    path.write_text(json.dumps(header) + "\n")
    with pytest.raises(SerializationError, match="メタ情報"):
        repository.load("version.jsonl")


def test_non_string_dictionary_keys_are_not_silently_changed(tmp_path):
    repository = ObjectRepository[dict[str, Any]](model=dict, base_directory=tmp_path)
    with pytest.raises(SerializationError, match="キー"):
        repository.save("keys.json", {1: "value"})


def test_missing_file_does_not_become_empty_rows(tmp_path):
    with pytest.raises(FileNotFoundError):
        RowsRepository(model=User, base_directory=tmp_path).load("missing.jsonl")


def test_alias_policy_is_owned_by_model(tmp_path):
    class Aliased(BaseModel):
        model_config = ConfigDict(populate_by_name=True)
        name: str = Field(alias="display_name")

    default = ObjectRepository(model=Aliased, base_directory=tmp_path)
    default.save("default.json", Aliased(name="A"))
    assert json.loads((tmp_path / "default.json").read_text()) == {"name": "A"}
    assert default.load("default.json").name == "A"
    aliased = ObjectRepository(
        model=Aliased, base_directory=tmp_path,
        serializers_by_extension={".json": JsonSerializer(dump_options=JsonDumpOptions(by_alias=True))},
    )
    aliased.save("alias.json", Aliased(name="A"))
    assert json.loads((tmp_path / "alias.json").read_text()) == {"display_name": "A"}
    assert aliased.load("alias.json").name == "A"


def test_invalid_payload_is_validated_without_casting_it_into_model(tmp_path):
    repository = create_mixed_repository(tmp_path)
    repository.save("bad.jsonl", [])
    with (tmp_path / "bad.jsonl").open("a") as stream:
        stream.write('{"type":"Event","id":"e"}\n')
    with pytest.raises(SerializationError, match="message"):
        repository.load("bad.jsonl")


@pytest.mark.parametrize("tag", ["Unknown", None, 3])
def test_unknown_or_invalid_tag_is_rejected(tmp_path, tag):
    repository = create_mixed_repository(tmp_path)
    repository.save("bad.jsonl", [])
    with (tmp_path / "bad.jsonl").open("a") as stream:
        stream.write(json.dumps({"type": tag, "id": "u"}) + "\n")
    with pytest.raises(SerializationError, match="型名"):
        repository.load("bad.jsonl")


def test_duplicate_names_need_explicit_fixed_tags(tmp_path):
    first = create_model("Same", x=(int, ...))
    second = create_model("Same", y=(str, ...))
    with pytest.raises(ConfigurationError, match="重複"):
        RowsRepository[BaseModel](model=(first, second), base_directory=tmp_path)
    repository = RowsRepository[BaseModel](
        model=(first, second), base_directory=tmp_path,
        serializers_by_extension={".jsonl": JsonlSerializer.for_models(model_tags={first: 'first', second: 'second'})},
    )
    repository.save("names.jsonl", [first(x=1), second(y="a")])
    assert [type(row) for row in repository.load("names.jsonl")] == [first, second]


def test_fixed_tag_survives_class_rename(tmp_path):
    old = RowsRepository(
        model=User, base_directory=tmp_path,
        serializers_by_extension={".jsonl": JsonlSerializer.for_models(model_tags={User: 'user'})},
    )
    old.save("users.jsonl", [User(id="u")])

    class RenamedUser(BaseModel):
        id: str
        name: str = ""

    new = RowsRepository(
        model=RenamedUser, base_directory=tmp_path,
        serializers_by_extension={".jsonl": JsonlSerializer.for_models(model_tags={RenamedUser: 'user'})},
    )
    assert type(new.load("users.jsonl")[0]) is RenamedUser


def test_save_rewrites_meta_and_empty_save_keeps_header(tmp_path):
    repository = create_mixed_repository(tmp_path)
    repository.save("events.jsonl", [User(id="old")])
    repository.save("events.jsonl", [Event(id="new", message="ok")], overwrite=True)
    lines = (tmp_path / "events.jsonl").read_text().splitlines()
    assert len(lines) == 2 and "__meta__" in json.loads(lines[0])
    assert repository.load("events.jsonl") == [Event(id="new", message="ok")]
    repository.save("events.jsonl", [], overwrite=True)
    assert len((tmp_path / "events.jsonl").read_text().splitlines()) == 1
    assert repository.load("events.jsonl") == []


def test_append_creates_and_preserves_one_header(tmp_path):
    repository = create_mixed_repository(tmp_path)
    repository.append_jsonl("events.jsonl", iter([User(id="u")]))
    header = (tmp_path / "events.jsonl").read_bytes().splitlines()[0]
    repository.append_jsonl("events.jsonl", [Event(id="e", message="ok")])
    lines = (tmp_path / "events.jsonl").read_bytes().splitlines()
    assert len(lines) == 3 and lines[0] == header
    assert [type(row) for row in repository.load("events.jsonl")] == [User, Event]


@pytest.mark.parametrize("suffix", [b"", b"\n", b"\n\n  ", b"\r\n\r\n"])
def test_append_handles_missing_newline_and_trailing_blank_lines(tmp_path, suffix):
    repository = create_mixed_repository(tmp_path)
    repository.save("events.jsonl", [User(id="u")])
    path = tmp_path / "events.jsonl"
    path.write_bytes(path.read_bytes().rstrip(b"\n") + suffix)
    repository.append_jsonl("events.jsonl", [Event(id="e", message="ok")])
    assert len(repository.load("events.jsonl")) == 2


def test_append_after_header_only_and_long_tail(tmp_path):
    repository = create_mixed_repository(tmp_path)
    repository.save("events.jsonl", [], overwrite=True)
    repository.append_jsonl("events.jsonl", [Event(id="long", message="x" * 20000)])
    repository.append_jsonl("events.jsonl", [User(id="last")])
    assert len(repository.load("events.jsonl")) == 2


def test_invalid_append_batch_does_not_partially_write(tmp_path):
    repository = create_mixed_repository(tmp_path)
    repository.save("events.jsonl", [User(id="original")])
    path = tmp_path / "events.jsonl"
    before = path.read_bytes()
    with pytest.raises(SerializationError, match="型"):
        repository.append_jsonl("events.jsonl", [User(id="valid"), {"id": "invalid"}])
    assert path.read_bytes() == before


@pytest.mark.parametrize("tail", [b'{"type":', b'{"type":"Unknown","id":"x"}', b'\xff'])
def test_partial_or_invalid_tail_is_rejected_without_modification(tmp_path, tail):
    repository = create_mixed_repository(tmp_path)
    repository.save("events.jsonl", [User(id="u")])
    path = tmp_path / "events.jsonl"
    path.write_bytes(path.read_bytes() + tail)
    before = path.read_bytes()
    with pytest.raises(SerializationError, match="末尾"):
        repository.append_jsonl("events.jsonl", [User(id="next")])
    assert path.read_bytes() == before


def test_append_rejects_metadata_mismatch(tmp_path):
    RowsRepository(model=User, base_directory=tmp_path).save("events.jsonl", [User(id="u")])
    path = tmp_path / "events.jsonl"
    before = path.read_bytes()
    with pytest.raises(SerializationError, match="メタ情報"):
        create_mixed_repository(tmp_path).append_jsonl("events.jsonl", [User(id="u")])
    assert path.read_bytes() == before


def test_absent_metadata_is_explicit_and_cannot_append(tmp_path):
    repository = RowsRepository(model=User, base_directory=tmp_path)
    path = tmp_path / "external.jsonl"
    path.write_text('{"id":"u"}\n', encoding="utf-8")
    with pytest.raises(SerializationError):
        repository.load("external.jsonl")
    external = RowsRepository(
        model=User, base_directory=tmp_path,
        serializers_by_extension={".jsonl": JsonlSerializer(
            load_options=JSONLLoadOptions(metadata="absent"),
        )},
    )
    assert external.load("external.jsonl") == [User(id="u")]
    with pytest.raises(ConfigurationError):
        external.append_jsonl("external.jsonl", [User(id="next")])


def test_metadata_required_even_for_empty_file(tmp_path):
    (tmp_path / "empty.jsonl").write_text("")
    with pytest.raises(SerializationError, match="メタ行"):
        RowsRepository(model=User, base_directory=tmp_path).load("empty.jsonl")


def test_empty_append_does_not_create_file(tmp_path):
    RowsRepository(model=User, base_directory=tmp_path).append_jsonl("absent.jsonl", [])
    assert not (tmp_path / "absent.jsonl").exists()


def test_lock_failure_does_not_fall_back(tmp_path):
    repository = ObjectRepository(model=User, base_directory=tmp_path, lock_timeout_seconds=0)
    path = tmp_path / "locked.json"
    with lock_file(path, timeout_seconds=0):
        with pytest.raises(portalocker.exceptions.LockException):
            repository.save("locked.json", User(id="u"))
    assert not path.exists()


def test_atomic_replace_failure_preserves_original_and_cleans_temp(tmp_path, monkeypatch):
    repository = ObjectRepository(model=User, base_directory=tmp_path)
    repository.save("user.json", User(id="old"))

    def fail(*args):
        raise OSError("replace failed")

    monkeypatch.setattr("DataManager.file_io.os.replace", fail)
    with pytest.raises(OSError, match="replace failed"):
        repository.save("user.json", User(id="new"), overwrite=True)
    assert repository.load("user.json").id == "old"
    assert list(tmp_path.glob("*.tmp")) == []


def test_concurrent_new_file_append_has_one_header_and_all_rows(tmp_path):
    repository = RowsRepository[dict[str, Any]](model=dict, base_directory=tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda index: repository.append_jsonl("race.jsonl", [{"id": index}]), range(20)))
    result = repository.load("race.jsonl")
    assert sorted(row["id"] for row in result) == list(range(20))
    assert len((tmp_path / "race.jsonl").read_text().splitlines()) == 21


def test_two_processes_append_without_lost_rows(tmp_path):
    source = Path(__file__).resolve().parents[1]
    code = (
        "import sys; from pathlib import Path; from DataManager import RowsRepository; "
        "repository = RowsRepository(model=dict, base_directory=Path(sys.argv[1])); "
        "[repository.append_jsonl('process.jsonl', [{'id': sys.argv[2] + str(i)}]) for i in range(8)]"
    )
    processes = [subprocess.Popen(
        [sys.executable, "-c", code, str(tmp_path), prefix],
        env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
        cwd=source,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ) for prefix in ("a", "b")]
    for process in processes:
        standard_output, standard_error = process.communicate(timeout=30)
        assert process.returncode == 0, (standard_output, standard_error)
    rows = RowsRepository[dict[str, Any]](model=dict, base_directory=tmp_path).load("process.jsonl")
    assert {row["id"] for row in rows} == {f"{prefix}{i}" for prefix in ("a", "b") for i in range(8)}
    assert len(rows) == 16


def test_unknown_fields_follow_model_validation_policy(tmp_path):
    class Strict(BaseModel):
        model_config = ConfigDict(extra="forbid")
        id: str

    (tmp_path / "strict.json").write_text('{"id":"u","unknown":1}')
    with pytest.raises(SerializationError):
        ObjectRepository(model=Strict, base_directory=tmp_path).load("strict.json")


def test_unregistered_subclass_and_unsupported_format_are_rejected(tmp_path):
    class SpecialUser(User):
        extra: str

    with pytest.raises(SerializationError):
        ObjectRepository(model=User, base_directory=tmp_path).save("user.json", SpecialUser(id="u", extra="x"))
    with pytest.raises(ConfigurationError, match="拡張子"):
        RowsRepository(model=User, base_directory=tmp_path).save("users.unsupported", [])


@pytest.mark.parametrize("value", [float("nan"), object()])
def test_invalid_json_value_does_not_create_file(tmp_path, value):
    repository = ObjectRepository[dict[str, Any]](model=dict, base_directory=tmp_path)
    with pytest.raises(SerializationError):
        repository.save("invalid.json", {"value": value})
    assert not (tmp_path / "invalid.json").exists()
