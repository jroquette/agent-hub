from typing import Any

import pytest

from agent_hub.core.bench.bench_cases import BenchCase
from agent_hub.core.bench.bench_plan import Job
from agent_hub.core.bench.bench_session import (
    AGENT_CONFIG,
    EFFORTS,
    MAX_TURNS,
    MODEL,
    agent_argv,
    agent_outcome,
    apply_failed_outcome,
    apply_tests_argv,
    git_argv,
    grade_outcome,
    grader_argvs,
    grader_env,
    plugin_id,
    record_line,
    result_of,
    run_record,
    sandbox_settings,
    session_env,
    settings_name,
    settings_text,
    timeout_outcome,
    validate_worktree_name,
    worktree_name,
)

SHA = "0123456789abcdef0123456789abcdef01234567"
WORKTREE = "<ROOT>/ws/_bench/wt/L1-T1-with-r1"
# The hub characterization golden's settings line (run_two_arms), plugin named per Q-5 (E2).
GOLDEN_SETTINGS = (
    '{"sandbox": {"enabled": true, "allowUnsandboxedCommands": false, "autoAllowBashIfSandboxed":'
    ' true, "network": {"allowedDomains": ["127.0.0.1", "localhost"], "allowLocalBinding": true},'
    ' "filesystem": {"allowWrite": ["<ROOT>/ws/_bench/wt/L1-T1-with-r1", "/private/tmp",'
    ' "/private/var/folders"], "denyWrite": ["<ROOT>/ws/_bench/wt/L1-T1-with-r1/.git"]}},'
    ' "enabledPlugins": {"hub-workflow@demo": true, "engineering@synced": false},'
    ' "effortLevel": "medium"}'
)


def a_case(**changes: Any) -> BenchCase:
    fields: dict[str, Any] = {
        "id": "T1",
        "repo": "api",
        "merge": SHA,
        "prompt": "Add the fix",
        "hidden_tests": ("t/__main__.py", "a/__main__.py", "t/__main__.py", "top.py"),
        "test_cmd": ("python3", "-m", "pytest"),
        "env": {"CHECK_MODE": "1", "GH_TOKEN": "case-value"},
    }
    fields.update(changes)
    return BenchCase(**fields)


def test_pins_constants_when_module_loaded() -> None:
    assert MODEL == "claude-sonnet-5"
    assert MAX_TURNS == 60
    assert EFFORTS == ("low", "medium", "high")
    assert AGENT_CONFIG == ("AGENTS.md", "CLAUDE.md", ".claude/rules", ".claude/settings.json")


def test_names_plugin_by_project_when_id_built() -> None:
    assert plugin_id("demo") == "hub-workflow@demo"
    assert plugin_id("agent-hub") == "hub-workflow@agent-hub"


def test_names_worktree_and_settings_when_job_given() -> None:
    name = worktree_name(label="L1", case_id="T1", arm="with", run=2)

    assert name == "L1-T1-with-r2"
    assert settings_name(name) == ".settings-L1-T1-with-r2.json"
    assert validate_worktree_name(case_id="T1", label="parent") == "validate-T1-parent"


@pytest.mark.parametrize(("arm", "enabled"), [("with", True), ("without", False)])
def test_enables_plugin_only_when_arm_is_with(arm: str, *, enabled: bool) -> None:
    settings = sandbox_settings(
        worktree=WORKTREE, arm=arm, plugin="hub-workflow@demo", effort="high"
    )

    assert settings["enabledPlugins"] == {"hub-workflow@demo": enabled, "engineering@synced": False}
    assert settings["effortLevel"] == "high"


@pytest.mark.parametrize("arm", ["with", "without"])
def test_keeps_script_key_order_when_settings_built(arm: str) -> None:
    settings = sandbox_settings(
        worktree=WORKTREE, arm=arm, plugin="hub-workflow@demo", effort="medium"
    )

    expected = GOLDEN_SETTINGS
    if arm == "without":
        expected = expected.replace('"hub-workflow@demo": true', '"hub-workflow@demo": false')
    assert settings_text(settings) == expected


def test_orders_argv_when_built() -> None:
    settings = "<ROOT>/ws/_bench/results/.settings-L1-T1-with-r1.json"

    json_argv = agent_argv(prompt="Add the fix", settings_path=settings, per_run=1.0, trace=False)
    trace_argv = agent_argv(prompt="-p x", settings_path=settings, per_run=0.135, trace=True)

    # The golden's argv: the script's order; the budget is the float's repr.
    assert json_argv == [
        "claude", "-p", "Add the fix", "--model", "claude-sonnet-5",
        "--output-format", "json",
        "--permission-mode", "acceptEdits", "--setting-sources", "user",
        "--settings", settings, "--max-budget-usd", "1.0",
        "--max-turns", "60", "--strict-mcp-config", "--no-session-persistence",
    ]  # fmt: skip
    # The trace keeps the session (no --no-session-persistence); a prompt is one argument.
    assert trace_argv == [
        "claude", "-p", "-p x", "--model", "claude-sonnet-5",
        "--output-format", "stream-json", "--verbose",
        "--permission-mode", "acceptEdits", "--setting-sources", "user",
        "--settings", settings, "--max-budget-usd", "0.135",
        "--max-turns", "60", "--strict-mcp-config",
    ]  # fmt: skip


