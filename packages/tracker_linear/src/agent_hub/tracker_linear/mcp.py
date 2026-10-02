"""The ``TrackerClient`` port over the user's Linear MCP server, through ``claude -p`` (ADR 0015).

Each port operation is one or more short headless ``claude -p`` calls (``mcp_protocol``): a
read is one call; a write is one read call, then the adapter decides, then at most one write
call. Every call runs in ``cwd`` (the hub root) with the caller's environment minus
``LINEAR_API_KEY``, under the caps given to the constructor (D9), with every hook off and no
session saved, in permission mode ``dontAsk``, with no built-in tool, the Linear tools its kind
needs allowed and every other Linear tool of the snapshot ``LINEAR_TOOLS`` denied. What the
flags cannot remove: the cwd's CLAUDE.md and AGENTS.md and the enabled plugins still load, and
the user's and the project's allow rules still apply to other MCP servers' tools and to Linear
tools added after the snapshot (``--setting-sources``/``--restricted``/``--bare`` are AGH-39,
which needs a live check). The adapter never trusts the model's filtering: ``list_ready``
filters the reply again by team, label and state type.

Every failure is a one-line ``TrackerError`` naming the operation, the issue id and the fix.
Nothing is retried. ``last_cost_usd`` is what the last port operation's calls cost, as each
result reports it; it is a lower bound when ``claude`` ran but reported no cost (a timeout, an
output over the cap, output that is not its JSON result).
"""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from agent_hub.core.errors import TrackerError
from agent_hub.core.json_form import InvalidJsonError, JsonValue, load_json_bytes
from agent_hub.core.tracker.tracker_client import ISSUE_ID_PATTERN, Issue
from agent_hub.tracker_linear.claude_process import (
    CLAUDE_PROGRAM,
    ClaudeOutput,
    ClaudeRunError,
    run_claude,
)
from agent_hub.tracker_linear.graphql import DONE_STATE_TYPES, LINEAR_API_KEY_VARIABLE
from agent_hub.tracker_linear.mcp_protocol import (
    DENIED,
    MAX_QUOTED_CHARS,
    MAX_READY_ISSUES,
    MAX_REPLY_BYTES,
    TOOLS,
    TRANSPORT_FIX,
    WRITE_FIX,
    CommentSaved,
    LabelsRead,
    McpCall,
    StateSaved,
    call_error,
    comment_read_call,
    get_issue_call,
    label_read_call,
    list_ready_call,
    parse_reply,
    prompt,
    quoted,
    save_comment_call,
    save_labels_call,
    save_state_call,
    state_read_call,
)

DEFAULT_MODEL = "haiku"
DEFAULT_MAX_TURNS = 6
DEFAULT_MAX_BUDGET_USD = 0.3
DEFAULT_EFFORT = "medium"
DEFAULT_TIMEOUT_S = 120.0

_RETRY_FIX = f"retry {TRANSPORT_FIX}"
# A subtype shown as is (error_max_turns); anything else is quoted.
_SUBTYPE = re.compile(r"[a-z_]{1,64}")


class Runner(Protocol):
    """Runs ``argv`` in ``cwd`` with exactly ``env``; ``run_claude`` is the default."""

    def __call__(
        self, argv: Sequence[str], *, cwd: Path | str, env: Mapping[str, str], timeout_s: float
    ) -> ClaudeOutput:
        """Run one call; ``TimeoutError`` past ``timeout_s``, ``OSError`` if it cannot start.

        ``ClaudeRunError`` (an ``OSError``) is an OS error after the call started.
        """
        ...


