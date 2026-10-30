"""``make perf``'s CLI and hook probes: the canonical paths, their commands and inputs, ``measure``.

A ``Probe`` is one row's command: ``argv`` and the ``stdin`` text it reads. The CLI probes run the
worktree's ``hub`` and the temp hub's ``./hub``; the hook probes run each rendered hook of the temp
hub on ``python3``, as Claude Code does, with an input from ``a_hook_input`` whose ``cwd`` is the
temp hub and whose transcript is the synthetic one, so no real transcript is read. ``measure``
runs a probe ``runs`` times through an injected runner and returns each run's wall time in
milliseconds; a run that exits non-zero raises ``SuiteError`` naming the probe's path.

A probe's ``seed`` runs once, untimed, before its runs. The ``session_start`` row's seed writes the
brief cache with ``hub brief --write-cache`` through the temp hub's ``uvx`` stand-in, so every run
reads a cache under the hook's 5 min refresh floor and starts no refresh: the warm path ADR 0055
names, with no background load between runs.
"""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from agent_hub.core.testing.hook_inputs import a_hook_input

CLI = "cli"
HOOK = "hook"
HUB_VERSION = "hub --version"
LOCAL_HUB_VERSION = "./hub --version (local uvx stand-in)"
HUB_BRIEF = "hub brief --no-network"
# The list commands, run in the temp hub: each row's path is its command line.
LIST_COMMANDS = (
    "hub repo list",
    "hub env list",
    "hub action list",
    "hub scenario list",
    "hub workflow list",
)
CLI_PATHS = (HUB_VERSION, LOCAL_HUB_VERSION, HUB_BRIEF, *LIST_COMMANDS)
SESSION_START = "session_start (local uvx stand-in)"
# Written once before the session_start runs; the stand-in runs the worktree's hub, offline.
BRIEF_CACHE_SEED = ("uvx", "hub", "brief", "--write-cache", "--no-network")
# (path, hook script, hook event); post_edit's input is an Edit of a hub file.
_HOOKS = (
    ("guard (PreToolUse Bash)", "guard", "PreToolUse"),
    ("event_sensor (PreToolUse, sensor closed)", "event_sensor", "PreToolUse"),
    ("post_edit (PostToolUse Edit)", "post_edit", "PostToolUse"),
    ("readonly_gate (PreToolUse Bash)", "readonly_gate", "PreToolUse"),
    ("session_end", "session_end", "SessionEnd"),
    ("stop_gate (no changes)", "stop_gate", "Stop"),
    (SESSION_START, "session_start", "SessionStart"),
    ("pre_compact", "pre_compact", "PreCompact"),
)
HOOK_PATHS = tuple(path for path, _script, _event in _HOOKS)
HOOKS_DIR = ("plugin", "hub-workflow", "hooks")
# The hub file post_edit is told was edited; ``hub init`` writes it.
EDITED_FILE = ("brain", "index.md")


class SuiteError(Exception):
    """The suite itself failed (a probe broke): ``make perf`` exits 2."""


@dataclass(frozen=True)
class Probe:
    """One row's command; ``stdin`` is the text it reads, ``None`` for none; ``seed`` runs once
    before the timed runs, ``None`` for none."""

    kind: str
    path: str
    argv: tuple[str, ...]
    stdin: str | None
    seed: tuple[str, ...] | None = None


class Completed(Protocol):
    @property
    def returncode(self) -> int: ...


class Runner(Protocol):
    """Runs ``argv`` with ``stdin`` to the end; the real one wraps ``subprocess.run``."""

    def __call__(self, argv: Sequence[str], stdin: str | None = None) -> Completed: ...


def cli_probes(hub_bin: Path, hub_dir: Path) -> list[Probe]:
    """The CLI rows: the worktree's ``hub`` and the temp hub's ``./hub``."""
    return [
        Probe(CLI, HUB_VERSION, (str(hub_bin), "--version"), None),
        Probe(CLI, LOCAL_HUB_VERSION, (str(hub_dir / "hub"), "--version"), None),
        Probe(CLI, HUB_BRIEF, (str(hub_bin), "brief", "--no-network"), None),
        *(Probe(CLI, path, (str(hub_bin), *path.split()[1:]), None) for path in LIST_COMMANDS),
    ]


def hook_probes(hub_dir: Path, transcript: Path) -> list[Probe]:
    """The hook rows: each hook of ``hub_dir`` on ``python3``, its input from the temp hub."""
    hooks = hub_dir.joinpath(*HOOKS_DIR)
    return [
        Probe(
            HOOK,
            path,
            ("python3", str(hooks / f"{script}.py")),
            json.dumps(_hook_input(script, event, hub_dir=hub_dir, transcript=transcript)),
            BRIEF_CACHE_SEED if path == SESSION_START else None,
        )
        for path, script, event in _HOOKS
    ]


def _hook_input(script: str, event: str, *, hub_dir: Path, transcript: Path) -> dict[str, Any]:
    overrides: dict[str, Any] = {
        "session_id": transcript.stem,
        "cwd": str(hub_dir),
        "transcript_path": str(transcript),
    }
    if script == "post_edit":
        edited = str(hub_dir.joinpath(*EDITED_FILE))
        overrides |= {
            "tool_name": "Edit",
            "tool_input": {"file_path": edited, "old_string": "# ", "new_string": "# "},
            "tool_response": {"filePath": edited, "success": True},
        }
    return a_hook_input(event, **overrides)


def measure(probe: Probe, *, runs: int, runner: Runner, clock: Callable[[], float]) -> list[float]:
    """Run ``probe``'s seed once, then ``probe`` ``runs`` times; each run's duration in ms
    (``clock`` reads seconds)."""
    if probe.seed is not None:
        seeded = runner(probe.seed, stdin=None)
        if seeded.returncode != 0:
            raise SuiteError(f"{probe.path}: seed exited {seeded.returncode}")
    samples = []
    for _ in range(runs):
        start = clock()
        completed = runner(probe.argv, stdin=probe.stdin)
        elapsed = clock() - start
        if completed.returncode != 0:
            raise SuiteError(f"{probe.path}: exited {completed.returncode}")
        samples.append(elapsed * 1000)
    return samples
