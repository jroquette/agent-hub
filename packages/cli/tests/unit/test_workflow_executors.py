"""The workflow ``NodeRunner`` (AGH-221 AC: agent, shell and script nodes run as children with
scoped environments; a failure's kind comes from where it happened)."""

import dataclasses
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from agent_hub.cli import workflow_command, workflow_executors
from agent_hub.cli.child_process import ChildResult
from agent_hub.cli.errors import ChildTimedOutError
from agent_hub.cli.run_children import RunChildren, RunOptions
from agent_hub.cli.workflow_executors import MAX_OUTPUT_BYTES, WorkflowExecutors
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.runner.session_settings import hooks_settings
from agent_hub.core.testing.builders import a_hub_settings_document, a_models_document, an_issue
from agent_hub.core.testing.workflow_fakes import ListRecorder, a_plan
from agent_hub.core.workflows.engine import MAX_PARALLEL
from agent_hub.core.workflows.failures import NodeFailedError
from agent_hub.core.workflows.nodes import ExecutableNode
from agent_hub.core.workflows.ports import NodeCall
from agent_hub.core.workflows.scope import RefScope, ScopeStep
from agent_hub.core.workflows.substitution import NodeResult, RefContext

GITHUB_VALUE = "g" * 8
ENVIRON = {
    "PATH": "/bin",
    "LINEAR_API_KEY": "l" * 8,
    "GH_TOKEN": GITHUB_VALUE,
    "GITHUB_TOKEN": GITHUB_VALUE,
    "GIT_DIR": "/elsewhere",
}
HUB_PROGRAM = ("/opt/hub/bin/python", "-m", "hub")


@dataclass
class FakeChild:
    """Records each call; answers with ``results`` in order, or raises an exception given."""

    results: list[ChildResult | BaseException] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, argv: Sequence[str], **options: Any) -> ChildResult:
        self.calls.append({"argv": list(argv), **options})
        answer = self.results.pop(0) if self.results else ChildResult(0, b"", b"")
        if isinstance(answer, BaseException):
            raise answer
        return answer


def claude_result(result: str, **extra: object) -> ChildResult:
    reply = {"type": "result", "is_error": False, "subtype": "success", "result": result}
    return ChildResult(0, json.dumps({**reply, **extra}).encode(), b"")


@pytest.fixture
def pack(tmp_path: Path) -> Path:
    root = tmp_path / "workflows" / "demo"
    (root / "prompts").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "prompts" / "plan.md").write_text("Plan for $INPUTS.issue now\n")
    (root / "scripts" / "count.py").write_text("print(1)\n")
    return root


def executors(tmp_path: Path, pack: Path, child: FakeChild) -> WorkflowExecutors:
    return WorkflowExecutors(
        hub=tmp_path / "hub",
        config=HubConfig.model_validate(a_models_document()),
        run_id="1a2b3c4d",
        pack_root=pack,
        environ=ENVIRON,
        hub_program=HUB_PROGRAM,
        child=child,
    )


def node(spec: Mapping[str, object]) -> ExecutableNode:
    found = a_plan(spec).document.nodes[0]
    assert not isinstance(found, dict)
    return found  # type: ignore[return-value]


def call(spec: Mapping[str, object], **options: Any) -> NodeCall:
    context = RefContext({"issue": "DEM-1", "repo": "demo-api"}, {})
    return NodeCall(node(spec), options.pop("attempt", 1), context, **options)


AGENT = {"id": "plan", "type": "agent", "prompt": "Plan it.", "model": "large"}


def hub_hooks(hub: Path) -> None:
    """Give ``hub`` the synthetic ``.claude/settings.json`` and an empty file per script."""
    document = a_hub_settings_document()
    (hub / ".claude").mkdir(parents=True, exist_ok=True)
    (hub / ".claude" / "settings.json").write_text(json.dumps(document))
    for script in hooks_settings(document, effort="medium", hub=str(hub))[1]:
        (hub / script).parent.mkdir(parents=True, exist_ok=True)
        (hub / script).touch()


