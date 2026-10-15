"""Synthetic scenarios for the stub ``claude`` CLI (P17), and the files a test hands it.

A scenario scripts what the stub does: one list of steps per user message (a turn: the one
``replies`` holds for the message's exact text, else the next of ``turns``), the session id it
reports, and its process behaviour (a grandchild to reap, lingering after stdin closes). The
shapes mirror what the local Claude Code CLI writes in stream-json mode, observed by the Wave 0
spike against a fake Messages API (no model call); every value here is synthetic.

A test writes the scenario with ``write_scenario``, a ``claude`` shim with ``write_shim`` and points
the SDK's ``cli_path`` (or ``PATH``) at the shim; ``read_records`` returns what the stub saw.
"""

import os
import stat
import sys
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

SCENARIO_ENV = "STUB_CLAUDE_SCENARIO"
RECORD_ENV = "STUB_CLAUDE_RECORD"
ARGV0_ENV = "STUB_CLAUDE_ARGV0"
STUB_MODULE = "agent_hub.claude_sessions.testing.stub_claude"
# Synthetic ids in the CLI's formats; no real session.
SESSION_ID = "00000000-0000-4000-8000-000000000001"
FORK_SESSION_ID = "00000000-0000-4000-8000-000000000002"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DeltaStep(_Frozen):
    """A partial text chunk (a ``stream_event`` text delta), sent only with partial messages."""

    kind: Literal["delta"] = "delta"
    text: str


class TextStep(_Frozen):
    """A complete assistant text block."""

    kind: Literal["text"] = "text"
    text: str


class ToolStep(_Frozen):
    """An assistant ``tool_use`` block, then a ``can_use_tool`` request the turn parks on."""

    kind: Literal["tool"] = "tool"
    name: str
    input: dict[str, JsonValue]
    tool_use_id: str = "toolu_stub_1"
    suggestions: list[dict[str, JsonValue]] = Field(default_factory=list)
    decision_reason: str | None = None


class HoldStep(_Frozen):
    """The turn stays open (a long stream or tool) until an interrupt ends it."""

    kind: Literal["hold"] = "hold"


class ResultStep(_Frozen):
    """The ``result`` message that ends the turn."""

    kind: Literal["result"] = "result"
    cost_usd: float = 0.0012
    input_tokens: int = 10
    output_tokens: int = 5


Step = Annotated[
    DeltaStep | TextStep | ToolStep | HoldStep | ResultStep, Field(discriminator="kind")
]


class Scenario(_Frozen):
    """What the stub answers and how it behaves as a process."""

    version: str = "2.1.296"
    session_id: str = SESSION_ID
    fork_session_id: str = FORK_SESSION_ID
    model: str = "claude-stub-model"
    slash_commands: list[str] = Field(default_factory=lambda: ["compact", "review"])
    turns: list[list[Step]] = Field(default_factory=list)
    # The turn played for a user message of exactly this text; other messages play ``turns``.
    replies: dict[str, list[Step]] = Field(default_factory=dict)
    # A sleeping grandchild in its own session, as the CLI runs its Bash tools.
    grandchild: bool = False
    # The CLI ends its tool processes when it exits; False leaves the grandchild behind.
    reap_grandchild: bool = True
    # Stay alive after stdin closes while a turn is open (the CLI with a running tool).
    linger_on_eof: bool = False
    # ``--help`` lists ``--cloud`` and ``--teleport``.
    cloud: bool = True
    # ``-p ... --cloud <id>``: stdout and exit code.
    cloud_output: str = ""
    cloud_exit: int = 0


class StubRecord(_Frozen):
    """One line the stub appends to its record file: a start, a spawn, a control request or a
    user message (with ``images``, each one's media type and decoded size, when it had any)."""

    event: Literal["start", "spawn", "control", "user"]
    pid: int
    argv0: str | None = None
    args: list[str] = Field(default_factory=list)
    env_keys: list[str] = Field(default_factory=list)
    grandchild_pid: int | None = None
    subtype: str | None = None
    data: dict[str, JsonValue] = Field(default_factory=dict)
    images: list[dict[str, JsonValue]] | None = None


def simple_turn(text: str = "Hello from the stub.") -> list[Step]:
    """Two text deltas, the full text, then a result: the first scenario of S.1."""
    middle = len(text) // 2
    return [
        DeltaStep(text=text[:middle]),
        DeltaStep(text=text[middle:]),
        TextStep(text=text),
        ResultStep(),
    ]


def local_settings_rule(tool: str, rule: str) -> dict[str, JsonValue]:
    """A permission suggestion that would add an allow rule to ``.claude/settings.local.json``."""
    return {
        "type": "addRules",
        "destination": "localSettings",
        "rules": [{"toolName": tool, "ruleContent": rule}],
        "behavior": "allow",
    }


def permission_turn(command: str = "npm run build") -> list[Step]:
    """A Bash call that needs approval, with the CLI's "always allow" suggestion, then a reply."""
    tool = ToolStep(
        name="Bash",
        input={"command": command, "description": "Run the build"},
        suggestions=[local_settings_rule("Bash", "npm run *")],
        decision_reason="This command requires approval",
    )
    return [tool, TextStep(text="The build ran."), ResultStep()]


def held_turn() -> list[Step]:
    """A turn that streams a little and then holds until it is interrupted."""
    return [DeltaStep(text="Working on it"), HoldStep()]


def write_scenario(directory: Path, scenario: Scenario) -> Path:
    """Write ``scenario`` as JSON in ``directory``; the path goes in ``STUB_CLAUDE_SCENARIO``."""
    path = directory / "stub-scenario.json"
    path.write_text(scenario.model_dump_json(), encoding="utf-8")
    return path


def write_shim(directory: Path, python: str = sys.executable) -> Path:
    """Write an executable ``claude`` in ``directory`` that runs the stub with this Python.

    The shim exports its own path as ``STUB_CLAUDE_ARGV0``, so a test can prove which ``claude``
    ran (the shim, not a bundled binary).
    """
    directory.mkdir(parents=True, exist_ok=True)
    shim = directory / "claude"
    script = f'#!/bin/sh\nSTUB_CLAUDE_ARGV0="$0" exec "{python}" -m {STUB_MODULE} "$@"\n'
    shim.write_text(script, encoding="utf-8")
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return shim


def stub_environment(scenario_path: Path, record_path: Path) -> dict[str, str]:
    """This process's environment plus the two variables the stub reads."""
    return {**os.environ, SCENARIO_ENV: str(scenario_path), RECORD_ENV: str(record_path)}


def read_records(record_path: Path) -> list[StubRecord]:
    """Every record the stub appended, oldest first; empty when it never ran."""
    if not record_path.exists():
        return []
    lines = record_path.read_text(encoding="utf-8").splitlines()
    return [StubRecord.model_validate_json(line) for line in lines if line]
