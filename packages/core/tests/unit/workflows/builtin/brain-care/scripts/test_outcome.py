"""The brain-care pack's ``outcome.py`` (AGH-487), in process: how a run ended, said even when no
PR opened."""

import importlib.util
import json
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(
    str(files("agent_hub.core").joinpath("workflows/builtin/brain-care/scripts/outcome.py"))
)

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.brain-care.scripts.outcome"
WORKTREE = ["--worktree", "/ws/hub/.claude/worktrees/x", "--branch", "jdoe/brain-care-inbox-x"]
CLEANUP = "git worktree remove /ws/hub/.claude/worktrees/x"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(MODULE, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # No __pycache__ beside the pack's files: the pack is seeded into hubs file by file.
    writes, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = writes
    return module


def outcome(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[str, str]:
    assert load().main(argv) == 0
    found = json.loads(capsys.readouterr().out)
    return found["outcome"], found["reason"]


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["--count", "0"], "empty"),
        (["--count", "3", "--groups", "0"], "nothing_decided"),
        (["--count", "3", "--groups", "2", "--acted", "0"], "kept"),
        (
            ["--count", "3", "--groups", "2", "--acted", "2", "--changes", "4", "--pr", "u"],
            "pr_opened",
        ),
        (["--count", "3", "--groups", "2", "--acted", "2", "--changes", "0"], "no_pr"),
    ],
)
def test_names_inbox_outcome_when_run_ends(
    capsys: pytest.CaptureFixture[str], argv: list[str], expected: str
) -> None:
    assert outcome(["inbox", *argv, *WORKTREE], capsys)[0] == expected


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["--decision", "skip"], "declined"),
        (["--decision", "trim", "--commits", "1", "--dirty", "false", "--pr", "u"], "pr_opened"),
        (["--decision", "trim", "--commits", "0", "--dirty", "false"], "no_pr"),
        (["--decision", "trim", "--commits", "1", "--dirty", "true"], "no_pr"),
    ],
)
def test_names_context_outcome_when_run_ends(
    capsys: pytest.CaptureFixture[str], argv: list[str], expected: str
) -> None:
    assert outcome(["context", *argv, *WORKTREE], capsys)[0] == expected


def test_says_why_and_how_to_clean_up_when_no_pr_opened(
    capsys: pytest.CaptureFixture[str],
) -> None:
    argv = ["inbox", "--count", "3", "--groups", "2", "--acted", "2", "--changes", "0"]

    found, reason = outcome([*argv, *WORKTREE], capsys)

    assert found == "no_pr"
    assert "every approved change was skipped" in reason
    assert CLEANUP in reason
    assert "git branch -D jdoe/brain-care-inbox-x" in reason


def test_names_cleanup_after_merge_when_pr_opened(capsys: pytest.CaptureFixture[str]) -> None:
    argv = ["context", "--decision", "trim", "--commits", "1", "--dirty", "false", "--pr", "u"]

    reason = outcome([*argv, *WORKTREE], capsys)[1]

    assert "u" in reason
    assert CLEANUP in reason


def test_says_nothing_to_clean_when_no_branch_made(capsys: pytest.CaptureFixture[str]) -> None:
    reason = outcome(["context", "--decision", "skip"], capsys)[1]

    assert "git worktree" not in reason


@pytest.mark.parametrize("argv", [["inbox", "--count", "x"], ["context", "--commits", "many"]])
def test_exits_two_when_input_not_a_count(argv: list[str]) -> None:
    assert load().main(argv) == 2
