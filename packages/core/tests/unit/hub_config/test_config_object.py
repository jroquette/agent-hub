import json
from types import MappingProxyType
from typing import Annotated, Any

import pytest
from pydantic import AfterValidator, Field, ValidationError
from pydantic_core import PydanticCustomError

from agent_hub.core.hub_config.config_object import ConfigObject, absent_by_default


def unpadded(value: str) -> str:
    if value != value.strip():
        raise PydanticCustomError(
            "padded_label", "label {label} has padding", {"label": json.dumps(value)}
        )
    return value


class Sample(ConfigObject):
    name: str
    note: str | None = absent_by_default()
    uri: str | None = absent_by_default(alias="$uri")
    code: Annotated[str, Field(pattern=r"^[a-z]+$")] = "a"
    label: Annotated[str, AfterValidator(unpadded)] = "x"


class Narrowed(Sample):
    rejected_keys = MappingProxyType({"old.key": "old.key is gone; remove it"})


NULL_MESSAGE = "null is not a value; give a value or leave the key out"


def errors_of(data: object) -> list[dict[str, Any]]:
    with pytest.raises(ValidationError) as caught:
        Sample.model_validate(data)
    return [dict(error) for error in caught.value.errors()]


def test_drops_underscore_keys_when_object_has_comment_keys() -> None:
    sample = Sample.model_validate({"_comment": "ignored", "name": "demo", "_note": {"x": 1}})

    assert sample.model_dump(exclude_none=True) == {"name": "demo", "code": "a", "label": "x"}


def test_rejects_unknown_key_when_key_not_underscore() -> None:
    with pytest.raises(ValidationError) as caught:
        Sample.model_validate({"name": "demo", "comment": "x"})

    assert [(error["loc"], error["type"]) for error in caught.value.errors()] == [
        (("comment",), "extra_forbidden")
    ]


@pytest.mark.parametrize("key", ["note", "$uri", "code"])
def test_rejects_null_when_value_is_null(key: str) -> None:
    errors = errors_of({"name": "demo", key: None})

    assert [(error["loc"], error["type"], error["msg"]) for error in errors] == [
        ((key,), "null_not_allowed", NULL_MESSAGE)
    ]


def test_rejects_null_when_required_key_is_null() -> None:
    errors = errors_of({"name": None})

    assert [(error["loc"], error["type"], error["msg"]) for error in errors] == [
        (("name",), "null_not_allowed", NULL_MESSAGE)
    ]


def test_reports_unknown_key_when_unknown_key_is_null() -> None:
    errors = errors_of({"name": "demo", "nmae": None, "note": None})

    assert sorted((error["loc"], error["type"]) for error in errors) == [
        (("nmae",), "extra_forbidden"),
        (("note",), "null_not_allowed"),
    ]


def test_keeps_error_shape_when_null_reported_alongside() -> None:
    alone = errors_of({"code": "BAD", "label": " x "})

    errors = errors_of({"code": "BAD", "label": " x ", "note": None})

    assert [(error["type"], error.get("ctx")) for error in alone] == [
        ("missing", None),
        ("string_pattern_mismatch", {"pattern": "^[a-z]+$"}),
        ("padded_label", {"label": '" x "'}),
    ]
    assert errors == [
        {"type": "null_not_allowed", "loc": ("note",), "msg": NULL_MESSAGE, "input": None},
        *alone,
    ]


def test_keeps_message_when_custom_error_text_has_placeholder() -> None:
    [alone] = errors_of({"name": "demo", "label": " {label} "})

    [_, error] = errors_of({"name": "demo", "label": " {label} ", "note": None})

    assert error["msg"] == alone["msg"] == 'label " {label} " has padding'
    assert "ctx" not in error


@pytest.mark.parametrize("value", [{}, None, "x"])
def test_reports_other_errors_when_rejected_key_given(value: object) -> None:
    with pytest.raises(ValidationError) as caught:
        Narrowed.model_validate({"old.key": value, "code": "BAD", "note": None})

    assert [(error["loc"], error["type"], error["msg"]) for error in caught.value.errors()] == [
        (("note",), "null_not_allowed", NULL_MESSAGE),
        (("old.key",), "key_not_allowed", "old.key is gone; remove it"),
        (("name",), "missing", "Field required"),
        (("code",), "string_pattern_mismatch", "String should match pattern '^[a-z]+$'"),
    ]


def test_rejects_object_when_data_not_object() -> None:
    assert [error["type"] for error in errors_of(["demo"])] == ["model_type"]


def test_declares_underscore_pattern_when_schema_exported() -> None:
    schema = Sample.model_json_schema()

    assert schema["additionalProperties"] is False
    assert schema["patternProperties"] == {"^_": {}}


def test_omits_null_branch_when_field_absent_by_default() -> None:
    properties = Sample.model_json_schema()["properties"]

    for key in ("note", "$uri"):
        assert properties[key]["type"] == "string"
        assert "anyOf" not in properties[key]
        assert "default" not in properties[key]
        assert "title" not in properties[key]
    assert Sample.model_validate({"name": "demo"}).note is None
