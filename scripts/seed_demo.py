"""``make demo``: load synthetic data into the running control plane, so every screen has content.

Against the app at ``--url`` (``make run`` or ``make up``), it:

1. reads the server's database path (``/api/v1/collector/status``);
2. makes a demo hub (``hub init demo``, tracker team ``AGH``) with a feature folder (spec, plan,
   eval, ``features.json``) and an inbox note, next to that database
   (``<database folder>/demo``), and registers it (``POST /api/v1/hubs``);
3. posts hook envelopes: a live ``/feature`` session for AGH-7 (its worktree names the issue)
   that runs a Skill, starts an ``Explore`` subagent, recovers from a failed check (a problem
   the agent handled) and has a push denied; an idle session whose failed ``make test`` needs
   you; and one waiting on a guard ask;
4. collects a failed ``hub run`` (``hub collect --runs``) and an ended session's transcript
   (``hub collect --transcript``, on branch ``demo/agh-7-demo-feature``, proposing the inbox
   note) into the same database.

Everything is synthetic, built from ``agent_hub.core.testing``; nothing is read from
``~/.claude``. ``--via compose`` runs ``hub`` and writes the files inside the Compose service
(``docker compose exec``); ``--via local`` runs the workspace's ``hub``; ``auto`` (the default)
picks compose when the service is running. Running it again adds fresh live events; the rest
is found already there. Exits 0 when everything is loaded, 1 otherwise.
"""

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

import httpx

from agent_hub.core.testing.hook_inputs import a_hook_input
from agent_hub.core.testing.run_lines import run_lines_failed_in_verify
from agent_hub.core.testing.transcript_lines import (
    a_text_block,
    a_tool_result_line,
    a_tool_use_block,
    a_usage,
    a_user_line,
    an_assistant_line,
    transcript_text,
)

DEFAULT_URL = "http://127.0.0.1:7420"
REQUEST_SECONDS = 10
COMMAND_SECONDS = 120
SERVICE = "agent-hub"
CONTAINER_DEMO_DIR = PurePosixPath("/data/demo")
DEMO_PROJECT = "demo"
DEMO_REPO = "demo-api"
DEMO_CWD = "/work/demo-api"
# Each run's sessions get the run's time as a suffix: events are keyed by session (and hook and
# tool use, or transcript line), so a second run's fresh events must not reuse the first's keys.
LIVE_SESSION = "demo-live"
ASK_SESSION = "demo-ask"
STUCK_SESSION = "demo-stuck"
BACKFILL_SESSION = "demo-ended"
FAILED_RUN = "5e6f7a8b"
FEATURE = "export-button"
ISSUE = "AGH-7"
# The feature's branch and worktree name the issue, so sessions read "AGH-7 · /feature".
DEMO_BRANCH = "demo/agh-7-demo-feature"
WORKTREE_CWD = f"{DEMO_CWD}/.claude/worktrees/agh-7-demo-feature"
INBOX_NOTE = "brain/_inbox/csv-header-order.md"
INBOX_TEXT = """\
---
kind: team
provenance: agent
---
# Keep the CSV header in the order of the table columns

The export test failed because the CSV header listed the columns alphabetically while the rows
followed the table's order. Build the header from the same column list as the rows, so both
always agree.
"""
ALREADY_A_HUB = "already a hub"
# The hub-init flags, so git is never asked; all values are made up.
HUB_FLAGS = (
    "--repos",
    f"acme/{DEMO_REPO}",
    "--tracker",
    "linear:AGH",
    "--branch-prefix",
    "demo/",
    "--hub-repo",
    "acme/demo-hub",
    "--author-name",
    "Demo Author",
    "--author-email",
    "demo@example.com",
)

type Runner = Callable[[list[str], str | None], subprocess.CompletedProcess[str]]


class SeedError(Exception):
    """A step failed; the message is the line to print."""


class Target(Protocol):
    """Where the demo's files are written and its ``hub`` commands run."""

    @property
    def workdir(self) -> PurePosixPath: ...

    def write(self, path: PurePosixPath, text: str) -> None: ...

    def hub(self, arguments: Sequence[str]) -> subprocess.CompletedProcess[str]: ...


def _run(command: list[str], stdin: str | None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, input=stdin, capture_output=True, text=True, timeout=COMMAND_SECONDS, check=False
    )


