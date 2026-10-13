"""A stub ``claude`` CLI that speaks Claude Code's stream-json and control protocol (P17).

Run as ``python -m agent_hub.claude_sessions.testing.stub_claude`` (through the shim of
``scenarios.write_shim``). It reads its scenario from ``STUB_CLAUDE_SCENARIO`` and appends what it
sees to ``STUB_CLAUDE_RECORD``. It answers ``-v``/``--version`` and ``--help``, the non-interactive
``--cloud`` forms, and in ``--input-format stream-json`` mode plays one scripted turn per user
message: ``system/init``, partial text deltas (with ``--include-partial-messages``), assistant
blocks, ``can_use_tool`` control requests (with ``--permission-prompt-tool stdio``) and a
``result``. It answers ``initialize``, ``interrupt``, ``set_permission_mode`` and ``set_model``.

It never reaches the network and holds no real output: the shapes are synthetic rewrites of what
the Wave 0 spike observed from the local CLI.
"""

import json
import os
import signal
import subprocess
import sys
import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from agent_hub.claude_sessions.testing.scenarios import (
    ARGV0_ENV,
    RECORD_ENV,
    SCENARIO_ENV,
    DeltaStep,
    HoldStep,
    ResultStep,
    Scenario,
    Step,
    StubRecord,
    TextStep,
    ToolStep,
)

type Message = dict[str, Any]

HELP = """Usage: claude [options] [command] [prompt]

Options:
  -p, --print                           Print response and exit
  --input-format <format>               Input format (choices: "text", "stream-json")
  --output-format <format>              Output format (choices: "text", "json", "stream-json")
  --permission-mode <mode>              Permission mode to use for the session
  --session-id <uuid>                   Use a specific session ID for the conversation
"""
CLOUD_HELP = """  --cloud [description|session_id|url]  Create a cloud session, or attach to one
  --teleport [session]                  Resume a teleport session
"""
CLOUD_TTY_ERROR = "Error: --cloud requires an interactive terminal.\n"
# The CLI reports ``manual`` as ``default``, and ``auto`` when no mode is passed.
MODE_ALIASES = {"manual": "default"}
NO_MODE = "auto"


@dataclass
class _Options:
    """The flags the stub reads; anything else is recorded and ignored."""

    stream: bool = False
    partials: bool = False
    stdio_prompts: bool = False
    mode: str = NO_MODE
    model: str | None = None
    resume: str | None = None
    session_id: str | None = None
    fork: bool = False


def _flag_value(args: Sequence[str], index: int) -> tuple[str, str | None]:
    """``--flag=value`` or ``--flag value``: the flag and its value (None for a bare flag)."""
    arg = args[index]
    if "=" in arg:
        flag, _, value = arg.partition("=")
        return flag, value
    following = args[index + 1] if index + 1 < len(args) else None
    if following is None or following.startswith("-"):
        return arg, None
    return arg, following


def parse_options(args: Sequence[str]) -> _Options:
    """Read the stream-json session flags from ``args``."""
    options = _Options()
    for index, arg in enumerate(args):
        if not arg.startswith("--"):
            continue
        flag, value = _flag_value(args, index)
        _apply_flag(options, flag, value)
    return options


_SWITCHES = {"--include-partial-messages": "partials", "--fork-session": "fork"}
_VALUES = {"--model": "model", "--resume": "resume", "--session-id": "session_id"}


def _apply_flag(options: _Options, flag: str, value: str | None) -> None:
    if flag in _SWITCHES:
        setattr(options, _SWITCHES[flag], True)
    elif flag in _VALUES:
        setattr(options, _VALUES[flag], value)
    elif flag == "--input-format":
        options.stream = value == "stream-json"
    elif flag == "--permission-prompt-tool":
        options.stdio_prompts = value == "stdio"
    elif flag == "--permission-mode" and value is not None:
        options.mode = MODE_ALIASES.get(value, value)


@dataclass
class _Turn:
    """The steps left in the turn being played, and what it is parked on."""

    steps: Iterator[Step]
    parked_on: str | None = None
    tool: ToolStep | None = None
    text: str = ""


