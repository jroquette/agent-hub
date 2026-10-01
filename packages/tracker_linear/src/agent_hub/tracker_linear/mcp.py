"""The ``TrackerClient`` port over the user's Linear MCP server, through ``claude -p`` (ADR 0015).

Each port operation is one or more short headless ``claude -p`` calls (``mcp_protocol``): a
read is one call; a write is one read call, then the adapter decides, then at most one write
call. Every call runs in ``cwd`` (the hub root) with the caller's environment minus
``LINEAR_API_KEY``, under the caps given to the constructor (D9), and is allowed only the
Linear tools its kind needs. The adapter never trusts the model's filtering: ``list_ready``
filters the reply again by team, label and state type.

Every failure is a one-line ``TrackerError`` naming the operation, the issue id and the fix.
Nothing is retried. ``last_cost_usd`` is what the last port operation's calls cost.
"""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from agent_hub.core.errors import TrackerError
from agent_hub.core.json_form import InvalidJsonError, JsonValue, load_json_bytes
from agent_hub.core.tracker.tracker_client import ISSUE_ID_PATTERN, Issue
from agent_hub.tracker_linear.claude_process import CLAUDE_PROGRAM, ClaudeOutput, run_claude
from agent_hub.tracker_linear.graphql import DONE_STATE_TYPES, LINEAR_API_KEY_VARIABLE
from agent_hub.tracker_linear.mcp_protocol import (
    MAX_QUOTED_CHARS,
    MAX_READY_ISSUES,
    TOOLS,
    TRANSPORT_FIX,
    McpCall,
    get_issue_call,
    list_ready_call,
    parse_reply,
    prompt,
)

DEFAULT_MODEL = "haiku"
DEFAULT_MAX_TURNS = 6
DEFAULT_MAX_BUDGET_USD = 0.3
DEFAULT_EFFORT = "medium"
DEFAULT_TIMEOUT_S = 120.0

_RETRY_FIX = f"retry {TRANSPORT_FIX}"


class Runner(Protocol):
    """Runs ``argv`` in ``cwd`` with exactly ``env``; ``run_claude`` is the default."""

    def __call__(
        self, argv: Sequence[str], *, cwd: Path | str, env: Mapping[str, str], timeout_s: float
    ) -> ClaudeOutput:
        """Run one call; ``TimeoutError`` past ``timeout_s``, ``OSError`` if it cannot start."""
        ...


class McpTrackerClient:
    """A ``TrackerClient`` that asks the Linear MCP server through ``claude -p`` calls."""

    def __init__(  # noqa: PLR0913 - the caps are D9's constructor parameters, all keyword-only
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
            if ready.issue.id.partition("-")[0] == team
            and label in ready.issue.labels
            and ready.state_type not in DONE_STATE_TYPES
        ]

    def get_issue(self, issue_id: str) -> Issue:
        """Return the issue with the identifier ``issue_id``."""
        self._start("get_issue", issue_id)
        issue = self._call(get_issue_call(issue_id))
        _check_same_issue("get_issue", issue_id, issue.id)
        return issue

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
            "--settings",
            json.dumps({"effortLevel": self.effort}),
            "--allowedTools",
            *TOOLS[call.kind],
        ]
        env = {
            name: value for name, value in self._environ.items() if name != LINEAR_API_KEY_VARIABLE
        }
        output = self.runner(argv, cwd=self.cwd, env=env, timeout_s=self.timeout_s)
        return parse_reply(call, self._result(call, output))

    def _result(self, call: McpCall[Any], output: ClaudeOutput) -> str:
        """The model's reply text from ``claude``'s JSON result; its cost is recorded first."""
        try:
            fields = _result_fields(load_json_bytes(output.stdout, strict=True))
        except InvalidJsonError:
            fields = None
        if fields is None:
            raise _error(
                call, f"claude printed no JSON result: {_quoted(output.stdout)}", _RETRY_FIX
            )
        text, _is_error, cost_usd = fields
        self.last_cost_usd += cost_usd
        return text


def _result_fields(value: JsonValue) -> tuple[str, bool, float] | None:
    """``claude``'s result object read as (reply text, is_error, cost), or None if it is not one."""
    if not isinstance(value, dict):
        return None
    text, is_error, cost_usd = (
        value.get(name) for name in ("result", "is_error", "total_cost_usd")
    )
    if not isinstance(text, str) or not isinstance(is_error, bool):
        return None
    if isinstance(cost_usd, bool) or not isinstance(cost_usd, int | float):
        return None
    return text, is_error, float(cost_usd)


def _check_same_issue(operation: str, issue_id: str, replied: str) -> None:
    if replied != issue_id:
        raise TrackerError(
            operation=operation,
            issue_id=issue_id,
            cause=f"the reply names another issue, {replied}",
            fix=_RETRY_FIX,
        )


def _error(call: McpCall[Any], cause: str, fix: str) -> TrackerError:
    return TrackerError(operation=call.operation, issue_id=call.issue_id, cause=cause, fix=fix)


def _quoted(text: bytes) -> str:
    """Untrusted output, decoded, cut to ``MAX_QUOTED_CHARS`` and quoted."""
    return repr(text.decode(errors="replace")[:MAX_QUOTED_CHARS])
