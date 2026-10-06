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
        states={"DEM": open_states, "APP": open_states, "OPS": open_states},
        team_labels={"DEM": ("demo-api", "demo-web"), "APP": (), "OPS": ()},
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


class RecordingTracker:
    """Wraps ``client``: records the ``(team, label)`` of each ``list_ready``; a team in
    ``failing`` raises the ``TrackerError`` an adapter would."""

    def __init__(self, client: TrackerClient, failing: frozenset[str] = frozenset()) -> None:
        self.client = client
        self.failing = failing
        self.calls: list[tuple[str, str]] = []

    def list_ready(self, team: str, label: str) -> list[Issue]:
        self.calls.append((team, label))
        if team in self.failing:
            raise TrackerError(operation="list_ready", cause="synthetic outage", fix="retry later")
        return self.client.list_ready(team, label)


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


# Each would move the cursor, clear the screen, reorder the line or end it on a terminal.
CONTROL_TEXTS = {
    "csi-escape": "\x1b[2J",
    "c1-csi": "\x9b",
    "bidi-override": "\u202e",
    "line-separator": "\u2028",
    "newline": "\n",
}


@pytest.mark.usefixtures("with_key")
@pytest.mark.parametrize("field", ["title", "url"])
@pytest.mark.parametrize("text", list(CONTROL_TEXTS.values()), ids=list(CONTROL_TEXTS))
def test_escapes_text_when_it_holds_control_characters(
    demo_workspace: Workspace,
    run_command: CommandRunner,
    *,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    text: str,
) -> None:
    title, url = "Synthetic title", url_of("DEM-5")
    if field == "title":
        title = f"Synthetic {text}title"
    else:
        url = f"{url}{text}"
    issue = an_issue(id="DEM-5", title=title, url=url)
    inject(monkeypatch, InMemoryTrackerClient(seeded_backend(issue)))

    result = run_command(demo_workspace.hub, "next")

    assert result.exit_code == 0, result.output
    shown_title = json.dumps(title) if field == "title" else title
    shown_url = json.dumps(url) if field == "url" else url
    assert result.stdout == f"DEM-5  ?  {shown_title}  {shown_url}\n"
    assert text not in result.stdout.removesuffix("\n")


