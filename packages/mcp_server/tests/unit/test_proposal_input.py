import pytest

from agent_hub.mcp_server.hub_context import ToolRefusal
from agent_hub.mcp_server.proposal_input import (
    KINDS,
    MAX_BODY_BYTES,
    MAX_PR_QUOTE_CHARS,
    MAX_PR_TITLE_CHARS,
    MAX_SLUG_CHARS,
    MAX_TITLE_CHARS,
    SESSION_ID,
    checked_body,
    checked_title,
    target_folder,
)


def _refusal(check: object, value: str) -> str:
    assert callable(check)
    with pytest.raises(ToolRefusal) as refused:
        check(value)
    return refused.value.line


def test_states_bounds_when_constants_read() -> None:
    assert MAX_TITLE_CHARS == 120
    assert MAX_BODY_BYTES == 65_536
    assert MAX_SLUG_CHARS == 50
    assert MAX_PR_TITLE_CHARS == 72
    assert MAX_PR_QUOTE_CHARS == 600
    assert SESSION_ID.pattern == "^[A-Za-z0-9_-]{1,128}$"
    assert KINDS == {
        "learning": "learnings",
        "playbook": "playbooks",
        "decision": "decisions",
        "domain": "domain",
        "system": "system",
    }


def test_keeps_trimmed_title_when_within_bounds() -> None:
    assert checked_title("  Worktrees need a fresh fetch  ") == "Worktrees need a fresh fetch"
    assert checked_title("x" * MAX_TITLE_CHARS) == "x" * MAX_TITLE_CHARS


@pytest.mark.parametrize(
    ("title", "line"),
    [
        ("", "propose: the title is empty"),
        ("   ", "propose: the title is empty"),
        ("x" * 121, "propose: the title is longer than 120 characters"),
        ("a\nb", "propose: the title must be one line with no control characters"),
        ("a\tb", "propose: the title must be one line with no control characters"),
        ("!!!", "propose: the title has no letters or digits for a file name"),
    ],
    ids=["empty", "blank", "long", "two-lines", "tab", "punctuation"],
)
def test_refuses_title_when_out_of_bounds(title: str, line: str) -> None:
    assert _refusal(checked_title, title) == line


def test_keeps_trimmed_body_when_within_bounds() -> None:
    assert checked_body("\n  Fetch first.\n\n") == "Fetch first."
    assert checked_body("é" * (MAX_BODY_BYTES // 2)) == "é" * (MAX_BODY_BYTES // 2)


@pytest.mark.parametrize(
    ("body", "line"),
    [
        ("", "propose: the body is empty"),
        (" \n\t", "propose: the body is empty"),
        ("x" * (MAX_BODY_BYTES + 1), "propose: the body is larger than 65536 bytes"),
        ("é" * (MAX_BODY_BYTES // 2) + "x", "propose: the body is larger than 65536 bytes"),
    ],
    ids=["empty", "blank", "long", "long-utf8"],
)
def test_refuses_body_when_out_of_bounds(body: str, line: str) -> None:
    assert _refusal(checked_body, body) == line


def test_names_target_folder_when_kind_is_brain_folder() -> None:
    assert target_folder("playbook") == "brain/playbooks/"
    assert target_folder("domain") == "brain/domain/"


def test_refuses_kind_when_not_a_brain_folder() -> None:
    line = _refusal(target_folder, "adr")

    assert line == "propose: the kind is not one of learning, playbook, decision, domain, system"
