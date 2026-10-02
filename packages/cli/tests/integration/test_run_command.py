"""``hub run``: one issue from the tracker to a PR through the ``TrackerClient`` port (AC-27.14 on).

Every run is in process, in a copy of the ``DEMO`` workspace (``demo_workspace``: team ``DEM``,
repos ``demo-api`` and ``demo-web``, default branch ``trunk``, branch prefix ``jdoe/``).

This module re-expresses hub ``tests/test_agent_runner.py`` at hub commit ``300559b``, the old
runner script's tests, against the command; the full matrix of cases lives here.
``TestUsage`` replaces its usage checks (``--repo`` outside ``hub.json``, an issue without the
team's prefix): each refusal is a usage error, exit 2, before any tracker call or child process.
"""

import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from click import unstyle
from typer.testing import Result

from agent_hub.cli import run_command, run_log, run_steps
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
PUSH_OPTIONS = (
    *("-c", "core.fsmonitor=false"),
    *("-c", "push.gpgSign=false"),
    *("-c", "core.hooksPath=/dev/null"),
)
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
            f" --add-dir {hub} {web} --permission-mode dontAsk --allowedTools Read Edit ",
            " --disallowedTools mcp__Linear mcp__claude_ai_Linear mcp__Linear__",
            " 'Bash(make:*)' 'Bash(ls:*)' ",
        ):
            assert piece in claude, piece
        # Tracker tools appear only after --disallowedTools: neither the prompt nor the allowed
        # tools name one.
        assert "mcp__" not in claude.split(" --disallowedTools ")[0]
        assert lines[2] == f"would run: bash -c 'make check'   (cwd {worktree})"
        assert lines[3] == (
            "would run: git -c core.fsmonitor=false -c push.gpgSign=false"
            " -c core.hooksPath=/dev/null push --no-verify -u origin jdoe/dem-1"
            f"   (cwd {worktree})"
        )
        assert lines[4].startswith(
            "would run: gh pr create --repo acme/demo-api --base trunk --head jdoe/dem-1"
            " --title '(dry run: subject of the last commit)' --body "
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

    @pytest.mark.parametrize(("repo", "branch"), [("demo-api", "master"), ("demo-web", "trunk")])
    def test_opens_pr_against_repo_branch_when_dry_run(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
        repo: str,
        branch: str,
    ) -> None:
        workspace = run_workspace.workspace
        workspace.use_repo_branch("demo-api", "master")
        inject(monkeypatch, run_tracker)

        result = run_command(workspace.hub, "run", "DEM-1", "--repo", repo)

        (pr,) = [line for line in dry_lines(result) if line.startswith("would run: gh ")]
        assert pr.startswith(
            f"would run: gh pr create --repo acme/{repo} --base {branch} --head jdoe/dem-1 "
        )


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
        # Outside the worktree, which must stay clean for the gate.
        script = b'#!/bin/sh\nexport -p > "$FAKE_RUN_LOGS/' + SETUP_LOG.encode() + b'"\n'
        workspace.advance("demo-api", {"scripts/worktree-setup.sh": (script, 0o755)})

        result = live(run_command, workspace)

        assert result.exit_code == 0, result.output
        (call,) = run_workspace.calls("claude")
        argv = call["argv"]
        tools = argv[argv.index("--allowedTools") + 1 : argv.index("--disallowedTools")]
        assert tuple(tools) == IMPLEMENTING_TOOLS
        assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
        denied = argv[argv.index("--disallowedTools") + 1 :]
        for rule in ("mcp__Linear", "mcp__claude_ai_Linear"):
            assert rule in denied
        for name in ("save_issue", "save_comment", "get_issue", "list_comments"):
            assert f"mcp__Linear__{name}" in denied
            assert f"mcp__claude_ai_Linear__{name}" in denied
        assert "--tools" not in argv
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
        setup = (run_workspace.logs / SETUP_LOG).read_text()
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
            *("pr", "create", "--repo", "acme/demo-api", "--base", "trunk"),
            *("--head", "jdoe/dem-1", "--title", COMMIT_SUBJECT, "--body"),
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

    def test_reads_commits_and_opens_pr_on_repo_branch_when_live(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = run_workspace.workspace
        workspace.use_repo_branch("demo-api", "master")
        inject(monkeypatch, run_tracker)
        base = workspace.origin_head("demo-api", "master")

        result = live(run_command, workspace)

        assert result.exit_code == 0, result.output
        worktree = worktree_of(workspace)
        assert f"created  {worktree} (jdoe/dem-1 from origin/master)" in result.stdout.splitlines()
        assert workspace.git(worktree, "rev-parse", "HEAD~1") == base
        (gh,) = run_workspace.calls("gh")
        assert gh["argv"][:10] == [
            *("pr", "create", "--repo", "acme/demo-api", "--base", "master"),
            *("--head", "jdoe/dem-1", "--title", COMMIT_SUBJECT),
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
            # The step's git command, after any -c options (the fetch has its own).
            command = argv[1:]
            while command[:1] == ["-c"]:
                command = command[2:]
            if command[:1] == [git_step]:
                raise error
            return real(argv, **options)

        monkeypatch.setattr(run_steps, "run_child", failing)

        result = live(run_command, run_workspace.workspace)

        assert result.exit_code == 1
        (comment,) = run_tracker.backend.comments
        assert " failed at WORKTREE. Diagnosis: " in comment[1]
        assert reason in comment[1]
        assert run_workspace.calls("claude") == []


TOKENS = (KEY_VARIABLE, "GH_TOKEN", "GITHUB_TOKEN")
GITHUB_TOKEN_VALUE = "ghp" + "_" + "z" * 36


def git_calls(run_workspace: Any, command: str) -> list[dict[str, Any]]:
    """The logged git calls whose first argument after the ``-c`` options is ``command``."""
    found = []
    for call in run_workspace.calls("git"):
        argv = list(call["argv"])
        while argv[:1] == ["-c"]:
            argv = argv[2:]
        if argv[:1] == [command]:
            found.append(call)
    return found


@pytest.mark.usefixtures("with_key")
class TestEnvironments:
    def test_reads_main_checkout_without_key_when_root_is_hub_worktree(
        self,
        logged_git: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = logged_git.workspace
        hub = workspace.hub
        workspace.git(hub, "-c", "init.defaultBranch=main", "init", "-q")
        workspace.git(hub, "add", "-A")
        workspace.git(hub, "commit", "-q", "-m", "hub")
        hub_worktree = hub / ".claude" / "worktrees" / "x"
        workspace.git(hub, "worktree", "add", "-q", "-b", "x", str(hub_worktree))
        resolve = inject(monkeypatch, run_tracker)

        result = run_command(
            workspace.base,
            "run",
            "DEM-1",
            "--repo",
            "demo-api",
            env={"AGENT_HUB_ROOT": str(hub_worktree)},
        )

        assert result.exit_code == 0, result.output
        assert [str(root) for root in resolve.roots] == [os.path.realpath(hub)]
        (read,) = git_calls(logged_git, "rev-parse")
        assert KEY_VARIABLE not in read["env"]

    def test_runs_gate_and_reads_without_tokens_when_live(
        self,
        logged_git: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        inject(monkeypatch, run_tracker)
        monkeypatch.setenv("GH_TOKEN", GH_TOKEN_VALUE)
        monkeypatch.setenv("GITHUB_TOKEN", GITHUB_TOKEN_VALUE)

        result = live(run_command, logged_git.workspace)

        assert result.exit_code == 0, result.output
        (gate,) = logged_git.calls("make")
        reads = [*git_calls(logged_git, "log"), *git_calls(logged_git, "status")]
        assert reads
        for call in [gate, *reads]:
            assert not [name for name in TOKENS if name in call["env"]], call["argv"]
        (push,) = git_calls(logged_git, "push")
        assert "GH_TOKEN" in push["env"]
        assert KEY_VARIABLE not in push["env"]
        assert push["argv"] == [
            *PUSH_OPTIONS,
            *("push", "--no-verify", "-u", "origin", "jdoe/dem-1"),
        ]

    def test_skips_planted_hook_when_pushing(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = run_workspace.workspace
        inject(monkeypatch, run_tracker)
        hooks = workspace.ws / "demo-api" / ".git" / "hooks"
        marker = run_workspace.logs / "hook-ran"
        for hook in ("pre-push", "reference-transaction"):
            (hooks / hook).write_text(f'#!/bin/sh\necho "$0" >> "{marker}"\n')
            (hooks / hook).chmod(0o755)

        result = live(run_command, workspace)

        assert result.exit_code == 0, result.output
        ran = marker.read_text() if marker.exists() else ""
        assert "pre-push" not in ran


@pytest.mark.usefixtures("with_key")
class TestRerun:
    def test_reports_existing_pr_when_rerun_after_pr_opened(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = run_workspace.workspace
        inject(monkeypatch, run_tracker)
        first = live(run_command, workspace)
        assert first.exit_code == 0, first.output
        monkeypatch.setenv("FAKE_GH_MODE", "exists")
        run_tracker.calls.clear()

        second = live(run_command, workspace)

        assert second.exit_code == 0, second.output
        issue = run_tracker.backend.issues["DEM-1"]
        assert "agent-failed" not in issue.labels
        assert issue.state == "In Review"
        assert [call[0] for call in run_tracker.calls] == ["get_issue", "move_state", "comment"]
        comments = [body for _, body in run_tracker.backend.comments]
        assert len(comments) == 2
        assert re.fullmatch(
            rf"Run [0-9a-f]{{8}} opened {re.escape(PR_URL)}\. {SUMMARY}", comments[1]
        )
        views = [
            call["argv"] for call in run_workspace.calls("gh") if call["argv"][:2] == ["pr", "view"]
        ]
        assert views == [
            ["pr", "view", "jdoe/dem-1", "--repo", "acme/demo-api", "--json", "url,state"]
        ]


@pytest.mark.usefixtures("with_key")
class TestCleanTree:
    def test_fails_verifying_when_session_leaves_changes(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        inject(monkeypatch, run_tracker)
        monkeypatch.setenv("FAKE_CLAUDE_MODE", "done-dirty")

        result = live(run_command, run_workspace.workspace)

        assert result.exit_code == 1
        (comment,) = [body for _, body in run_tracker.backend.comments]
        assert re.fullmatch(
            r"Run [0-9a-f]{8} failed at VERIFYING\. Diagnosis: uncommitted changes in the worktree",
            comment,
        )
        assert run_workspace.calls("make") == []
        assert run_workspace.calls("gh") == []

    def test_pushes_when_session_leaves_untracked_file(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Owner decision 2026-10-02: tracked files only. An untracked file is never in the PR,
        # and build output or editor files would otherwise stop runs.
        inject(monkeypatch, run_tracker)
        monkeypatch.setenv("FAKE_CLAUDE_MODE", "done-untracked")

        result = live(run_command, run_workspace.workspace)

        assert result.exit_code == 0, result.output
        assert [call["argv"] for call in run_workspace.calls("make")] == [["check"]]

    def test_fails_verifying_when_from_verify_finds_changes(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = run_workspace.workspace
        inject(monkeypatch, run_tracker)
        worktree = worktree_of(workspace)
        clone = workspace.ws / "demo-api"
        workspace.git(
            clone, "worktree", "add", "-q", "-b", "jdoe/dem-1", str(worktree), "origin/trunk"
        )
        (worktree / "done.txt").write_text("done\n")
        workspace.git(worktree, "add", "done.txt")
        workspace.git(worktree, "commit", "-q", "-m", "feat(api): done (DEM-1)")
        # A tracked file changed and not committed (an untracked one is no reason to stop).
        (worktree / "done.txt").write_text("changed\n")

        result = run_command(
            workspace.hub, "run", "DEM-1", "--repo", "demo-api", "--live", "--from", "verify"
        )

        assert result.exit_code == 1
        assert f"exists   {worktree}" in result.stdout.splitlines()
        (comment,) = [body for _, body in run_tracker.backend.comments]
        assert comment.endswith(
            " failed at VERIFYING. Diagnosis: uncommitted changes in the worktree"
        )
        assert run_workspace.calls("claude") == []
        assert run_workspace.calls("make") == []


def records(workspace: Any) -> list[dict[str, Any]]:
    """Every record the runs wrote to the hub's ``.agent-runs`` files, in order."""
    found = []
    for path in sorted((workspace.hub / ".agent-runs").glob("*.jsonl")):
        found += [json.loads(line) for line in path.read_text().splitlines()]
    return found


@pytest.mark.usefixtures("with_key")
class TestRunLoose:
    def test_bounds_child_output_when_gate_prints_more_than_cap(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        inject(monkeypatch, run_tracker)
        monkeypatch.setenv("FAKE_MAKE_EXIT", "2")
        monkeypatch.setenv("FAKE_MAKE_BYTES", str(1 << 20))
        limits: list[object] = []
        real = run_steps.run_child

        def spy(argv: list[str], **options: Any) -> Any:
            limits.append(options.get("output_limit"))
            return real(argv, **options)

        monkeypatch.setattr(run_steps, "run_child", spy)

        result = live(run_command, run_workspace.workspace)

        assert result.exit_code == 1
        assert limits
        assert all(
            limit is not None and limit <= run_steps.SESSION_OUTPUT_LIMIT for limit in limits
        )
        assert run_steps.CHILD_OUTPUT_LIMIT == 64 * 1024
        assert run_steps.SESSION_OUTPUT_LIMIT == 1 << 20
        (failed,) = [
            record for record in records(run_workspace.workspace) if record["event"] == "failed"
        ]
        assert failed["stage"] == "VERIFYING"
        assert failed["reason"].endswith("synthetic gate output\n")
        assert len(failed["reason"]) <= 1_500

    def test_fails_stage_when_git_read_fails(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = run_workspace.workspace
        inject(monkeypatch, run_tracker)
        clone = workspace.ws / "demo-api"
        worktree = worktree_of(workspace)
        workspace.git(
            clone, "worktree", "add", "-q", "-b", "jdoe/dem-1", str(worktree), "origin/trunk"
        )
        workspace.git(clone, "update-ref", "-d", "refs/remotes/origin/trunk")

        result = run_command(
            workspace.hub, "run", "DEM-1", "--repo", "demo-api", "--live", "--from", "verify"
        )

        assert result.exit_code == 1
        (comment,) = [body for _, body in run_tracker.backend.comments]
        assert " failed at IMPLEMENTING. Diagnosis: git log failed: " in comment
        assert "no commit on the branch" not in comment

    def test_names_pr_and_writes_not_done_when_record_fails_after_pr_opened(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        inject(monkeypatch, run_tracker)
        real = run_log.RunLog._append

        def failing(self: Any, folder: Any, moment: Any, *, suffix: str, line: str) -> None:
            if '"event": "pr_open"' in line:
                raise PermissionError(13, "Permission denied")
            real(self, folder, moment, suffix=suffix, line=line)

        monkeypatch.setattr(run_log.RunLog, "_append", failing)

        result = live(run_command, run_workspace.workspace)

        assert result.exit_code == 1
        assert isinstance(result.exception, SystemExit)
        lines = result.stderr.splitlines()
        assert "hub run: could not write the run's records: Permission denied" in lines
        assert f"hub run: the PR is open: {PR_URL}" in lines
        assert "not done: move_state(DEM-1, In Review)" in lines
        assert "not done: remove_label(DEM-1, agent-failed)" in lines
        assert [line for line in lines if line.startswith("not done: comment(DEM-1, Run ")]
        assert [call[0] for call in run_tracker.calls] == ["get_issue"]

    def test_records_verdict_when_session_finished(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        inject(monkeypatch, run_tracker)

        result = live(run_command, run_workspace.workspace)

        assert result.exit_code == 0, result.output
        (finished,) = [
            record
            for record in records(run_workspace.workspace)
            if record["event"] == "agent_finished"
        ]
        assert finished["verdict"] == {
            "status": "done",
            "summary": SUMMARY,
            "tests": "make check-fast",
        }
        assert finished["subtype"] == "success"


FAILED_COMMENT = re.compile(r"Run [0-9a-f]{8} failed at ([A-Z_]+)\. Diagnosis: (.*)", re.DOTALL)


def assert_failed_at(result: Result, run_tracker: Any, stage: str) -> str:
    """Exit 1, ``agent-failed`` added and exactly one comment naming ``stage``; its diagnosis."""
    assert result.exit_code == 1, result.output
    assert "agent-failed" in run_tracker.backend.issues["DEM-1"].labels
    (comment,) = [body for _, body in run_tracker.backend.comments]
    found = FAILED_COMMENT.fullmatch(comment)
    assert found is not None, comment
    assert found.group(1) == stage
    assert len(found.group(2)) <= 900
    assert "Agent" not in comment
    assert [call[0] for call in run_tracker.calls] == ["get_issue", "add_label", "comment"]
    return found.group(2)


def assert_never_pushed(run_workspace: Any) -> None:
    workspace = run_workspace.workspace
    branches = workspace.git(workspace.origin("demo-api"), "branch", "--list", "jdoe/dem-1")
    assert branches == ""
    assert [
        call for call in run_workspace.calls("gh") if call["argv"][:2] == ["pr", "create"]
    ] == []


def verify_ready_worktree(workspace: Any) -> None:
    """The issue's worktree with one commit, as a session would have left it."""
    worktree = worktree_of(workspace)
    clone = workspace.ws / "demo-api"
    workspace.git(clone, "worktree", "add", "-q", "-b", "jdoe/dem-1", str(worktree), "origin/trunk")
    (worktree / "done.txt").write_text("done\n")
    workspace.git(worktree, "add", "done.txt")
    workspace.git(worktree, "commit", "-q", "-m", "feat(api): done before (DEM-1)")


@pytest.mark.usefixtures("with_key")
class TestVerdict:
    """The old runner's verdict cases (hub tests/test_agent_runner.py at 300559b), live."""

    @pytest.mark.parametrize(
        ("mode", "diagnosis"),
        [
            ("blocked", "the implementing session stopped: needs a plan"),
            (
                "blocked-text",
                "the implementing session stopped: BLOCKED: the issue has an open question",
            ),
        ],
        ids=["verdict", "text"],
    )
    def test_fails_implementing_when_blocked(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
        mode: str,
        diagnosis: str,
    ) -> None:
        inject(monkeypatch, run_tracker)
        monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)

        result = live(run_command, run_workspace.workspace)

        assert assert_failed_at(result, run_tracker, "IMPLEMENTING") == diagnosis
        assert_never_pushed(run_workspace)
        assert run_workspace.calls("make") == []

    def test_fails_implementing_when_session_errors(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        inject(monkeypatch, run_tracker)
        monkeypatch.setenv("FAKE_CLAUDE_MODE", "error")

        result = live(run_command, run_workspace.workspace)

        diagnosis = assert_failed_at(result, run_tracker, "IMPLEMENTING")
        assert diagnosis == "the implementing session errored (success): ran out of turns"
        assert_never_pushed(run_workspace)

    def test_opens_pr_from_commits_when_no_verdict(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        inject(monkeypatch, run_tracker)
        monkeypatch.setenv("FAKE_CLAUDE_MODE", "prose")

        result = live(run_command, run_workspace.workspace)

        assert result.exit_code == 0, result.output
        (create,) = [
            call for call in run_workspace.calls("gh") if call["argv"][:2] == ["pr", "create"]
        ]
        body = create["argv"][-1]
        assert body == f"DEM-1\n\n{COMMIT_SUBJECT}\n\n## Verification\nGates green: `make check`."
        (comment,) = [body for _, body in run_tracker.backend.comments]
        assert comment.endswith(f"opened {PR_URL}. {COMMIT_SUBJECT}")

    @pytest.mark.parametrize("mode", ["silent", "done-no-commit"], ids=["no-verdict", "done"])
    def test_fails_when_session_leaves_no_commit(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
        mode: str,
    ) -> None:
        inject(monkeypatch, run_tracker)
        monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)

        result = live(run_command, run_workspace.workspace)

        diagnosis = assert_failed_at(result, run_tracker, "IMPLEMENTING")
        assert diagnosis == (
            "no commit on the branch (the session reported done or gave no verdict)"
        )
        assert_never_pushed(run_workspace)

    def test_never_pushes_when_gate_fails(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        inject(monkeypatch, run_tracker)
        monkeypatch.setenv("FAKE_MAKE_EXIT", "2")

        result = live(run_command, run_workspace.workspace)

        diagnosis = assert_failed_at(result, run_tracker, "VERIFYING")
        assert diagnosis == "gate failed: make check\nsynthetic gate output\n"
        assert_never_pushed(run_workspace)

    def test_skips_session_when_from_verify(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = run_workspace.workspace
        inject(monkeypatch, run_tracker)
        verify_ready_worktree(workspace)

        result = run_command(
            workspace.hub, "run", "DEM-1", "--repo", "demo-api", "--live", "--from", "verify"
        )

        assert result.exit_code == 0, result.output
        assert run_workspace.calls("claude") == []
        assert [call["argv"] for call in run_workspace.calls("make")] == [["check"]]
        (comment,) = [body for _, body in run_tracker.backend.comments]
        assert comment.endswith(f"opened {PR_URL}. feat(api): done before (DEM-1)")

    def test_fails_pr_open_when_gh_prints_no_url(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        inject(monkeypatch, run_tracker)
        monkeypatch.setenv("FAKE_GH_MODE", "no-url")

        result = live(run_command, run_workspace.workspace)

        assert assert_failed_at(result, run_tracker, "PR_OPEN") == "gh printed no PR url"

    def test_refuses_empty_check_when_hub_json_has_one(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        spy: Spy,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        hub = run_workspace.workspace.hub
        inject(monkeypatch, run_tracker)
        document = json.loads((hub / "hub.json").read_text())
        document["repos"][1]["check"] = ""
        (hub / "hub.json").write_text(json.dumps(document, indent=2) + "\n")

        result = live(run_command, run_workspace.workspace)

        assert result.exit_code == 1
        assert result.stdout == ""
        lines = result.stderr.splitlines()
        assert lines
        assert all(line.startswith("hub.json: ") for line in lines), lines
        assert any("repos[1].check" in line for line in lines), lines
        assert run_tracker.calls == []
        assert [name for name, _ in spy.calls if name != "resolve_tracker_client"] == []
        for tool in ("claude", "gh", "make"):
            assert run_workspace.calls(tool) == []


OUTAGE = "synthetic outage; retry later"


def inbox_lines(workspace: Any) -> list[str]:
    found = []
    for path in sorted((workspace.hub / "brain" / "_inbox" / "runs").glob("*.md")):
        found += path.read_text().splitlines()
    return found


@pytest.mark.usefixtures("with_key")
class TestTrackerFailures:
    def test_creates_nothing_when_read_fails(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = run_workspace.workspace
        inject(monkeypatch, run_tracker)
        run_tracker.fail_on = {"get_issue"}

        result = live(run_command, workspace)

        assert result.exit_code == 1
        assert result.stderr == f"{API_LINE}\nget_issue DEM-1: {OUTAGE}\n"
        assert not worktree_of(workspace).exists()
        assert run_tracker.calls == [("get_issue", "DEM-1")]
        (failed,) = records(workspace)
        assert (failed["event"], failed["state"], failed["stage"]) == ("failed", "PICKED", "PICKED")
        assert failed["reason"] == f"get_issue DEM-1: {OUTAGE}"
        for tool in ("claude", "gh", "make"):
            assert run_workspace.calls(tool) == []

    def test_stops_report_when_move_fails(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = run_workspace.workspace
        inject(monkeypatch, run_tracker)
        run_tracker.fail_on = {"move_state"}

        result = live(run_command, workspace)

        assert result.exit_code == 1
        assert [call[0] for call in run_tracker.calls] == ["get_issue", "move_state"]
        lines = result.stderr.splitlines()
        assert f"hub run: move_state DEM-1: {OUTAGE}" in lines
        assert f"hub run: the PR is open: {PR_URL}" in lines
        assert "not done: remove_label(DEM-1, agent-failed)" in lines
        assert [line for line in lines if line.startswith("not done: comment(DEM-1, Run ")]
        reported = [record for record in records(workspace) if record["event"] == "reported"]
        assert [(record["ok"], record["pr"]) for record in reported] == [(False, PR_URL)]
        (inbox,) = inbox_lines(workspace)
        assert inbox.endswith(f": PR {PR_URL}; report failed; $0.42")

    def test_stops_report_when_add_label_fails(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        inject(monkeypatch, run_tracker)
        monkeypatch.setenv("FAKE_MAKE_EXIT", "2")
        run_tracker.fail_on = {"add_label"}

        result = live(run_command, run_workspace.workspace)

        assert result.exit_code == 1
        assert [call[0] for call in run_tracker.calls] == ["get_issue", "add_label"]
        assert run_tracker.backend.comments == []
        # The comment holds the gate's output, so its line is shown JSON-escaped.
        not_done = [line for line in result.stderr.splitlines() if line.startswith("not done: ")]
        assert [line for line in not_done if "comment(DEM-1, Run " in line]

    @pytest.mark.parametrize(
        ("failing", "gate_exit"),
        [
            ("move_state", "0"),
            ("remove_label", "0"),
            ("comment", "0"),
            ("add_label", "2"),
            ("comment", "2"),
        ],
        ids=["move", "remove", "comment", "add-on-failure", "comment-on-failure"],
    )
    def test_calls_each_write_at_most_once_when_any_fails(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
        failing: str,
        gate_exit: str,
    ) -> None:
        inject(monkeypatch, run_tracker)
        monkeypatch.setenv("FAKE_MAKE_EXIT", gate_exit)
        run_tracker.fail_on = {failing}

        result = live(run_command, run_workspace.workspace)

        assert result.exit_code == 1
        operations = [call[0] for call in run_tracker.calls]
        assert operations[-1] == failing
        assert all(operations.count(operation) == 1 for operation in operations)


RECORD_FIELDS = ["ts", "run", "issue", "repo", "state", "event", "live"]
TRACKER_COST = 0.01


@pytest.mark.usefixtures("with_key")
class TestRecords:
    def test_appends_one_line_per_transition_when_live(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = run_workspace.workspace
        # Each port operation of an MCP adapter reports what it cost (Q-10).
        run_tracker.last_cost_usd = TRACKER_COST
        inject(monkeypatch, run_tracker)

        result = live(run_command, workspace)

        assert result.exit_code == 0, result.output
        found = records(workspace)
        assert [(record["state"], record["event"]) for record in found] == [
            ("PICKED", "picked"),
            ("WORKTREE", "worktree_ready"),
            ("IMPLEMENTING", "agent_finished"),
            ("IMPLEMENTING", "commits"),
            ("VERIFYING", "gate_ok"),
            ("PR_OPEN", "pr_open"),
            ("REPORTED", "reported"),
        ]
        run_id = run_id_of(run_workspace)
        for record in found:
            assert list(record)[:7] == RECORD_FIELDS
            assert (record["run"], record["issue"], record["repo"], record["live"]) == (
                run_id,
                "DEM-1",
                "demo-api",
                True,
            )
        picked, reported = found[0], found[-1]
        assert {name: picked[name] for name in list(picked)[7:]} == {
            "budget": 3.0,
            "max_turns": 40,
            "model": "sonnet",
            "transport": "api",
        }
        operations = len(run_tracker.calls)
        assert operations == 4
        assert {name: reported[name] for name in list(reported)[7:]} == {
            "ok": True,
            "total_cost_usd": round(0.42 + operations * TRACKER_COST, 4),
            "pr": PR_URL,
            "failed_stage": None,
        }

    def test_appends_inbox_line_when_run_ends(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = run_workspace.workspace
        inject(monkeypatch, run_tracker)
        succeeded = live(run_command, workspace)
        first_id = run_id_of(run_workspace)
        monkeypatch.setenv("FAKE_MAKE_EXIT", "2")
        (run_workspace.logs / "claude.jsonl").unlink()

        failed = live(run_command, workspace)

        assert (succeeded.exit_code, failed.exit_code) == (0, 1)
        second_id = run_id_of(run_workspace)
        assert inbox_lines(workspace) == [
            f"- DEM-1 (demo-api) run {first_id}: PR {PR_URL}; $0.42",
            f"- DEM-1 (demo-api) run {second_id}: FAILED at VERIFYING; $0.42",
        ]
        reported = [record for record in records(workspace) if record["event"] == "reported"]
        assert [record["failed_stage"] for record in reported] == [None, "VERIFYING"]

    def test_writes_to_main_checkout_when_run_from_hub_worktree(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = run_workspace.workspace
        hub = workspace.hub
        workspace.git(hub, "-c", "init.defaultBranch=main", "init", "-q")
        workspace.git(hub, "add", "-A")
        workspace.git(hub, "commit", "-q", "-m", "hub")
        hub_worktree = hub / ".claude" / "worktrees" / "x"
        workspace.git(hub, "worktree", "add", "-q", "-b", "x", str(hub_worktree))
        inject(monkeypatch, run_tracker)

        result = run_command(
            workspace.base,
            "run",
            "DEM-1",
            "--repo",
            "demo-api",
            "--live",
            env={"AGENT_HUB_ROOT": str(hub_worktree)},
        )

        assert result.exit_code == 0, result.output
        assert [record["event"] for record in records(workspace)][-1] == "reported"
        assert len(inbox_lines(workspace)) == 1
        assert not (hub_worktree / ".agent-runs").exists()
        assert not (hub_worktree / "brain" / "_inbox" / "runs").exists()


def every_text(run_workspace: Any, result: Result) -> str:
    """Everything a run showed or left: stdout, stderr, each fake's log, records and inbox."""
    workspace = run_workspace.workspace
    texts = [result.stdout, result.stderr]
    texts += [path.read_text() for path in sorted(run_workspace.logs.glob("*.jsonl"))]
    for folder in (workspace.hub / ".agent-runs", workspace.hub / "brain" / "_inbox" / "runs"):
        texts += [path.read_text() for path in sorted(folder.glob("*"))]
    return "\n".join(texts)


@pytest.mark.usefixtures("with_key")
class TestSecrecy:
    def test_strips_paths_and_attribution_when_pr_body_built(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = run_workspace.workspace
        ws = os.path.realpath(workspace.ws)
        trailer = "Co-" + "Authored-By: " + "Claude <noreply@example.com>"
        summary = f"Edits {ws}/demo-api/src/x.py and {ws}/hub/brain/now.md.\n{trailer}"
        monkeypatch.setenv("FAKE_CLAUDE_SUMMARY", summary)
        inject(monkeypatch, run_tracker)

        result = live(run_command, workspace)

        assert result.exit_code == 0, result.output
        (create,) = [
            call for call in run_workspace.calls("gh") if call["argv"][:2] == ["pr", "create"]
        ]
        body = create["argv"][-1]
        assert body == (
            "DEM-1\n\nEdits demo-api/src/x.py and hub/brain/now.md.\n\n"
            "## Verification\nGates green: `make check`."
        )
        (comment,) = [text for _, text in run_tracker.backend.comments]
        assert comment.endswith(f"opened {PR_URL}. Edits demo-api/src/x.py and hub/brain/now.md.")
        for text in (body, comment):
            assert ws not in text
            assert "Authored-By" not in text

    def test_never_shows_key_when_run_live(
        self,
        logged_git: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = logged_git.workspace
        monkeypatch.setenv("GH_TOKEN", GH_TOKEN_VALUE)
        monkeypatch.setenv("GITHUB_TOKEN", GITHUB_TOKEN_VALUE)
        inject(monkeypatch, run_tracker)

        result = live(run_command, workspace)

        assert result.exit_code == 0, result.output
        shown = every_text(logged_git, result)
        shown += "\n".join(text for _, text in run_tracker.backend.comments)
        for secret in (synthetic_key(), GH_TOKEN_VALUE, GITHUB_TOKEN_VALUE):
            assert secret not in shown
        (session,) = logged_git.calls("claude")
        (gate,) = logged_git.calls("make")
        for call in (session, gate):
            assert not [name for name in TOKENS if name in call["env"]]
        for call in [*logged_git.calls("git"), *logged_git.calls("gh")]:
            assert KEY_VARIABLE not in call["env"], call["argv"]


NESTED_NOTE = "note: launching a nested headless claude from inside a Claude session"


class CallSpy:
    """Every ``run_child`` and ``stream_child`` call of any ``agent_hub.cli`` module, with its
    keyword options."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[tuple[str, list[str], dict[str, Any]]] = []
        for module_name, module in list(sys.modules.items()):
            if not module_name.startswith("agent_hub.cli"):
                continue
            for name in ("run_child", "stream_child"):
                real = getattr(module, name, None)
                if callable(real):
                    monkeypatch.setattr(module, name, self._wrap(name, real))

    def _wrap(self, name: str, real: Callable[..., Any]) -> Callable[..., Any]:
        def spy(argv: list[str], **options: Any) -> Any:
            self.calls.append((name, [os.path.basename(argv[0]), *argv[1:]], options))
            return real(argv, **options)

        return spy

    def timeout_of(self, program: str, *first: str) -> list[object]:
        return [
            options.get("timeout")
            for name, argv, options in self.calls
            if name == "run_child"
            and argv[0] == program
            and argv[1 : 1 + len(first)] == list(first)
        ]


@pytest.mark.usefixtures("with_key")
class TestProcesses:
    def test_keeps_children_in_caller_group_when_run_live(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = run_workspace.workspace
        inject(monkeypatch, run_tracker)
        script = b'#!/bin/sh\necho "set up $1"\n'
        workspace.advance("demo-api", {"scripts/worktree-setup.sh": (script, 0o755)})
        calls = CallSpy(monkeypatch)

        result = live(run_command, workspace)

        assert result.exit_code == 0, result.output
        children = [options for name, _, options in calls.calls if name == "run_child"]
        assert children
        assert all(options.get("own_session", "unset") is False for options in children)
        streamed = [argv for name, argv, _ in calls.calls if name == "stream_child"]
        assert [argv[0] for argv in streamed] == ["worktree-setup.sh"]
        programs = {argv[0] for name, argv, _ in calls.calls if name == "run_child"}
        assert programs == {"git", "claude", "bash", "gh"}

    def test_uses_step_timeouts_when_children_run(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from agent_hub.tracker_linear import mcp  # noqa: PLC0415 - the MCP adapter's own cap

        assert (
            run_steps.SESSION_TIMEOUT,
            run_steps.GATE_TIMEOUT,
            run_steps.PUSH_TIMEOUT,
            run_steps.GH_TIMEOUT,
            run_steps.WORKTREE_GIT_TIMEOUT,
            mcp.DEFAULT_TIMEOUT_S,
        ) == (3_600, 1_800, 300, 120, 1_800, 120)
        inject(monkeypatch, run_tracker)
        calls = CallSpy(monkeypatch)

        result = live(run_command, run_workspace.workspace)

        assert result.exit_code == 0, result.output
        assert calls.timeout_of("claude") == [3_600]
        assert calls.timeout_of("bash") == [1_800]
        assert calls.timeout_of("git", *PUSH_OPTIONS, "push") == [300]
        assert calls.timeout_of("gh") == [120]
        fetch_options = ("-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false")
        assert set(calls.timeout_of("git", *fetch_options, "fetch")) == {1_800}
        assert set(calls.timeout_of("git", "-c", "core.hooksPath=/dev/null", "worktree")) == {1_800}

    def test_fails_stage_when_gate_times_out(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        inject(monkeypatch, run_tracker)
        monkeypatch.setattr(run_steps, "GATE_TIMEOUT", 1.0)
        monkeypatch.setenv("FAKE_MAKE_SLEEP", "30")

        result = live(run_command, run_workspace.workspace)

        assert assert_failed_at(result, run_tracker, "VERIFYING") == "bash timed out after 1 s"
        reported = [r for r in records(run_workspace.workspace) if r["event"] == "reported"]
        assert [r["failed_stage"] for r in reported] == ["VERIFYING"]
        assert_never_pushed(run_workspace)

    def test_leaves_gate_grandchild_in_caller_group_when_gate_times_out(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # E6's residual, as documented in run_steps: the timeout kills the gate's direct child
        # only; a process it started stays in the caller's group, for the caller's group kill.
        inject(monkeypatch, run_tracker)
        monkeypatch.setattr(run_steps, "GATE_TIMEOUT", 1.0)
        monkeypatch.setenv("FAKE_MAKE_SLEEP", "30")
        monkeypatch.setenv("FAKE_MAKE_GRANDCHILD", "1")
        pid_file = run_workspace.logs / "grandchild.pid"
        try:
            result = live(run_command, run_workspace.workspace)

            assert result.exit_code == 1
            pid = int(pid_file.read_text())
            assert os.getpgid(pid) == os.getpgrp()
        finally:
            with contextlib.suppress(FileNotFoundError, ProcessLookupError, ValueError):
                os.kill(int(pid_file.read_text()), signal.SIGKILL)

    def test_fails_stage_when_tool_missing(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        inject(monkeypatch, run_tracker)
        (run_workspace.bin / "gh").unlink()

        result = live(run_command, run_workspace.workspace)

        assert assert_failed_at(result, run_tracker, "PR_OPEN") == "gh is not on PATH"

    @pytest.mark.parametrize("live_run", [True, False], ids=["live", "dry"])
    def test_notes_nested_session_when_claudecode_set(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
        live_run: bool,
    ) -> None:
        inject(monkeypatch, run_tracker)
        monkeypatch.setenv("CLAUDECODE", "1")

        result = run_command(
            run_workspace.workspace.hub,
            "run",
            "DEM-1",
            "--repo",
            "demo-api",
            *(["--live"] * live_run),
        )

        assert result.exit_code == 0, result.output
        assert (NESTED_NOTE in result.stderr.splitlines()) is live_run


RISKY = "git config holds keys a push would use ({}); the branch was not pushed"
FETCH_RISKY = "git config holds keys a fetch would use ({}); nothing was fetched"
NOT_GITHUB = "remote.origin.url is not the GitHub url of acme/demo-api; the branch was not pushed"


@pytest.mark.usefixtures("with_key")
class TestPushGuard:
    """Owner decision 2026-10-02: risky keys only, on every run, and origin must be the repo's
    GitHub url from hub.json."""

    def test_refuses_push_when_session_plants_helper(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        inject(monkeypatch, run_tracker)
        monkeypatch.setenv("FAKE_CLAUDE_MODE", "config-helper")

        result = live(run_command, run_workspace.workspace)

        diagnosis = assert_failed_at(result, run_tracker, "PR_OPEN")
        assert diagnosis == RISKY.format("credential.helper")
        assert "synthetic" not in diagnosis
        assert_never_pushed(run_workspace)
        assert run_workspace.calls("gh") == []

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("credential.helper", "!echo planted"),
            ("remote.origin.pushurl", "https://github.com/acme/other.git"),
            ("core.fsmonitor", "./planted"),
            ("filter.x.clean", "./planted"),
            ("remote.origin.receivepack", "./planted"),
        ],
        ids=["helper", "pushurl", "fsmonitor", "filter", "receivepack"],
    )
    def test_refuses_fetch_when_plant_survives_refused_run(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
        key: str,
        value: str,
    ) -> None:
        workspace = run_workspace.workspace
        inject(monkeypatch, run_tracker)
        # Left in the clone's shared config by an earlier run's session.
        workspace.git(workspace.ws / "demo-api", "config", key, value)

        result = live(run_command, workspace)

        # Owner decision: every token-bearing call is guarded; the fetch is the first one.
        diagnosis = assert_failed_at(result, run_tracker, "WORKTREE")
        assert diagnosis == FETCH_RISKY.format(key)
        assert "planted" not in diagnosis
        assert not worktree_of(workspace).exists()
        assert_never_pushed(run_workspace)
        assert run_workspace.calls("gh") == []

    def test_refuses_push_when_origin_names_another_repo(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        inject(monkeypatch, run_tracker)
        monkeypatch.setenv("FAKE_CLAUDE_MODE", "config-remote")

        result = live(run_command, run_workspace.workspace)

        assert assert_failed_at(result, run_tracker, "PR_OPEN") == NOT_GITHUB
        assert_never_pushed(run_workspace)
        assert run_workspace.calls("gh") == []

    def test_pushes_when_session_sets_benign_keys(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        inject(monkeypatch, run_tracker)
        monkeypatch.setenv("FAKE_CLAUDE_MODE", "config-benign")

        result = live(run_command, run_workspace.workspace)

        assert result.exit_code == 0, result.output
        assert "agent-failed" not in run_tracker.backend.issues["DEM-1"].labels

    def test_refuses_fetch_when_from_verify_finds_helper(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = run_workspace.workspace
        inject(monkeypatch, run_tracker)
        verify_ready_worktree(workspace)
        workspace.git(workspace.ws / "demo-api", "config", "credential.helper", "!echo planted")

        result = run_command(
            workspace.hub, "run", "DEM-1", "--repo", "demo-api", "--live", "--from", "verify"
        )

        assert assert_failed_at(result, run_tracker, "WORKTREE") == FETCH_RISKY.format(
            "credential.helper"
        )
        assert_never_pushed(run_workspace)
        assert run_workspace.calls("gh") == []
        assert run_workspace.calls("make") == []

    def test_refuses_push_when_worktree_scope_names_another_remote(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = run_workspace.workspace
        clone = workspace.ws / "demo-api"
        inject(monkeypatch, run_tracker)
        verify_ready_worktree(workspace)
        workspace.git(clone, "config", "core.repositoryformatversion", "1")
        workspace.git(clone, "config", "extensions.worktreeConfig", "true")
        worktree = worktree_of(workspace)
        workspace.git(worktree, "config", "--worktree", "remote.origin.url", "/elsewhere/x.git")

        result = run_command(
            workspace.hub, "run", "DEM-1", "--repo", "demo-api", "--live", "--from", "verify"
        )

        assert assert_failed_at(result, run_tracker, "PR_OPEN") == NOT_GITHUB
        assert run_workspace.calls("gh") == []


PUSH_OVERRIDES = {
    "GIT_CONFIG_COUNT": "3",
    "GIT_CONFIG_KEY_0": "core.fsmonitor",
    "GIT_CONFIG_VALUE_0": "false",
    "GIT_CONFIG_KEY_1": "push.gpgSign",
    "GIT_CONFIG_VALUE_1": "false",
    "GIT_CONFIG_KEY_2": "core.hooksPath",
    "GIT_CONFIG_VALUE_2": "/dev/null",
}


@pytest.mark.usefixtures("with_key")
class TestPushOverrides:
    def test_overrides_risky_config_when_pushing_and_calling_gh(
        self,
        logged_git: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        inject(monkeypatch, run_tracker)

        result = live(run_command, logged_git.workspace)

        assert result.exit_code == 0, result.output
        (push,) = git_calls(logged_git, "push")
        assert push["values"] | PUSH_OVERRIDES == push["values"]
        # GIT_CONFIG_PARAMETERS (the caller's -c) outranks GIT_CONFIG_COUNT: the push repeats
        # the overrides as its own -c, which come last.
        assert push["argv"][:6] == list(PUSH_OPTIONS)
        (gh,) = logged_git.calls("gh")
        assert gh["values"] | PUSH_OVERRIDES == gh["values"]
        (gate,) = logged_git.calls("make")
        assert "GIT_CONFIG_COUNT" not in gate["env"]


@pytest.mark.usefixtures("with_key")
class TestWorktreeEnvironments:
    def test_keeps_tokens_for_fetch_only_when_worktree_made(
        self,
        logged_git: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = logged_git.workspace
        inject(monkeypatch, run_tracker)
        monkeypatch.setenv("GH_TOKEN", GH_TOKEN_VALUE)
        script = b'#!/bin/sh\nexport -p > "$FAKE_RUN_LOGS/' + SETUP_LOG.encode() + b'"\n'
        workspace.advance("demo-api", {"scripts/worktree-setup.sh": (script, 0o755)})
        marker = logged_git.logs / "hook-ran"
        hook = workspace.ws / "demo-api" / ".git" / "hooks" / "post-checkout"
        hook.write_text(f'#!/bin/sh\necho "$0" >> "{marker}"\n')
        hook.chmod(0o755)

        result = live(run_command, workspace)

        assert result.exit_code == 0, result.output
        (fetch,) = git_calls(logged_git, "fetch")
        assert "GH_TOKEN" in fetch["env"]
        (add,) = git_calls(logged_git, "worktree")
        assert add["argv"][:2] == ["-c", "core.hooksPath=/dev/null"]
        assert not [name for name in TOKENS if name in add["env"]]
        setup = (logged_git.logs / SETUP_LOG).read_text()
        assert "GH_TOKEN" not in setup
        assert GH_TOKEN_VALUE not in setup
        assert not marker.exists()


@pytest.mark.usefixtures("with_key")
class TestFetchGuard:
    def test_fetches_nothing_when_clone_holds_helper(
        self,
        logged_git: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = logged_git.workspace
        inject(monkeypatch, run_tracker)
        workspace.git(workspace.ws / "demo-api", "config", "credential.helper", "!echo planted")

        result = live(run_command, workspace)

        assert assert_failed_at(result, run_tracker, "WORKTREE") == FETCH_RISKY.format(
            "credential.helper"
        )
        assert git_calls(logged_git, "fetch") == []
        (listed,) = git_calls(logged_git, "config")
        assert listed["cwd"] == str(workspace.ws / "demo-api")
        assert not [name for name in TOKENS if name in listed["env"]]

    def test_names_included_keys_when_include_path_set(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = run_workspace.workspace
        inject(monkeypatch, run_tracker)
        included = workspace.base / "included.gitconfig"
        included.write_text("[credential]\n\thelper = !echo planted\n")
        workspace.git(workspace.ws / "demo-api", "config", "include.path", str(included))

        result = live(run_command, workspace)

        diagnosis = assert_failed_at(result, run_tracker, "WORKTREE")
        assert diagnosis == FETCH_RISKY.format("credential.helper, include.path")

    def test_refuses_fetch_when_clone_origin_names_another_repo(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        run_tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = run_workspace.workspace
        inject(monkeypatch, run_tracker)
        clone = workspace.ws / "demo-api"
        workspace.git(clone, "remote", "set-url", "origin", "https://github.com/acme/other.git")

        result = live(run_command, workspace)

        assert assert_failed_at(result, run_tracker, "WORKTREE") == (
            "remote.origin.url is not the GitHub url of acme/demo-api; nothing was fetched"
        )

    def test_blocks_other_protocols_when_run_workspace_built(
        self, run_workspace: Workspace
    ) -> None:
        assert os.environ["GIT_ALLOW_PROTOCOL"] == "file"


@pytest.mark.usefixtures("with_key")
class TestFetchHooks:
    def test_runs_no_hook_when_fetch_holds_tokens(
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
        monkeypatch.setenv("GITHUB_TOKEN", GITHUB_TOKEN_VALUE)
        leaked = run_workspace.logs / "hook-env.txt"
        hooks = workspace.ws / "demo-api" / ".git" / "hooks"
        # Planted by an earlier run's session or gate: each logs the token names it can see.
        for hook in ("reference-transaction", "post-checkout"):
            (hooks / hook).write_text(
                "#!/bin/sh\n"
                f'for name in GH_TOKEN GITHUB_TOKEN LINEAR_API_KEY; do eval "v=\\${{$name-}}";'
                f' [ -n "$v" ] && echo "$0 $name" >> "{leaked}"; done\n'
                f'echo "$0 ran" >> "{leaked}"\n'
            )
            (hooks / hook).chmod(0o755)

        result = live(run_command, workspace)

        assert result.exit_code == 0, result.output
        # The session's own commit runs hooks with no token; no hook may see one.
        seen = leaked.read_text().splitlines() if leaked.exists() else []
        assert not [line for line in seen if "TOKEN" in line or "LINEAR" in line], seen
