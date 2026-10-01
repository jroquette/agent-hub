"""``hub brief``: the session brief, against the hub's brief characterization (AC-15.5, AC-15.6).

The ten goldens in ``golden/brief/`` are hub ``tests/characterization/golden/brief/*.golden`` at
hub commit ``8eaebae``, byte for byte; ``brief_workspace`` rebuilds that commit's synthetic
workspace (nothing is copied from the hub's brain).
"""

import datetime
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from agent_hub.cli import brief_command
from agent_hub.cli.main import app

# The conftest's workspace (tests cannot import a conftest in importlib mode).
type Workspace = Any

# The conftest's BRIEF_GH rules for api and web (the hub's calls match none).
BRIEF_PRS = (
    "#41 Add login endpoint\n"
    "#40 Refactor the session storage layer so that every adapter shares one connection pool"
    " and retry policy\n"
    "#38 Fix pagination\n#37 Bump dependencies\n#35 Fifth PR is never shown\n"
)
BRIEF_RULES: list[dict[str, Any]] = [
    {"argv_has": ["pr", "acme/api"], "stdout": BRIEF_PRS},
    {"argv_has": ["run", "acme/api"], "stdout": "lint\nbuild\nlint\n"},
    {"argv_has": ["acme/web"], "stdout": ""},
]
# How long each fake gh call waits at the barrier for the others (inside the gh phase budget).
BARRIER_WAIT = 4.0


def test_rebuilds_hub_workspace_when_brief_fixture_built(brief_workspace: Workspace) -> None:
    web = brief_workspace.ws / "web"
    api = brief_workspace.ws / "api"

    assert brief_workspace.git("rev-parse", "--short", "HEAD", cwd=web) == "dd68590"
    assert brief_workspace.git("branch", "--show-current", cwd=web) == ""
    assert brief_workspace.git("rev-list", "--count", "HEAD..origin/trunk", cwd=api) == "1"
    status = brief_workspace.git("status", "--porcelain", cwd=api)
    assert [line.split()[-1] for line in status.splitlines()] == ["README.md", "notes.txt"]
    hub = brief_workspace.hub
    assert brief_workspace.git("status", "--porcelain", cwd=hub) == ""
    assert brief_workspace.git("rev-list", "--count", "HEAD..origin/trunk", cwd=hub) == "0"
    assert not (brief_workspace.ws / "ui").exists()


GOLDEN = Path(__file__).parent / "golden" / "brief"
TODAY = datetime.date(2026, 1, 15)
LONG_NOW = "---\nlast_verified: 2026-01-14\n---\n# Now\n" + "".join(
    f"- item {index:03d}: " + "keep the brief short and current " * 3 + "\n"
    for index in range(1, 61)
)
FRESH_NOW = "---\nlast_verified: 2026-01-12\n---\n# Now\nShip the collector.\nThen the CLI.\n"
JOURNAL = "brain/journal/2026/01/"
# Each case of hub tests/characterization/test_brief.py: the hub changes, the argv, the gh rules.
CASES: dict[str, dict[str, Any]] = {
    "fresh_network": {},
    "no_network": {"argv": ("--no-network",)},
    "stale_now": {"changes": {"brain/now.md": FRESH_NOW.replace("2026-01-12", "2026-01-11")}},
    "undated_now": {
        "changes": {"brain/now.md": FRESH_NOW.replace("last_verified: 2026-01-12", "type: now")}
    },
    "missing_now_no_journal": {
        "changes": {
            "brain/now.md": None,
            f"{JOURNAL}14.md": None,
            f"{JOURNAL}13.md": None,
            f"{JOURNAL}10.md": None,
            f"{JOURNAL}06.md": None,
            f"{JOURNAL}07.md": "## Eight days ago\n",
        }
    },
    "now_without_heading": {
        "changes": {
            "brain/now.md": (
                "---\nlast_verified: 2026-01-12\n---\nFirst content line.\nSecond content line.\n"
            )
        }
    },
    "truncated": {"changes": {"brain/now.md": LONG_NOW}},
    "gh_failing": {"answers": [{"stderr": "HTTP 503\n", "rc": 1}]},
    "journal_week_edge": {
        "changes": {
            f"{JOURNAL}14.md": None,
            f"{JOURNAL}13.md": None,
            f"{JOURNAL}10.md": None,
            f"{JOURNAL}06.md": None,
            f"{JOURNAL}08.md": "## Exactly seven days ago\n",
            f"{JOURNAL}07.md": "## Eight days ago\n",
        }
    },
}
PINNED_COMMAND = (
    "uvx --from git+https://github.com/jroquette/agent-hub@v0.0.1"
    "#subdirectory=packages/agent-hub hub"
)