def test_runs_claude_in_hub_when_agent_node_called(tmp_path: Path, pack: Path) -> None:
    child = FakeChild([claude_result("All planned.", session_id="s-1")])
    spec = {**AGENT, "limits": {"max_turns": 7, "max_cost_usd": 1.5}}

    reply = executors(tmp_path, pack, child).run(call(spec, prompt="Plan it.", attempt=3))

    argv = child.calls[0]["argv"]
    assert (reply.text, reply.session) == ("All planned.", "s-1")
    assert argv[:3] == ["claude", "-p", "Plan it."]
    assert argv[argv.index("--model") + 1] == "claude-opus-4-1"
    assert argv[argv.index("--max-turns") + 1] == "7"
    assert argv[argv.index("--max-budget-usd") + 1] == "1.5"
    assert str(tmp_path / "demo-api") in argv
    assert "mcp__Linear" in argv
    assert child.calls[0]["cwd"] == tmp_path / "hub"


def test_gives_read_only_tools_and_denies_edits_when_agent_node_is_read_only(
    tmp_path: Path, pack: Path
) -> None:
    child = FakeChild([claude_result("ok")])

    executors(tmp_path, pack, child).run(call({**AGENT, "mutates_checkout": False}, prompt="x"))

    argv = child.calls[0]["argv"]
    allowed = argv[argv.index("--allowedTools") + 1 : argv.index("--disallowedTools")]
    denied = argv[argv.index("--disallowedTools") + 1 :]
    assert {"Read", "Grep", "Bash(git show:*)", "Bash(git log:*)"} <= set(allowed)
    assert not {"Edit", "Write", "Bash(git commit:*)", "Bash(git add:*)", "Bash(make:*)"} & set(
        allowed
    )
    # No shell reader that can run or write (rg --pre, cat > file): the Read and Grep tools read.
    assert not [tool for tool in allowed if tool.startswith(("Bash(rg", "Bash(grep", "Bash(cat"))]
    # git's read forms can write with --output: denied wherever it stands.
    assert {"Edit", "Write", "NotebookEdit", "Bash(git *--output*)"} <= set(denied)


def test_gives_session_env_with_node_step_when_agent_node_called(
    tmp_path: Path, pack: Path
) -> None:
    child = FakeChild([claude_result("ok")])

    executors(tmp_path, pack, child).run(call(AGENT, prompt="Plan it.", attempt=4))

    env = child.calls[0]["env"]
    assert (env["AGENT_HUB_RUN_ID"], env["AGENT_HUB_STEP"], env["AGENT_HUB_ATTEMPT"]) == (
        "1a2b3c4d",
        "plan",
        "4",
    )
    assert not {"LINEAR_API_KEY", "GH_TOKEN", "GITHUB_TOKEN", "GIT_DIR"} & set(env)


def test_resumes_session_when_call_names_one(tmp_path: Path, pack: Path) -> None:
    child = FakeChild([claude_result("ok")])

    executors(tmp_path, pack, child).run(call(AGENT, prompt="x", resume_session="s-9"))

    assert child.calls[0]["argv"][-2:] == ["--resume", "s-9"]


def test_renders_prompt_file_when_agent_node_has_one(tmp_path: Path, pack: Path) -> None:
    child = FakeChild([claude_result("ok")])
    spec = {"id": "plan", "type": "agent", "prompt_file": "plan.md"}

    executors(tmp_path, pack, child).run(call(spec))

    assert child.calls[0]["argv"][2] == "Plan for DEM-1 now\n"


def test_fails_config_when_prompt_file_missing(tmp_path: Path, pack: Path) -> None:
    spec = {"id": "plan", "type": "agent", "prompt_file": "absent.md"}

    with pytest.raises(NodeFailedError) as raised:
        executors(tmp_path, pack, FakeChild()).run(call(spec))

    assert raised.value.kind == "config"


def test_returns_last_json_line_when_agent_node_has_output_format(
    tmp_path: Path, pack: Path
) -> None:
    child = FakeChild([claude_result('Done.\n{"done": true}')])
    spec = {**AGENT, "output_format": {"type": "object"}}

    reply = executors(tmp_path, pack, child).run(call(spec, prompt="x"))

    assert json.loads(reply.text) == {"done": True}


