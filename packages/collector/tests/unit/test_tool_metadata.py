from pathlib import PurePosixPath

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agent_hub.collector.tool_metadata import (
    ERROR_MESSAGE_LIMIT,
    error_message,
    learning_proposal,
    output_bytes,
    repo_root_of,
    tool_call_payload,
)

ROOT = PurePosixPath("/work/demo-api")
SENTINEL = "SENTINEL-content-never-stored"


def test_keeps_relative_path_and_line_counts_when_edit() -> None:
    payload = tool_call_payload(
        "Edit",
        {
            "file_path": "/work/demo-api/src/app.py",
            "old_string": f"one\ntwo {SENTINEL}",
            "new_string": f"one\ntwo\nthree {SENTINEL}\n",
        },
        repo_root=ROOT,
    )

    assert payload == {
        "path": "src/app.py",
        "lines_added": 3,
        "lines_removed": 2,
        "new_file": False,
    }


def test_sums_line_counts_when_multi_edit() -> None:
    payload = tool_call_payload(
        "MultiEdit",
        {
            "file_path": "/work/demo-api/src/app.py",
            "edits": [
                {"old_string": "a", "new_string": "b\nc"},
                {"old_string": "d\ne\nf", "new_string": ""},
                "not an edit",
            ],
        },
        repo_root=ROOT,
    )

    assert payload == {
        "path": "src/app.py",
        "lines_added": 2,
        "lines_removed": 4,
        "new_file": False,
    }


def test_drops_content_when_write_holds_sentinel() -> None:
    payload = tool_call_payload(
        "Write",
        {"file_path": "/work/demo-api/notes.md", "content": f"# Title\n{SENTINEL}\nlast"},
        repo_root=ROOT,
    )

    # A PreToolUse input cannot tell a new file from a replaced one: new_file is left out.
    assert payload == {"path": "notes.md", "lines_added": 3}
    assert SENTINEL not in repr(payload)


def test_keeps_absolute_path_when_file_outside_repo() -> None:
    payload = tool_call_payload("Read", {"file_path": "/etc/hosts"}, repo_root=ROOT)

    assert payload == {"path": "/etc/hosts"}


def test_keeps_given_path_when_no_repo_root() -> None:
    payload = tool_call_payload("Read", {"file_path": "/work/x.py"}, repo_root=None)

    assert payload == {"path": "/work/x.py"}


def test_clips_redacted_command_when_bash_command_long() -> None:
    token = "gh" + "p_" + "Z9y8X7w6" * 5
    command = "x" * 490 + token + " tail"

    payload = tool_call_payload("Bash", {"command": command}, repo_root=ROOT)

    shown = payload["command"]
    assert isinstance(shown, str)
    assert len(shown) <= 500
    assert "gh" + "p_" not in shown
    assert shown.endswith("…")


def test_keeps_pattern_when_grep_or_glob() -> None:
    grep = tool_call_payload(
        "Grep", {"pattern": "def .*_when_", "path": "/work/demo-api/src"}, repo_root=ROOT
    )
    glob = tool_call_payload("Glob", {"pattern": "p" * 300}, repo_root=ROOT)

    assert grep == {"pattern": "def .*_when_", "path": "src"}
    assert glob == {"pattern": "p" * 199 + "…"}


def test_keeps_scheme_host_and_path_when_web_fetch() -> None:
    payload = tool_call_payload(
        "WebFetch",
        {"url": "https://user:pw@docs.example.com/a/b?q=secret#frag", "prompt": SENTINEL},
        repo_root=ROOT,
    )

    assert payload == {"url": "https://docs.example.com/a/b"}


def test_keeps_names_and_argument_keys_when_mcp_tool() -> None:
    payload = tool_call_payload(
        "mcp__linear__save_issue",
        {"title": SENTINEL, "description": SENTINEL, "team": "DEM"},
        repo_root=ROOT,
    )

    assert payload == {
        "mcp_server": "linear",
        "mcp_tool": "save_issue",
        "arg_keys": ["description", "team", "title"],
    }


