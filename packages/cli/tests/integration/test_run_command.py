"""``hub run``: one issue from the tracker to a PR through the ``TrackerClient`` port (AC-27.14 on).

Every run is in process, in a copy of the ``DEMO`` workspace (``demo_workspace``: team ``DEM``,
repos ``demo-api`` and ``demo-web``, default branch ``trunk``, branch prefix ``jdoe/``).

This module re-expresses hub ``tests/test_agent_runner.py`` at hub commit ``300559b``, the old
runner script's tests, against the command; the full matrix of cases lives here.
``TestUsage`` replaces its usage checks (``--repo`` outside ``hub.json``, an issue without the
team's prefix): each refusal is a usage error, exit 2, before any tracker call or child process.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from click import unstyle
from typer.testing import Result

from agent_hub.cli import run_command, run_steps
from agent_hub.cli.errors import ChildTimedOutError
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.runner.session_prompt import IMPLEMENTING_TOOLS
from agent_hub.core.tracker.tracker_client import TrackerClient

pytestmark = pytest.mark.disable_socket

# The conftest's in-process run (tests cannot import a conftest in importlib mode).
type CommandRunner = Callable[..., Result]
type Workspace = Any

PR_URL = "https://github.com/acme/demo-api/pull/99"
COMMIT_SUBJECT = "feat(api): synthetic change (DEM-1)"
# The characters of the box Rich may draw around a usage error.
BOX_CHARACTERS = "│╭╮╰╯─"
# What a refused run must never reach: the tracker, or any child process.
GUARDED = ("resolve_tracker_client", "run_child", "stream_child")


class Spy:
    """Every guarded call any ``agent_hub.cli`` module makes: ``(name, argv or None)``."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def guard(self, name: str, real: Callable[..., Any]) -> Callable[..., Any]:
        def spy(*args: Any, **kwargs: Any) -> Any:
            self.calls.append((name, args[0] if args and name != GUARDED[0] else None))
            return real(*args, **kwargs)

        return spy


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> Iterator[Spy]:
    """Wrap every guarded name in every loaded ``agent_hub.cli`` module (each import holds its own
    reference), so a call from any module is seen."""
    import agent_hub.cli.main  # noqa: F401 - loads every command module before patching

    seen = Spy()
    for module_name, module in list(sys.modules.items()):
        if not module_name.startswith("agent_hub.cli"):
            continue
        for name in GUARDED:
            real = getattr(module, name, None)
            if callable(real):
                monkeypatch.setattr(module, name, seen.guard(name, real))
    yield seen


@pytest.fixture(autouse=True)
def wide_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    # A usage message stays on one line of Rich's box.
    monkeypatch.setenv("COLUMNS", "200")


def assert_refused(result: Result, message: str) -> None:
    """Exit 2 with ``message`` as one line of the usage error on stderr, nothing on stdout."""
    assert result.exit_code == 2, result.output
    assert result.stdout == ""
    shown = unstyle(result.stderr)
    assert "Usage: hub run" in shown
    texts = [line.strip(BOX_CHARACTERS + " ") for line in shown.splitlines()]
    assert [text for text in texts if message in text] == [message], shown


SHAPE = "issue must look like DEM-<n> (e.g. DEM-1)"


