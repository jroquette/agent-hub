from typing import Any

import pytest
from pydantic import ValidationError
from pydantic_core import InitErrorDetails, PydanticCustomError

from agent_hub.core.hub_config.doctor_rules import DoctorRules
from agent_hub.core.hub_config.document_check import check_hub_document
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ConfigProblem
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.core.testing.platform_repository_cases import SECRET_PARTS

RUNNING = "0.3.1"
MAX_LINES_PATH = 'doctor.rules["instructions.size"].max_lines'


def a_pinned_document() -> dict[str, Any]:
    document = a_hub_document()
    document["platform"]["version"] = RUNNING
    return document


def with_max_lines(max_lines: dict[str, object]) -> dict[str, Any]:
    document = a_pinned_document()
    document["doctor"] = {"rules": {"instructions.size": {"max_lines": max_lines}}}
    return document


def in_first_repo(key: str, value: object) -> dict[str, Any]:
    document = a_pinned_document()
    document["repos"][0][key] = value
    return document


def problems_of(document: object) -> tuple[ConfigProblem, ...]:
    result = check_hub_document(document, running_version=RUNNING)
    assert isinstance(result, tuple)
    return result


def test_returns_config_when_document_valid_and_versions_supported() -> None:
    document = a_pinned_document()

    assert check_hub_document(document, running_version=RUNNING) == HubConfig.model_validate(
        document
    )


def test_reports_only_pin_when_pin_differs_and_fields_invalid() -> None:
    document = a_pinned_document()
    document["platform"]["version"] = "9.9.9"
    document["schema_version"] = 2
    document["project"]["name"] = "Not Kebab"

    (problem,) = problems_of(document)

    assert problem.path == "platform.version"


def test_reports_only_schema_version_when_it_differs_and_fields_invalid() -> None:
    document = a_pinned_document()
    document["schema_version"] = 2
    document["unknown"] = True
    document["project"]["name"] = "Not Kebab"

    (problem,) = problems_of(document)

    assert problem.path == "schema_version"


def test_lists_one_problem_per_error_when_validation_fails() -> None:
    document = a_pinned_document()
    document["project"]["name"] = "Not Kebab"
    document["a\nb"] = "c\nd"
    document["repos"][0]["dir"] = "a/b"

    problems = problems_of(document)

    assert {problem.path for problem in problems} == {"project.name", '["a\\nb"]', "repos[0].dir"}
    for problem in problems:
        assert problem.message
        assert len(problem.message.splitlines()) == 1


def test_escapes_line_breaks_when_message_holds_them(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_forged_error(document: object) -> HubConfig:
        raise ValidationError.from_exception_data(
            "HubConfig",
            [
                InitErrorDetails(
                    type=PydanticCustomError("forged", "first\nhub.json: $: forged x\ty"),
                    loc=("project", "name"),
                    input=document,
                )
            ],
        )

    monkeypatch.setattr(HubConfig, "model_validate", raise_forged_error)

    problems = problems_of(a_pinned_document())

    assert problems == (ConfigProblem("project.name", "first\\nhub.json: $: forged\\u2028x\\ty"),)


@pytest.mark.parametrize(
    ("loc", "path"),
    [
        (("repos", 5, "x", "[key]"), "repos[5].x"),
        (("project", "name", "x", "[key]"), "project.name.x"),
        (("project", "absent", "[key]"), "project.absent"),
    ],
    ids=["index-past-list", "key-under-string", "absent-key"],
)
def test_drops_marker_when_location_not_in_file(
    monkeypatch: pytest.MonkeyPatch, loc: tuple[str | int, ...], path: str
) -> None:
    def raise_key_error(document: object) -> HubConfig:
        raise ValidationError.from_exception_data(
            "HubConfig",
            [InitErrorDetails(type=PydanticCustomError("bad_key", "bad key"), loc=loc, input="x")],
        )

    monkeypatch.setattr(HubConfig, "model_validate", raise_key_error)

    assert problems_of(a_pinned_document()) == (ConfigProblem(path, "bad key"),)


def test_stops_path_at_key_when_map_key_invalid() -> None:
    (problem,) = problems_of(with_max_lines({"": 5}))

    assert problem.path == f'{MAX_LINES_PATH}[""]'


@pytest.mark.parametrize(
    ("document", "path"),
    [
        (with_max_lines({"[key]": 0}), f'{MAX_LINES_PATH}["[key]"]'),
        ({**a_pinned_document(), "[key]": "x"}, '["[key]"]'),
        (in_first_repo("[key]", "x"), 'repos[0]["[key]"]'),
    ],
    ids=["map-value", "unknown-key", "unknown-key-in-list-item"],
)
def test_quotes_key_when_file_key_spelled_like_marker(document: dict[str, Any], path: str) -> None:
    (problem,) = problems_of(document)

    assert problem.path == path


# AGH-94: every key that holds an object, at each level (each doctor rule's settings included),
# with a value of another JSON type that carries a marker; the text a message would show if it
# echoed the value is listed with it.
OBJECT_KEYS: list[tuple[str | int, ...]] = [
    ("platform",),
    ("project",),
    ("project", "conventions"),
    ("tracker",),
    ("repos", 0),
    ("repos", 0, "conventions"),
    ("guard",),
    ("modules",),
    *[("modules", name) for name in ("bench", "cloud", "contract-sync", "marketplace")],
    ("doctor",),
    ("doctor", "rules"),
    *[("doctor", "rules", field.alias or name) for name, field in DoctorRules.model_fields.items()],
    ("doctor", "rules", "instructions.size", "max_lines"),
]
NOT_OBJECTS: list[tuple[object, str]] = [
    (SECRET_PARTS[1], SECRET_PARTS[1]),
    (31337, "31337"),
    ([SECRET_PARTS[1]], SECRET_PARTS[1]),
    (True, "true"),
]


def with_value_at(key: tuple[str | int, ...], value: object) -> dict[str, Any]:
    document = a_pinned_document()
    parent: Any = document
    for segment in key[:-1]:
        parent = parent.setdefault(segment, {}) if isinstance(segment, str) else parent[segment]
    parent[key[-1]] = value
    return document


@pytest.mark.parametrize("key", OBJECT_KEYS, ids=[".".join(map(str, key)) for key in OBJECT_KEYS])
@pytest.mark.parametrize(
    ("value", "shown"), NOT_OBJECTS, ids=["string", "number", "array", "boolean"]
)
def test_never_echoes_value_when_object_key_holds_other_type(
    key: tuple[str | int, ...], value: object, shown: str
) -> None:
    problems = problems_of(with_value_at(key, value))

    assert problems
    assert not [problem for problem in problems if shown in problem.message]