class LocalTarget:
    """The workspace's ``hub`` (beside this interpreter) and the local file system."""

    def __init__(self, *, workdir: PurePosixPath, runner: Runner = _run) -> None:
        self.workdir = workdir
        self._runner = runner

    def write(self, path: PurePosixPath, text: str) -> None:
        local = Path(path)
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text(text, encoding="utf-8")

    def hub(self, arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return self._runner([str(Path(sys.executable).with_name("hub")), *arguments], None)


class ComposeTarget:
    """``hub`` and files inside the running Compose service, through ``docker compose exec``."""

    def __init__(
        self, *, workdir: PurePosixPath = CONTAINER_DEMO_DIR, runner: Runner = _run
    ) -> None:
        self.workdir = workdir
        self._runner = runner
        self._exec = ["docker", "compose", "exec", "-T", SERVICE]

    def write(self, path: PurePosixPath, text: str) -> None:
        script = 'mkdir -p "$(dirname "$1")" && cat > "$1"'
        result = self._runner([*self._exec, "sh", "-c", script, "sh", str(path)], text)
        if result.returncode != 0:
            raise SeedError(f"writing {path} in the container failed: {result.stderr.strip()}")

    def hub(self, arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return self._runner([*self._exec, "hub", *arguments], None)


def compose_running() -> bool:
    """Whether the Compose service of this repo is running."""
    docker = shutil.which("docker")
    if docker is None:
        return False
    command = [docker, "compose", "ps", "--status", "running", "-q", SERVICE]
    try:
        result = _run(command, None)
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def choose_target(via: str, *, compose_running: bool, db_path: str) -> Target:
    """``compose`` (or ``auto`` with the service running) runs in the container; else local,
    with the demo folder next to the server's database."""
    if via == "compose" or (via == "auto" and compose_running):
        return ComposeTarget()
    return LocalTarget(workdir=PurePosixPath(db_path).parent / "demo")


def _envelope(hook: dict[str, Any], *, repo: str, at: datetime, **extra: Any) -> dict[str, Any]:
    return {
        "v": 1,
        "project": DEMO_PROJECT,
        "repo": repo,
        "run": None,
        "step": None,
        "attempt": None,
        "sent_at": at.isoformat(),
        "hook": hook,
    } | extra


def session_ids(now: datetime) -> tuple[str, str, str, str]:
    """The live, the waiting, the ended (backfilled) and the idle session of a run at ``now``."""
    suffix = f"{now:%Y%m%d%H%M%S}"
    return (
        f"{LIVE_SESSION}-{suffix}",
        f"{ASK_SESSION}-{suffix}",
        f"{BACKFILL_SESSION}-{suffix}",
        f"{STUCK_SESSION}-{suffix}",
    )


def _tool(name: str, tool_input: dict[str, Any], tool_use_id: str) -> dict[str, Any]:
    return {"tool_name": name, "tool_input": tool_input, "tool_use_id": tool_use_id}


def _live_steps() -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """The live session's hooks in order: ``/feature`` (a Skill call), an ``Explore`` subagent
    started by an Agent call, a failed check the agent fixed, an edit, a push the guard denied."""
    explore = {"agent_id": "agent-demo-1", "agent_type": "Explore"}
    skill = _tool("Skill", {"skill": "feature"}, "toolu_demo_skill")
    agent = _tool(
        "Agent",
        {
            "subagent_type": "Explore",
            "description": "Find the CSV export code",
            "prompt": "Where is the CSV export built?",
        },
        "toolu_demo_agent",
    )
    grep = _tool("Grep", {"pattern": "def export_csv", "path": "src"}, "toolu_demo_grep")
    check = {"command": "make check-fast", "description": "Run the fast gate"}
    failed = _tool("Bash", check, "toolu_demo_check_1")
    passed = _tool("Bash", check, "toolu_demo_check_2")
    error = "Exit code 2\nFAILED tests/test_export.py::test_csv_header - columns out of order"
    edit = _tool(
        "Edit",
        {
            "file_path": f"{WORKTREE_CWD}/src/export.py",
            "old_string_lines": 2,
            "new_string_lines": 9,
        },
        "toolu_demo_edit",
    )
    push = _tool("Bash", {"command": "git push origin main"}, "toolu_demo_push")
    deny = {"by": "guard", "kind": "deny", "rule": "push-to-main"}
    return [
        ("SessionStart", {}, {}),
        ("UserPromptSubmit", {"prompt": "/feature add the CSV export button"}, {}),
        ("PreToolUse", skill, {}),
        ("PostToolUse", skill, {}),
        ("PreToolUse", agent, {}),
        ("SubagentStart", explore, {}),
        ("PreToolUse", grep | explore, {}),
        ("PostToolUse", grep | explore, {}),
        ("SubagentStop", explore, {}),
        ("PostToolUse", agent, {}),
        ("PreToolUse", edit, {}),
        ("PostToolUse", edit, {}),
        ("PreToolUse", failed, {}),
        ("PostToolUseFailure", failed | {"error": error}, {}),
        ("PreToolUse", passed, {}),
        ("PostToolUse", passed, {}),
        ("PreToolUse", push, {"decision": deny}),
    ]


def demo_envelopes(now: datetime) -> list[dict[str, Any]]:
    """The live AGH-7 session, an idle one whose failed test needs you, and one waiting on a
    guard ask."""
    live_id, ask_id, _, stuck_id = session_ids(now)
    live = {"session_id": live_id, "cwd": WORKTREE_CWD}
    ask = {"session_id": ask_id, "cwd": DEMO_CWD}
    stuck = {"session_id": stuck_id, "cwd": DEMO_CWD}
    adr = {
        "tool_name": "Edit",
        "tool_input": {"file_path": f"{DEMO_CWD}/docs/adr/0009-export.md"},
        "tool_use_id": "toolu_demo_adr",
    }
    test = _tool("Bash", {"command": "make test"}, "toolu_demo_test")
    test_error = "Exit code 1\nAssertionError: expected 3 rows, got 2"
    ask_decision = {"by": "guard", "kind": "ask", "rule": "ask_before_edit"}
    steps = _live_steps()
    live_envelopes = [
        _envelope(
            a_hook_input(name, **fields) | live,
            repo=DEMO_REPO,
            at=now - timedelta(seconds=8 * (len(steps) - index)),
            **extra,
        )
        for index, (name, fields, extra) in enumerate(steps)
    ]
    minutes = [now - timedelta(minutes=minutes) for minutes in (12, 11, 10)]
    return [
        *live_envelopes,
        _envelope(a_hook_input("SessionStart") | stuck, repo=DEMO_REPO, at=minutes[0]),
        _envelope(a_hook_input("PreToolUse", **test) | stuck, repo=DEMO_REPO, at=minutes[1]),
        _envelope(
            a_hook_input("PostToolUseFailure", **test, error=test_error) | stuck,
            repo=DEMO_REPO,
            at=minutes[2],
        ),
        _envelope(
            a_hook_input("SessionStart") | ask, repo=DEMO_REPO, at=now - timedelta(seconds=110)
        ),
        _envelope(
            a_hook_input("PreToolUse", **adr) | ask,
            repo=DEMO_REPO,
            at=now - timedelta(seconds=30),
            decision=ask_decision,
        ),
    ]


def demo_transcript(now: datetime) -> str:
    """An ended session's transcript: read, edit and test, with token usage (an estimated cost)."""
    session = session_ids(now)[2]
    start = now - timedelta(hours=2)
    numbers = iter(range(1, 20))

    def at() -> dict[str, Any]:
        number = next(numbers)
        stamp = (start + timedelta(seconds=20 * number)).isoformat().replace("+00:00", "Z")
        return {
            "timestamp": stamp,
            "sessionId": session,
            "uuid": f"{session}-{number:02d}",
            "cwd": DEMO_CWD,
            "gitBranch": DEMO_BRANCH,
        }

    note = {"file_path": f"/work/demo-hub/{INBOX_NOTE}", "content": INBOX_TEXT}
    calls = [
        ("toolu_demo_read", "Read", {"file_path": f"{DEMO_CWD}/src/export.py"}),
        ("toolu_demo_write", "Edit", {"file_path": f"{DEMO_CWD}/src/export.py"}),
        ("toolu_demo_test", "Bash", {"command": "make check-fast"}),
        # The same tool use id every run, so a second run proposes the same learning.
        ("toolu_demo_note", "Write", note),
    ]
    lines = [a_user_line("/feature add the CSV export button", **at())]
    for number, (tool_use_id, name, tool_input) in enumerate(calls, start=1):
        block = a_tool_use_block(tool_use_id, name, tool_input)
        usage = a_usage(2400 * number, 310, cache_read=18_000, cache_write=1_200)
        lines.append(an_assistant_line([block], usage, message_id=f"msg_demo_{number}", **at()))
        lines.append(a_tool_result_line(tool_use_id, content="ok", **at()))
    final = an_assistant_line(
        [a_text_block("Done: the button exports CSV.")],
        a_usage(9000, 120, cache_read=20_000),
        message_id="msg_demo_5",
        **at(),
    )
    lines.append(final)
    return transcript_text(lines)


def _hub_files(hub: PurePosixPath) -> dict[PurePosixPath, str]:
    """The feature folder (spec, plan, eval, ``features.json``) and the proposed inbox note."""
    folder = hub / "brain" / "features" / FEATURE
    acs = [
        {
            "id": f"AC-7.{index}",
            "description": description,
            "repo": DEMO_REPO,
            "verification": "make check",
            "passes": index < 3,
            "evidence": "test run" if index < 3 else None,
        }
        for index, description in enumerate(
            (
                "The sessions list has an Export CSV button",
                "The CSV header follows the table's column order",
                "An export of 10,000 rows finishes in under 2 s",
            ),
            start=1,
        )
    ]
    criteria = "".join(f"- {ac['id']} {ac['description']}\n" for ac in acs)
    spec = f"---\ntype: spec\nprocess_size: bounded\nrepos: [{DEMO_REPO}]\nlinear: [{ISSUE}]\n---\n"
    record = {"feature": FEATURE, "linear": [ISSUE], "acs": acs}
    return {
        folder / "features.json": json.dumps(record, indent=2) + "\n",
        folder / "spec.md": (
            f"{spec}# Export button\n\nLet the owner export the sessions list as CSV.\n\n"
            f"## Acceptance criteria\n\n{criteria}"
        ),
        folder / "plan.md": (
            "# Plan\n\n1. Add the export route (`GET /sessions.csv`).\n"
            "2. Build the header and the rows from one column list.\n"
            "3. Add the button to the sessions list.\n"
        ),
        folder / "eval.md": (
            "# Eval\n\n**Verdict: SHIP-WITH-OWNER-STEPS**\n\n"
            "AC-7.1 and AC-7.2 pass by command; AC-7.3 needs a timing on the owner's machine.\n"
        ),
        hub / INBOX_NOTE: INBOX_TEXT,
    }


def _checked_hub(target: Target, arguments: Sequence[str], *, tolerate: str = "") -> None:
    result = target.hub(arguments)
    if result.returncode != 0 and not (tolerate and tolerate in result.stderr):
        raise SeedError(f"hub {arguments[0]} failed: {result.stderr.strip()}")


def seed(client: httpx.Client, target: Target, *, db_path: str, now: datetime) -> None:
    """Every step of the demo against ``client``'s server, files and commands on ``target``."""
    hub = target.workdir / "demo-hub"
    _checked_hub(
        target, ["init", DEMO_PROJECT, *HUB_FLAGS, "--dir", str(hub)], tolerate=ALREADY_A_HUB
    )
    for path, text in _hub_files(hub).items():
        target.write(path, text)
    registered = client.post("/api/v1/hubs", json={"path": str(hub)})
    if registered.status_code not in {httpx.codes.CREATED, httpx.codes.CONFLICT}:
        raise SeedError(f"registering {hub} failed: {registered.status_code} {registered.text}")
    for envelope in demo_envelopes(now):
        posted = client.post("/api/v1/events/hooks", json=envelope)
        if posted.status_code != httpx.codes.ACCEPTED:
            raise SeedError(f"posting a hook event failed: {posted.status_code} {posted.text}")
    labels = ["--project", DEMO_PROJECT, "--db", db_path]
    runs = target.workdir / "runs" / "2026-10-11.jsonl"
    records = run_lines_failed_in_verify(run_id=FAILED_RUN)
    target.write(runs, "".join(json.dumps(record) + "\n" for record in records))
    _checked_hub(target, ["collect", "--runs", str(runs), *labels])
    transcript = target.workdir / "transcripts" / f"{session_ids(now)[2]}.jsonl"
    target.write(transcript, demo_transcript(now))
    _checked_hub(target, ["collect", "--transcript", str(transcript), *labels])


def main(
    argv: Sequence[str] | None = None,
    *,
    target: Target | None = None,
    transport: httpx.BaseTransport | None = None,
) -> int:
    """Load the demo; see the module docstring for the steps and exit codes."""
    arguments = _parser().parse_args(argv)
    url: str = arguments.url.rstrip("/")
    try:
        with httpx.Client(base_url=url, timeout=REQUEST_SECONDS, transport=transport) as client:
            status = client.get("/api/v1/collector/status")
            status.raise_for_status()
            db_path = str(status.json()["db_path"])
            chosen = target or choose_target(
                arguments.via, compose_running=compose_running(), db_path=db_path
            )
            seed(client, chosen, db_path=db_path, now=datetime.now(UTC))
    except httpx.HTTPError:
        print(
            f"error: no agent-hub answers at {url}; start it with make up or make run",
            file=sys.stderr,
        )
        return 1
    except SeedError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"demo data loaded: open {url}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.seed_demo", description=__doc__)
    parser.add_argument(
        "--url", default=DEFAULT_URL, help=f"the control plane (default {DEFAULT_URL})"
    )
    parser.add_argument(
        "--via",
        choices=("auto", "compose", "local"),
        default="auto",
        help="where hub runs: the Compose service, the workspace, or auto (default)",
    )
    return parser


if __name__ == "__main__":
    sys.exit(main())
