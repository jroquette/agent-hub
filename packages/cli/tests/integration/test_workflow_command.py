"""``hub workflow list|validate|run`` over a hub's ``workflows/`` packs (AC-213.1, AC-213.3).

The ``run`` cases cover AGH-221's AC: the engine runs a sample pack end to end against the
existing fakes (claude, make, git, gh), records it under ``.agent-runs/workflows/<run>/`` and
sends its events; resume and abandon act on that record.

Each case builds a hub under ``tmp_path`` and points the built-ins at a folder of its own, so the
packs the platform ships never change what a case sees.
"""

import fcntl
import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from agent_hub.cli import workflow_command, workflow_runs
from agent_hub.cli.main import app
from agent_hub.storage.event_store import open_event_store

CHECK_YAML = """\
version: 1
name: check
revision: 1
description: Lint, then test.
nodes:
  - id: lint
    type: shell
    command: [make, lint]
  - id: test
    type: shell
    command: [make, test]
    depends_on: [lint]
"""


@pytest.fixture
def builtins(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path_factory.mktemp("builtin")
    monkeypatch.setattr(workflow_command, "BUILTIN_WORKFLOWS", folder)
    return folder


@pytest.fixture
def hub(tmp_path: Path, builtins: Path) -> Path:
    (tmp_path / "hub.json").write_text("{}\n")
    (tmp_path / "workflows" / "demo").mkdir(parents=True)
    return tmp_path


def write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def run(hub: Path, *args: str) -> Result:
    return CliRunner().invoke(app, ["workflow", *args], env={"AGENT_HUB_ROOT": str(hub)})


def test_lists_each_workflow_when_every_file_loads(hub: Path) -> None:
    write(hub, "workflows/demo/check.yaml", CHECK_YAML)
    deliver = {
        "version": 1,
        "name": "deliver",
        "revision": 2,
        "nodes": [{"id": "a", "type": "halt", "reason": "x"}],
    }
    write(hub, "workflows/ship/deliver.json", json.dumps(deliver))

    result = run(hub, "list")

    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == ["check  2 nodes  Lint, then test.", "deliver  1 nodes"]


def test_lists_nothing_when_hub_has_no_workflows_folder(tmp_path: Path, builtins: Path) -> None:
    (tmp_path / "hub.json").write_text("{}\n")

    result = run(tmp_path, "list")

    assert (result.exit_code, result.stdout) == (0, "")


def test_lists_the_loading_ones_and_exits_one_when_a_file_is_broken(hub: Path) -> None:
    write(hub, "workflows/demo/check.yaml", CHECK_YAML)
    write(hub, "workflows/demo/broken.yaml", "version: 1\nname: broken\nname: again\n")

    result = run(hub, "list")

    assert result.exit_code == 1
    assert result.stdout.splitlines() == ["check  2 nodes  Lint, then test."]
    assert result.stderr.startswith("workflows/demo/broken.yaml:3: $: ")


def test_validates_each_workflow_when_every_file_loads(hub: Path) -> None:
    write(hub, "workflows/demo/check.yaml", CHECK_YAML)

    result = run(hub, "validate")

    assert result.exit_code == 0, result.output
    assert result.stdout == "check: valid (2 nodes in 2 layers)\n"


def test_names_file_line_and_key_when_validate_finds_load_errors(hub: Path) -> None:
    write(
        hub,
        "workflows/demo/check.yaml",
        CHECK_YAML.replace(
            "    command: [make, lint]\n", "    command: [make, lint]\n    promt: x\n"
        ),
    )
    write(
        hub,
        "workflows/demo/cycle.yaml",
        "version: 1\nname: cycle\nrevision: 1\nnodes:\n"
        "  - id: a\n    type: halt\n    reason: x\n    depends_on: [b]\n"
        "  - id: b\n    type: halt\n    reason: x\n    depends_on: [a]\n",
    )

    result = run(hub, "validate")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr.splitlines() == [
        "workflows/demo/check.yaml:9: nodes[0].promt: unknown key",
        "workflows/demo/cycle.yaml:8: nodes[0].depends_on: a cycle runs through the nodes a, b",
    ]


def test_checks_only_the_named_workflow_when_validate_gets_a_name(hub: Path) -> None:
    write(hub, "workflows/demo/check.yaml", CHECK_YAML)
    write(hub, "workflows/demo/broken.yaml", "version: 1\nname: broken\nname: again\n")

    result = run(hub, "validate", "check")

    assert (result.exit_code, result.stdout) == (0, "check: valid (2 nodes in 2 layers)\n")


def test_exits_one_when_validate_names_no_workflow(hub: Path) -> None:
    result = run(hub, "validate", "ghost")

    assert result.exit_code == 1
    assert result.stderr == "no workflow named ghost in workflows/ or the built-ins\n"


def test_refuses_the_file_when_it_is_over_the_size_cap(hub: Path) -> None:
    write(hub, "workflows/demo/check.yaml", CHECK_YAML + "#" * (256 * 1024) + "\n")

    result = run(hub, "validate")

    assert result.exit_code == 1
    assert result.stderr.startswith("workflows/demo/check.yaml: $: the file is over 262144 bytes")


def test_refuses_the_file_when_it_links_out_of_its_pack(
    hub: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    target = write(tmp_path_factory.mktemp("elsewhere"), "check.yaml", CHECK_YAML)
    (hub / "workflows" / "demo" / "check.yaml").symlink_to(target)

    result = run(hub, "validate")

    assert result.exit_code == 1
    assert result.stderr.startswith("workflows/demo/check.yaml: $: a link that leaves its pack")


def test_overrides_the_builtin_when_hub_has_a_workflow_of_its_name(
    hub: Path, builtins: Path
) -> None:
    write(builtins, "base/check.yaml", CHECK_YAML.replace("Lint, then test.", "Built in."))
    write(builtins, "base/broken.yaml", "version: 1\nname: broken\nname: again\n")
    write(hub, "workflows/demo/check.yaml", CHECK_YAML)

    result = run(hub, "list")

    assert result.stdout.splitlines() == ["check  2 nodes  Lint, then test."]
    assert result.stderr.startswith("<builtin>/base/broken.yaml:3: $: ")


def test_exits_two_when_folder_is_not_a_hub(tmp_path: Path, builtins: Path) -> None:
    result = run(tmp_path, "list")

    assert result.exit_code == 2
    assert "not a hub" in result.stderr


def test_keeps_folder_problems_when_validate_gets_a_name(
    tmp_path: Path, builtins: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    (tmp_path / "hub.json").write_text("{}\n")
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    write(elsewhere, "demo/check.yaml", CHECK_YAML)
    (tmp_path / "workflows").symlink_to(elsewhere)

    result = run(tmp_path, "validate", "check")

    assert result.exit_code == 1
    assert result.stderr.startswith("workflows: $: the workflows folder is a link")


# ``hub workflow run`` (AGH-221): a sample pack run end to end in the DEMO workspace against the
# fakes of ``run_workspace`` (claude, make, gh, and the real git).
SAMPLE_YAML = """\
version: 1
name: sample
revision: 3
inputs:
  issue: {type: string, required: true}
returns: report
outcome_field: delivered
nodes:
  - id: plan
    type: agent
    prompt_file: plan.md
    model: large
  - id: implement
    type: agent
    prompt: "Implement the plan: $plan.output"
    depends_on: [plan]
    limits: {max_turns: 5, max_cost_usd: 0.5}
  - id: gate
    type: shell
    command: [make, check]
    depends_on: [implement]
  - id: status
    type: shell
    command: [git, status, --short]
    cwd: ../demo-api
    depends_on: [gate]
  - id: pr
    type: shell
    command: [gh, pr, view, jdoe/dem-1]
    depends_on: [gate]
    output_format:
      type: object
      required: [url]
      properties: {url: {type: string}}
  - id: report
    type: script
    runtime: sh
    script: report.sh
    args: [$pr.output.url]
    depends_on: [pr]
    output_format:
      type: object
      required: [delivered]
      properties: {delivered: {type: boolean}}
"""
REPORT_SH = 'printf \'{"delivered": true, "url": "%s"}\' "$1"\n'
RUN_ID = "r1"


class SampleRun:
    """The DEMO hub with the ``sample`` pack, and the calls its fakes logged."""

    def __init__(self, run_workspace: Any) -> None:
        self.fakes = run_workspace
        self.hub: Path = run_workspace.workspace.hub
        write(self.hub, "workflows/sample/sample.yaml", SAMPLE_YAML)
        write(self.hub, "workflows/sample/prompts/plan.md", "Plan $INPUTS.issue now\n")
        write(self.hub, "workflows/sample/scripts/report.sh", REPORT_SH)
        (run_workspace.bin / "sh").symlink_to(os.path.realpath(shutil.which("sh") or "/bin/sh"))

    def run(self, *args: str) -> Result:
        return run(self.hub, "run", *args)

    def records(self, run_id: str = RUN_ID) -> list[dict[str, Any]]:
        path = self.hub / ".agent-runs" / "workflows" / run_id / "records.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()]

    def ends(self, run_id: str = RUN_ID) -> list[tuple[str, str]]:
        return [
            (record["node"], record["status"])
            for record in self.records(run_id)
            if record["event"] == "step_end"
        ]


@pytest.fixture
def sample(run_workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SampleRun:
    monkeypatch.setattr(workflow_command, "BUILTIN_WORKFLOWS", tmp_path / "no-builtins")
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "done-no-commit")
    monkeypatch.setenv("FAKE_GH_MODE", "exists")
    monkeypatch.setenv("LINEAR_API_KEY", "lin_" + "x" * 12)
    monkeypatch.setenv("GH_TOKEN", "g" * 12)
    monkeypatch.setenv("AGENT_HUB_DB", str(tmp_path / "events.db"))
    return SampleRun(run_workspace)


def test_runs_sample_pack_end_to_end_when_run_live(sample: SampleRun) -> None:
    result = sample.run("sample", "--input", "issue=DEM-1", "--live", "--run-id", RUN_ID)

    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[-1] == "run r1: done, outcome True"
    assert sample.ends() == [
        ("plan", "ok"),
        ("implement", "ok"),
        ("gate", "ok"),
        ("status", "ok"),
        ("pr", "ok"),
        ("report", "ok"),
    ]
    end = sample.records()[-2]
    assert (end["event"], end["status"], end["outcome"]) == ("end", "done", True)
    plan, implement = sample.fakes.calls("claude")
    assert plan["argv"][1] == "Plan DEM-1 now\n"
    assert implement["argv"][1].startswith("Implement the plan: Done.\n")
    assert plan["argv"][plan["argv"].index("--model") + 1] == "opus"
    assert implement["argv"][implement["argv"].index("--max-turns") + 1] == "5"
    assert plan["cwd"] == str(sample.hub)
    assert [call["argv"] for call in sample.fakes.calls("make")] == [["check"]]
    assert [call["argv"] for call in sample.fakes.calls("gh")] == [["pr", "view", "jdoe/dem-1"]]


def test_scopes_child_environments_when_run_live(sample: SampleRun) -> None:
    sample.run("sample", "--input", "issue=DEM-1", "--live", "--run-id", RUN_ID)

    calls = [call for tool in ("claude", "make", "gh") for call in sample.fakes.calls(tool)]
    assert calls
    assert all("LINEAR_API_KEY" not in call["env"] for call in calls)
    assert all("GH_TOKEN" not in call["env"] for call in calls)
    plan, implement = sample.fakes.calls("claude")
    assert "AGENT_HUB_STEP" in plan["env"]
    assert plan["values"]["OTEL_RESOURCE_ATTRIBUTES"] == "repo=,issue=DEM-1,agent_run=r1"


def test_writes_snapshot_and_events_when_run_live(sample: SampleRun, tmp_path: Path) -> None:
    sample.run("sample", "--input", "issue=DEM-1", "--live", "--run-id", RUN_ID)

    snapshot = sample.hub / ".agent-runs" / "workflows" / RUN_ID / "snapshot"
    assert (snapshot / "prompts" / "plan.md").read_text() == "Plan $INPUTS.issue now\n"
    assert (snapshot / "scripts" / "report.sh").read_text() == REPORT_SH
    start = sample.records()[0]
    assert (start["workflow"], start["revision"]) == ("sample", 3)
    assert start["content_hash"].startswith("sha256:")
    stored = open_event_store(tmp_path / "events.db").read_all()
    assert {event.session for event in stored} == {"run:r1"}
    assert [event.step for event in stored if event.type == "step.start"] == [
        "plan",
        "implement",
        "gate",
        "status",
        "pr",
        "report",
    ]
    (end,) = [event for event in stored if event.type == "run.end"]
    assert (end.payload["status"], end.payload["outcome"]) == ("done", True)


def test_prints_what_would_run_when_not_live(sample: SampleRun) -> None:
    result = sample.run("sample", "--input", "issue=DEM-1")

    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == [
        "would run: plan (agent)",
        "would run: implement (agent)",
        "would run: gate (shell): make check",
        "would run: status (shell): git status --short",
        "would run: pr (shell): gh pr view jdoe/dem-1",
        "would run: report (script): sh scripts/report.sh '$pr.output.url'",
    ]
    assert sample.fakes.calls("claude") == []
    assert not (sample.hub / ".agent-runs" / "workflows").exists()


def test_exits_two_when_run_misses_a_required_input(sample: SampleRun) -> None:
    result = sample.run("sample", "--live")

    assert result.exit_code == 2
    assert 'the input "issue" is required' in result.stderr
    assert sample.fakes.calls("claude") == []


def test_fails_run_and_skips_dependants_when_gate_fails(
    sample: SampleRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_MAKE_EXIT", "1")

    result = sample.run("sample", "--input", "issue=DEM-1", "--live", "--run-id", RUN_ID)

    assert result.exit_code == 1
    assert result.stdout.splitlines()[-1] == "run r1: failed"
    assert sample.ends()[2:] == [
        ("gate", "failed"),
        ("status", "skipped"),
        ("pr", "skipped"),
        ("report", "skipped"),
    ]
    gate = [r for r in sample.records() if r.get("node") == "gate"][-1]
    assert gate["failure_kind"] == "exec_failed"


def test_reuses_completed_nodes_when_failed_run_resumed(
    sample: SampleRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_MAKE_EXIT", "1")
    sample.run("sample", "--input", "issue=DEM-1", "--live", "--run-id", RUN_ID)
    monkeypatch.setenv("FAKE_MAKE_EXIT", "0")

    result = sample.run("--resume", RUN_ID)

    assert result.exit_code == 0, result.output
    assert len(sample.fakes.calls("claude")) == 2
    resumed = sample.ends()[6:]
    assert resumed[:3] == [("plan", "skipped"), ("implement", "skipped"), ("gate", "ok")]
    gates = [r["attempt"] for r in sample.records() if r.get("node") == "gate" and "status" in r]
    assert gates == [1, 2]
    assert [r["status"] for r in sample.records() if r["event"] == "end"] == ["failed", "done"]


def test_ends_run_cancelled_when_abandoned(sample: SampleRun, tmp_path: Path) -> None:
    sample.run("sample", "--input", "issue=DEM-1", "--live", "--run-id", RUN_ID)
    # A done run cannot be abandoned; a failed one can, once.
    assert sample.run("--abandon", RUN_ID).exit_code == 1

    records = sample.hub / ".agent-runs" / "workflows" / RUN_ID / "records.jsonl"
    lines = records.read_text().splitlines()
    end = json.loads(lines[-2])
    records.write_text("\n".join([*lines[:-2], json.dumps({**end, "status": "failed"})]) + "\n")

    result = sample.run("--abandon", RUN_ID)

    assert result.exit_code == 0, result.output
    assert sample.records()[-1]["status"] == "cancelled"
    assert sample.run("--resume", RUN_ID).exit_code == 1
    stored = open_event_store(tmp_path / "events.db").read_all()
    ends = sorted(event.source_id for event in stored if event.type == "run.end")
    assert ends == ["r1:run:0:end", "r1:run:1:end"]


@pytest.mark.parametrize(
    "args",
    [
        ("sample", "--live", "--run-id", "r" * 201),
        ("sample", "--live", "--run-id", "../escape"),
        ("--resume", "R1"),
        ("--abandon", "x" * 33),
    ],
)
def test_exits_two_before_running_when_run_id_is_malformed(
    sample: SampleRun, args: tuple[str, ...]
) -> None:
    result = (
        sample.run(*args, "--input", "issue=DEM-1") if args[0] == "sample" else sample.run(*args)
    )

    assert result.exit_code == 2, result.output
    assert "use 1 to 32 of a-z 0-9 -" in result.stderr
    assert sample.fakes.calls("claude") == []
    assert not (sample.hub / ".agent-runs").exists()


def started(sample: SampleRun, *more: str) -> Result:
    return sample.run("sample", "--input", "issue=DEM-1", "--live", "--run-id", RUN_ID, *more)


def run_path(sample: SampleRun, *parts: str) -> Path:
    return sample.hub.joinpath(".agent-runs", "workflows", RUN_ID, *parts)


def test_ignores_modules_planted_in_hub_when_hub_step_node_runs(sample: SampleRun) -> None:
    marker = sample.hub / "planted-ran"
    write(sample.hub, "typer/__init__.py", f"open({str(marker)!r}, 'w').close()\n")
    step = "version: 1\nname: step\nrevision: 1\nnodes:\n  - id: s\n    type: shell\n"
    write(sample.hub, "workflows/step/step.yaml", step + "    command: [hub, step]\n")

    result = sample.run("step", "--live", "--run-id", "s1")

    assert result.exit_code == 1
    assert not marker.exists()
    assert workflow_command.own_hub_program()[1:] == ("-I", "-m", "agent_hub.cli")


@pytest.mark.parametrize("action", ["--resume", "--abandon"])
def test_refuses_run_when_another_process_holds_its_lock(
    sample: SampleRun, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    monkeypatch.setenv("FAKE_MAKE_EXIT", "1")
    started(sample)
    before = run_path(sample, "records.jsonl").read_text()
    descriptor = os.open(run_path(sample, "lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = sample.run(action, RUN_ID)
    finally:
        os.close(descriptor)

    assert result.exit_code == 1
    assert "is in use by another hub workflow run" in result.stderr
    assert run_path(sample, "records.jsonl").read_text() == before


def test_resumes_when_last_record_line_is_torn(
    sample: SampleRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_MAKE_EXIT", "1")
    started(sample)
    with run_path(sample, "records.jsonl").open("a") as file:
        file.write('{"event": "st')
    monkeypatch.setenv("FAKE_MAKE_EXIT", "0")

    result = sample.run("--resume", RUN_ID)

    assert result.exit_code == 0, result.output
    again = sample.run("--abandon", RUN_ID)
    assert again.exit_code == 1
    assert "already ended done" in again.stderr


def test_refuses_resume_when_a_record_line_is_not_an_object(
    sample: SampleRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_MAKE_EXIT", "1")
    started(sample)
    with run_path(sample, "records.jsonl").open("a") as file:
        file.write("[1]\n")

    result = sample.run("--resume", RUN_ID)

    assert result.exit_code == 1
    assert "cannot read the run r1" in result.stderr


def test_refuses_resume_when_snapshot_changed(
    sample: SampleRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_MAKE_EXIT", "1")
    started(sample)
    run_path(sample, "snapshot", "prompts", "plan.md").write_text("Something else\n")

    result = sample.run("--resume", RUN_ID)

    assert result.exit_code == 1
    assert "snapshot no longer matches" in result.stderr
    assert len(sample.fakes.calls("claude")) == 2


def test_leaves_no_run_folder_when_a_pack_file_is_over_the_cap(sample: SampleRun) -> None:
    big = workflow_runs.MAX_SNAPSHOT_FILE_BYTES + 1
    write(sample.hub, "workflows/sample/scripts/report.sh", "#" * big)

    result = started(sample)

    assert result.exit_code == 1
    assert "scripts/report.sh is larger than" in result.stderr
    assert not run_path(sample).exists()
    assert sample.fakes.calls("claude") == []
