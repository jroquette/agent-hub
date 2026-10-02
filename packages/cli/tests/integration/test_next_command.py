"""``hub next``: the tracker's ready issues, one line each, in issue-number order (AC-27.13).

Every run is in process, in a copy of the ``DEMO`` workspace (``demo_workspace``: team ``DEM``,
repos ``demo-api`` and ``demo-web``). The tracker is injected by replacing
``next_command.resolve_tracker_client`` with a spy that returns an ``InMemoryTrackerClient``
over a synthetic backend, so no test reaches Linear; ``TestTransport`` also runs the real
resolution with transport ``"mcp"`` against a fake ``claude`` on ``PATH`` (AC-27.15).
"""

import json
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest
from click import unstyle
from typer.testing import Result

from agent_hub.cli import next_command
from agent_hub.core.errors import TrackerError
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import an_issue
from agent_hub.core.testing.fakes import FakeTrackerBackend, InMemoryTrackerClient, TrackerState
from agent_hub.core.tracker.tracker_client import Issue, TrackerClient

pytestmark = pytest.mark.disable_socket

# The conftest's in-process run (tests cannot import a conftest in importlib mode).
type CommandRunner = Callable[..., Result]
type Workspace = Any

KEY_VARIABLE = "LINEAR_API_KEY"
API_LINE = 'tracker: Linear API (tracker.transport "api")\n'
MCP_LINE = 'tracker: Linear MCP via claude -p (tracker.transport "mcp")\n'
MISSING_KEY = (
    'hub next: LINEAR_API_KEY is not set; export it, or set tracker.transport: "mcp"'
    " in hub.json to reach Linear through its MCP server with claude -p\n"
)
NONE_READY = "no ready issues (team DEM, label agent-ready)\n"
# The characters of the box Rich may draw around a usage error.
BOX_CHARACTERS = "│╭╮╰╯─"


def synthetic_key() -> str:
    return "lin" + "_api_" + "x" * 40


def url_of(issue_id: str) -> str:
    return f"https://linear.app/demo/issue/{issue_id}"


def seeded_backend(*issues: Issue) -> FakeTrackerBackend:
    open_states = (TrackerState(name="Todo", closed=False), TrackerState(name="Done", closed=True))
    return FakeTrackerBackend(
        states={"DEM": open_states, "OPS": open_states},
        team_labels={"DEM": ("demo-api", "demo-web"), "OPS": ()},
        workspace_labels=("agent-ready", "agent-failed"),
        issues={issue.id: issue for issue in issues},
    )


def demo_backend() -> FakeTrackerBackend:
    """E3's seeds: inserted out of order, two repo labels, both, none, a closed and an OPS one."""
    ready = "agent-ready"
    return seeded_backend(
        an_issue(id="DEM-12", title="Synthetic api work", labels=(ready, "demo-api")),
        an_issue(id="DEM-3", title="Synthetic web work", labels=("demo-web", ready)),
        an_issue(id="DEM-7", title="Synthetic both", labels=(ready, "demo-api", "demo-web")),
        an_issue(id="DEM-9", title="Synthetic no repo", labels=(ready, "bug")),
        an_issue(id="DEM-2", title="Synthetic done", state="Done", labels=(ready, "demo-api")),
        an_issue(id="OPS-1", title="Synthetic other team", labels=(ready, "demo-api")),
    )


class ResolveSpy:
    """Replaces ``resolve_tracker_client``: records each call, returns the given client."""

    def __init__(self, client: object) -> None:
        self.client = client
        self.calls: list[tuple[str, Path]] = []

    def __call__(
        self, config: HubConfig, environ: Mapping[str, str], *, hub_root: Path
    ) -> TrackerClient:
        self.calls.append((config.tracker.team, hub_root))
        return self.client  # type: ignore[return-value]


class FailingTracker:
    """A tracker whose ``list_ready`` fails as an adapter does: one ``TrackerError``."""

    def list_ready(self, team: str, label: str) -> list[Issue]:
        raise TrackerError(operation="list_ready", cause="synthetic outage", fix="retry later")


@pytest.fixture
def with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_VARIABLE, synthetic_key())


def inject(monkeypatch: pytest.MonkeyPatch, client: object) -> ResolveSpy:
    spy = ResolveSpy(client)
    monkeypatch.setattr(next_command, "resolve_tracker_client", spy)
    return spy