@pytest.mark.parametrize(
    "result",
    [
        ChildResult(0, json.dumps({"is_error": True, "result": "turns"}).encode(), b""),
        ChildResult(1, b"not json", b""),
    ],
)
def test_fails_exec_failed_when_claude_errors(
    tmp_path: Path, pack: Path, result: ChildResult
) -> None:
    with pytest.raises(NodeFailedError) as raised:
        executors(tmp_path, pack, FakeChild([result])).run(call(AGENT, prompt="x"))

    assert raised.value.kind == "exec_failed"


def test_runs_argv_without_shell_when_shell_node_called(tmp_path: Path, pack: Path) -> None:
    child = FakeChild([ChildResult(0, b"lint ok\n", b"")])
    spec = {"id": "lint", "type": "shell", "command": ["make", "lint"], "env": {"LEVEL": "2"}}

    reply = executors(tmp_path, pack, child).run(
        call(spec, argv=("make", "lint"), cwd="sub", env={"LEVEL": "2"})
    )

    sent = child.calls[0]
    assert reply.text == "lint ok\n"
    assert (sent["argv"], sent["cwd"], sent["own_session"]) == (
        ["make", "lint"],
        (tmp_path / "hub" / "sub").resolve(),
        True,
    )
    assert callable(sent["on_start"])
    assert sent["env"]["LEVEL"] == "2"
    assert not {"LINEAR_API_KEY", "GH_TOKEN", "GITHUB_TOKEN", "GIT_DIR"} & set(sent["env"])


def test_refuses_token_when_shell_node_env_names_one(tmp_path: Path, pack: Path) -> None:
    spec = {"id": "lint", "type": "shell", "command": ["make"], "env": {"GH_TOKEN": "x"}}

    with pytest.raises(NodeFailedError) as raised:
        executors(tmp_path, pack, FakeChild()).run(
            call(spec, argv=("make",), env={"GH_TOKEN": "x"})
        )

    assert raised.value.kind == "config"


def test_runs_own_hub_with_child_env_when_node_is_hub_step(tmp_path: Path, pack: Path) -> None:
    child = FakeChild()
    spec = {"id": "wt", "type": "shell", "command": ["hub", "step", "worktree"]}

    executors(tmp_path, pack, child).run(call(spec, argv=("hub", "step", "worktree")))

    sent = child.calls[0]
    assert sent["argv"] == [*HUB_PROGRAM, "step", "worktree"]
    assert sent["cwd"] == (tmp_path / "hub").resolve()
    assert sent["env"]["GH_TOKEN"] == GITHUB_VALUE
    assert "LINEAR_API_KEY" not in sent["env"]
    assert sent["env"]["AGENT_HUB_RUN_ID"] == "1a2b3c4d"


def test_gives_the_run_id_over_the_node_env_when_script_node_called(
    tmp_path: Path, pack: Path
) -> None:
    child = FakeChild()
    spec = {"id": "count", "type": "script", "runtime": "python", "script": "count.py"}

    executors(tmp_path, pack, child).run(call(spec, env={"AGENT_HUB_RUN_ID": "forged"}))

    assert child.calls[0]["env"]["AGENT_HUB_RUN_ID"] == "1a2b3c4d"


@pytest.mark.parametrize("case", [("python", ["uv", "run"]), ("sh", ["sh"])])
def test_runs_pack_script_with_args_when_script_node_called(
    tmp_path: Path, pack: Path, case: tuple[str, list[str]]
) -> None:
    runtime, program = case
    child = FakeChild()
    spec = {
        "id": "count",
        "type": "script",
        "runtime": runtime,
        "script": "count.py",
        "args": ["a"],
    }

    executors(tmp_path, pack, child).run(call(spec, argv=("a",)))

    path = str((pack / "scripts" / "count.py").resolve())
    assert child.calls[0]["argv"] == [*program, path, "a"]


def test_fails_exec_failed_with_stderr_when_command_exits_non_zero(
    tmp_path: Path, pack: Path
) -> None:
    child = FakeChild([ChildResult(2, b"", b"boom")])
    spec = {"id": "lint", "type": "shell", "command": ["make"]}

    with pytest.raises(NodeFailedError) as raised:
        executors(tmp_path, pack, child).run(call(spec, argv=("make",)))

    assert (raised.value.kind, raised.value.detail) == ("exec_failed", "make exited 2: boom")