@dataclass
class StubSession:
    """The stream-json side of the stub: one instance per process."""

    scenario: Scenario
    options: _Options
    out: TextIO
    record: Path | None = None
    session_id: str = ""
    mode: str = NO_MODE
    model: str = ""
    turn: _Turn | None = None
    queued: list[str] = field(default_factory=list)
    turns_played: int = 0
    requests: int = 0

    def __post_init__(self) -> None:
        self.session_id = _session_id(self.scenario, self.options)
        self.mode = self.options.mode
        self.model = self.options.model or self.scenario.model

    @property
    def busy(self) -> bool:
        """A turn is open (playing or parked)."""
        return self.turn is not None

    def handle(self, message: Message) -> None:
        """React to one stdin message."""
        match message.get("type"):
            case "user":
                self._write_record("user", data={"text": _user_text(message)})
                self.queued.append(_user_text(message))
                self._start_next()
            case "control_request":
                self._control(message)
            case "control_response":
                self._permission_answer(message.get("response", {}))
            case _:
                pass

    # Turns.

    def _start_next(self) -> None:
        if self.turn is not None or not self.queued:
            return
        text = self.queued.pop(0)
        steps = self.scenario.replies.get(text)
        if steps is None:
            index = min(self.turns_played, len(self.scenario.turns) - 1)
            steps = self.scenario.turns[index] if self.scenario.turns else []
        self.turns_played += 1
        self.turn = _Turn(steps=iter(steps))
        self._emit(self._init())
        self._play()

    def _play(self) -> None:
        turn = self.turn
        while turn is not None and turn.parked_on is None:
            step = next(turn.steps, None)
            if step is None:
                self._finish(ResultStep())
                return
            self._step(turn, step)
            turn = self.turn

    def _step(self, turn: _Turn, step: Step) -> None:
        match step:
            case DeltaStep(text=text) if self.options.partials:
                self._emit(self._delta(text))
            case TextStep(text=text):
                turn.text = text
                self._emit(self._assistant([{"type": "text", "text": text}]))
            case ToolStep():
                self._tool(turn, step)
            case HoldStep():
                turn.parked_on = "hold"
            case ResultStep():
                self._finish(step)
            case _:
                pass

    def _tool(self, turn: _Turn, step: ToolStep) -> None:
        block = {"type": "tool_use", "id": step.tool_use_id, "name": step.name, "input": step.input}
        self._emit(self._assistant([block]))
        if not self.options.stdio_prompts:
            self._tool_result(step, "Permission prompts are not answered here.", is_error=True)
            return
        self.requests += 1
        request_id = f"stub-permission-{self.requests}"
        turn.parked_on, turn.tool = request_id, step
        request = {
            "subtype": "can_use_tool",
            "tool_name": step.name,
            "input": step.input,
            "permission_suggestions": step.suggestions,
            "tool_use_id": step.tool_use_id,
            "decision_reason": step.decision_reason,
            "display_name": step.name,
        }
        self._emit({"type": "control_request", "request_id": request_id, "request": request})

    def _permission_answer(self, response: Message) -> None:
        turn = self.turn
        if turn is None or turn.tool is None or response.get("request_id") != turn.parked_on:
            return
        answer = response.get("response") or {}
        self._write_record("control", subtype="can_use_tool_answer", data=answer)
        if answer.get("behavior") == "allow":
            self._tool_result(turn.tool, "ok", is_error=False)
        else:
            self._tool_result(turn.tool, str(answer.get("message", "denied")), is_error=True)
        turn.parked_on, turn.tool = None, None
        self._play()

    def _tool_result(self, step: ToolStep, content: str, *, is_error: bool) -> None:
        block = {
            "type": "tool_result",
            "tool_use_id": step.tool_use_id,
            "content": content,
            "is_error": is_error,
        }
        message = {"role": "user", "content": [block]}
        self._emit({"type": "user", "message": message, **self._ids(), "parent_tool_use_id": None})

    def _finish(self, step: ResultStep, *, terminal_reason: str = "completed") -> None:
        text = self.turn.text if self.turn is not None else ""
        self.turn = None
        self._emit(self._result(step, terminal_reason, text))
        self._start_next()

    # Control requests from the SDK.

    def _control(self, message: Message) -> None:
        request = message.get("request", {})
        subtype = str(request.get("subtype"))
        self._write_record("control", subtype=subtype, data=_json_object(request))
        response: Message = {}
        match subtype:
            case "initialize":
                response = self._capabilities()
            case "set_permission_mode":
                self.mode = MODE_ALIASES.get(request["mode"], request["mode"])
                self._emit(
                    {
                        "type": "system",
                        "subtype": "status",
                        "permissionMode": self.mode,
                        **self._ids(),
                    }
                )
            case "set_model":
                self.model = request.get("model") or self.scenario.model
            case "interrupt":
                self._interrupt()
            case _:
                pass
        payload = {
            "subtype": "success",
            "request_id": message.get("request_id"),
            "response": response,
        }
        self._emit({"type": "control_response", "response": payload})

    def _interrupt(self) -> None:
        turn = self.turn
        if turn is None:
            return
        reason = "aborted_tools" if turn.tool is not None else "aborted_streaming"
        self.queued.clear()
        self.turn = None
        self._emit(self._result(ResultStep(cost_usd=0.0), reason, ""))

    # Messages.

    def _ids(self) -> Message:
        return {"session_id": self.session_id, "uuid": str(uuid.uuid4())}

    def _init(self) -> Message:
        return {
            "type": "system",
            "subtype": "init",
            "cwd": str(Path.cwd()),
            "model": self.model,
            "permissionMode": self.mode,
            "slash_commands": self.scenario.slash_commands,
            "tools": ["Bash", "Edit", "Read", "Write", "AskUserQuestion", "ExitPlanMode"],
            "claude_code_version": self.scenario.version,
            "apiKeySource": "none",
            **self._ids(),
        }

    def _capabilities(self) -> Message:
        commands = [
            {"name": name, "description": "", "argumentHint": ""}
            for name in self.scenario.slash_commands
        ]
        models = [
            {"value": alias, "displayName": alias}
            for alias in ("default", "opus", "sonnet", "haiku")
        ]
        return {
            "commands": commands,
            "models": models,
            "current_permission_mode": self.mode,
            "pid": os.getpid(),
        }

    def _delta(self, text: str) -> Message:
        event = {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": text},
        }
        return {"type": "stream_event", "event": event, "parent_tool_use_id": None, **self._ids()}

    def _assistant(self, content: list[Message]) -> Message:
        message = {
            "id": f"msg_stub_{uuid.uuid4().hex[:12]}",
            "type": "message",
            "role": "assistant",
            "model": self.model,
            "content": content,
            "stop_reason": None,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        return {"type": "assistant", "message": message, "parent_tool_use_id": None, **self._ids()}

    def _result(self, step: ResultStep, terminal_reason: str, text: str) -> Message:
        completed = terminal_reason == "completed"
        usage = {"input_tokens": step.input_tokens, "output_tokens": step.output_tokens}
        return {
            "type": "result",
            "subtype": "success" if completed else "error_during_execution",
            "is_error": not completed,
            "duration_ms": 12,
            "duration_api_ms": 10,
            "num_turns": self.turns_played,
            "result": text,
            "stop_reason": "end_turn" if completed else None,
            "total_cost_usd": step.cost_usd,
            "usage": usage,
            "modelUsage": {self.model: {**usage, "costUSD": step.cost_usd}},
            "permission_denials": [],
            "terminal_reason": terminal_reason,
            **self._ids(),
        }

    def _emit(self, message: Message) -> None:
        self.out.write(json.dumps(message) + "\n")
        self.out.flush()

    def _write_record(
        self, event: str, *, subtype: str | None = None, data: Message | None = None
    ) -> None:
        line = {"event": event, "pid": os.getpid(), "subtype": subtype, "data": data or {}}
        _append(self.record, StubRecord.model_validate(line))


def _session_id(scenario: Scenario, options: _Options) -> str:
    if options.resume is not None:
        return scenario.fork_session_id if options.fork else options.resume
    return options.session_id or scenario.session_id


def _user_text(message: Message) -> str:
    content = message.get("message", {}).get("content", "")
    if isinstance(content, str):
        return content
    return " ".join(str(block.get("text", "")) for block in content if isinstance(block, dict))


def _json_object(value: object) -> Message:
    return value if isinstance(value, dict) else {}


def _append(record: Path | None, line: StubRecord) -> None:
    if record is None:
        return
    with record.open("a", encoding="utf-8") as handle:
        handle.write(line.model_dump_json() + "\n")


def load_scenario(environ: Mapping[str, str]) -> Scenario:
    """The scenario named by ``STUB_CLAUDE_SCENARIO``, or the default one."""
    path = environ.get(SCENARIO_ENV)
    if not path:
        return Scenario()
    return Scenario.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _spawn_grandchild() -> subprocess.Popen[bytes]:
    """A sleeping process in its own session, as the CLI starts its Bash tools."""
    argv = [sys.executable, "-c", "import time; time.sleep(300)"]
    return subprocess.Popen(argv, start_new_session=True)  # noqa: S603 - fixed argv, no shell


def _serve(session: StubSession, stdin: TextIO) -> None:
    for line in iter(stdin.readline, ""):
        if line.strip():
            session.handle(json.loads(line))
    if session.busy and session.scenario.linger_on_eof:
        signal.pause()


def _run_stream(
    scenario: Scenario, options: _Options, io: tuple[TextIO, TextIO], *, record: Path | None
) -> int:
    stdin, stdout = io
    grandchild = _spawn_grandchild() if scenario.grandchild else None
    spawned = grandchild.pid if grandchild is not None else None
    _append(record, StubRecord(event="spawn", pid=os.getpid(), grandchild_pid=spawned))
    session = StubSession(scenario=scenario, options=options, out=stdout, record=record)
    try:
        _serve(session, stdin)
    finally:
        if grandchild is not None and scenario.reap_grandchild:
            grandchild.kill()
            grandchild.wait()
    return 0


def _run_cloud(scenario: Scenario, args: Sequence[str], stdout: TextIO) -> int:
    if "-p" not in args and "--print" not in args:
        sys.stderr.write(CLOUD_TTY_ERROR)
        return 1
    stdout.write(scenario.cloud_output)
    return scenario.cloud_exit


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    environ: Mapping[str, str] = os.environ,
) -> int:
    """Run the stub with ``argv`` (default: this process's arguments); return the exit code."""
    args = list(sys.argv[1:] if argv is None else argv)
    scenario = load_scenario(environ)
    record = Path(environ[RECORD_ENV]) if environ.get(RECORD_ENV) else None
    start = StubRecord(
        event="start",
        pid=os.getpid(),
        argv0=environ.get(ARGV0_ENV),
        args=args,
        env_keys=sorted(environ),
    )
    _append(record, start)
    if "-v" in args or "--version" in args:
        stdout.write(f"{scenario.version} (Claude Code)\n")
        return 0
    if "--help" in args or "-h" in args:
        stdout.write(HELP + (CLOUD_HELP if scenario.cloud else ""))
        return 0
    if any(arg == "--cloud" or arg.startswith("--cloud=") for arg in args):
        return _run_cloud(scenario, args, stdout)
    options = parse_options(args)
    if not options.stream:
        sys.stderr.write("Error: the stub only speaks --input-format stream-json\n")
        return 1
    return _run_stream(scenario, options, (stdin, stdout), record=record)


def _exit_on_signal(signum: int, _frame: object) -> None:
    """SIGTERM ends the stub through ``finally``, so the grandchild is reaped as the CLI does."""
    raise SystemExit(128 + signum)


def run() -> int:
    """The process entry point: SIGTERM exits cleanly, then ``main``."""
    signal.signal(signal.SIGTERM, _exit_on_signal)
    return main()


if __name__ == "__main__":
    sys.exit(run())
