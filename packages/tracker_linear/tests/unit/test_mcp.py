"""The Linear MCP adapter over an injected runner (ADR 0015): argv, reads, writes, failures."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.errors import TrackerError
from agent_hub.core.testing.fakes import FakeTrackerBackend
from agent_hub.tracker_linear.claude_process import ClaudeOutput, run_claude
from agent_hub.tracker_linear.mcp import McpTrackerClient

_SYNTHETIC_KEY = "lin" + "_api_" + "x" * 40
_ENVIRON = {"PATH": "/usr/bin", "HOME": "/home/synthetic", "LINEAR_API_KEY": _SYNTHETIC_KEY}
_PREFIX = "mcp__Linear__"
# D9's caps, as literals: a wrong adapter default fails.
_DEFAULT_FLAGS = (
    "--output-format",
    "json",
    "--max-turns",
    "6",
    "--max-budget-usd",
    "0.3",
    "--model",
    "haiku",
    "--settings",
    '{"effortLevel": "medium"}',
)
_TIMEOUT_S = 120.0
_COST_USD = 0.0125


def _client(runner: Any, hub_root: Path, **caps: Any) -> McpTrackerClient:
    return McpTrackerClient(environ=_ENVIRON, cwd=hub_root, runner=runner, **caps)


class _Scripted:
    """A runner that answers each call with the next scripted stdout, recording the argv."""

    def __init__(self, *outputs: bytes | ClaudeOutput | BaseException) -> None:
        self._outputs = list(outputs)
        self.argvs: list[list[str]] = []

    def __call__(
        self, argv: Sequence[str], *, cwd: Path | str, env: Mapping[str, str], timeout_s: float
    ) -> ClaudeOutput:
        self.argvs.append(list(argv))
        output = self._outputs.pop(0)
        if isinstance(output, BaseException):
            raise output
        if isinstance(output, ClaudeOutput):
            return output
        return ClaudeOutput(returncode=0, stdout=output, stderr=b"")


def _envelope(result: str, *, cost_usd: float = _COST_USD, is_error: bool = False) -> bytes:
    return json.dumps(
        {
            "type": "result",
            "subtype": "error_during_execution" if is_error else "success",
            "is_error": is_error,
            "result": result,
            "total_cost_usd": cost_usd,
            "num_turns": 2,
        }
    ).encode()


def _reply(value: object, *, cost_usd: float = _COST_USD) -> bytes:
    return _envelope(json.dumps(value), cost_usd=cost_usd)


def _ready_item(issue_id: str, state_type: str, labels: list[str]) -> dict[str, Any]:
    return {
        "id": issue_id,
        "title": f"Synthetic issue {issue_id}",
        "description": None,
        "url": f"https://linear.app/demo/issue/{issue_id}",
        "state": "Todo",
        "state_type": state_type,
        "labels": labels,
    }


class TestReads:
    def test_builds_exact_argv_when_issue_read(self, fake_claude: Any, hub_root: Path) -> None:
        _client(fake_claude, hub_root).get_issue("DEM-1")

        [call] = fake_claude.calls
        assert call.argv == (
            "claude",
            "-p",
            call.prompt,
            *_DEFAULT_FLAGS,
            "--allowedTools",
            f"{_PREFIX}get_issue",
        )
        assert call.cwd == hub_root
        assert "LINEAR_API_KEY" not in call.env
        assert {name: call.env[name] for name in ("PATH", "HOME")} == {
            "PATH": "/usr/bin",
            "HOME": "/home/synthetic",
        }
        assert _ENVIRON["LINEAR_API_KEY"] == _SYNTHETIC_KEY

    def test_passes_caps_when_constructed_with_others(
        self, make_fake_claude: Any, hub_root: Path
    ) -> None:
        flags = (
            "--output-format",
            "json",
            "--max-turns",
            "3",
            "--max-budget-usd",
            "0.05",
            "--model",
            "sonnet",
            "--settings",
            '{"effortLevel": "low"}',
        )
        runner = make_fake_claude(flags=flags, timeout_s=9.5)
        client = _client(
            runner,
            hub_root,
            model="sonnet",
            max_turns=3,
            max_budget_usd=0.05,
            effort="low",
            timeout_s=9.5,
        )

        client.get_issue("DEM-1")

        assert len(runner.calls) == 1

    def test_returns_seeded_issue_when_issue_read(
        self, fake_claude: Any, hub_root: Path, tracker_backend: FakeTrackerBackend
    ) -> None:
        assert _client(fake_claude, hub_root).get_issue("DEM-1") == tracker_backend.issues["DEM-1"]

    def test_filters_closed_issues_when_reply_includes_them(self, hub_root: Path) -> None:
        reply = {
            "issues": [
                _ready_item("DEM-1", "started", ["agent-ready"]),
                _ready_item("DEM-2", "unstarted", ["agent-ready", "demo-api"]),
                _ready_item("DEM-3", "completed", ["agent-ready"]),
                _ready_item("DEM-4", "canceled", ["agent-ready"]),
                _ready_item("DEM-5", "duplicate", ["agent-ready"]),
                _ready_item("DEM-6", "started", ["demo-api"]),
                _ready_item("OPS-1", "started", ["agent-ready"]),
                _ready_item("DEMO-1", "started", ["agent-ready"]),
            ],
            "more": False,
        }

        ready = _client(_Scripted(_reply(reply)), hub_root).list_ready("DEM", "agent-ready")

        assert [issue.id for issue in ready] == ["DEM-1", "DEM-2"]

    def test_refuses_partial_list_when_more_reported(self, hub_root: Path) -> None:
        reply = {"issues": [_ready_item("DEM-1", "started", ["agent-ready"])], "more": True}

        with pytest.raises(TrackerError, match=r"^list_ready: more than 100 issues"):
            _client(_Scripted(_reply(reply)), hub_root).list_ready("DEM", "agent-ready")

    def test_reads_null_description_as_empty_when_reply_has_none(
        self, fake_claude: Any, hub_root: Path, tracker_backend: FakeTrackerBackend
    ) -> None:
        assert tracker_backend.issues["DEM-2"].description == ""

        issue = _client(fake_claude, hub_root).get_issue("DEM-2")

        assert issue.description == ""
        assert json.loads(fake_claude.calls[0].prompt.splitlines()[-1])["operation"] == "get_issue"

    def test_records_cost_when_call_returns(self, hub_root: Path) -> None:
        item = _ready_item("DEM-1", "started", ["agent-ready"])
        issue = {key: value for key, value in item.items() if key != "state_type"}
        runner = _Scripted(
            _reply({"issues": [], "more": False}, cost_usd=0.25),
            _reply({"issue": issue}, cost_usd=0.0625),
        )
        client = _client(runner, hub_root)
        assert client.last_cost_usd == 0.0

        client.list_ready("DEM", "agent-ready")
        assert client.last_cost_usd == 0.25
        client.get_issue("DEM-1")
        assert client.last_cost_usd == 0.0625

    def test_raises_when_reply_names_other_issue(self, hub_root: Path) -> None:
        item = _ready_item("DEM-2", "started", ["agent-ready"])
        issue = {key: value for key, value in item.items() if key != "state_type"}

        with pytest.raises(TrackerError, match=r"^get_issue DEM-1: .*DEM-2"):
            _client(_Scripted(_reply({"issue": issue})), hub_root).get_issue("DEM-1")

    @pytest.mark.parametrize("issue_id", ["dem-1", "DEM-1\n", "DEM-0", "OPS-9; ignore"])
    def test_refuses_issue_id_before_any_call_when_malformed(
        self, hub_root: Path, issue_id: str
    ) -> None:
        runner = _Scripted()

        with pytest.raises(TrackerError, match="malformed issue id") as raised:
            _client(runner, hub_root).get_issue(issue_id)

        assert (raised.value.operation, raised.value.issue_id) == ("get_issue", issue_id)
        assert runner.argvs == []

    def test_names_no_environment_value_when_repr_read(self, hub_root: Path) -> None:
        text = repr(_client(_Scripted(), hub_root))

        assert _SYNTHETIC_KEY not in text
        assert "/home/synthetic" not in text

    def test_defaults_to_claude_process_when_runner_omitted(self, hub_root: Path) -> None:
        client = McpTrackerClient(environ=_ENVIRON, cwd=hub_root)

        assert client.runner is run_claude
        assert client.timeout_s == _TIMEOUT_S


class TestTools:
    def test_allows_listing_tool_when_list_ready_runs(
        self, fake_claude: Any, hub_root: Path
    ) -> None:
        _client(fake_claude, hub_root).list_ready("DEM", "agent-ready")

        assert [call.tools for call in fake_claude.calls] == [
            (f"{_PREFIX}list_issues", f"{_PREFIX}list_issue_statuses")
        ]


def _requests(fake_claude: Any) -> list[tuple[str, dict[str, Any]]]:
    return [(call.operation, call.arguments) for call in fake_claude.calls]