@pytest.fixture(autouse=True)
def frozen_today(monkeypatch: pytest.MonkeyPatch) -> None:
    """Today is the hub goldens' frozen day; the cwd that ``run_brief`` changes is restored."""
    monkeypatch.setattr(brief_command, "today", lambda: TODAY)
    monkeypatch.chdir(Path.cwd())


def run_brief(workspace: Workspace, *args: str, cwd: Path | None = None, **env: str) -> Result:
    os.chdir(cwd or workspace.hub)
    return CliRunner().invoke(app, ["brief", *args], env=env or None)


def sorted_lines(data: bytes) -> list[bytes]:
    return sorted(data.splitlines())


def golden_of(case: str, golden_sections: Callable[[Path], dict[str, bytes]]) -> dict[str, bytes]:
    return golden_sections(GOLDEN / f"{case}.golden")


@pytest.mark.parametrize("case", list(CASES))
def test_matches_golden_when_case_runs(
    brief_workspace: Workspace,
    golden_sections: Callable[[Path], dict[str, bytes]],
    monkeypatch: pytest.MonkeyPatch,
    *,
    case: str,
) -> None:
    monkeypatch.chdir(brief_workspace.hub)
    setup = CASES[case]
    if "changes" in setup:
        brief_workspace.commit_hub(setup["changes"])
    if "answers" in setup:
        brief_workspace.answer(setup["answers"])
    golden = golden_of(case, golden_sections)

    result = run_brief(brief_workspace, *setup.get("argv", ()))

    assert result.exit_code == int(golden["rc"]), result.output
    assert result.stdout_bytes == golden["stdout"]
    assert result.stderr_bytes == golden["stderr"]
    # The calls run concurrently (plan E4): their order is not kept, each call is.
    assert sorted_lines(brief_workspace.calls()) == sorted_lines(golden["calls"])


