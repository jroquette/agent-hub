"""``hub step prompt|output`` (AGH-579, ADR 0050): an ``implement`` stage's agent prompt and its
output checked, for a session that runs the stage as its own subagent.

The prompt is the one a workflow run gives its ``claude -p`` child, and the output the value the
run's record steps get, so a ticket's records written in the session parse as a run's do: a
stubbed ``implement`` run and the same steps run by hand, from the same agent reply, write the
same preflight run and change request (but for the time and the run's id).
"""

import json
import shutil
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from click import unstyle
from typer.testing import CliRunner, Result

from agent_hub.cli.child_process import ChildResult
from agent_hub.cli.main import app
from agent_hub.cli.step_stages import STAGES
from agent_hub.cli.workflow_executors import WorkflowExecutors
from agent_hub.core.features.output_models import PreflightRecord
from agent_hub.core.features.ticket_records import preflight_record
from agent_hub.core.runner.session_prompt import CLAUDE_PROGRAM
from agent_hub.generator.workflow_discovery import BUILTIN_WORKFLOWS

pytestmark = pytest.mark.disable_socket

type CommandRunner = Callable[..., Result]
type Workspace = Any

FEATURE = "brain/features/demo-flow"
FEATURES_JSON = {
    "tickets": [
        {"key": "T1", "id": "DEM-7", "repo": "demo-api", "blocked_by": []},
        {"key": "T2", "id": "DEM-8", "repo": "demo-api", "blocked_by": ["T1"]},
    ],
    "acs": [{"id": "AC-1.1", "description": "It works.", "passes": False, "ticket": "T2"}],
}
PLAN = "# Plan\n\n### T2 api: the handler\n\nChange `src/api/handler.py`.\n"
PLAN_DRIFT = {
    "drift": "plan",
    "local_notes": [],
    "blockers_read": ["DEM-7"],
    "evidence": "The handler moved to src/api/routes.py.",
    "proposal": "Route T2 through routes.py.",
    "affected": "",
    "summary": "T2 goes through routes.py",
}
# A subagent's reply: an explanation, then the JSON alone on the last line.
REPLY = "The handler moved, so the plan no longer holds.\n\n" + json.dumps(PLAN_DRIFT) + "\n"
SESSION_RUN = "session-dem-8"
REVIEW = {
    "schema": "agent-hub/review/1",
    "reviewer": "spec",
    "ticket": "DEM-8",
    "task": "DEM-8",
    "round": 1,
    "commit": "4e1a9c2d",
    "verdict": "PASS",
    "findings": [],
}
EVAL = {
    "schema": "agent-hub/eval/1",
    "delivery": "dem-8",
    "verdict": "SHIP",
    "commit": "4e1a9c2d",
    "tickets": ["DEM-8"],
    "acs": ["AC-1.1"],
    "results": [
        {"ac": "AC-1.1", "command": "make test", "exit_code": 0, "status": "pass", "summary": "ok"}
    ],
    "gates": [{"repo": "demo-api", "name": "check", "exit_code": 0, "status": "pass"}],
    "red_on_parent": [],
    "owner_steps": [],
}


@pytest.fixture
def hub(demo_workspace: Workspace) -> Path:
    root: Path = demo_workspace.hub
    feature = root / FEATURE
    feature.mkdir(parents=True)
    (feature / "features.json").write_text(json.dumps(FEATURES_JSON))
    (feature / "plan.md").write_text(PLAN)
    demo_workspace.init_hub_repo(None)
    demo_workspace.git(demo_workspace.ws / "demo-api", "fetch", "-q", "origin")
    return root


def piped(root: Path, monkeypatch: pytest.MonkeyPatch, *args: str, reply: str) -> Result:
    """``hub <args>`` in ``root`` with ``reply`` on stdin."""
    monkeypatch.chdir(root)
    return CliRunner().invoke(app, list(args), input=reply)


def ok(result: Result) -> str:
    assert result.exit_code == 0, result.output
    return result.stdout


def refused(result: Result, name: str) -> str:
    assert result.exit_code == 1, result.output
    assert result.stdout == ""
    [line] = result.stderr.splitlines()
    assert line.startswith(f"hub step {name}: ")
    return line


def withs(values: dict[str, str]) -> list[str]:
    return [item for name, value in values.items() for item in ("--with", f"{name}={value}")]


def preflight_withs(hub: Path, brief: dict[str, str]) -> dict[str, str]:
    """The preflight's values as pass-1 of an implement run gives them (no input)."""
    return {
        "feature": "demo-flow",
        "ticket": "DEM-8",
        "brief": brief["path"],
        "hub": brief["hub"],
        "base": brief["commit"],
        "input": "none",
        "note": "",
        "superseded": "",
    }


