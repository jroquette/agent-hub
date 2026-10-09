from typing import Any

import pytest

from agent_hub.core.hub_config.document_check import check_hub_document
from agent_hub.core.hub_config.platform_repository import PLATFORM_REPOSITORY_MESSAGE
from agent_hub.core.hub_config.problems import ConfigProblem
from agent_hub.core.hub_config.versions import (
    ECHO_LIMIT,
    PINNED_RELEASE_COMMAND,
    SUPPORTED_SCHEMA_VERSION,
    find_version_problem,
    pinned_release,
    pinned_release_command,
    pinned_repository,
)
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.core.testing.platform_repository_cases import (
    CUSTOM_REPOSITORY,
    REPOSITORY_CASES,
    SECRET_PARTS,
    RepositoryCase,
)

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


# AGH-94: a value pasted where the platform object belongs may be a secret, so the problem names
# its JSON type, never the value.
SECRET = SECRET_PARTS[1]


@pytest.mark.parametrize(
    ("platform", "json_type"),
    [
        (SECRET, "a string"),
        (31337, "a number"),
        (3.25, "a number"),
        ([SECRET], "an array"),
        (True, "a boolean"),
        (False, "a boolean"),
        (None, "null"),
    ],
    ids=["string", "integer", "float", "array", "true", "false", "null"],
)
def test_names_json_type_when_platform_not_object(platform: object, json_type: str) -> None:
    problem = find_version_problem(a_pinned_document(platform=platform), running_version=RUNNING)

    assert problem == ConfigProblem("platform", f"must be an object, not {json_type}")


def test_returns_nothing_when_both_versions_supported() -> None:
    document = a_pinned_document(project="not checked here", unknown="ignored")

    assert find_version_problem(document, running_version=RUNNING) is None


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        (a_pinned_document(platform={"version": "0.0.1"}), "0.0.1"),
        (_without("platform"), None),
        (a_pinned_document(platform=["0.0.1"]), None),
        (a_pinned_document(platform={}), None),
        (a_pinned_document(platform={"version": 1}), None),
        (a_pinned_document(platform={"version": "0.1"}), None),
        (a_pinned_document(platform={"version": "0.1.0\n"}), None),
        (a_pinned_document(platform={"version": "\u0660.1.0"}), None),
        ([a_pinned_document(platform={"version": "0.0.1"})], None),
    ],
    ids=[
        "well-formed",
        "platform-absent",
        "platform-array",
        "version-absent",
        "version-number",
        "version-two-numbers",
        "version-trailing-newline",
        "version-non-ascii-digit",
        "top-level-array",
    ],
)
def test_returns_pin_when_pin_well_formed(document: object, expected: str | None) -> None:
    assert pinned_release(document) == expected


def test_formats_pinned_command_when_pin_short() -> None:
    assert pinned_release_command("0.0.1") == (
        "uvx --from git+https://github.com/jroquette/agent-hub@v0.0.1"
        "#subdirectory=packages/agent-hub hub"
    )


def test_drops_pinned_command_when_pin_longer_than_limit() -> None:
    at_limit = "1" * (ECHO_LIMIT - 4) + ".0.0"
    over_limit = "1" * (ECHO_LIMIT - 3) + ".0.0"

    assert len(at_limit) == ECHO_LIMIT
    assert pinned_release_command(at_limit) == PINNED_RELEASE_COMMAND.format(version=at_limit)
    assert pinned_release_command(over_limit) is None


DEFAULT_REPOSITORY = "git+https://github.com/jroquette/agent-hub"
BAD_REPOSITORIES = [case for case in REPOSITORY_CASES if not case.is_valid]
# ``null`` keeps the null message in the model (ConfigObject); the pre-check omits it all alike.
BAD_NON_NULL_REPOSITORIES = [case for case in BAD_REPOSITORIES if case.value is not None]


def case_name(case: RepositoryCase) -> str:
    return case.name


def with_repository(value: object, *, version: str = RUNNING) -> dict[str, Any]:
    return a_pinned_document(platform={"version": version, "repository": value})


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        (None, DEFAULT_REPOSITORY),
        ([], DEFAULT_REPOSITORY),
        (_without("platform"), DEFAULT_REPOSITORY),
        (a_pinned_document(platform=[CUSTOM_REPOSITORY]), DEFAULT_REPOSITORY),
        (a_pinned_document(), DEFAULT_REPOSITORY),
        (with_repository(CUSTOM_REPOSITORY), CUSTOM_REPOSITORY),
        *((with_repository(case.value), None) for case in BAD_REPOSITORIES),
    ],
    ids=[
        "null-document",
        "array-document",
        "platform-absent",
        "platform-array",
        "key-absent",
        "custom",
        *(f"bad-{case.name}" for case in BAD_REPOSITORIES),
    ],
)
def test_reads_repository_leniently_when_document_parsed(
    document: object, expected: str | None
) -> None:
    assert pinned_repository(document) == expected


def test_names_custom_source_when_pin_differs_and_hub_sets_repository() -> None:
    problem = find_version_problem(
        with_repository(CUSTOM_REPOSITORY, version="0.0.1"), running_version=RUNNING
    )

    assert problem is not None
    assert problem.path == "platform.version"
    assert problem.message.endswith(
        "run the pinned release: uvx --from"
        " git+https://git.acme.test/tools/agent-hub@v0.0.1#subdirectory=packages/agent-hub hub"
    )


def test_names_full_source_when_pin_differs_and_repository_at_cap() -> None:
    [case] = [case for case in REPOSITORY_CASES if case.name == "200-chars"]
    assert isinstance(case.value, str)

    problem = find_version_problem(
        with_repository(case.value, version="0.0.1"), running_version=RUNNING
    )

    assert problem is not None
    assert problem.message.endswith(
        f"run the pinned release: uvx --from {case.value}@v0.0.1"
        "#subdirectory=packages/agent-hub hub"
    )


@pytest.mark.parametrize("case", BAD_REPOSITORIES, ids=case_name)
def test_omits_pinned_command_when_repository_invalid(case: RepositoryCase) -> None:
    problem = find_version_problem(
        with_repository(case.value, version="0.0.1"), running_version=RUNNING
    )

    assert problem == ConfigProblem(
        "platform.version",
        f"this hub is pinned to 0.0.1 but this hub command is {RUNNING}; run the pinned release",
    )
    assert [part for part in SECRET_PARTS if part in problem.message] == []


@pytest.mark.parametrize("case", BAD_NON_NULL_REPOSITORIES, ids=case_name)
def test_reports_repository_after_pin_matches_when_value_bad(case: RepositoryCase) -> None:
    document = with_repository(case.value)

    assert find_version_problem(document, running_version=RUNNING) is None
    assert check_hub_document(document, running_version=RUNNING) == (
        ConfigProblem("platform.repository", PLATFORM_REPOSITORY_MESSAGE),
    )