class TestUsage:
    def test_lists_options_with_defaults_when_help_requested(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        result = run_command(demo_workspace.hub, "run", "--help")

        assert result.exit_code == 0
        words = " ".join(unstyle(result.stdout).replace(BOX_CHARACTERS[0], " ").split())
        for text in (
            "ISSUE",
            "--repo",
            "--live",
            "--max-turns",
            "[default: 40]",
            "--budget",
            "[default: 3",
            "--model",
            "[default: sonnet]",
            "--from",
            "implement|verify",
            "[default: implement]",
            "--effort",
            "low|medium|high",
            "[default: medium]",
        ):
            assert text in words, text

    @pytest.mark.parametrize("issue", ["dem-1", "OPS-1", "DEM-0", "DEM-1x", "DEM-"])
    def test_refuses_issue_when_shape_wrong(
        self, demo_workspace: Workspace, run_command: CommandRunner, spy: Spy, *, issue: str
    ) -> None:
        result = run_command(demo_workspace.hub, "run", issue, "--repo", "demo-api")

        assert_refused(result, SHAPE)
        assert spy.calls == []

    def test_refuses_repo_when_unknown(
        self, demo_workspace: Workspace, run_command: CommandRunner, spy: Spy
    ) -> None:
        result = run_command(demo_workspace.hub, "run", "DEM-1", "--repo", "nope")

        assert_refused(result, "unknown repo in --repo: nope; use one of: demo-api demo-web")
        assert spy.calls == []

    @pytest.mark.parametrize(
        ("arguments", "message"),
        [
            ((), "Missing argument 'ISSUE'."),
            (("--repo", "demo-api"), "Missing argument 'ISSUE'."),
            (("DEM-1",), "Missing option '--repo'."),
        ],
        ids=["nothing", "no-issue", "no-repo"],
    )
    def test_refuses_when_issue_or_repo_missing(
        self,
        demo_workspace: Workspace,
        run_command: CommandRunner,
        spy: Spy,
        *,
        arguments: tuple[str, ...],
        message: str,
    ) -> None:
        result = run_command(demo_workspace.hub, "run", *arguments)

        assert_refused(result, message)
        assert spy.calls == []

    @pytest.mark.parametrize(
        ("option", "value", "message"),
        [
            ("--max-turns", "0", "Invalid value for '--max-turns': 0 is not in the range x>=1."),
            (
                "--budget",
                "0",
                BUDGET := "Invalid value for '--budget': use a number of USD above 0",
            ),
            ("--budget", "-1", BUDGET),
            ("--budget", "inf", BUDGET),
            ("--budget", "nan", BUDGET),
            (
                "--model",
                "m" * 65,
                MODEL := "Invalid value for '--model': use 1 to 64 of A-Z a-z 0-9 . _ -",
            ),
            ("--model", "son net", MODEL),
            ("--model", "", MODEL),
            (
                "--from",
                "plan",
                "Invalid value for '--from': 'plan' is not one of 'implement', 'verify'.",
            ),
            (
                "--effort",
                "huge",
                "Invalid value for '--effort': 'huge' is not one of 'low', 'medium', 'high'.",
            ),
        ],
        ids=[
            "turns-zero",
            "budget-zero",
            "budget-negative",
            "budget-inf",
            "budget-nan",
            "model-long",
            "model-space",
            "model-empty",
            "from-plan",
            "effort-huge",
        ],
    )
    def test_refuses_option_when_value_invalid(
        self,
        demo_workspace: Workspace,
        run_command: CommandRunner,
        spy: Spy,
        *,
        option: str,
        value: str,
        message: str,
    ) -> None:
        result = run_command(
            demo_workspace.hub, "run", "DEM-1", "--repo", "demo-api", option, value
        )

        assert_refused(result, message)
        assert spy.calls == []

    def test_exits_two_when_not_a_hub(
        self, demo_workspace: Workspace, run_command: CommandRunner, spy: Spy
    ) -> None:
        result = run_command(demo_workspace.ws, "run", "DEM-1", "--repo", "demo-api")

        assert result.exit_code == 2
        assert result.stdout == ""
        assert result.stderr == (
            f"{demo_workspace.ws}: not a hub: no hub.json in this folder"
            " (hub run runs in the hub folder or through ./hub)\n"
        )
        assert spy.calls == []


def run_tool(name: str, *args: str, cwd: Any) -> subprocess.CompletedProcess[str]:
    """Run ``name`` as a child of the test would, found on the run workspace's ``PATH``."""
    found = shutil.which(name, path=os.environ["PATH"])
    assert found is not None, f"{name} is not on the run workspace's PATH"
    return subprocess.run(  # noqa: S603 - a fake or linked tool of the workspace's bin, absolute
        [found, *args], cwd=cwd, env=dict(os.environ), capture_output=True, text=True, check=False
    )


class TestRunWorkspace:
    def test_runs_fakes_from_path_when_workspace_built(self, run_workspace: Workspace) -> None:
        workspace = run_workspace.workspace
        clone = workspace.ws / "demo-api"

        claude = run_tool("claude", "-p", "x", "--allowedTools", "Read", cwd=clone)
        gh = run_tool("gh", "pr", "create", cwd=clone)
        gate = run_tool("bash", "-c", "make check", cwd=clone)

        assert claude.returncode == 0, claude.stderr
        reply = json.loads(claude.stdout)
        assert json.loads(reply["result"].splitlines()[-1])["status"] == "done"
        assert workspace.git(clone, "log", "-1", "--format=%s") == COMMIT_SUBJECT
        assert gh.stdout == f"{PR_URL}\n"
        assert gate.returncode == 0
        assert [call["argv"] for call in run_workspace.calls("make")] == [["check"]]
        logged = run_workspace.calls("claude")
        assert [call["cwd"] for call in logged] == [str(clone)]
        assert logged[0]["pgid"] == os.getpgid(0)
        assert "PATH" in logged[0]["env"]
        assert str(run_workspace.bin) not in json.dumps(logged[0]["env"])


KEY_VARIABLE = "LINEAR_API_KEY"
API_LINE = 'tracker: Linear API (tracker.transport "api")'
MCP_LINE = 'tracker: Linear MCP via claude -p (tracker.transport "mcp")'
MISSING_KEY = (
    'hub run: LINEAR_API_KEY is not set; export it, or set tracker.transport: "mcp"'
    " in hub.json to reach Linear through its MCP server with claude -p"
)
RUN_DESCRIPTION = "Add a synthetic change.\n\n- touch one file\n- keep the gate green\n"
RUN_ID = re.compile(r"[0-9a-f]{8}")


def synthetic_key() -> str:
    return "lin" + "_api_" + "x" * 40


class Resolve:
    """Replaces ``run_command.resolve_tracker_client``: records the hub root, returns ``client``."""

    def __init__(self, client: object) -> None:
        self.client = client
        self.roots: list[object] = []

    def __call__(self, config: HubConfig, environ: object, *, hub_root: object) -> TrackerClient:
        self.roots.append(hub_root)
        return self.client  # type: ignore[return-value]


def inject(monkeypatch: pytest.MonkeyPatch, client: object) -> Resolve:
    resolve = Resolve(client)
    monkeypatch.setattr(run_command, "resolve_tracker_client", resolve)
    return resolve


def set_transport(hub: Any, transport: str) -> None:
    document = json.loads((hub / "hub.json").read_text())
    document["tracker"]["transport"] = transport
    (hub / "hub.json").write_text(json.dumps(document, indent=2) + "\n")


@pytest.fixture
def with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_VARIABLE, synthetic_key())