class McpTrackerClient:
    """A ``TrackerClient`` that asks the Linear MCP server through ``claude -p`` calls."""

    def __init__(
        self,
        *,
        environ: Mapping[str, str],
        cwd: Path,
        runner: Runner = run_claude,
        model: str = DEFAULT_MODEL,
        max_turns: int = DEFAULT_MAX_TURNS,
        max_budget_usd: float = DEFAULT_MAX_BUDGET_USD,
        effort: str = DEFAULT_EFFORT,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._environ = environ
        self.cwd = cwd
        self.runner = runner
        self.model = model
        self.max_turns = max_turns
        self.max_budget_usd = max_budget_usd
        self.effort = effort
        self.timeout_s = timeout_s
        self.last_cost_usd = 0.0

    def __repr__(self) -> str:
        # Names no environment value: the caller's environment may hold secrets.
        return (
            f"McpTrackerClient(cwd={str(self.cwd)!r}, model={self.model!r},"
            f" max_turns={self.max_turns}, max_budget_usd={self.max_budget_usd},"
            f" effort={self.effort!r}, timeout_s={self.timeout_s})"
        )

    def list_ready(self, team: str, label: str) -> list[Issue]:
        """Return the team's issues with the label whose state is not done, from one call."""
        self.last_cost_usd = 0.0
        reply = self._call(list_ready_call(team, label))
        if reply.more:
            raise TrackerError(
                operation="list_ready",
                cause=f"more than {MAX_READY_ISSUES} issues match",
                fix="close or unlabel issues in Linear, or list a narrower label",
            )
        return [
            ready.issue
            for ready in reply.issues
            if _team_of(ready.issue.id) == team
            and label in ready.issue.labels
            and ready.state_type not in DONE_STATE_TYPES
        ]

    def get_issue(self, issue_id: str) -> Issue:
        """Return the issue with the identifier ``issue_id``."""
        self._start("get_issue", issue_id)
        issue = self._call(get_issue_call(issue_id))
        _check_same_issue("get_issue", issue_id, issue.id)
        return issue

    def move_state(self, issue_id: str, state_name: str) -> None:
        """Move the issue to its team's state ``state_name``; the current state is a no-op."""
        self._start("move_state", issue_id)
        read = self._call(state_read_call(issue_id))
        _check_same_issue("move_state", issue_id, read.issue_id)
        if state_name not in read.states:
            team = _team_of(issue_id)
            raise TrackerError(
                operation="move_state",
                issue_id=issue_id,
                cause=f"state {state_name!r} not found in team {team}",
                fix=f"use the name of a workflow state of team {team}",
            )
        if read.state == state_name:
            return
        saved = self._call(save_state_call(issue_id, state_name))
        _check_echo(
            "move_state", issue_id, echoed=saved == StateSaved(issue_id=issue_id, state=state_name)
        )

    def add_label(self, issue_id: str, name: str) -> None:
        """Add a label of the issue's team or the workspace; a present label is a no-op."""
        read = self._label_read("add_label", issue_id, name)
        if name not in read.labels:
            self._save_labels("add_label", issue_id, (*read.labels, name))

    def remove_label(self, issue_id: str, name: str) -> None:
        """Remove a label; a known label the issue does not carry is a no-op."""
        read = self._label_read("remove_label", issue_id, name)
        if name in read.labels:
            labels = tuple(label for label in read.labels if label != name)
            self._save_labels("remove_label", issue_id, labels)

    def comment(self, issue_id: str, body: str) -> None:
        """Add one comment with ``body`` to the issue; never retried."""
        self._start("comment", issue_id)
        write = save_comment_call(issue_id, body)  # refuses a long body before any call
        seen = self._call(comment_read_call(issue_id))
        _check_same_issue("comment", issue_id, seen.issue_id)
        saved = self._call(write)
        _check_echo(
            "comment", issue_id, echoed=saved == CommentSaved(issue_id=issue_id, commented=True)
        )

    def _label_read(self, operation: str, issue_id: str, name: str) -> LabelsRead:
        """The read call of a label write; a name neither known nor on the issue raises."""
        self._start(operation, issue_id)
        read = self._call(label_read_call(operation, issue_id))
        _check_same_issue(operation, issue_id, read.issue_id)
        if name not in read.available_labels and name not in read.labels:
            raise TrackerError(
                operation=operation,
                issue_id=issue_id,
                cause=f"label {name!r} not found in team {_team_of(issue_id)} or the workspace",
                fix="create the label in Linear first",
            )
        return read

    def _save_labels(self, operation: str, issue_id: str, labels: tuple[str, ...]) -> None:
        """The write call of a label change: the full label set, echoed back."""
        saved = self._call(save_labels_call(operation, issue_id, labels))
        _check_echo(
            operation,
            issue_id,
            echoed=saved.issue_id == issue_id and sorted(saved.labels) == sorted(labels),
        )

    def _start(self, operation: str, issue_id: str) -> None:
        """Begin a port operation on ``issue_id``: reset the cost, refuse a malformed id."""
        self.last_cost_usd = 0.0
        if not ISSUE_ID_PATTERN.fullmatch(issue_id):
            raise TrackerError(
                operation=operation,
                issue_id=issue_id,
                cause="malformed issue id",
                fix="pass an identifier such as DEM-1",
            )

    def _call[R](self, call: McpCall[R]) -> R:
        """Run one ``claude -p`` call and return its checked reply; its cost is added."""
        argv = [
            CLAUDE_PROGRAM,
            "-p",
            prompt(call),
            "--output-format",
            "json",
            "--max-turns",
            str(self.max_turns),
            "--max-budget-usd",
            str(self.max_budget_usd),
            "--model",
            self.model,
            # Hooks off: from the hub root, its SessionStart, Stop and SessionEnd hooks would
            # inject the brief, run its checks past the timeout and leave a session stub.
            "--settings",
            json.dumps({"effortLevel": self.effort, "disableAllHooks": True}),
            "--no-session-persistence",
            # A permissive defaultMode in the user's settings cannot widen the call.
            "--permission-mode",
            "dontAsk",
            # No built-in tool; the kind's Linear tools, and a deny of every other Linear tool,
            # since --allowedTools only adds to the user's and the project's allow-lists.
            "--tools",
            "",
            "--allowedTools",
            *TOOLS[call.kind],
            "--disallowedTools",
            *DENIED[call.kind],
        ]
        env = {
            name: value for name, value in self._environ.items() if name != LINEAR_API_KEY_VARIABLE
        }
        output = self._run(call, argv, env)
        return parse_reply(call, self._result(call, output))

    def _run(self, call: McpCall[Any], argv: list[str], env: dict[str, str]) -> ClaudeOutput:
        """Run the call; a runner failure becomes a ``TrackerError`` naming its fix."""
        try:
            return self.runner(argv, cwd=self.cwd, env=env, timeout_s=self.timeout_s)
        except TimeoutError:
            # Before OSError, of which TimeoutError is a subclass.
            raise call_error(
                call, f"no answer from claude within {self.timeout_s:g} s", _RETRY_FIX
            ) from None
        except ClaudeRunError as error:
            # claude ran: a write call may have written.
            raise call_error(
                call, f"claude failed while running: {quoted(error.strerror)}", _RETRY_FIX
            ) from None
        except FileNotFoundError as error:
            if str(error.filename) == str(self.cwd):
                raise call_error(
                    call,
                    f"cannot start claude in {str(self.cwd)!r}: no such directory",
                    "run the command in the hub, or set AGENT_HUB_ROOT to it",
                    call_ran=False,
                ) from None
            if error.filename == argv[0]:
                raise call_error(
                    call,
                    "claude (Claude Code) is not on PATH",
                    f"install Claude Code, {TRANSPORT_FIX}",
                    call_ran=False,
                ) from None
            raise _start_error(call, error) from None
        except OSError as error:
            raise _start_error(call, error) from None

    def _result(self, call: McpCall[Any], output: ClaudeOutput) -> str:
        """The model's reply text from ``claude``'s JSON result; its cost is recorded first."""
        if len(output.stdout) > MAX_REPLY_BYTES:
            raise call_error(
                call, f"claude's output is over {MAX_REPLY_BYTES // 1024**2} MiB", _RETRY_FIX
            )
        try:
            value = load_json_bytes(output.stdout, strict=True)
        except InvalidJsonError:
            value = None
        # Any result that names a cost was paid for, even when nothing else in it is usable.
        self.last_cost_usd += _cost_usd(value)
        envelope = _envelope(value)
        if envelope is None:
            raise _no_result(call, output)
        if envelope.is_error:
            raise call_error(
                call,
                _stopped_cause(envelope),
                f"check that claude is logged in and within its budget, {TRANSPORT_FIX}",
            )
        if output.returncode != 0 or envelope.result is None:
            raise _no_result(call, output)
        return envelope.result


@dataclass(frozen=True, kw_only=True, slots=True)
class _Envelope:
    """``claude``'s JSON result: an error result (stopped early) may have no ``result``."""

    is_error: bool
    result: str | None
    subtype: str | None
    errors: tuple[str, ...]


def _is_cost(value: JsonValue) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _cost_usd(value: JsonValue) -> float:
    """The result's ``total_cost_usd`` when it is a number, else 0."""
    cost = value.get("total_cost_usd") if isinstance(value, dict) else None
    if isinstance(cost, bool) or not isinstance(cost, int | float):
        return 0.0
    return float(cost)


def _envelope(value: JsonValue) -> _Envelope | None:
    """``value`` read as ``claude``'s result, or None when it is not one."""
    if not isinstance(value, dict) or not isinstance(value.get("is_error"), bool):
        return None
    is_error, result, subtype, errors = (
        value.get(name) for name in ("is_error", "result", "subtype", "errors")
    )
    if not (isinstance(result, str) or (is_error and result is None)):
        return None
    if not isinstance(subtype, str | None) or not _is_cost(value.get("total_cost_usd")):
        return None
    return _Envelope(
        is_error=bool(is_error),
        result=result if isinstance(result, str) else None,
        subtype=subtype,
        errors=tuple(str(error) for error in errors) if isinstance(errors, list) else (),
    )


def _stopped_cause(envelope: _Envelope) -> str:
    """Why an error result stopped: its text, else its subtype and errors (quoted, cut)."""
    if envelope.result is not None:
        return f"claude reported an error: {quoted(envelope.result)}"
    subtype = envelope.subtype or "error"
    name = subtype if _SUBTYPE.fullmatch(subtype) else quoted(subtype)
    if not envelope.errors:
        return f"claude stopped: {name}"
    return f"claude stopped: {name}: {quoted('; '.join(envelope.errors))}"


def _start_error(call: McpCall[Any], error: OSError) -> TrackerError:
    return call_error(
        call, f"could not start claude: {quoted(error.strerror)}", _RETRY_FIX, call_ran=False
    )


def _no_result(call: McpCall[Any], output: ClaudeOutput) -> TrackerError:
    """The error for a call that gave no usable result: a failed exit, else no JSON."""
    if output.returncode != 0:
        detail = _head(output.stderr or output.stdout).strip()
        return call_error(
            call,
            f"claude exited with status {output.returncode}: {quoted(detail)}",
            f"run claude -p in the hub to see why, {TRANSPORT_FIX}",
        )
    return call_error(call, f"claude printed no JSON result: {_quoted(output.stdout)}", _RETRY_FIX)


def _team_of(issue_id: str) -> str:
    return issue_id.partition("-")[0]


def _check_echo(operation: str, issue_id: str, *, echoed: bool) -> None:
    if not echoed:
        raise TrackerError(
            operation=operation,
            issue_id=issue_id,
            cause="the write reply names another change",
            fix=WRITE_FIX,
        )


def _check_same_issue(operation: str, issue_id: str, replied: str) -> None:
    if replied != issue_id:
        raise TrackerError(
            operation=operation,
            issue_id=issue_id,
            cause=f"the reply names another issue, {replied}",
            fix=_RETRY_FIX,
        )


def _head(output: bytes) -> str:
    """The start of untrusted output, decoded: never more bytes than a quote can show."""
    return output[: 4 * MAX_QUOTED_CHARS].decode(errors="replace")


def _quoted(output: bytes) -> str:
    """Untrusted output, decoded, cut to ``MAX_QUOTED_CHARS`` and quoted."""
    return quoted(_head(output))