@pytest.mark.parametrize("tool", ["Agent", "Task"])
def test_keeps_subagent_type_and_short_description_when_agent_tool(tool: str) -> None:
    payload = tool_call_payload(
        tool,
        {"subagent_type": "Explore", "description": "d" * 100, "prompt": SENTINEL},
        repo_root=ROOT,
    )

    assert payload == {"subagent_type": "Explore", "description": "d" * 79 + "…"}


def test_keeps_nothing_when_tool_unknown_or_input_malformed() -> None:
    assert tool_call_payload("TodoWrite", {"todos": [SENTINEL]}, repo_root=ROOT) == {}
    assert tool_call_payload("Bash", {"command": 3}, repo_root=ROOT) == {}
    assert tool_call_payload("Edit", {"file_path": None}, repo_root=ROOT) == {}
    assert tool_call_payload("WebFetch", {"url": "not a url"}, repo_root=ROOT) == {}
    assert tool_call_payload("mcp__broken", {}, repo_root=ROOT) == {}


def test_finds_worktree_root_when_cwd_inside_repo_worktree() -> None:
    cwd = "/work/demo-api/.claude/worktrees/dem-7/src/pkg"

    assert repo_root_of(cwd, "demo-api") == PurePosixPath("/work/demo-api/.claude/worktrees/dem-7")
    assert repo_root_of("/work/demo-api/src", "demo-api") == ROOT
    assert repo_root_of("/elsewhere", "demo-api") is None
    assert repo_root_of(None, "demo-api") is None
    assert repo_root_of("/work/demo-api", None) is None


def test_counts_utf8_bytes_when_output_given() -> None:
    assert output_bytes("héllo") == 6
    assert output_bytes({"stdout": "ok"}) == len('{"stdout":"ok"}')
    assert output_bytes(None) is None


def test_proposes_learning_with_heading_when_write_under_brain_inbox() -> None:
    proposal = learning_proposal(
        "Write",
        {
            "file_path": "/work/demo-hub/brain/_inbox/2026-10-11-migrations.md",
            "content": "---\nprovenance: agent\n---\n\n"
            f"# Run the migrations check first\n{SENTINEL}",
        },
        tool_use_id="toolu_9",
    )

    assert proposal == {
        "proposal": "toolu_9",
        "text": "Run the migrations check first",
        "target": "brain/_inbox/2026-10-11-migrations.md",
    }


def test_proposes_nothing_when_write_outside_brain_inbox() -> None:
    assert learning_proposal("Write", {"file_path": "/w/notes.md"}, tool_use_id="t") is None
    assert learning_proposal("Edit", {"file_path": "/w/brain/_inbox/a.md"}, tool_use_id="t") is None
    assert (
        learning_proposal(
            "Write", {"file_path": "/w/brain/_inbox/a.md", "content": 1}, tool_use_id="t"
        )
        is None
    )


def test_keeps_skill_name_when_tool_is_skill() -> None:
    payload = tool_call_payload(
        "Skill", {"skill": "hub-workflow:feature", "args": SENTINEL}, repo_root=ROOT
    )

    assert payload == {"skill": "hub-workflow:feature"}


def test_keeps_recipient_when_tool_is_send_message() -> None:
    payload = tool_call_payload(
        "SendMessage", {"to": "reviewer-" + "x" * 100, "message": SENTINEL}, repo_root=ROOT
    )

    assert set(payload) == {"to"}
    shown = payload["to"]
    assert isinstance(shown, str)
    assert shown.startswith("reviewer-")
    assert len(shown) <= 80
    assert SENTINEL not in repr(payload)


def test_keeps_nothing_when_skill_or_recipient_not_text() -> None:
    assert tool_call_payload("Skill", {"skill": 3}, repo_root=ROOT) == {}
    assert tool_call_payload("SendMessage", {"to": ["a"]}, repo_root=ROOT) == {}


def test_collapses_whitespace_when_error_spans_lines() -> None:
    message = error_message("  Exit code 2\n\n\tmake: *** [check]   Error 2\r\n  ")

    assert message == "Exit code 2 make: *** [check] Error 2"