def dry_lines(result: Result) -> list[str]:
    assert result.exit_code == 0, result.output
    return result.stdout.splitlines()


@pytest.mark.usefixtures("with_key")
class TestDryRun:
    def test_prints_every_step_when_dry_run(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = run_workspace.workspace
        resolve = inject(monkeypatch, run_tracker)
        hub = os.path.realpath(workspace.hub)
        worktree = os.path.realpath(workspace.ws / "demo-api") + "/.claude/worktrees/dem-1"
        web = os.path.realpath(workspace.ws / "demo-web")

        result = run_command(workspace.hub, "run", "DEM-1", "--repo", "demo-api")

        lines = dry_lines(result)
        assert result.stderr == API_LINE + "\n"
        assert run_tracker.calls == [("get_issue", "DEM-1")]
        assert [str(root) for root in resolve.roots] == [hub]
        assert lines[0] == "would run: ./hub worktree dem-1 --only demo-api"
        claude = lines[1]
        assert claude.startswith("would run: claude -p ")
        assert claude.endswith(f"   (cwd {worktree})")
        for piece in (
            "DEM-1",
            "Synthetic run issue",
            "https://linear.app/demo/issue/DEM-1",
            json.dumps(RUN_DESCRIPTION)[1:-1],
            " --output-format json --max-turns 40 --max-budget-usd 3 --model sonnet ",
            """ --settings '{"effortLevel": "medium"}' """,
            f" --add-dir {hub} {web} --allowedTools Read Edit ",
            " 'Bash(make:*)' 'Bash(ls:*)' ",
        ):
            assert piece in claude, piece
        assert "mcp__" not in claude
        assert lines[2] == f"would run: bash -c 'make check'   (cwd {worktree})"
        assert lines[3] == f"would run: git push -u origin jdoe/dem-1   (cwd {worktree})"
        assert lines[4].startswith(
            "would run: gh pr create --base trunk --head jdoe/dem-1 --title DEM-1 --body "
        )
        assert "Gates green: `make check`." in lines[4]
        assert lines[5:7] == [
            "would call: move_state(DEM-1, In Review)",
            "would call: remove_label(DEM-1, agent-failed)",
        ]
        comment = re.fullmatch(
            r"would call: comment\(DEM-1, Run (\w+) opened \(dry run\)\. \(dry run\)\)", lines[7]
        )
        assert comment is not None, lines[7]
        assert RUN_ID.fullmatch(comment.group(1))
        assert len(lines) == 8
        assert run_workspace.calls("claude") == []

    def test_writes_nothing_when_dry_run(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
        tree_digest: Callable[[Any], dict[str, Any]],
    ) -> None:
        workspace = run_workspace.workspace
        inject(monkeypatch, run_tracker)
        before = tree_digest(workspace.ws)

        result = run_command(workspace.hub, "run", "DEM-1", "--repo", "demo-api")

        assert result.exit_code == 0, result.output
        assert tree_digest(workspace.ws) == before
        assert not (workspace.hub / ".agent-runs").exists()
        assert not (workspace.hub / "brain" / "_inbox" / "runs").exists()
        assert [call[0] for call in run_tracker.calls] == ["get_issue"]
        for tool in ("claude", "gh", "make"):
            assert run_workspace.calls(tool) == []

    def test_omits_remove_when_issue_lacks_failed_label(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        issue = run_tracker.backend.issues["DEM-1"]
        unlabelled = tuple(label for label in issue.labels if label != "agent-failed")
        run_tracker.backend.issues["DEM-1"] = issue.model_copy(update={"labels": unlabelled})
        inject(monkeypatch, run_tracker)

        result = run_command(run_workspace.workspace.hub, "run", "DEM-1", "--repo", "demo-api")

        calls = [line for line in dry_lines(result) if line.startswith("would call: ")]
        assert [line.split("(")[0] for line in calls] == [
            "would call: move_state",
            "would call: comment",
        ]

    def test_prints_no_claude_when_from_verify(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        inject(monkeypatch, run_tracker)

        result = run_command(
            run_workspace.workspace.hub, "run", "DEM-1", "--repo", "demo-api", "--from", "verify"
        )

        lines = dry_lines(result)
        assert not [line for line in lines if line.startswith("would run: claude")]
        assert lines[0] == "would run: ./hub worktree dem-1 --only demo-api"
        assert lines[1].startswith("would run: bash -c 'make check'")

    def test_escapes_issue_text_when_it_holds_control_characters(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        issue = run_tracker.backend.issues["DEM-1"]
        title = "Synthetic \x1b[2J\u202e title"
        run_tracker.backend.issues["DEM-1"] = issue.model_copy(update={"title": title})
        inject(monkeypatch, run_tracker)

        result = run_command(run_workspace.workspace.hub, "run", "DEM-1", "--repo", "demo-api")

        assert "\x1b" not in result.stdout
        assert "\u202e" not in result.stdout
        assert all(line.isprintable() for line in dry_lines(result))

    def test_exits_one_when_read_fails(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        del run_tracker.backend.issues["DEM-1"]
        inject(monkeypatch, run_tracker)

        result = run_command(run_workspace.workspace.hub, "run", "DEM-1", "--repo", "demo-api")

        assert result.exit_code == 1
        assert result.stdout == ""
        lines = result.stderr.splitlines()
        assert lines[0] == API_LINE
        assert len(lines) == 2
        assert lines[1].startswith("get_issue DEM-1: ")
        assert run_tracker.calls == [("get_issue", "DEM-1")]


class TestTransport:
    @pytest.mark.parametrize("live", [False, True], ids=["dry", "live"])
    @pytest.mark.parametrize("transport", [None, "api"], ids=["absent", "api"])
    @pytest.mark.parametrize("key", [None, ""], ids=["unset", "empty"])
    def test_exits_one_when_key_missing(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        spy: Spy,
        *,
        monkeypatch: pytest.MonkeyPatch,
        live: bool,
        transport: str | None,
        key: str | None,
    ) -> None:
        hub = run_workspace.workspace.hub
        if transport is not None:
            set_transport(hub, transport)
        if key is None:
            monkeypatch.delenv(KEY_VARIABLE, raising=False)
        else:
            monkeypatch.setenv(KEY_VARIABLE, key)

        result = run_command(hub, "run", "DEM-1", "--repo", "demo-api", *(["--live"] * live))

        assert result.exit_code == 1
        assert result.stdout == ""
        assert result.stderr == MISSING_KEY + "\n"
        assert spy.calls == []
        for tool in ("claude", "gh", "make"):
            assert run_workspace.calls(tool) == []

    @pytest.mark.parametrize("key", [None, "set"], ids=["no-key", "key"])
    def test_uses_mcp_adapter_when_transport_mcp(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        tmp_path: Any,
        *,
        monkeypatch: pytest.MonkeyPatch,
        key: str | None,
    ) -> None:
        hub = run_workspace.workspace.hub
        set_transport(hub, "mcp")
        if key is None:
            monkeypatch.delenv(KEY_VARIABLE, raising=False)
        else:
            monkeypatch.setenv(KEY_VARIABLE, synthetic_key())
        issue = {
            "id": "DEM-1",
            "title": "Synthetic MCP issue",
            "description": RUN_DESCRIPTION,
            "url": "https://linear.app/demo/issue/DEM-1",
            "state": "Todo",
            "labels": ["agent-ready", "demo-api"],
        }
        (tmp_path / "issue.json").write_text(json.dumps(issue))
        monkeypatch.setenv("FAKE_CLAUDE_ISSUE", str(tmp_path / "issue.json"))

        result = run_command(hub, "run", "DEM-1", "--repo", "demo-api")

        lines = dry_lines(result)
        assert result.stderr == MCP_LINE + "\n"
        assert "Synthetic MCP issue" in lines[1]
        calls = run_workspace.calls("claude")
        assert len(calls) == 1
        assert calls[0]["tracker"] is True
        assert calls[0]["cwd"] == os.path.realpath(hub)
        assert KEY_VARIABLE not in calls[0]["env"]
        assert [line.split("(")[0] for line in lines[5:]] == [
            "would call: move_state",
            "would call: comment",
        ]


SUMMARY = "Adds the synthetic change."
OTEL = re.compile(r"repo=demo-api,issue=DEM-1,agent_run=([0-9a-f]{8})")
GH_TOKEN_VALUE = "gh" + "o_" + "y" * 36
SETUP_LOG = "setup-env.txt"


def live(run_command: CommandRunner, workspace: Any) -> Result:
    return run_command(workspace.hub, "run", "DEM-1", "--repo", "demo-api", "--live")


def worktree_of(workspace: Any) -> Any:
    return workspace.ws / "demo-api" / ".claude" / "worktrees" / "dem-1"


def run_id_of(run_workspace: Any) -> str:
    (call,) = run_workspace.calls("claude")
    found = OTEL.fullmatch(call["values"]["OTEL_RESOURCE_ATTRIBUTES"])
    assert found is not None, call["values"]
    return found.group(1)


@pytest.mark.usefixtures("with_key")
class TestLiveSuccess:
    def test_creates_worktree_as_hub_worktree_does_when_live(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = run_workspace.workspace
        inject(monkeypatch, run_tracker)
        base = workspace.origin_head("demo-api")

        result = live(run_command, workspace)

        assert result.exit_code == 0, result.output
        worktree = worktree_of(workspace)
        assert f"created  {worktree} (jdoe/dem-1 from origin/trunk)" in result.stdout.splitlines()
        assert workspace.git(worktree, "branch", "--show-current") == "jdoe/dem-1"
        assert workspace.git(worktree, "rev-parse", "HEAD~1") == base

    def test_runs_session_with_issue_text_and_no_tracker_tool_when_live(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = run_workspace.workspace
        inject(monkeypatch, run_tracker)
        monkeypatch.setenv("GH_TOKEN", GH_TOKEN_VALUE)
        script = b'#!/bin/sh\nexport -p > "$1/' + SETUP_LOG.encode() + b'"\n'
        workspace.advance("demo-api", {"scripts/worktree-setup.sh": (script, 0o755)})

        result = live(run_command, workspace)

        assert result.exit_code == 0, result.output
        (call,) = run_workspace.calls("claude")
        argv = call["argv"]
        tools = argv[argv.index("--allowedTools") + 1 :]
        assert tuple(tools) == IMPLEMENTING_TOOLS
        assert tools.count("Bash(make:*)") == 1
        prompt = argv[argv.index("-p") + 1]
        for text in ("DEM-1", "Synthetic run issue", RUN_DESCRIPTION, "untrusted"):
            assert text in prompt
        assert "mcp__" not in prompt
        assert call["cwd"] == str(worktree_of(workspace))
        assert call["pgid"] == os.getpgid(0)
        assert OTEL.fullmatch(call["values"]["OTEL_RESOURCE_ATTRIBUTES"])
        for hidden in (KEY_VARIABLE, "GH_TOKEN", "GITHUB_TOKEN"):
            assert hidden not in call["env"]
        setup = (worktree_of(workspace) / SETUP_LOG).read_text()
        assert KEY_VARIABLE not in setup
        assert synthetic_key() not in setup
        (gh,) = run_workspace.calls("gh")
        assert "GH_TOKEN" in gh["env"]
        assert KEY_VARIABLE not in gh["env"]

    def test_opens_pr_and_reports_when_session_done(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = run_workspace.workspace
        inject(monkeypatch, run_tracker)

        result = live(run_command, workspace)

        assert result.exit_code == 0, result.output
        worktree = str(worktree_of(workspace))
        assert [(call["argv"], call["cwd"]) for call in run_workspace.calls("make")] == [
            (["check"], worktree)
        ]
        assert workspace.git(
            workspace.origin("demo-api"), "log", "-1", "--format=%s", "jdoe/dem-1"
        ) == (COMMIT_SUBJECT)
        (gh,) = run_workspace.calls("gh")
        assert gh["cwd"] == worktree
        assert gh["argv"] == [
            *("pr", "create", "--base", "trunk", "--head", "jdoe/dem-1"),
            *("--title", COMMIT_SUBJECT, "--body"),
            f"DEM-1\n\n{SUMMARY}\n\n## Verification\nGates green: `make check`.",
        ]
        run_id = run_id_of(run_workspace)
        backend = run_tracker.backend
        assert backend.issues["DEM-1"].state == "In Review"
        assert "agent-failed" not in backend.issues["DEM-1"].labels
        assert backend.comments == [("DEM-1", f"Run {run_id} opened {PR_URL}. {SUMMARY}")]
        assert [call[0] for call in run_tracker.calls] == [
            "get_issue",
            "move_state",
            "remove_label",
            "comment",
        ]


@pytest.mark.usefixtures("with_key")
class TestWorktreeStage:
    def test_fails_worktree_stage_when_repo_not_cloned(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = run_workspace.workspace
        inject(monkeypatch, run_tracker)
        shutil.rmtree(workspace.ws / "demo-api" / ".git")

        result = live(run_command, workspace)

        assert result.exit_code == 1
        (comment,) = run_tracker.backend.comments
        assert re.fullmatch(
            r"Run [0-9a-f]{8} failed at WORKTREE\. Diagnosis: demo-api is not a git checkout;"
            r" clone it next to the hub",
            comment[1],
        ), comment
        assert "agent-failed" in run_tracker.backend.issues["DEM-1"].labels
        assert [call[0] for call in run_tracker.calls] == ["get_issue", "add_label", "comment"]
        for tool in ("claude", "gh", "make"):
            assert run_workspace.calls(tool) == []

    @pytest.mark.parametrize(
        ("git_step", "error", "reason"),
        [
            ("check-ref-format", PermissionError(13, "Permission denied"), "git could not run"),
            (
                "fetch",
                ChildTimedOutError(program="git", timeout=1800),
                "git timed out after 1800 s",
            ),
        ],
        ids=["oserror", "timeout"],
    )
    def test_fails_worktree_stage_when_git_call_raises(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
        git_step: str,
        error: Exception,
        reason: str,
    ) -> None:
        inject(monkeypatch, run_tracker)
        real = run_steps.run_child

        def failing(argv: list[str], **options: Any) -> Any:
            if argv[1:2] == [git_step]:
                raise error
            return real(argv, **options)

        monkeypatch.setattr(run_steps, "run_child", failing)

        result = live(run_command, run_workspace.workspace)

        assert result.exit_code == 1
        (comment,) = run_tracker.backend.comments
        assert " failed at WORKTREE. Diagnosis: " in comment[1]
        assert reason in comment[1]
        assert run_workspace.calls("claude") == []
