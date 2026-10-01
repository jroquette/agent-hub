"""The Linear MCP adapter over an injected runner (ADR 0015): argv, reads, writes, failures."""

import copy
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


def _issue_reply(issue_id: str) -> dict[str, Any]:
    item = _ready_item(issue_id, "started", ["agent-ready"])
    return {key: value for key, value in item.items() if key != "state_type"}


class TestWrites:
    def test_reads_then_writes_once_when_change_needed(
        self, fake_claude: Any, hub_root: Path, tracker_backend: FakeTrackerBackend
    ) -> None:
        client = _client(fake_claude, hub_root)

        client.move_state("DEM-1", "In Progress")
        client.add_label("DEM-1", "bug")
        client.remove_label("DEM-1", "agent-ready")
        client.comment("DEM-2", "Run 1a2b3c4d opened a PR.")

        assert _requests(fake_claude) == [
            ("read_state", {"issue_id": "DEM-1"}),
            ("save_state", {"issue_id": "DEM-1", "state": "In Progress"}),
            ("read_labels", {"issue_id": "DEM-1"}),
            ("save_labels", {"issue_id": "DEM-1", "labels": ["agent-ready", "demo-api", "bug"]}),
            ("read_labels", {"issue_id": "DEM-1"}),
            ("save_labels", {"issue_id": "DEM-1", "labels": ["demo-api", "bug"]}),
            ("read_issue", {"issue_id": "DEM-2"}),
            ("save_comment", {"issue_id": "DEM-2", "body": "Run 1a2b3c4d opened a PR."}),
        ]
        dem_1 = tracker_backend.issues["DEM-1"]
        assert (dem_1.state, dem_1.labels) == ("In Progress", ("demo-api", "bug"))
        assert tracker_backend.comments == [("DEM-2", "Run 1a2b3c4d opened a PR.")]
        assert client.last_cost_usd == 2 * _COST_USD

    @pytest.mark.parametrize(
        ("operation", "arguments", "read"),
        [
            ("move_state", ("DEM-1", "Todo"), "read_state"),
            ("add_label", ("DEM-1", "demo-api"), "read_labels"),
            ("remove_label", ("DEM-1", "bug"), "read_labels"),
        ],
        ids=["current-state", "present-label", "absent-label"],
    )
    def test_makes_no_write_call_when_change_is_noop(
        self,
        fake_claude: Any,
        hub_root: Path,
        tracker_backend: FakeTrackerBackend,
        *,
        operation: str,
        arguments: tuple[str, str],
        read: str,
    ) -> None:
        before = copy.deepcopy(tracker_backend)

        getattr(_client(fake_claude, hub_root), operation)(*arguments)

        assert [call.operation for call in fake_claude.calls] == [read]
        assert tracker_backend == before

    @pytest.mark.parametrize(
        ("operation", "arguments", "cause"),
        [
            ("move_state", ("DEM-1", "Shipped"), "state 'Shipped' not found in team DEM"),
            ("move_state", ("OPS-1", "Duplicate"), "state 'Duplicate' not found in team OPS"),
            (
                "add_label",
                ("DEM-1", "no-such-label"),
                "label 'no-such-label' not found in team DEM or the workspace",
            ),
            (
                "remove_label",
                ("OPS-1", "demo-api"),
                "label 'demo-api' not found in team OPS or the workspace",
            ),
        ],
        ids=["state", "state-of-other-team", "added-label", "removed-label-of-other-team"],
    )
    def test_makes_no_write_call_when_name_unknown(
        self,
        fake_claude: Any,
        hub_root: Path,
        tracker_backend: FakeTrackerBackend,
        *,
        operation: str,
        arguments: tuple[str, str],
        cause: str,
    ) -> None:
        before = copy.deepcopy(tracker_backend)

        with pytest.raises(TrackerError) as raised:
            getattr(_client(fake_claude, hub_root), operation)(*arguments)

        assert str(raised.value).startswith(f"{operation} {arguments[0]}: {cause}; ")
        assert len(fake_claude.calls) == 1
        assert tracker_backend == before

    def test_sends_full_label_set_when_label_added(self, fake_claude: Any, hub_root: Path) -> None:
        _client(fake_claude, hub_root).add_label("OPS-1", "agent-failed")

        write = fake_claude.calls[-1]
        assert (write.operation, write.arguments) == (
            "save_labels",
            {"issue_id": "OPS-1", "labels": ["agent-ready", "agent-failed"]},
        )

    @pytest.mark.parametrize(
        ("operation", "arguments", "read", "write"),
        [
            (
                "move_state",
                ("DEM-1", "In Progress"),
                {"id": "DEM-1", "state": "Todo", "states": ["Todo", "In Progress"]},
                {"id": "DEM-1", "state": "Done"},
            ),
            (
                "move_state",
                ("DEM-1", "In Progress"),
                {"id": "DEM-1", "state": "Todo", "states": ["Todo", "In Progress"]},
                {"id": "DEM-2", "state": "In Progress"},
            ),
            (
                "add_label",
                ("DEM-1", "bug"),
                {"id": "DEM-1", "labels": ["demo-api"], "available_labels": ["demo-api", "bug"]},
                {"id": "DEM-1", "labels": ["demo-api", "bug", "agent-failed"]},
            ),
            (
                "remove_label",
                ("DEM-1", "demo-api"),
                {"id": "DEM-1", "labels": ["demo-api"], "available_labels": ["demo-api"]},
                {"id": "DEM-1", "labels": ["demo-api"]},
            ),
            (
                "comment",
                ("DEM-1", "A comment."),
                {"id": "DEM-1"},
                {"id": "DEM-1", "commented": False},
            ),
            (
                "comment",
                ("DEM-1", "A comment."),
                {"id": "DEM-1"},
                {"id": "DEM-7", "commented": True},
            ),
        ],
        ids=[
            "other-state",
            "other-issue",
            "extra-label",
            "label-kept",
            "not-commented",
            "other-comment-issue",
        ],
    )
    def test_raises_when_write_reply_names_other_change(
        self,
        hub_root: Path,
        *,
        operation: str,
        arguments: tuple[str, str],
        read: dict[str, Any],
        write: dict[str, Any],
    ) -> None:
        runner = _Scripted(_reply(read), _reply(write))

        with pytest.raises(TrackerError, match="the write reply names another change") as raised:
            getattr(_client(runner, hub_root), operation)(*arguments)

        assert str(raised.value).startswith(f"{operation} {arguments[0]}: ")
        assert len(runner.argvs) == 2

    def test_raises_when_read_reply_names_other_issue(self, hub_root: Path) -> None:
        runner = _Scripted(_reply({"id": "DEM-2", "state": "Todo", "states": ["Todo", "Done"]}))

        with pytest.raises(TrackerError, match=r"^move_state DEM-1: the reply names another issue"):
            _client(runner, hub_root).move_state("DEM-1", "Done")

        assert len(runner.argvs) == 1

    @pytest.mark.parametrize("operation", ["move_state", "add_label", "remove_label", "comment"])
    def test_refuses_issue_id_before_any_call_when_write_id_malformed(
        self, hub_root: Path, operation: str
    ) -> None:
        runner = _Scripted()

        with pytest.raises(TrackerError, match="malformed issue id"):
            getattr(_client(runner, hub_root), operation)("dem-1", "x")

        assert runner.argvs == []


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