def test_prints_reader_lines_when_hub_json_invalid(
    brief_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(brief_workspace.hub)
    document = json.loads((brief_workspace.hub / "hub.json").read_text())
    del document["tracker"]
    brief_workspace.commit_hub({"hub.json": json.dumps(document, indent=2) + "\n"})

    result = run_brief(brief_workspace)

    assert result.exit_code == 1
    assert result.stdout == ""
    lines = result.stderr.splitlines()
    assert lines
    assert all(line.startswith("hub.json: ") for line in lines), lines
    assert any("tracker" in line for line in lines), lines
    assert brief_workspace.calls() == b""


def test_refuses_when_pin_differs(
    brief_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(brief_workspace.hub)
    document = json.loads((brief_workspace.hub / "hub.json").read_text())
    document["platform"]["version"] = "0.0.1"
    brief_workspace.commit_hub({"hub.json": json.dumps(document, indent=2) + "\n"})

    result = run_brief(brief_workspace)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert PINNED_COMMAND in result.stderr
    assert brief_workspace.calls() == b""


def test_exits_two_when_not_a_hub(brief_workspace: Workspace) -> None:
    elsewhere = brief_workspace.root / "elsewhere"

    result = run_brief(brief_workspace, cwd=elsewhere)

    assert result.exit_code == 2
    assert result.stderr == (
        f"{elsewhere}: not a hub: no hub.json in this folder"
        " (hub brief runs in the hub folder or through ./hub)\n"
    )
    assert brief_workspace.calls() == b""


def test_uses_agent_hub_root_when_run_elsewhere(
    brief_workspace: Workspace, golden_sections: Callable[[Path], dict[str, bytes]]
) -> None:
    golden = golden_of("fresh_network", golden_sections)

    result = run_brief(
        brief_workspace,
        cwd=brief_workspace.root / "elsewhere",
        AGENT_HUB_ROOT=str(brief_workspace.hub),
    )

    assert result.exit_code == 0, result.output
    assert result.stdout_bytes == golden["stdout"]
    # gh runs in the hub whatever the caller's folder (plan E12).
    assert sorted_lines(brief_workspace.calls()) == sorted_lines(golden["calls"])


def test_keeps_repo_order_when_gh_answers_out_of_order(brief_workspace: Workspace) -> None:
    # The hub answers last, then api, then web: the reverse of the output order.
    brief_workspace.answer(
        [
            {"argv_has": ["pr", "acme/demo-hub"], "stdout": "#9 Hub change\n", "delay": 0.6},
            {"argv_has": ["run", "acme/demo-hub"], "stdout": "hub-ci\n", "delay": 0.6},
            *({**rule, "delay": 0.3} for rule in BRIEF_RULES[:2]),
            {"argv_has": ["pr", "acme/web"], "stdout": "#7 Web change\n"},
            {"argv_has": ["run", "acme/web"], "stdout": "web-ci\n"},
        ]
    )

    result = run_brief(brief_workspace)

    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    repos = lines[lines.index("## Repos") + 1 : lines.index("## Repos") + 9]
    assert repos == [
        "- hub: trunk, 0 changed file(s), 0 behind origin/trunk",
        "  open PRs: #9 Hub change",
        "  ⚠ failing on main: hub-ci",
        "- api: trunk, 2 changed file(s), 1 behind origin/trunk",
        "  open PRs: #41 Add login endpoint | #40 Refactor the session storage layer so that"
        " every adapter shares on | #38 Fix pagination | #37 Bump dependencies",
        "  ⚠ failing on main: build, lint",
        "- web: detached@dd68590, 0 changed file(s), ? behind origin/trunk",
        "  open PRs: #7 Web change",
    ]


def test_runs_gh_concurrently_when_network_on(
    brief_workspace: Workspace, golden_sections: Callable[[Path], dict[str, bytes]]
) -> None:
    # Every call waits at a barrier for all six: made one after another, the first would give up.
    folder = brief_workspace.root / "elsewhere" / "barrier"
    folder.mkdir()
    barrier = {"dir": str(folder), "count": 6, "wait": BARRIER_WAIT}
    brief_workspace.answer(
        [
            {"argv_has": ["acme/demo-hub"], "rc": 1, "barrier": barrier},
            *({**rule, "barrier": barrier} for rule in BRIEF_RULES),
        ]
    )

    result = run_brief(brief_workspace)

    assert result.exit_code == 0, result.output
    assert result.stdout_bytes == golden_of("fresh_network", golden_sections)["stdout"]
    assert len(list(folder.iterdir())) == 6


class TestNetwork:
    def test_calls_no_gh_when_no_network(
        self, brief_workspace: Workspace, golden_sections: Callable[[Path], dict[str, bytes]]
    ) -> None:
        result = run_brief(brief_workspace, "--no-network")

        assert result.exit_code == 0, result.output
        assert result.stdout_bytes == golden_of("no_network", golden_sections)["stdout"]
        assert brief_workspace.calls() == b""

    def test_prints_no_pr_line_when_gh_missing(
        self, brief_workspace: Workspace, golden_sections: Callable[[Path], dict[str, bytes]]
    ) -> None:
        (brief_workspace.root / "bin" / "gh").unlink()

        result = run_brief(brief_workspace)

        assert result.exit_code == 0, result.output
        assert result.stdout_bytes == golden_of("no_network", golden_sections)["stdout"]
        assert brief_workspace.calls() == b""


def test_writes_nothing_when_brief_runs(
    brief_workspace: Workspace, tree_digest: Callable[[Path], dict[str, Any]]
) -> None:
    indexes = sorted(brief_workspace.ws.glob("*/.git/index"))
    assert len(indexes) == 3
    before = tree_digest(brief_workspace.ws)
    stamps = [index.stat().st_mtime_ns for index in indexes]

    result = run_brief(brief_workspace)

    assert result.exit_code == 0, result.output
    assert tree_digest(brief_workspace.ws) == before
    assert [index.stat().st_mtime_ns for index in indexes] == stamps


def test_warns_undated_when_last_verified_invalid(brief_workspace: Workspace) -> None:
    now = FRESH_NOW.replace("2026-01-12", "2026-02-30")
    brief_workspace.commit_hub({"brain/now.md": now})

    result = run_brief(brief_workspace, "--no-network")

    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[3].startswith("> ⚠ now.md is undated: ")


def test_replaces_bytes_when_now_not_utf8(brief_workspace: Workspace) -> None:
    now = FRESH_NOW.encode().replace(b"Then the CLI.", b"Then the \xff CLI.")
    brief_workspace.commit_hub({"brain/now.md": now})

    result = run_brief(brief_workspace, "--no-network")

    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[4] == "Then the � CLI."


def test_keeps_journal_when_file_not_utf8(brief_workspace: Workspace) -> None:
    brief_workspace.commit_hub({f"{JOURNAL}13.md": b"## Fixed the \xff loader\n"})

    result = run_brief(brief_workspace, "--no-network")

    assert result.exit_code == 0, result.output
    assert "- 2026-01-13: Fixed the � loader" in result.stdout.splitlines()


def test_says_missing_when_now_is_folder(brief_workspace: Workspace) -> None:
    now = brief_workspace.hub / "brain" / "now.md"
    now.unlink()
    now.mkdir()

    result = run_brief(brief_workspace, "--no-network")

    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[2:5] == ["## Now", "(brain/now.md missing)", ""]


def test_says_not_found_when_git_is_link(brief_workspace: Workspace) -> None:
    api = brief_workspace.ws / "api"
    (api / ".git").rename(brief_workspace.root / "elsewhere" / "api.git")
    (api / ".git").symlink_to(brief_workspace.root / "elsewhere" / "api.git")

    result = run_brief(brief_workspace, "--no-network")

    assert result.exit_code == 0, result.output
    assert "- api: not found" in result.stdout.splitlines()


def test_ignores_git_dir_when_caller_sets_it(
    brief_workspace: Workspace,
    golden_sections: Callable[[Path], dict[str, bytes]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A decoy repo on another branch: read through GIT_DIR, every line would name it.
    decoy = brief_workspace.root / "elsewhere" / "decoy"
    decoy.mkdir()
    brief_workspace.git("init", "-q", "-b", "decoy", cwd=decoy)
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))

    result = run_brief(brief_workspace, "--no-network")

    assert result.exit_code == 0, result.output
    assert result.stdout_bytes == golden_of("no_network", golden_sections)["stdout"]


def test_prints_git_state_when_gh_hangs(
    brief_workspace: Workspace,
    golden_sections: Callable[[Path], dict[str, bytes]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Every gh call hangs far past the per-call timeout; the gh phase's budget ends them all.
    monkeypatch.setattr(brief_command, "GH_PHASE_BUDGET", 0.5)
    brief_workspace.answer([{"stdout": "#1 never shown\n", "delay": 120}])
    started = time.monotonic()

    result = run_brief(brief_workspace)

    assert result.exit_code == 0, result.output
    assert result.stdout_bytes == golden_of("no_network", golden_sections)["stdout"]
    assert len(brief_workspace.calls().splitlines()) == 6
    assert time.monotonic() - started < brief_command.BRIEF_GH_TIMEOUT


def test_skips_git_calls_when_git_budget_spent(
    brief_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No time left for git: each value is left out, as for a git that fails.
    monkeypatch.setattr(brief_command, "GIT_PHASE_BUDGET", 0)

    result = run_brief(brief_workspace, "--no-network")

    assert result.exit_code == 0, result.output
    repos = result.stdout.splitlines()
    assert "- hub: detached@, 0 changed file(s), ? behind origin/trunk" in repos
    assert "- api: detached@, 0 changed file(s), ? behind origin/trunk" in repos


def test_strips_control_characters_when_gh_prints_them(brief_workspace: Workspace) -> None:
    title = "#5 \x1b[31mRed\x1b[0m title\x07 done\x9b\n"
    brief_workspace.answer([{"argv_has": ["pr", "acme/api"], "stdout": title}])

    result = run_brief(brief_workspace)

    assert result.exit_code == 0, result.output
    assert "  open PRs: #5 [31mRed[0m title done" in result.stdout.splitlines()


def test_keeps_children_in_caller_group_when_brief_runs(brief_workspace: Workspace) -> None:
    # The SessionStart hook kills its call's process group on its deadline: gh must be in it.
    group_file = brief_workspace.root / "elsewhere" / "gh-group"
    brief_workspace.answer([{"argv_has": ["pr", "acme/api"], "group_file": str(group_file)}])

    result = run_brief(brief_workspace)

    assert result.exit_code == 0, result.output
    assert group_file.read_text() == str(os.getpgrp())
