import re

import pytest

from agent_hub.core.hub_config.model import Guard, Repo
from agent_hub.core.hub_config.platform_repository import (
    DEFAULT_PLATFORM_REPOSITORY,
    MAX_PLATFORM_REPOSITORY_CHARS,
    PLATFORM_REPOSITORY_FORM,
    PLATFORM_REPOSITORY_MESSAGE,
    PLATFORM_REPOSITORY_PATTERN,
    is_platform_repository,
)
from agent_hub.core.testing.platform_repository_cases import REPOSITORY_CASES, RepositoryCase

GOOD_CASES = [case for case in REPOSITORY_CASES if case.is_valid]
BAD_CASES = [case for case in REPOSITORY_CASES if not case.is_valid]
CHARACTER_CLASS = re.compile(r"(\[[^\]]+\])([+*]?)")


def case_name(case: RepositoryCase) -> str:
    return case.name


def without_anchors(pattern: str) -> str:
    assert pattern.startswith("^")
    assert pattern.endswith("$")
    return pattern[1:-1]


def character_set(character_class: str) -> frozenset[str]:
    """The ASCII characters a ``[...]`` class matches."""
    return frozenset(
        character for character in map(chr, range(128)) if re.fullmatch(character_class, character)
    )


@pytest.mark.parametrize("case", GOOD_CASES, ids=case_name)
def test_accepts_value_when_case_good(case: RepositoryCase) -> None:
    assert is_platform_repository(case.value) is True


@pytest.mark.parametrize("case", BAD_CASES, ids=case_name)
def test_rejects_value_when_case_bad(case: RepositoryCase) -> None:
    assert is_platform_repository(case.value) is False


def test_caps_value_at_literal_length_when_checked() -> None:
    prefix = "git+https://github.com/acme/"

    assert MAX_PLATFORM_REPOSITORY_CHARS == 200
    assert is_platform_repository(prefix + "a" * (200 - len(prefix))) is True
    assert is_platform_repository(prefix + "a" * (201 - len(prefix))) is False


def test_composes_model_patterns_when_pattern_read() -> None:
    host = without_anchors(
        Guard.model_json_schema()["properties"]["deny_hosts"]["items"]["pattern"]
    )
    segment = without_anchors(Repo.model_json_schema()["properties"]["dir"]["pattern"])

    assert rf"git\+https://{host}(?:/{segment})+" == PLATFORM_REPOSITORY_PATTERN


def test_keeps_separators_out_of_segments_when_pattern_parsed() -> None:
    """A separator character that a label or segment also matches makes ``re`` backtrack."""
    after_scheme = PLATFORM_REPOSITORY_PATTERN.removeprefix(r"git\+https://")
    host, marker, path = after_scheme.partition("(?:/")
    assert marker
    label_classes = {cls for cls, _ in CHARACTER_CLASS.findall(host)}
    segment_classes = {cls for cls, repeated in CHARACTER_CLASS.findall(path) if repeated}
    path_separators = {cls for cls, repeated in CHARACTER_CLASS.findall(path) if not repeated}
    assert label_classes
    assert segment_classes
    assert path_separators == {"[.-]"}

    label_characters = frozenset().union(*map(character_set, label_classes))
    segment_characters = frozenset().union(*map(character_set, segment_classes))
    separator_characters = frozenset().union(*map(character_set, path_separators))

    assert r"(?:\." in host
    assert {".", "/"} & label_characters == frozenset()
    assert "/" not in segment_characters
    assert "/" not in separator_characters
    assert separator_characters & segment_characters == frozenset()


def repeated_group_bodies(pattern: str) -> list[str]:
    """The text inside each ``(...)`` group that is followed by ``*`` or ``+``."""
    bodies: list[str] = []
    starts: list[int] = []
    index = 0
    while index < len(pattern):
        character = pattern[index]
        if character == "\\":
            index += 1
        elif character == "[":
            index = pattern.index("]", index + 1)
        elif character == "(":
            starts.append(index)
        elif character == ")":
            start = starts.pop()
            if pattern[index + 1 : index + 2] in {"*", "+"}:
                bodies.append(pattern[start + 1 : index].removeprefix("?:"))
        index += 1
    assert not starts
    return bodies


def test_starts_each_repeated_group_with_separator_when_pattern_parsed() -> None:
    """No nested quantifier without a separator: ``(?:[A-Za-z0-9-]+)+`` backtracks exponentially.

    Every group repeated by ``*`` or ``+`` must open with one unrepeated separator (``\\.``, ``/``
    or a class without a quantifier), which the separator test above keeps out of the labels and
    segments; so each repetition is anchored to a separator and ``re`` has one way to match.
    """
    separator = re.compile(r"\\\.|/|\[[^\]]+\](?![*+?{])")
    bodies = repeated_group_bodies(PLATFORM_REPOSITORY_PATTERN)

    for body in bodies:
        assert separator.match(body), body
    assert len(bodies) == 3


@pytest.mark.parametrize(
    "value",
    ["git+https://" + "a-" * 90 + "!", "git+https://h/" + "a." * 90 + "!"],
    ids=["dashed-host", "dotted-path"],
)
def test_rejects_hostile_value_when_regex_could_backtrack(value: str) -> None:
    assert len(value) <= 200
    assert is_platform_repository(value) is False


@pytest.mark.parametrize("text", [PLATFORM_REPOSITORY_PATTERN, PLATFORM_REPOSITORY_FORM])
def test_renders_safely_when_pattern_and_form_quoted(text: str) -> None:
    """Both go into single-quoted shell, ``r"..."`` Python and ``@@{...}`` templates."""
    for unsafe in ("'", '"', "`", "$", "{", "}", "@@"):
        assert unsafe not in text
    assert "\\" not in PLATFORM_REPOSITORY_FORM
    assert "200" in PLATFORM_REPOSITORY_FORM
    assert "git+https://" in PLATFORM_REPOSITORY_FORM
    assert f"must be {PLATFORM_REPOSITORY_FORM}" == PLATFORM_REPOSITORY_MESSAGE


def test_names_default_source_when_default_read() -> None:
    assert DEFAULT_PLATFORM_REPOSITORY == "git+https://github.com/jroquette/agent-hub"
    assert is_platform_repository(DEFAULT_PLATFORM_REPOSITORY) is True