def test_applies_case_env_only_to_grader_when_envs_built() -> None:
    base = {"PATH": "/bin", "CHECK_MODE": "0"}
    case = a_case()

    session = session_env(base, case=case, arm="with")
    grader = grader_env(base, case=case)

    assert session == {
        "PATH": "/bin",
        "CHECK_MODE": "0",
        "OTEL_RESOURCE_ATTRIBUTES": "repo=api,bench_case=T1,bench_arm=with",
    }
    assert grader == {"PATH": "/bin", "CHECK_MODE": "1", "GH_TOKEN": "case-value"}
    assert base == {"PATH": "/bin", "CHECK_MODE": "0"}


def test_reads_pathspecs_literally_when_git_argv_built() -> None:
    case = a_case()

    assert git_argv("/wt", "reset", "-q") == [
        "git", "--literal-pathspecs", "-C", "/wt", "reset", "-q",
    ]  # fmt: skip
    assert apply_tests_argv(worktree="/wt", case=case) == [
        "git", "--literal-pathspecs", "-C", "/wt", "checkout", SHA, "--",
        "t/__main__.py", "a/__main__.py", "t/__main__.py", "top.py",
    ]  # fmt: skip


def test_runs_tests_then_their_dirs_when_grader_argvs_built() -> None:
    hidden, related = grader_argvs(a_case())

    assert hidden == [
        "python3", "-m", "pytest", "t/__main__.py", "a/__main__.py", "t/__main__.py", "top.py",
    ]  # fmt: skip
    # Sorted and deduplicated; a top-level test's dir is `.`.
    assert related == ["python3", "-m", "pytest", ".", "a", "t"]


def test_reads_result_when_stdout_json() -> None:
    reply = '{"total_cost_usd": 0.5, "num_turns": 7, "subtype": "success"}'
    stream = "\n".join(
        [
            'cut": 1}',
            '{"type": "result", "total_cost_usd": 0.1}',
            "{not json",
            '{"type": "assistant"}',
            '{"type": "result", "total_cost_usd": 0.2, "num_turns": 3}',
            '{"type": "user"}',
        ]
    )

    assert result_of(reply, trace=False) == {
        "total_cost_usd": 0.5,
        "num_turns": 7,
        "subtype": "success",
    }
    assert result_of("not json\n", trace=False) == {}
    assert result_of("[1]", trace=False) == {}
    assert result_of(stream, trace=True) == {
        "type": "result",
        "total_cost_usd": 0.2,
        "num_turns": 3,
    }
    assert result_of('{"type": "assistant"}', trace=True) == {}


def test_builds_record_when_run_ends() -> None:
    job = Job(case=a_case(), arm="with", run=1)
    agent = agent_outcome(
        rc=0,
        result={"total_cost_usd": 0.5, "num_turns": 7, "subtype": "success"},
        secs=12,
        stderr="ignored when rc is 0",
    )
    grade = grade_outcome(
        hidden_rc=0, hidden_stdout="a\nlast line\n\n", related_rc=1, related_stdout=""
    )

    record = run_record(label="L1", job=job, agent=agent, grade=grade, ts="2026-01-15T10:30:00")

    # The script's field order: job, agent, grade, then the timestamp.
    assert list(record.items()) == [
        ("label", "L1"),
        ("case", "T1"),
        ("arm", "with"),
        ("run", 1),
        ("model", "claude-sonnet-5"),
        ("agent_rc", 0),
        ("cost", 0.5),
        ("turns", 7),
        ("secs", 12),
        ("subtype", "success"),
        ("agent_error", ""),
        ("pass", False),
        ("hidden_rc", 0),
        ("related_rc", 1),
        ("hidden_tail", "last line"),
        ("related_tail", ""),
        ("ts", "2026-01-15T10:30:00"),
    ]
    assert record_line({"pass": True, "turns": None}) == '{"pass": true, "turns": null}'


def test_keeps_tails_when_agent_fails() -> None:
    error = "HEAD" + "." * 292 + "boom\n"

    failed = agent_outcome(
        rc=1, result={"total_cost_usd": True, "num_turns": "7"}, secs=0, stderr=error
    )
    grade = grade_outcome(hidden_rc=0, hidden_stdout="x" * 201, related_rc=0, related_stdout="ok\n")

    assert failed == {
        "agent_rc": 1,
        "cost": 0.0,
        "turns": None,
        "secs": 0,
        "subtype": None,
        "agent_error": error[-300:],
    }
    assert grade["pass"] is True
    # The script's `or 0.0`, for finite numbers only.
    for cost in (0, float("nan"), "0.5"):
        outcome = agent_outcome(rc=0, result={"total_cost_usd": cost}, secs=0, stderr="")
        assert outcome["cost"] == 0.0
    assert grade["hidden_tail"] == "x" * 200
    assert timeout_outcome(per_run=2.0, secs=1800) == {
        "agent_rc": "timeout",
        "cost": 2.0,
        "secs": 1800,
    }
    assert apply_failed_outcome("e" * 301) == {"pass": False, "error": "apply-tests: " + "e" * 300}
