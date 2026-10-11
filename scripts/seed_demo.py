"""``make demo``: load synthetic data into the running control plane, so every screen has content.

Against the app at ``--url`` (``make run`` or ``make up``), it:

1. reads the server's database path (``/api/v1/collector/status``);
2. makes a demo hub (``hub init demo``) with one feature folder, next to that database
   (``<database folder>/demo``), and registers it (``POST /api/v1/hubs``);
3. posts hook envelopes: a live session with a guard denial, and one waiting on a guard ask;
4. collects a failed ``hub run`` (``hub collect --runs``) and an ended session's transcript
   (``hub collect --transcript``) into the same database.

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
BACKFILL_SESSION = "demo-ended"
FAILED_RUN = "5e6f7a8b"
FEATURE = "export-button"
ALREADY_A_HUB = "already a hub"
# The hub-init flags, so git is never asked; all values are made up.
HUB_FLAGS = (
    "--repos",
    f"acme/{DEMO_REPO}",
    "--tracker",
    "linear:DEM",
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


def session_ids(now: datetime) -> tuple[str, str, str]:
    """The live, the waiting and the ended (backfilled) session of a run at ``now``."""
    suffix = f"{now:%Y%m%d%H%M%S}"
    return f"{LIVE_SESSION}-{suffix}", f"{ASK_SESSION}-{suffix}", f"{BACKFILL_SESSION}-{suffix}"


def demo_envelopes(now: datetime) -> list[dict[str, Any]]:
    """A live session that ran tools and had a push denied, and one waiting on a guard ask."""
    live_id, ask_id, _ = session_ids(now)
    live = {"session_id": live_id, "cwd": DEMO_CWD}
    ask = {"session_id": ask_id, "cwd": DEMO_CWD}
    edit = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": f"{DEMO_CWD}/src/export.py",
            "old_string_lines": 2,
            "new_string_lines": 9,
        },
        "tool_use_id": "toolu_demo_edit",
    }
    push = {
        "tool_name": "Bash",
        "tool_input": {"command": "git push origin main"},
        "tool_use_id": "toolu_demo_push",
    }
    adr = {
        "tool_name": "Edit",
        "tool_input": {"file_path": f"{DEMO_CWD}/docs/adr/0009-export.md"},
        "tool_use_id": "toolu_demo_adr",
    }
    deny = {"by": "guard", "kind": "deny", "rule": "push-to-main"}
    ask_decision = {"by": "guard", "kind": "ask", "rule": "ask_before_edit"}
    at = [now - timedelta(seconds=seconds) for seconds in (150, 140, 120, 110, 90, 80, 60, 30)]
    return [
        _envelope(a_hook_input("SessionStart") | live, repo=DEMO_REPO, at=at[0]),
        _envelope(a_hook_input("UserPromptSubmit") | live, repo=DEMO_REPO, at=at[1]),
        _envelope(a_hook_input("PreToolUse") | live, repo=DEMO_REPO, at=at[2]),
        _envelope(a_hook_input("PostToolUse") | live, repo=DEMO_REPO, at=at[3]),
        _envelope(a_hook_input("PreToolUse", **edit) | live, repo=DEMO_REPO, at=at[4]),
        _envelope(a_hook_input("PostToolUse", **edit) | live, repo=DEMO_REPO, at=at[5]),
        _envelope(
            a_hook_input("PreToolUse", **push) | live, repo=DEMO_REPO, at=at[6], decision=deny
        ),
        _envelope(a_hook_input("SessionStart") | ask, repo=DEMO_REPO, at=at[3]),
        _envelope(
            a_hook_input("PreToolUse", **adr) | ask,
            repo=DEMO_REPO,
            at=at[7],
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
        return {"timestamp": stamp, "sessionId": session, "uuid": f"{session}-{number:02d}"}

    calls = [
        ("toolu_demo_read", "Read", {"file_path": f"{DEMO_CWD}/src/export.py"}),
        ("toolu_demo_write", "Edit", {"file_path": f"{DEMO_CWD}/src/export.py"}),
        ("toolu_demo_test", "Bash", {"command": "make check-fast"}),
    ]
    lines = [a_user_line("add the CSV export button", **at())]
    for number, (tool_use_id, name, tool_input) in enumerate(calls, start=1):
        block = a_tool_use_block(tool_use_id, name, tool_input)
        usage = a_usage(2400 * number, 310, cache_read=18_000, cache_write=1_200)
        lines.append(an_assistant_line([block], usage, message_id=f"msg_demo_{number}", **at()))
        lines.append(a_tool_result_line(tool_use_id, content="ok", **at()))
    final = an_assistant_line(
        [a_text_block("Done: the button exports CSV.")],
        a_usage(9000, 120, cache_read=20_000),
        message_id="msg_demo_4",
        **at(),
    )
    lines.append(final)
    return transcript_text(lines)


def _feature_files(hub: PurePosixPath) -> dict[PurePosixPath, str]:
    folder = hub / "brain" / "features" / FEATURE
    acs = [
        {
            "id": f"AC-7.{index}",
            "description": f"Criterion {index}",
            "repo": DEMO_REPO,
            "verification": "make check",
            "passes": index < 3,
            "evidence": "test run" if index < 3 else None,
        }
        for index in (1, 2, 3)
    ]
    criteria = "".join(f"- AC-7.{index} Criterion {index}\n" for index in (1, 2, 3))
    spec = "---\ntype: spec\nprocess_size: bounded\nrepos: [demo-api]\nlinear: [DEM-7]\n---\n"
    return {
        folder / "features.json": json.dumps({"feature": FEATURE, "linear": ["DEM-7"], "acs": acs}),
        folder / "spec.md": f"{spec}# Export button\n\n{criteria}",
        folder / "plan.md": "# Plan\n",
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
    for path, text in _feature_files(hub).items():
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
