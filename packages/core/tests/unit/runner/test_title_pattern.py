import re

import pytest

from agent_hub.core.hub_config.conventions import DEFAULT_COMMIT_TITLE
from agent_hub.core.runner.title_pattern import (
    MAX_PARSED_SUBJECT_CHARS,
    TitleParts,
    parse_title,
    render_title,
    title_regex,
)

PARTS = TitleParts(issue="DEM-1", type="feat", scope="core", summary="add x")


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        (DEFAULT_COMMIT_TITLE, PARTS),
        ("{ISSUE}: {type}({scope}): {summary}", PARTS),
        ("{type}({scope}): {summary}", PARTS._replace(issue="")),
        ("{ISSUE}: {summary}", TitleParts(issue="DEM-1", summary="add x")),
    ],
)
def test_returns_parts_when_rendered_title_parsed(pattern: str, expected: TitleParts) -> None:
    assert parse_title(pattern, render_title(pattern, expected)) == expected


def test_renders_title_when_parts_filled() -> None:
    rendered = render_title("{ISSUE}: {type}({scope}): {summary}", PARTS)

    assert rendered == "DEM-1: feat(core): add x"


def test_parses_default_title_when_subject_conventional() -> None:
    assert parse_title(DEFAULT_COMMIT_TITLE, "feat(core): add x (DEM-1)") == PARTS


@pytest.mark.parametrize("subject", ["feat: add x (DEM-1)", "DEM-1 add x", ""])
def test_finds_no_match_when_subject_off_pattern(subject: str) -> None:
    assert parse_title(DEFAULT_COMMIT_TITLE, subject) is None


@pytest.mark.parametrize(
    ("pattern", "subject", "expected"),
    [
        ("[{type}+] {summary}.", "[feat+] add x.", TitleParts(type="feat", summary="add x")),
        ("[{type}+] {summary}.", "[feat++ add x.", None),
        ("[{type}+] {summary}.", "Xfeat+] add x!", None),
        ("[{type}+] {summary}.", "[feat+] add x!", None),
        ("{summary} (v{ISSUE})", "add x (vDEM-1)", TitleParts(issue="DEM-1", summary="add x")),
        ("{summary} (v{ISSUE})", "add x vDEM-1)", None),
    ],
)
def test_matches_regex_characters_literally_when_pattern_has_them(
    pattern: str, subject: str, expected: TitleParts | None
) -> None:
    assert parse_title(pattern, subject) == expected


@pytest.mark.parametrize(
    ("pattern", "subject", "expected"),
    [
        (
            "{ISSUE} {scope}: {summary}",
            "DEM-1 core: add x",
            TitleParts(issue="DEM-1", scope="core", summary="add x"),
        ),
        (
            "{type}/{scope}-{summary}",
            "feat/core-api-add x",
            TitleParts(type="feat", scope="core", summary="api-add x"),
        ),
    ],
)
def test_stops_group_at_next_literal_when_class_holds_its_character(
    pattern: str, subject: str, expected: TitleParts
) -> None:
    assert parse_title(pattern, subject) == expected


def test_caps_parsed_subject_at_literal_length_when_long() -> None:
    assert MAX_PARSED_SUBJECT_CHARS == 1_000
    frame = "feat(core):  (DEM-1)"
    at_cap = f"feat(core): {'x' * (1_000 - len(frame))} (DEM-1)"

    assert len(at_cap) == 1_000
    assert parse_title(DEFAULT_COMMIT_TITLE, at_cap) == PARTS._replace(
        summary="x" * (1_000 - len(frame))
    )
    assert parse_title(DEFAULT_COMMIT_TITLE, at_cap.replace(" (", "x (")) is None


@pytest.mark.parametrize(
    ("pattern", "subject"),
    [
        pytest.param(DEFAULT_COMMIT_TITLE, "(" * 497 + ")" * 496 + " (DEM-1", id="parens"),
        pytest.param(DEFAULT_COMMIT_TITLE, "feat(core): " + " (DEM-1" * 141, id="open-issues"),
        pytest.param(DEFAULT_COMMIT_TITLE, "feat(core): " + " (a1-" * 197, id="issue-heads"),
        pytest.param("{summary} {scope} {type}: {ISSUE}", "a " * 500, id="spaced-groups"),
    ],
)
def test_finds_no_match_when_subject_pathological(pattern: str, subject: str) -> None:
    # The scale guard is test_uses_one_free_group_when_regex_built (possessive groups).
    assert len(subject) <= 1_000

    assert parse_title(pattern, subject) is None


def test_uses_one_free_group_when_regex_built() -> None:
    regex = title_regex("[{ISSUE}.] {type}({scope}): {summary}.")
    unescaped = re.sub(r"\\.", "", regex.pattern)

    assert set(regex.groupindex) == {"ISSUE", "type", "scope", "summary"}
    assert unescaped.count(".") == 1
    assert "(?P<summary>.+)" in regex.pattern
    # E18: each fixed group ends possessive (``++)``) before the next group starts.
    possessive = {
        name
        for name in ("ISSUE", "type", "scope")
        if re.search(rf"\(\?P<{name}>(?:(?!\(\?P<).)*?\+\+\)", regex.pattern)
    }
    assert possessive == {"ISSUE", "type", "scope"}


def test_keeps_group_possessive_when_class_holds_next_literal() -> None:
    # The scope class holds "-", so its group is wrapped in a stop lookahead: still possessive.
    regex = title_regex("{type}/{scope}-{summary}")

    assert re.search(r"\(\?P<scope>\(\?:\(\?!.*?\+\+\)", regex.pattern)