def stub_claude(monkeypatch: pytest.MonkeyPatch, prompts: list[str]) -> None:
    """Every ``claude -p`` child of a run replies ``REPLY``; its prompt is kept."""
    spawn = WorkflowExecutors._spawn

    def stubbed(self: WorkflowExecutors, argv: Sequence[str], **kwargs: Any) -> ChildResult:
        if argv[0] != CLAUDE_PROGRAM:
            return spawn(self, argv, **kwargs)
        prompts.append(argv[argv.index("-p") + 1])
        result = {"type": "result", "subtype": "success", "is_error": False, "result": REPLY}
        return ChildResult(0, json.dumps(result).encode(), b"")

    monkeypatch.setattr(WorkflowExecutors, "_spawn", stubbed)


def runs_without_time(record: PreflightRecord | str | None) -> list[dict[str, Any]]:
    assert isinstance(record, PreflightRecord), record
    dropped = {"ran_at", "run_id"}
    return [
        {key: value for key, value in run.model_dump(mode="json").items() if key not in dropped}
        for run in record.runs
    ]


def without_lines(text: str, *starts: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.startswith(starts))


def test_prints_the_runs_prompt_when_prompt_renders_a_stage(
    hub: Path, run_command: CommandRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompts: list[str] = []
    stub_claude(monkeypatch, prompts)
    given = ("--input", "feature=demo-flow", "--input", "issue=DEM-8", "--input", "issue_text=x")
    ok(run_command(hub, "workflow", "run", "implement", *given, "--live", "--run-id", "impl-1"))
    records = [
        json.loads(line)
        for line in (hub / ".agent-runs/workflows/impl-1/records.jsonl").read_text().splitlines()
    ]
    [context] = [
        r["output"] for r in records if r.get("event") == "step_end" and r.get("node") == "context"
    ]
    brief = {key: context[key] for key in ("path", "hub", "commit")}

    printed = ok(
        run_command(
            hub, "step", "prompt", "--stage", "preflight", *withs(preflight_withs(hub, brief))
        )
    )

    assert prompts == [printed]


@pytest.mark.parametrize(
    ("values", "reason"),
    [
        (
            {"feature": "demo-flow"},
            "give --with for base, brief, hub, input, note, superseded, ticket",
        ),
        (
            {
                "feature": "demo-flow",
                "ticket": "DEM-8",
                "base": "a",
                "brief": "b",
                "hub": "h",
                "input": "none",
                "note": "",
                "superseded": "",
                "spec": "x",
            },
            "preflight takes no spec",
        ),
    ],
    ids=["missing", "unknown"],
)
def test_refuses_values_the_node_does_not_take_when_prompt_runs(
    hub: Path, run_command: CommandRunner, *, values: dict[str, str], reason: str
) -> None:
    line = refused(
        run_command(hub, "step", "prompt", "--stage", "preflight", *withs(values)), "prompt"
    )

    assert reason in line


def test_reads_a_hubs_own_workflow_over_the_built_in_when_prompt_runs(
    hub: Path, run_command: CommandRunner
) -> None:
    pack = hub / "workflows/sdlc"
    # hub init seeds the sdlc pack into the hub; the hub's copy is the one a run reads.
    assert (pack / "ticket-pass.yaml").read_bytes() == (
        BUILTIN_WORKFLOWS / "sdlc/ticket-pass.yaml"
    ).read_bytes()
    (pack / "prompts/ticket-plan.md").write_text("Our own plan prompt for $WITH.ticket here\n")
    values = {"feature": "demo-flow", "ticket": "DEM-8", "brief": "b", "checkout": "c"}

    printed = ok(run_command(hub, "step", "prompt", "--stage", "ticket-plan", *withs(values)))

    assert printed == "Our own plan prompt for DEM-8 here\n"


@pytest.mark.parametrize(
    ("stage", "value"),
    [
        ("preflight", PLAN_DRIFT),
        ("spec-lens", REVIEW),
        ("quality-lens", REVIEW | {"reviewer": "quality"}),
        ("ticket-eval", EVAL),
        ("ticket-plan", {"path": f"{FEATURE}/tickets/DEM-8/plan.md"}),
    ],
)
def test_prints_the_last_json_line_checked_when_output_reads_a_reply(
    hub: Path, monkeypatch: pytest.MonkeyPatch, *, stage: str, value: dict[str, Any]
) -> None:
    reply = f"Done.\n\n`{json.dumps(value)}`\n"

    printed = ok(piped(hub, monkeypatch, "step", "output", "--stage", stage, reply=reply))

    assert json.loads(printed) == value


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        ("No JSON here.", "no JSON object on its last line"),
        (json.dumps(PLAN_DRIFT | {"drift": "maybe"}), "drift"),
        (json.dumps({k: v for k, v in PLAN_DRIFT.items() if k != "summary"}), "required"),
    ],
    ids=["no-json", "bad-enum", "missing-key"],
)
def test_refuses_a_reply_the_run_would_fail_when_output_reads_it(
    hub: Path, monkeypatch: pytest.MonkeyPatch, *, reply: str, reason: str
) -> None:
    line = refused(
        piped(hub, monkeypatch, "step", "output", "--stage", "preflight", reply=reply), "output"
    )

    assert reason in line