def set_transport(hub: Path, transport: str) -> None:
    document = json.loads((hub / "hub.json").read_text())
    document["tracker"]["transport"] = transport
    (hub / "hub.json").write_text(json.dumps(document, indent=2) + "\n")


@pytest.mark.usefixtures("with_key")
def test_lists_ready_issues_in_number_order_when_run(
    demo_workspace: Workspace, run_command: CommandRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = inject(monkeypatch, InMemoryTrackerClient(demo_backend()))

    result = run_command(demo_workspace.hub, "next")

    assert result.exit_code == 0, result.output
    assert result.stdout == (
        f"DEM-3  demo-web  Synthetic web work  {url_of('DEM-3')}\n"
        f"DEM-7  ?  Synthetic both  {url_of('DEM-7')}\n"
        f"DEM-9  ?  Synthetic no repo  {url_of('DEM-9')}\n"
        f"DEM-12  demo-api  Synthetic api work  {url_of('DEM-12')}\n"
    )
    assert result.stderr == API_LINE
    assert spy.calls == [("DEM", Path(os.path.realpath(demo_workspace.hub)))]


@pytest.mark.usefixtures("with_key")
def test_escapes_title_when_it_holds_newline(
    demo_workspace: Workspace, run_command: CommandRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    title = "Synthetic first line\nDEM-99  demo-api  forged  https://example.com"
    inject(monkeypatch, InMemoryTrackerClient(seeded_backend(an_issue(id="DEM-5", title=title))))

    result = run_command(demo_workspace.hub, "next")

    assert result.exit_code == 0, result.output
    assert result.stdout == f"DEM-5  ?  {json.dumps(title)}  {url_of('DEM-5')}\n"


@pytest.mark.usefixtures("with_key")
def test_says_none_ready_when_list_empty(
    demo_workspace: Workspace, run_command: CommandRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed = an_issue(id="DEM-4", state="Done")
    inject(monkeypatch, InMemoryTrackerClient(seeded_backend(closed)))

    result = run_command(demo_workspace.hub, "next")

    assert result.exit_code == 0, result.output
    assert result.stdout == NONE_READY
    assert result.stderr == API_LINE


@pytest.mark.usefixtures("with_key")
def test_exits_one_when_tracker_fails(
    demo_workspace: Workspace, run_command: CommandRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    inject(monkeypatch, FailingTracker())

    result = run_command(demo_workspace.hub, "next")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == API_LINE + "list_ready: synthetic outage; retry later\n"


@pytest.mark.usefixtures("with_key")
def test_prints_reader_lines_when_hub_json_invalid(
    demo_workspace: Workspace, run_command: CommandRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = inject(monkeypatch, InMemoryTrackerClient(demo_backend()))
    (demo_workspace.hub / "hub.json").write_bytes(b"{}\n")

    result = run_command(demo_workspace.hub, "next")

    assert result.exit_code == 1
    assert result.stdout == ""
    lines = result.stderr.splitlines()
    assert lines
    assert all(line.startswith("hub.json: ") for line in lines), lines
    assert spy.calls == []


@pytest.mark.usefixtures("with_key")
class TestUsage:
    def test_exits_two_when_not_a_hub(
        self, demo_workspace: Workspace, run_command: CommandRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spy = inject(monkeypatch, InMemoryTrackerClient(demo_backend()))

        result = run_command(demo_workspace.ws, "next")

        assert result.exit_code == 2
        assert result.stdout == ""
        assert result.stderr == (
            f"{demo_workspace.ws}: not a hub: no hub.json in this folder"
            " (hub next runs in the hub folder or through ./hub)\n"
        )
        assert spy.calls == []

    def test_refuses_when_argument_given(
        self, demo_workspace: Workspace, run_command: CommandRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spy = inject(monkeypatch, InMemoryTrackerClient(demo_backend()))

        result = run_command(demo_workspace.hub, "next", "DEM-1")

        assert result.exit_code == 2
        assert result.stdout == ""
        shown = unstyle(result.stderr)
        assert "Usage: hub next" in shown
        texts = [line.strip(BOX_CHARACTERS + " ") for line in shown.splitlines()]
        assert "Got unexpected extra argument(s) (DEM-1)" in texts, shown
        assert spy.calls == []


# A fake ``claude``: logs its argv, cwd and whether it got the key, then answers the
# list_ready request (its prompt's last line) from the JSON reply in FAKE_CLAUDE_REPLY.
_FAKE_CLAUDE = """import json, os, sys
argv = sys.argv[1:]
request = json.loads(argv[argv.index("-p") + 1].splitlines()[-1])
with open(os.environ["FAKE_CLAUDE_LOG"], "a") as log:
    log.write(json.dumps({
        "request": request,
        "allowed": argv[argv.index("--allowedTools") + 1:argv.index("--disallowedTools")],
        "cwd": os.getcwd(),
        "has_key": "LINEAR_API_KEY" in os.environ,
    }) + "\\n")
with open(os.environ["FAKE_CLAUDE_REPLY"]) as reply:
    result = reply.read().strip()
print(json.dumps({"type": "result", "is_error": False, "result": result, "total_cost_usd": 0.01}))
"""


def mcp_issue(issue_id: str, labels: list[str], state_type: str) -> dict[str, object]:
    return {
        "id": issue_id,
        "title": f"Synthetic issue {issue_id}",
        "description": None,
        "url": url_of(issue_id),
        "state": "Done" if state_type == "completed" else "Todo",
        "labels": labels,
        "state_type": state_type,
    }


@pytest.fixture
def fake_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """``PATH`` holds only a fake ``claude`` answering ``list_ready``; returns its call log."""
    script = tmp_path / "fake_claude.py"
    script.write_text(_FAKE_CLAUDE)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    wrapper = bin_dir / "claude"
    wrapper.write_text(f"#!/bin/sh\nexec '{sys.executable}' '{script}' \"$@\"\n")
    wrapper.chmod(0o755)
    reply = {
        "issues": [
            mcp_issue("DEM-12", ["agent-ready", "demo-api"], "unstarted"),
            mcp_issue("DEM-3", ["agent-ready", "demo-web"], "started"),
            mcp_issue("DEM-4", ["agent-ready", "demo-api"], "completed"),
        ],
        "more": False,
    }
    (tmp_path / "reply.json").write_text(json.dumps(reply))
    log = tmp_path / "claude.jsonl"
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("FAKE_CLAUDE_REPLY", str(tmp_path / "reply.json"))
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    return log


class TestTransport:
    @pytest.mark.parametrize("transport", [None, "api"], ids=["absent", "api"])
    @pytest.mark.parametrize("key", [None, ""], ids=["unset", "empty"])
    def test_exits_one_when_key_missing(
        self,
        demo_workspace: Workspace,
        run_command: CommandRunner,
        *,
        monkeypatch: pytest.MonkeyPatch,
        transport: str | None,
        key: str | None,
    ) -> None:
        if transport is not None:
            set_transport(demo_workspace.hub, transport)
        if key is None:
            monkeypatch.delenv(KEY_VARIABLE, raising=False)
        else:
            monkeypatch.setenv(KEY_VARIABLE, key)
        spy = inject(monkeypatch, InMemoryTrackerClient(demo_backend()))

        result = run_command(demo_workspace.hub, "next")

        assert result.exit_code == 1
        assert result.stdout == ""
        assert result.stderr == MISSING_KEY
        assert spy.calls == []

    @pytest.mark.parametrize("key", [None, "set"], ids=["no-key", "key"])
    def test_uses_mcp_adapter_when_transport_mcp(
        self,
        demo_workspace: Workspace,
        run_command: CommandRunner,
        *,
        monkeypatch: pytest.MonkeyPatch,
        fake_claude: Path,
        key: str | None,
    ) -> None:
        set_transport(demo_workspace.hub, "mcp")
        if key is None:
            monkeypatch.delenv(KEY_VARIABLE, raising=False)
        else:
            monkeypatch.setenv(KEY_VARIABLE, synthetic_key())

        result = run_command(demo_workspace.hub, "next")

        assert result.exit_code == 0, result.output
        assert result.stdout == (
            f"DEM-3  demo-web  Synthetic issue DEM-3  {url_of('DEM-3')}\n"
            f"DEM-12  demo-api  Synthetic issue DEM-12  {url_of('DEM-12')}\n"
        )
        assert result.stderr == MCP_LINE
        calls = [json.loads(line) for line in fake_claude.read_text().splitlines()]
        assert calls == [
            {
                "request": {
                    "operation": "list_ready",
                    "arguments": {"team": "DEM", "label": "agent-ready"},
                },
                "allowed": ["mcp__Linear__list_issues", "mcp__Linear__list_issue_statuses"],
                "cwd": os.path.realpath(demo_workspace.hub),
                "has_key": False,
            }
        ]
