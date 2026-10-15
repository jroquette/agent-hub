"""The workflow ``NodeRunner`` (AGH-221 AC: agent, shell and script nodes run as children with
scoped environments; a failure's kind comes from where it happened)."""

import dataclasses
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from agent_hub.cli import workflow_executors
from agent_hub.cli.child_process import ChildResult
from agent_hub.cli.errors import ChildTimedOutError
from agent_hub.cli.run_children import RunChildren, RunOptions
from agent_hub.cli.workflow_executors import MAX_OUTPUT_BYTES, WorkflowExecutors
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_models_document, an_issue
from agent_hub.core.testing.workflow_fakes import a_plan
from agent_hub.core.workflows.failures import NodeFailedError
from agent_hub.core.workflows.nodes import ExecutableNode
from agent_hub.core.workflows.ports import NodeCall
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


def test_runs_claude_in_worktree_as_hub_run_does_when_agent_node_has_cwd(
    tmp_path: Path, pack: Path
) -> None:
    worktree = tmp_path / "demo-api" / ".claude" / "worktrees" / "dem-1"
    worktree.mkdir(parents=True)
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
    assert child.calls[0]["argv"][3:] == expected[3:]
    assert child.calls[0]["cwd"] == worktree.resolve()


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
    big = "x" * (MAX_OUTPUT_BYTES + 1)

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