@pytest.mark.parametrize(
    "case",
    [
        (ChildTimedOutError(program="make", timeout=5.0), "timeout"),
        (FileNotFoundError(2, "No such file or directory"), "config"),
    ],
)
def test_fails_with_kind_when_child_times_out_or_cannot_start(
    tmp_path: Path, pack: Path, case: tuple[BaseException, str]
) -> None:
    error, kind = case
    spec = {"id": "lint", "type": "shell", "command": ["make"], "timeout": "5s"}
    child = FakeChild([error])

    with pytest.raises(NodeFailedError) as raised:
        executors(tmp_path, pack, child).run(call(spec, argv=("make",)))

    assert raised.value.kind == kind
    assert child.calls[0]["timeout"] == 5.0


def test_fails_output_contract_when_stdout_past_cap(tmp_path: Path, pack: Path) -> None:
    child = FakeChild([ChildResult(0, b"x" * (MAX_OUTPUT_BYTES + 1), b"")])
    spec = {"id": "lint", "type": "shell", "command": ["make"]}

    with pytest.raises(NodeFailedError) as raised:
        executors(tmp_path, pack, child).run(call(spec, argv=("make",)))

    assert raised.value.kind == "output_contract"
    assert child.calls[0]["output_limit"] == MAX_OUTPUT_BYTES + 1


def test_returns_exit_code_when_until_bash_runs(tmp_path: Path, pack: Path) -> None:
    child = FakeChild([ChildResult(1, b"", b"")])
    spec = {**AGENT, "type": "loop", "max_iterations": 2, "until_bash": ["test", "-f", "x"]}

    code = executors(tmp_path, pack, child).until_exit(["test", "-f", "x"], call(spec))

    assert code == 1
    assert "GH_TOKEN" not in child.calls[0]["env"]


def test_reads_upstream_reference_when_prompt_file_renders(tmp_path: Path, pack: Path) -> None:
    (pack / "prompts" / "fix.md").write_text("Fix $lint.output\n")
    child = FakeChild([claude_result("ok")])
    spec = {"id": "fix", "type": "agent", "prompt_file": "fix.md"}
    context = RefContext({}, {"lint": NodeResult("completed", "E1")})

    executors(tmp_path, pack, child).run(NodeCall(node(spec), 1, context))

    assert child.calls[0]["argv"][2] == "Fix E1\n"


def test_runs_in_repo_when_cwd_names_a_configured_repo(tmp_path: Path, pack: Path) -> None:
    child = FakeChild()
    spec = {"id": "st", "type": "shell", "command": ["git", "status"], "cwd": "../demo-api"}

    executors(tmp_path, pack, child).run(call(spec, argv=("git", "status"), cwd="../demo-api"))

    assert child.calls[0]["cwd"] == (tmp_path / "demo-api").resolve()


@pytest.mark.parametrize("cwd", ["/etc", "../elsewhere", "out"])
def test_fails_config_when_cwd_leaves_hub_and_repos(tmp_path: Path, pack: Path, cwd: str) -> None:
    (tmp_path / "hub").mkdir()
    (tmp_path / "hub" / "out").symlink_to(tmp_path / "elsewhere")
    child = FakeChild()
    spec = {"id": "st", "type": "shell", "command": ["ls"], "cwd": cwd}

    with pytest.raises(NodeFailedError) as raised:
        executors(tmp_path, pack, child).run(call(spec, argv=("ls",), cwd=cwd))

    assert raised.value.kind == "config"
    assert child.calls == []


def test_fails_config_when_prompt_file_leaves_pack(tmp_path: Path, pack: Path) -> None:
    (pack / "prompts" / "out.md").symlink_to(tmp_path / "secret.md")
    (tmp_path / "secret.md").write_text("x")
    spec = {"id": "plan", "type": "agent", "prompt_file": "out.md"}
    child = FakeChild()

    with pytest.raises(NodeFailedError) as raised:
        executors(tmp_path, pack, child).run(call(spec))

    assert raised.value.kind == "config"
    assert child.calls == []