def test_writes_the_runs_records_when_a_session_records_the_same_preflight(
    hub: Path,
    run_command: CommandRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feature = hub / FEATURE
    pristine = hub.parent / "feature-before"
    shutil.copytree(feature, pristine)
    stub_claude(monkeypatch, [])
    given = ("--input", "feature=demo-flow", "--input", "issue=DEM-8", "--input", "issue_text=x")
    started = ok(
        run_command(hub, "workflow", "run", "implement", *given, "--live", "--run-id", "impl-1")
    )
    assert "run impl-1: paused at " in started
    run_preflight = (feature / "tickets/DEM-8/preflight.json").read_bytes()
    run_request = (feature / "change-requests/1.md").read_text()
    shutil.rmtree(feature)
    shutil.copytree(pristine, feature)

    # The session: the brief, the subagent's reply checked, the request, then the run recorded.
    brief = json.loads(
        ok(run_command(hub, "step", "ticket-brief", "--feature", "demo-flow", "--ticket", "DEM-8"))
    )
    findings = ok(
        piped(hub, monkeypatch, "step", "output", "--stage", "preflight", reply=REPLY)
    ).strip()
    env = {"AGENT_HUB_RUN_ID": SESSION_RUN}
    ticket = ("--feature", "demo-flow", "--ticket", "DEM-8")
    request = json.loads(
        ok(
            run_command(
                hub,
                "step",
                "change-request",
                *ticket,
                # The texts come from the findings: the session pastes none of them.
                *("--findings", findings, "--commit", brief["commit"]),
                env=env,
            )
        )
    )
    ok(
        run_command(
            hub,
            "step",
            "preflight",
            *ticket,
            *("--findings", findings, "--commit", brief["commit"], "--input", "none"),
            *("--input-text", "", "--request", str(request["n"]), "--declined-request", ""),
            *("--read", ""),
            env=env,
        )
    )

    session_preflight = (feature / "tickets/DEM-8/preflight.json").read_bytes()
    session_request = (feature / "change-requests/1.md").read_text()
    session_record = preflight_record(session_preflight, folder="DEM-8")
    run_record = preflight_record(run_preflight, folder="DEM-8")
    assert runs_without_time(session_record) == runs_without_time(run_record)
    assert isinstance(session_record, PreflightRecord)
    assert [run.run_id for run in session_record.runs] == [SESSION_RUN]
    assert without_lines(session_request, "opened_at:", "run_id:") == without_lines(
        run_request, "opened_at:", "run_id:"
    )
    assert f"run_id: {SESSION_RUN}" in session_request


def test_needs_the_texts_or_the_findings_when_change_request_opens_one(
    hub: Path, run_command: CommandRunner
) -> None:
    result = run_command(
        hub, "step", "change-request", "--feature", "demo-flow", "--ticket", "DEM-8"
    )

    assert result.exit_code == 2, result.output
    # The usage box may be colored and wrap the message: compare its words alone.
    words = " ".join(unstyle(result.output).replace("│", " ").split())
    assert "give --evidence and --proposal, or --findings" in words
    assert not (hub / FEATURE / "change-requests").exists()


def test_names_the_stages_the_skill_names_when_stages_listed() -> None:
    # The /implement skill's render test pins the same map (generator tests import no cli).
    assert {name.value: (s.workflow, s.node) for name, s in STAGES.items()} == {
        "preflight": ("preflight-check", "preflight"),
        "ticket-plan": ("ticket-pass", "plan"),
        "spec-lens": ("ticket-pass", "spec"),
        "quality-lens": ("ticket-pass", "quality"),
        "ticket-eval": ("implement", "eval"),
    }