def test_returns_none_when_error_blank_or_not_text() -> None:
    assert error_message(" \n\t ") is None
    assert error_message({"_omitted_bytes": 70_000}) is None
    assert error_message(None) is None


def test_hides_token_when_token_straddles_error_message_cap() -> None:
    token = "gh" + "p_" + "Z9y8X7w6" * 5
    text = "e" * (ERROR_MESSAGE_LIMIT - 10) + " " + token + " tail"

    message = error_message(text)

    assert message is not None
    assert len(message) <= ERROR_MESSAGE_LIMIT
    assert message.endswith("…")
    assert not _survives(token, message)


# One synthetic sample of every r1 kind, built from fragments: (text holding it, secret part).
_ALNUM = "A1b2C3d4E5f6G7h8"
_PEM_LINES = ["MIIEow" + _ALNUM * 4, _ALNUM * 4 + "Zz", "QwErTy" + _ALNUM]
_SECRET_SAMPLES: tuple[tuple[str, str], ...] = (
    ("gh" + "p_" + _ALNUM * 2 + "xyzw", "gh" + "p_" + _ALNUM * 2 + "xyzw"),
    ("github" + "_pat_" + "11AB" + _ALNUM * 3, "github" + "_pat_" + "11AB" + _ALNUM * 3),
    ("lin" + "_api_" + _ALNUM * 2 + "Qq", "lin" + "_api_" + _ALNUM * 2 + "Qq"),
    ("sk" + "-ant-" + "api03-" + _ALNUM * 3, "sk" + "-ant-" + "api03-" + _ALNUM * 3),
    ("sk" + "-proj-" + _ALNUM * 3, "sk" + "-proj-" + _ALNUM * 3),
    ("AK" + "IA" + "QWERTY2345ZXCV78", "AK" + "IA" + "QWERTY2345ZXCV78"),
    (
        "aws_secret_access_key" + " = " + "wJalr" + "XUtnFEMI/K7MDENG/bPxRfiCY" + "EXAMPLEKEY",
        "wJalr" + "XUtnFEMI/K7MDENG/bPxRfiCY" + "EXAMPLEKEY",
    ),
    (
        "Authorization: Bearer " + "eyJ" + _ALNUM * 2 + ".payload" + _ALNUM,
        "eyJ" + _ALNUM * 2 + ".payload" + _ALNUM,
    ),
    (
        "-----BEGIN "
        + "RSA PRIVATE KEY-----\n"
        + "\n".join(_PEM_LINES)
        + "\n-----END RSA PRIVATE KEY-----",
        "".join(_PEM_LINES),
    ),
    (
        "https://" + "deploy:" + "s3cr3t" + "Passw0rd" + "@git.example.com/acme/repo.git",
        "deploy:" + "s3cr3t" + "Passw0rd",
    ),
    ("DB_PASSWORD=" + "hunter2" + "Hunter2", "hunter2" + "Hunter2"),
)


def _survives(secret: str, text: str, *, window: int = 8) -> bool:
    """Whether any ``window``-long piece of ``secret`` is still in ``text``."""
    pieces = {secret[start : start + window] for start in range(len(secret) - window + 1)}
    return any(piece in text for piece in pieces)


@settings(max_examples=300, deadline=None)
@given(
    filler=st.text(max_size=400),
    index=st.integers(min_value=0, max_value=len(_SECRET_SAMPLES) - 1),
    offset=st.integers(min_value=0, max_value=400),
    spacing=st.sampled_from([" ", "\n", "\t  ", "\r\n\n"]),
)
def test_keeps_no_secret_when_error_message_built_property(
    *, filler: str, index: int, offset: int, spacing: str
) -> None:
    text, secret = _SECRET_SAMPLES[index]
    cut = min(offset, len(filler))
    error = f"{filler[:cut]}{spacing}{text}{spacing}{filler[cut:]}"

    message = error_message(error) or ""
    command = tool_call_payload("Bash", {"command": error}, repo_root=ROOT).get("command", "")

    assert isinstance(command, str)
    assert len(message) <= ERROR_MESSAGE_LIMIT
    for shown in (message, command):
        assert not _survives(secret, shown)