@pytest.mark.parametrize("session", ["", "-p", "a b", "x" * 200, "s;rm"])
def test_fails_config_when_resumed_session_id_is_unsafe(
    tmp_path: Path, pack: Path, session: str
) -> None:
    child = FakeChild()

    with pytest.raises(NodeFailedError) as raised:
        executors(tmp_path, pack, child).run(call(AGENT, prompt="x", resume_session=session))

    assert raised.value.kind == "config"
    assert child.calls == []


def test_drops_session_id_when_claude_reports_an_unsafe_one(tmp_path: Path, pack: Path) -> None:
    child = FakeChild([claude_result("ok", session_id="--dangerous")])

    reply = executors(tmp_path, pack, child).run(call(AGENT, prompt="x"))

    assert reply.session is None


def test_kills_child_group_when_interrupted(
    tmp_path: Path, pack: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    killed: list[int] = []
    monkeypatch.setattr(workflow_executors.os, "killpg", lambda group, _: killed.append(group))

    def interrupted(argv: Sequence[str], **options: Any) -> ChildResult:
        options["on_start"](4242)
        raise KeyboardInterrupt

    runner = executors(tmp_path, pack, FakeChild())
    runner = dataclasses.replace(runner, child=interrupted)
    spec = {"id": "lint", "type": "shell", "command": ["make"]}

    with pytest.raises(KeyboardInterrupt):
        runner.run(call(spec, argv=("make",)))

    assert killed == [4242]


def test_renders_prompt_file_through_the_call_scope_when_the_node_was_included(
    tmp_path: Path, pack: Path
) -> None:
    (pack / "prompts" / "fix.md").write_text("Fix $INPUTS.issue after $prep.output\n")
    child = FakeChild([claude_result("ok")])
    spec = {"id": "c__fix", "type": "agent", "prompt_file": "fix.md"}
    scope = RefScope((ScopeStep({"prep": "c__prep"}, {"issue": "CHILD"}, hermetic=True),))
    context = RefContext({"issue": "MAIN"}, {"c__prep": NodeResult("completed", "P")})
    the_node = node({**spec, "id": "fix"}).model_copy(update={"id": "c__fix"})

    executors(tmp_path, pack, child).run(NodeCall(the_node, 1, context, scope=scope))

    assert child.calls[0]["argv"][2] == "Fix CHILD after P\n"


def test_runs_claude_in_worktree_as_hub_run_does_when_agent_node_has_cwd(
    tmp_path: Path, pack: Path
) -> None:
    worktree = tmp_path / "demo-api" / ".claude" / "worktrees" / "dem-1"
    worktree.mkdir(parents=True)
    hub_hooks(tmp_path / "hub")
    child = FakeChild([claude_result("ok")])
    config = HubConfig.model_validate(a_models_document())
    spec = {**AGENT, "model": "medium", "cwd": "../demo-api"}

    executors(tmp_path, pack, child).run(call(spec, prompt="Go.", cwd=str(worktree)))

    children = RunChildren(
        config=config, hub=tmp_path / "hub", repo="demo-api", issue_id="DEM-1", branch_prefix="j/"
    )
    model = config.models.model_for("medium")
    options = RunOptions(
        live=True, max_turns=40, budget=3.0, model=model, start="implement", effort="medium"
    )
    expected = children.session_argv(an_issue(), options)
    argv = child.calls[0]["argv"]
    assert argv[3:] == expected[3:]
    assert child.calls[0]["cwd"] == worktree.resolve()
    assert child.calls[0]["argv"][argv.index("--settings") + 1] == str(
        tmp_path / "hub" / ".agent-runs" / "session-settings" / "medium.json"
    )


@pytest.mark.parametrize("cwd", [None, ".", "./", "link"], ids=["none", "dot", "dot-slash", "link"])
def test_gives_effort_only_settings_when_agent_runs_in_hub(
    tmp_path: Path, pack: Path, cwd: str | None
) -> None:
    (tmp_path / "hub" / "inside").mkdir(parents=True)
    (tmp_path / "hub" / "link").symlink_to(tmp_path / "hub" / "inside")
    child = FakeChild([claude_result("ok")])
    spec = {**AGENT, "model": "medium"}

    executors(tmp_path, pack, child).run(call(spec, prompt="Go.", cwd=cwd))

    argv = child.calls[0]["argv"]
    assert argv.count("--settings") == 1
    assert json.loads(argv[argv.index("--settings") + 1]) == {"effortLevel": "medium"}
    assert not (tmp_path / "hub" / ".agent-runs").exists()


@pytest.mark.parametrize("cwd", [None, "."], ids=["none", "dot"])
def test_gives_effort_only_settings_when_repo_dir_links_to_hub(
    tmp_path: Path, pack: Path, cwd: str | None
) -> None:
    # A repo that resolves to the hub: the hub's own settings load, so no hooks file (each
    # hook would run twice).
    hub_hooks(tmp_path / "hub")
    (tmp_path / "demo-api").symlink_to(tmp_path / "hub")
    child = FakeChild([claude_result("ok")])
    spec = {**AGENT, "model": "medium"}

    executors(tmp_path, pack, child).run(call(spec, prompt="Go.", cwd=cwd))

    argv = child.calls[0]["argv"]
    assert argv.count("--settings") == 1
    assert json.loads(argv[argv.index("--settings") + 1]) == {"effortLevel": "medium"}
    assert not (tmp_path / "hub" / ".agent-runs").exists()


def test_gives_hub_hooks_settings_file_when_agent_runs_in_repo(tmp_path: Path, pack: Path) -> None:
    worktree = tmp_path / "demo-api" / ".claude" / "worktrees" / "dem-1"
    worktree.mkdir(parents=True)
    hub_hooks(tmp_path / "hub")
    stale = tmp_path / "hub" / ".agent-runs" / "session-settings" / "medium.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("{}")
    child = FakeChild([claude_result("ok")])
    spec = {**AGENT, "model": "medium", "cwd": "../demo-api"}

    executors(tmp_path, pack, child).run(call(spec, prompt="Go.", cwd=str(worktree)))

    argv = child.calls[0]["argv"]
    assert argv.count("--settings") == 1
    assert argv[argv.index("--settings") + 1] == str(stale)
    written = json.loads(stale.read_text())
    assert list(written) == ["effortLevel", "hooks"]
    (guard,) = written["hooks"]["PreToolUse"][0]["hooks"]
    assert guard["command"].startswith(f'python3 "{tmp_path}/hub/plugin/hub-workflow/hooks/')
    assert stale.stat().st_mode & 0o777 == 0o600


def test_rewrites_settings_file_when_attempt_repeats_or_resumes(tmp_path: Path, pack: Path) -> None:
    worktree = tmp_path / "demo-api" / ".claude" / "worktrees" / "dem-1"
    worktree.mkdir(parents=True)
    hub_hooks(tmp_path / "hub")
    written = tmp_path / "hub" / ".agent-runs" / "session-settings" / "medium.json"
    child = FakeChild([claude_result("ok"), claude_result("ok"), claude_result("ok")])
    spec = {**AGENT, "model": "medium", "cwd": "../demo-api"}
    runner = executors(tmp_path, pack, child)

    runner.run(call(spec, prompt="Go.", cwd=str(worktree)))
    written.unlink()
    runner.run(call(spec, prompt="Go.", cwd=str(worktree), attempt=2))
    second = written.exists()
    written.unlink()
    runner.run(call(spec, prompt="Go.", cwd=str(worktree), resume_session="s-9"))

    assert second
    assert written.exists()
    assert child.calls[2]["argv"][-2:] == ["--resume", "s-9"]


def test_fails_config_without_claude_when_repo_cwd_hub_hooks_missing(
    tmp_path: Path, pack: Path
) -> None:
    worktree = tmp_path / "demo-api" / ".claude" / "worktrees" / "dem-1"
    worktree.mkdir(parents=True)
    (tmp_path / "hub").mkdir()
    child = FakeChild([claude_result("ok")])
    spec = {**AGENT, "model": "medium", "cwd": "../demo-api"}

    with pytest.raises(NodeFailedError) as raised:
        executors(tmp_path, pack, child).run(call(spec, prompt="Go.", cwd=str(worktree)))

    assert raised.value.kind == "config"
    assert str(raised.value).startswith("cannot wire the hub's hooks")
    assert child.calls == []


@pytest.mark.parametrize("cwd", ["/etc", "..", "../demo-api/../..", "../demo-api/out"])
def test_fails_config_when_agent_cwd_leaves_hub_and_repos(
    tmp_path: Path, pack: Path, cwd: str
) -> None:
    (tmp_path / "demo-api").mkdir()
    (tmp_path / "demo-api" / "out").symlink_to(tmp_path / "elsewhere")
    child = FakeChild()
    spec = {**AGENT, "cwd": "../demo-api"}

    with pytest.raises(NodeFailedError) as raised:
        executors(tmp_path, pack, child).run(call(spec, prompt="Go.", cwd=cwd))

    assert raised.value.kind == "config"
    assert child.calls == []


def test_writes_stdin_when_shell_node_has_one(tmp_path: Path, pack: Path) -> None:
    child = FakeChild()
    spec = {"id": "read", "type": "shell", "command": ["hub", "step", "verdict"], "stdin": "x"}

    executors(tmp_path, pack, child).run(call(spec, argv=tuple(spec["command"]), stdin="é\x00"))

    assert child.calls[0]["stdin"] == "é\x00".encode()


def test_fails_config_when_stdin_past_cap(tmp_path: Path, pack: Path) -> None:
    child = FakeChild()
    spec = {"id": "read", "type": "shell", "command": ["cat"], "stdin": "x"}
    big = "x" * 1_048_577

    with pytest.raises(NodeFailedError) as raised:
        executors(tmp_path, pack, child).run(call(spec, argv=("cat",), stdin=big))

    assert raised.value.kind == "config"
    assert child.calls == []


def test_fails_config_when_child_refuses_its_arguments(tmp_path: Path, pack: Path) -> None:
    child = FakeChild([ValueError("embedded null byte")])
    spec = {"id": "st", "type": "shell", "command": ["ls"]}

    with pytest.raises(NodeFailedError) as raised:
        executors(tmp_path, pack, child).run(call(spec, argv=("ls",)))

    assert raised.value.kind == "config"


def test_passes_stdin_when_exactly_at_session_cap(tmp_path: Path, pack: Path) -> None:
    child = FakeChild()
    spec = {"id": "read", "type": "shell", "command": ["cat"], "stdin": "x"}

    executors(tmp_path, pack, child).run(call(spec, argv=("cat",), stdin="x" * 1_048_576))

    assert len(child.calls[0]["stdin"]) == 1_048_576


@pytest.mark.parametrize(("size", "passes"), [(1_048_576, True), (1_048_577, False)])
def test_bounds_agent_reply_at_session_cap_when_claude_answers(
    tmp_path: Path, pack: Path, *, size: int, passes: bool
) -> None:
    child = FakeChild([claude_result("x" * size)])

    if passes:
        reply = executors(tmp_path, pack, child).run(call(AGENT, prompt="Go."))
        assert len(reply.text) == size
    else:
        with pytest.raises(NodeFailedError) as raised:
            executors(tmp_path, pack, child).run(call(AGENT, prompt="Go."))
        assert raised.value.kind == "output_contract"


def test_runs_one_attempt_at_a_time_when_hub_steps_run_in_process(
    tmp_path: Path, pack: Path
) -> None:
    in_process = dataclasses.replace(
        executors(tmp_path, pack, FakeChild()), hub_steps=lambda *_: "{}"
    )

    ports = workflow_command._ports(in_process, ListRecorder(), None)

    assert ports.max_parallel == 1
    assert executors(tmp_path, pack, FakeChild()).max_parallel == MAX_PARALLEL


@pytest.mark.parametrize(
    "spec",
    [
        {"id": "send", "type": "action", "action": "send-queue-message"},
        {"id": "wait", "type": "expect", "action": "get-order", "every": "5s", "timeout": "1m"}
        | {"until_when": "$self.output.status == 'OK'"},
    ],
)
def test_fails_config_without_child_when_action_node_called(
    tmp_path: Path, pack: Path, spec: Mapping[str, object]
) -> None:
    child = FakeChild()

    with pytest.raises(NodeFailedError) as raised:
        executors(tmp_path, pack, child).run(call(spec))

    assert raised.value.kind == "config"
    assert "scenario run" in raised.value.detail
    assert child.calls == []