@pytest.mark.usefixtures("with_key")
def test_escapes_id_when_it_holds_newline(
    demo_workspace: Workspace, run_command: CommandRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Adapters refuse such an id; the line is still safe if one ever got through.
    issue = an_issue(id="DEM-5\n", url=url_of("DEM-5"))
    inject(monkeypatch, InMemoryTrackerClient(seeded_backend(issue)))

    result = run_command(demo_workspace.hub, "next")

    assert result.exit_code == 0, result.output
    assert result.stdout == f'"DEM-5\\n"  ?  {issue.title}  {url_of("DEM-5")}\n'


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


def teams_backend() -> FakeTrackerBackend:
    """Ready issues of ``APP`` and ``OPS``, seeded out of order, plus one of ``DEM``."""
    ready = "agent-ready"
    return seeded_backend(
        an_issue(id="OPS-3", title="Synthetic ops work", labels=(ready, "demo-api")),
        an_issue(id="APP-9", title="Synthetic app later", labels=(ready, "demo-web")),
        an_issue(id="APP-2", title="Synthetic app first", labels=(ready,)),
        an_issue(id="DEM-1", title="Synthetic demo work", labels=(ready, "demo-api")),
    )


APP_LINES = (
    f"APP-2  ?  Synthetic app first  {url_of('APP-2')}\n"
    f"APP-9  demo-web  Synthetic app later  {url_of('APP-9')}\n"
)
OPS_LINES = f"OPS-3  demo-api  Synthetic ops work  {url_of('OPS-3')}\n"
OUTAGE = "list_ready: synthetic outage; retry later"


@pytest.mark.usefixtures("with_key")
def test_lists_each_team_in_config_order_when_hub_lists_teams(
    demo_workspace: Workspace, run_command: CommandRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    demo_workspace.use_teams("APP", "OPS")
    tracker = RecordingTracker(InMemoryTrackerClient(teams_backend()))
    inject(monkeypatch, tracker)

    result = run_command(demo_workspace.hub, "next")

    assert result.exit_code == 0, result.output
    assert result.stdout == APP_LINES + OPS_LINES
    assert result.stderr == API_LINE
    assert tracker.calls == [("APP", "agent-ready"), ("OPS", "agent-ready")]


@pytest.mark.usefixtures("with_key")
def test_lists_other_teams_when_one_team_fails(
    demo_workspace: Workspace, run_command: CommandRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    demo_workspace.use_teams("APP", "OPS")
    tracker = RecordingTracker(InMemoryTrackerClient(teams_backend()), failing=frozenset({"OPS"}))
    inject(monkeypatch, tracker)

    result = run_command(demo_workspace.hub, "next")

    assert result.exit_code == 1
    assert result.stdout == APP_LINES
    assert result.stderr == API_LINE + f"team OPS: {OUTAGE}\n"
    assert tracker.calls == [("APP", "agent-ready"), ("OPS", "agent-ready")]


@pytest.mark.usefixtures("with_key")
def test_names_succeeding_teams_when_none_ready(
    demo_workspace: Workspace, run_command: CommandRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    demo_workspace.use_teams("APP", "OPS")
    closed = an_issue(id="APP-4", state="Done")
    inject(monkeypatch, RecordingTracker(InMemoryTrackerClient(seeded_backend(closed))))

    result = run_command(demo_workspace.hub, "next")

    assert result.exit_code == 0, result.output
    assert result.stdout == "no ready issues (teams APP, OPS, label agent-ready)\n"
    assert result.stderr == API_LINE


@pytest.mark.usefixtures("with_key")
def test_names_failure_per_team_when_every_team_fails(
    demo_workspace: Workspace, run_command: CommandRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    demo_workspace.use_teams("APP", "OPS")
    failing = frozenset({"APP", "OPS"})
    inject(monkeypatch, RecordingTracker(InMemoryTrackerClient(teams_backend()), failing=failing))

    result = run_command(demo_workspace.hub, "next")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == API_LINE + f"team APP: {OUTAGE}\nteam OPS: {OUTAGE}\n"


@pytest.mark.usefixtures("with_key")
def test_calls_tracker_once_when_hub_has_one_team(
    demo_workspace: Workspace, run_command: CommandRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    tracker = RecordingTracker(InMemoryTrackerClient(teams_backend()))
    inject(monkeypatch, tracker)

    result = run_command(demo_workspace.hub, "next")

    assert result.exit_code == 0, result.output
    assert result.stdout == f"DEM-1  demo-api  Synthetic demo work  {url_of('DEM-1')}\n"
    assert tracker.calls == [("DEM", "agent-ready")]


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


def write_local(hub: Path, document: object) -> None:
    (hub / "hub.local.json").write_text(json.dumps(document), encoding="utf-8")


class TestLocalFile:
    def test_uses_mcp_adapter_when_local_file_sets_mcp(
        self,
        demo_workspace: Workspace,
        run_command: CommandRunner,
        *,
        monkeypatch: pytest.MonkeyPatch,
        fake_claude: Path,
    ) -> None:
        set_transport(demo_workspace.hub, "api")
        write_local(demo_workspace.hub, {"tracker": {"transport": "mcp"}})
        monkeypatch.delenv(KEY_VARIABLE, raising=False)

        result = run_command(demo_workspace.hub, "next")

        assert result.exit_code == 0, result.output
        assert result.stdout == (
            f"DEM-3  demo-web  Synthetic issue DEM-3  {url_of('DEM-3')}\n"
            f"DEM-12  demo-api  Synthetic issue DEM-12  {url_of('DEM-12')}\n"
        )
        assert result.stderr == MCP_LINE
        calls = [json.loads(line) for line in fake_claude.read_text().splitlines()]
        assert [call["request"]["operation"] for call in calls] == ["list_ready"]

    @pytest.mark.parametrize("key", [None, "set"], ids=["no-key", "key"])
    def test_uses_api_adapter_when_local_file_absent(
        self,
        demo_workspace: Workspace,
        run_command: CommandRunner,
        *,
        monkeypatch: pytest.MonkeyPatch,
        key: str | None,
    ) -> None:
        set_transport(demo_workspace.hub, "api")
        if key is None:
            monkeypatch.delenv(KEY_VARIABLE, raising=False)
        else:
            monkeypatch.setenv(KEY_VARIABLE, synthetic_key())
        spy = inject(monkeypatch, InMemoryTrackerClient(demo_backend()))

        result = run_command(demo_workspace.hub, "next")

        if key is None:
            assert result.exit_code == 1
            assert result.stderr == MISSING_KEY
            assert spy.calls == []
        else:
            assert result.exit_code == 0, result.output
            assert result.stderr == API_LINE
            assert len(spy.calls) == 1

    @pytest.mark.usefixtures("with_key")
    @pytest.mark.parametrize(
        ("document", "expected_path"),
        [
            ([], "$"),
            ({"guard": {}}, "guard"),
            ({"tracker": {"transport": "ftp"}}, "tracker.transport"),
        ],
        ids=["array", "guard", "bad-transport"],
    )
    def test_prints_local_lines_when_local_file_invalid(
        self,
        demo_workspace: Workspace,
        run_command: CommandRunner,
        *,
        monkeypatch: pytest.MonkeyPatch,
        document: object,
        expected_path: str,
    ) -> None:
        spy = inject(monkeypatch, InMemoryTrackerClient(demo_backend()))
        write_local(demo_workspace.hub, document)

        result = run_command(demo_workspace.hub, "next")

        assert result.exit_code == 1
        assert result.stdout == ""
        lines = result.stderr.splitlines()
        assert len(lines) == 1, lines
        assert lines[0].startswith(f"hub.local.json: {expected_path}: "), lines
        assert spy.calls == []

    def test_reads_local_file_from_main_checkout_when_run_from_hub_worktree(
        self, demo_workspace: Workspace, run_command: CommandRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        hub = demo_workspace.hub
        demo_workspace.git(hub, "-c", "init.defaultBranch=trunk", "init", "-q")
        demo_workspace.git(hub, "add", "-A")
        demo_workspace.git(hub, "commit", "-q", "-m", "hub")
        worktree = hub / ".claude" / "worktrees" / "dem-1-x"
        demo_workspace.git(hub, "worktree", "add", "-q", "-b", "dem-1-x", str(worktree))
        # Only the main checkout holds the developer's file; the worktree's hub.json says api.
        write_local(hub, {"tracker": {"transport": "mcp"}})
        assert not (worktree / "hub.local.json").exists()
        monkeypatch.delenv(KEY_VARIABLE, raising=False)
        spy = inject(monkeypatch, InMemoryTrackerClient(demo_backend()))

        result = run_command(worktree, "next")

        assert result.exit_code == 0, result.output
        assert result.stderr == MCP_LINE
        assert spy.calls == [("DEM", Path(os.path.realpath(worktree)))]