_READ_TOOLS = {
    "move_state": ("get_issue", "list_issue_statuses"),
    "add_label": ("get_issue", "list_issue_labels"),
    "remove_label": ("get_issue", "list_issue_labels"),
    "comment": ("get_issue",),
}
_WRITE_TOOLS = {
    "move_state": ("save_issue",),
    "add_label": ("save_issue",),
    "remove_label": ("save_issue",),
    "comment": ("save_comment",),
}
_WRITES = {
    "move_state": ("DEM-1", "In Progress"),
    "add_label": ("DEM-1", "bug"),
    "remove_label": ("DEM-1", "agent-ready"),
    "comment": ("DEM-1", "A comment."),
}


class TestWriteTools:
    @pytest.mark.parametrize("operation", list(_WRITES))
    def test_allows_listing_tool_when_write_reads(
        self, fake_claude: Any, hub_root: Path, operation: str
    ) -> None:
        getattr(_client(fake_claude, hub_root), operation)(*_WRITES[operation])

        read = fake_claude.calls[0]
        assert read.tools == tuple(_PREFIX + name for name in _READ_TOOLS[operation])
        assert read.argv[-len(read.tools) - 1 :] == ("--allowedTools", *read.tools)

    @pytest.mark.parametrize("operation", list(_WRITES))
    def test_allows_only_write_tool_when_write_runs(
        self, fake_claude: Any, hub_root: Path, operation: str
    ) -> None:
        getattr(_client(fake_claude, hub_root), operation)(*_WRITES[operation])

        assert len(fake_claude.calls) == 2
        write = fake_claude.calls[1]
        assert write.tools == tuple(_PREFIX + name for name in _WRITE_TOOLS[operation])
        assert write.argv[-2:] == ("--allowedTools", *write.tools)
