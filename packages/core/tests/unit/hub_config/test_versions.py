from typing import Any

import pytest

from agent_hub.core.hub_config.versions import (
    ECHO_LIMIT,
    PINNED_RELEASE_COMMAND,
    SUPPORTED_SCHEMA_VERSION,
    find_version_problem,
)
from agent_hub.core.testing.builders import a_hub_document

RUNNING = "0.3.1"


def a_pinned_document(**overrides: object) -> dict[str, Any]:
    document = a_hub_document()
    document["platform"]["version"] = RUNNING
    document.update(overrides)
    return document


def test_reports_pin_first_when_both_versions_differ() -> None:
    document = a_pinned_document(platform={"version": "0.2.0"}, schema_version=2)

    problem = find_version_problem(document, running_version=RUNNING)

    assert problem is not None
    assert problem.path == "platform.version"
    assert "0.2.0" in problem.message
    assert RUNNING in problem.message
    assert PINNED_RELEASE_COMMAND.format(version="0.2.0") in problem.message
    assert "\n" not in problem.message


def test_reports_schema_version_when_pin_matches() -> None:
    problem = find_version_problem(a_pinned_document(schema_version=2), running_version=RUNNING)

    assert problem is not None
    assert problem.path == "schema_version"
    # Errata 11: the pin already matches, so the fix is the file or another pinned release.
    assert problem.message.endswith(
        f"update the file to schema version {SUPPORTED_SCHEMA_VERSION},"
        " or pin a release that reads schema version 2"
    )
    assert "uvx" not in problem.message


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        (a_pinned_document(platform={"version": "9" * 500}), '"' + "9" * 78 + "…"),
        # A cut never splits an escape: ``\n`` is two characters, and 38 of them fit.
        (a_pinned_document(platform={"version": ["\n" * 200]}), '["' + "\\n" * 38 + "…"),
        (a_pinned_document(platform={"version": "a" * 77 + "\n"}), '"' + "a" * 77 + "…"),
        (a_pinned_document(platform={"version": "a" * 75 + "é"}), '"' + "a" * 75 + "…"),
        (a_pinned_document(schema_version="1" * 500), '"' + "1" * 78 + "…"),
    ],
    ids=[
        "long-version",
        "long-line-breaks",
        "escape-at-cut",
        "unicode-escape-at-cut",
        "long-schema-version",
    ],
)
def test_truncates_value_when_echoed_value_long(document: dict[str, Any], expected: str) -> None:
    problem = find_version_problem(document, running_version=RUNNING)

    assert problem is not None
    shown = problem.message.split(", not ", 1)[1]
    assert shown == expected
    assert len(shown) <= ECHO_LIMIT
    assert len(problem.message.splitlines()) == 1


def test_truncates_schema_version_when_integer_long() -> None:
    long_integer = 10**200

    problem = find_version_problem(
        a_pinned_document(schema_version=long_integer), running_version=RUNNING
    )

    assert problem is not None
    assert problem.path == "schema_version"
    assert str(long_integer)[:40] in problem.message
    assert str(long_integer) not in problem.message
    assert problem.message.count("…") == 2
    assert len(problem.message) < 3 * ECHO_LIMIT + 150


def test_omits_pinned_command_when_pinned_version_long() -> None:
    pinned = "1" * 200 + ".0.0"

    problem = find_version_problem(
        a_pinned_document(platform={"version": pinned}), running_version=RUNNING
    )

    assert problem is not None
    assert problem.path == "platform.version"
    assert pinned not in problem.message
    assert "1" * 60 in problem.message
    assert RUNNING in problem.message
    assert "uvx" not in problem.message
    assert len(problem.message) < ECHO_LIMIT + 150


def _without(key: str) -> dict[str, Any]:
    document = a_pinned_document()
    del document[key]
    return document


@pytest.mark.parametrize(
    ("document", "path"),
    [
        (_without("platform"), "platform"),
        (a_pinned_document(platform=[]), "platform"),
        (a_pinned_document(platform={}), "platform.version"),
        (a_pinned_document(platform={"version": "1.2"}), "platform.version"),
        (a_pinned_document(platform={"version": 1}), "platform.version"),
        (a_pinned_document(platform={"version": f"{RUNNING}\n"}), "platform.version"),
        (_without("schema_version"), "schema_version"),
        (a_pinned_document(schema_version=True), "schema_version"),
        (a_pinned_document(schema_version="1"), "schema_version"),
        (a_pinned_document(schema_version=1.0), "schema_version"),
        ([a_pinned_document()], "$"),
    ],
    ids=[
        "platform-absent",
        "platform-array",
        "version-absent",
        "version-two-numbers",
        "version-number",
        "version-trailing-newline",
        "schema-version-absent",
        "schema-version-true",
        "schema-version-string",
        "schema-version-float",
        "top-level-array",
    ],
)
def test_reports_version_path_when_missing_or_malformed(document: object, path: str) -> None:
    problem = find_version_problem(document, running_version=RUNNING)

    assert problem is not None
    assert problem.path == path
    assert problem.message
    assert len(problem.message.splitlines()) == 1


def test_returns_nothing_when_both_versions_supported() -> None:
    document = a_pinned_document(project="not checked here", unknown="ignored")

    assert find_version_problem(document, running_version=RUNNING) is None
