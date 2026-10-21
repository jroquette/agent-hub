"""``hub scenario list|plan`` (AC-350.8, .13, .17, .18, .28, .42; docs/design/scenarios.md).

Each test builds a workspace under ``tmp_path``: a hub (``hub.json`` with the environments of
``an_environments_document``) holding the ``demo`` action pack and the ``orders`` scenario pack,
a git checkout with its own identity, and runs the command in process with ``AGENT_HUB_ROOT``
naming the hub. Every action script appends its stdin to the file ``MARKER`` names, so a test
sees which mode ran, if any. Output is read without colour codes (CI forces a terminal).
"""

import json
import os
import pty
import re
import select
import shutil
import signal
import subprocess
import sys
import time
from datetime import date
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from agent_hub.cli.main import app
from agent_hub.cli.workflow_runs import snapshot_hash
from agent_hub.core.events.event import Event
from agent_hub.core.testing.builders import an_environments_document
from agent_hub.storage.event_store import open_event_store

SCRIPT = """\
stdin=$(cat)
printf '%s\\n' "$stdin" >> "$MARKER"
case "$stdin" in
  *'"mode": "plan"'*) printf '{"summary": "would act"}' ;;
  *) printf '{"order": "o-1", "status": "ON_HOLD"}' ;;
esac
"""
ACTION = """\
version: 1
name: {name}
description: A demo {effect}
effect: {effect}
runtime: sh
script: scripts/{name}.sh
inputs:
  target: {{type: service, required: true}}
  ref: {{type: string}}
  count: {{type: integer, default: 1}}
output_format:
  type: object
  required: [order]
  properties: {{order: {{type: string}}, status: {{type: string}}}}
"""
SCENARIO = """\
version: 1
kind: scenario
name: order-walk
revision: 1
description: One demo order from send to hold
inputs:
  ref: {type: string, required: true}
nodes:
  - id: send-order
    type: action
    action: send-order
    with: {target: api, ref: $INPUTS.ref}
  - id: order-held
    type: expect
    depends_on: [send-order]
    action: demo/get-order
    with: {target: api, ref: $INPUTS.ref}
    every: 10s
    timeout: 5m
    until_when: "$self.output.status == 'ON_HOLD'"
    capture: {order_id: $self.output.order}
  - id: check-order
    type: action
    depends_on: [order-held]
    action: get-order
    with: {target: api, ref: $CTX.order_id}
"""


def git(hub: Path, *args: str) -> None:
    found = shutil.which("git")
    assert found is not None
    identity = ("-c", "user.name=Demo Dev", "-c", "user.email=dev@example.com")
    command = [found, *identity, *args]
    subprocess.run(command, cwd=hub, check=True, capture_output=True)  # noqa: S603 - absolute git, fixed arguments


def write_action(hub: Path, name: str, effect: str) -> None:
    pack = hub / "actions" / "demo"
    (pack / "scripts").mkdir(parents=True, exist_ok=True)
    (pack / f"{name}.yaml").write_text(ACTION.format(name=name, effect=effect))
    (pack / "scripts" / f"{name}.sh").write_text(SCRIPT)


def write_scenario(hub: Path, text: str, *, pack: str = "demo") -> Path:
    path = hub / "scenarios" / pack / f"{_name(text)}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _name(text: str) -> str:
    found = re.search(r"^name: (\S+)$", text, re.MULTILINE)
    assert found is not None
    return found[1]


def a_hub(root: Path) -> Path:
    root.mkdir(parents=True)
    document = an_environments_document()
    document["platform"]["version"] = version("agent-hub-cli")
    (root / "hub.json").write_text(json.dumps(document, indent=2) + "\n")
    return root


@pytest.fixture
def hub(tmp_path: Path) -> Path:
    """A committed hub: the read action ``get-order``, the write ``send-order`` and the scenario
    ``order-walk`` that uses both."""
    root = a_hub(tmp_path / "workspace" / "hub")
    write_action(root, "get-order", "read")
    write_action(root, "send-order", "write")
    write_scenario(root, SCENARIO)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "demo hub")
    return root


@pytest.fixture
def marker(tmp_path: Path) -> Path:
    return tmp_path / "marker"


def run_hub(hub: Path, marker: Path, *args: str) -> Result:
    environ = {
        "AGENT_HUB_ROOT": str(hub),
        "MARKER": str(marker),
        "AGENT_HUB_DB": str(hub.parent.parent / "events.db"),
    }
    return CliRunner().invoke(app, list(args), env=environ, input="")


def plain(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def test_lists_scenario_when_scenario_kind_in_scenarios(hub: Path, marker: Path) -> None:
    other = SCENARIO.replace("name: order-walk", "name: invoice-walk").replace(
        "description: One demo order from send to hold\n", ""
    )
    write_scenario(hub, other, pack="billing")

    result = run_hub(hub, marker, "scenario", "list")

    assert (result.exit_code, plain(result.stderr)) == (0, ""), result.output
    assert plain(result.stdout).splitlines() == [
        "invoice-walk  billing  3 nodes",
        "order-walk  demo  3 nodes  One demo order from send to hold",
    ]


def test_hides_scenario_from_workflow_list_when_scenario_kind(hub: Path, marker: Path) -> None:
    listed = run_hub(hub, marker, "workflow", "list")
    stray = hub / "workflows" / "demo" / "stray-walk.yaml"
    stray.parent.mkdir(parents=True)
    stray.write_text(SCENARIO.replace("name: order-walk", "name: stray-walk"))

    refused = run_hub(hub, marker, "workflow", "list")

    assert listed.exit_code == 0, listed.output
    assert "order-walk" not in plain(listed.output)
    assert refused.exit_code == 1, refused.output
    assert "walk" not in plain(refused.stdout)
    assert plain(refused.stderr).splitlines() == [
        "workflows/demo/stray-walk.yaml:2: $: kind: scenario belongs in scenarios/<pack>/,"
        " not workflows/"
    ]


def test_prints_file_line_node_type_when_scenario_kind_forbids_node(
    hub: Path, marker: Path
) -> None:
    shell = SCENARIO.replace("name: order-walk", "name: shell-walk") + (
        "  - id: wipe\n    type: shell\n    command: [rm, -rf, build]\n"
    )
    write_scenario(hub, shell)

    result = run_hub(hub, marker, "scenario", "list")

    assert result.exit_code == 1, result.output
    assert plain(result.stdout).splitlines() == [
        "order-walk  demo  3 nodes  One demo order from send to hold"
    ]
    assert plain(result.stderr).splitlines() == [
        'scenarios/demo/shell-walk.yaml:28: nodes[3].type: the node "wipe" has type shell:'
        " a scenario takes only action, expect, approval, wait, loop_group and include nodes"
    ]


def test_prints_no_scenarios_when_empty_hub(tmp_path: Path, marker: Path) -> None:
    root = a_hub(tmp_path / "workspace" / "hub")

    result = run_hub(root, marker, "scenario", "list")

    assert (result.exit_code, plain(result.stdout)) == (0, "no scenarios yet\n")


def modes(marker: Path) -> list[str]:
    if not marker.exists():
        return []
    return [json.loads(line)["mode"] for line in marker.read_text().splitlines()]


def plan_hub(hub: Path, marker: Path, environment: str, *args: str) -> Result:
    return run_hub(
        hub,
        marker,
        "scenario",
        "plan",
        "order-walk",
        "--env",
        environment,
        "--input",
        "ref=T-1",
        *args,
    )


def content_hash(hub: Path, name: str) -> str:
    listed = json.loads(run_hub(hub, Path("/dev/null"), "action", "list", "--json").stdout)
    return next(
        item["content_hash"] for item in listed["actions"] if item["action"] == f"demo/{name}"
    )


ENV_FILE = "demo-api/environment/.env.local"
ENV_SECRET = "x-" + "secret" + "-y"


def test_prints_every_column_when_plan_on_write_environment(
    hub: Path, marker: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = json.loads((hub / "hub.json").read_text())
    document["environments"]["local"]["credentials"] = {"env_file": ENV_FILE}
    (hub / "hub.json").write_text(json.dumps(document, indent=2) + "\n")
    env_file = hub.parent / ENV_FILE
    env_file.parent.mkdir(parents=True)
    env_file.write_text(f"DEMO_TOKEN={ENV_SECRET}\n")
    opened: list[str] = []
    monkeypatch.setattr(
        "agent_hub.cli.action_command.load_env_file",
        lambda *args, **kwargs: opened.append("action_command") or {},
    )
    monkeypatch.setattr(
        "agent_hub.cli.env_files_loader.load_env_file",
        lambda *args, **kwargs: opened.append("env_files_loader") or {},
    )
    send, get = content_hash(hub, "send-order"), content_hash(hub, "get-order")

    result = plan_hub(hub, marker, "local")

    assert (result.exit_code, plain(result.stderr)) == (0, ""), result.output
    assert plain(result.stdout).splitlines() == [
        "scenario: order-walk (environment local, access write)",
        "send-order  action  demo/send-order  write  allow",
        "  args: target=api, ref=T-1, count=1",
        "  endpoints: target → demo-api/api http://localhost:8000",
        f"  content hash: {send}",
        "  draft: no",
        "  plan: would act",
        "order-held  expect  demo/get-order  read  allow",
        "  args: target=api, ref=T-1, count=1",
        "  endpoints: target → demo-api/api http://localhost:8000",
        "  polls: every 10s, timeout 5m",
        f"  content hash: {get}",
        "  draft: no",
        "  plan: would act",
        "check-order  action  demo/get-order  read  allow",
        "  args: target=api, ref=<$CTX.order_id from order-held>, count=1",
        "  endpoints: target → demo-api/api http://localhost:8000",
        f"  content hash: {get}",
        "  draft: no",
        "  plan: runs with values known at run time",
    ]
    # Only plan-mode calls, for the two steps whose args are known; no credential, no event,
    # no run folder, and the env file never read.
    assert modes(marker) == ["plan", "plan"]
    assert ENV_SECRET not in marker.read_text()
    assert opened == []
    assert not (hub.parent.parent / "events.db").exists()
    assert not (hub / ".agent-runs").exists()


def test_prints_same_data_when_plan_json(hub: Path, marker: Path) -> None:
    result = plan_hub(hub, marker, "local", "--json")

    assert (result.exit_code, plain(result.stderr)) == (0, ""), result.output
    planned = json.loads(plain(result.stdout))
    assert {key: planned[key] for key in ("scenario", "environment", "access", "production")} == {
        "scenario": "order-walk",
        "environment": "local",
        "access": "write",
        "production": False,
    }
    assert (planned["denied"], planned["problems"]) == (False, [])
    send, held, check = planned["rows"]
    assert send == {
        "step": "send-order",
        "type": "action",
        "action": "demo/send-order",
        "effect": "write",
        "args": {"target": "api", "ref": "T-1", "count": "1"},
        "endpoints": {
            "target": {"service": "demo-api/api", "url": "http://localhost:8000", "resource": None}
        },
        "every": None,
        "timeout": None,
        "content_hash": content_hash(hub, "send-order"),
        "draft": False,
        "decision": "allow",
        "reason_kind": "table",
        "reason": None,
        "plan": "would act",
    }
    assert (held["every"], held["timeout"], held["plan"]) == ("10s", "5m", "would act")
    assert check["args"]["ref"] == "<$CTX.order_id from order-held>"
    assert check["plan"] == "runs with values known at run time"
    assert modes(marker) == ["plan", "plan"]


def test_exits_one_when_deny_refuses_start_plan(hub: Path, marker: Path) -> None:
    result = plan_hub(hub, marker, "live")

    assert result.exit_code == 1, result.output
    lines = plain(result.stdout).splitlines()
    assert lines[0] == "scenario: order-walk (environment live, access read, production)"
    assert lines[1] == (
        "send-order  action  demo/send-order  write"
        "  deny (live is a production environment: writes and destroys are denied)"
    )
    assert "order-held  expect  demo/get-order  read  allow" in lines
    assert plain(result.stderr).splitlines() == [
        "hub scenario plan: order-walk cannot start in live: a step is denied"
    ]
    assert "run" not in modes(marker)


def test_names_service_and_environment_when_service_input_has_no_endpoint(
    hub: Path, marker: Path
) -> None:
    scenario = hub / "scenarios" / "demo" / "order-walk.yaml"
    scenario.write_text(
        SCENARIO.replace(
            "with: {target: api, ref: $INPUTS.ref}\n  - id: order-held",
            "with: {target: orders, ref: $INPUTS.ref}\n  - id: order-held",
        )
    )

    result = plan_hub(hub, marker, "local")

    assert result.exit_code == 1, result.output
    assert plain(result.stderr).splitlines() == [
        "hub scenario plan: step send-order: input target: service orders has no endpoint"
        " in environment local",
    ]
    assert "  plan: not planned" in plain(result.stdout).splitlines()


def test_exits_one_when_unordered_gates_planned(hub: Path, marker: Path) -> None:
    scenario = hub / "scenarios" / "demo" / "order-walk.yaml"
    scenario.write_text(
        SCENARIO
        + "  - id: send-again\n    type: action\n    action: send-order\n    with: {target: api}\n"
    )

    result = plan_hub(hub, marker, "staging")

    assert result.exit_code == 1, result.output
    assert plain(result.stderr).splitlines()[0] == (
        "hub scenario plan: steps send-order and send-again both need a gate and have no order"
        " between them: one must depend on the other"
    )
    assert "run" not in modes(marker)


def test_exits_one_when_deny_refuses_start_plan_access_read(hub: Path, marker: Path) -> None:
    document = json.loads((hub / "hub.json").read_text())
    document["environments"]["review"] = {"access": "read"}
    endpoints = document["repos"][0]["services"]["api"]["endpoints"]
    endpoints["review"] = {"url": "https://api.review.example.com"}
    (hub / "hub.json").write_text(json.dumps(document, indent=2) + "\n")

    result = plan_hub(hub, marker, "review")

    assert result.exit_code == 1, result.output
    lines = plain(result.stdout).splitlines()
    assert lines[0] == "scenario: order-walk (environment review, access read)"
    assert lines[1] == (
        "send-order  action  demo/send-order  write"
        "  deny (access read in review does not allow write)"
    )
    assert "order-held  expect  demo/get-order  read  allow" in lines
    assert "check-order  action  demo/get-order  read  allow" in lines
    assert plain(result.stderr).splitlines() == [
        "hub scenario plan: order-walk cannot start in review: a step is denied"
    ]
    assert "run" not in modes(marker)


# hub scenario run (AC-350.4, .5, .8, .10, .18, .19, .42): regression mode only until T9.

RUN = "walk-1"
FAKE_CLAUDE = """#!/bin/sh
echo started > "$CLAUDE_MARKER"
"""


def run_scenario(
    hub: Path,
    marker: Path,
    environment: str,
    *extra: str,
    mode: str | None = "regression",
    env: dict[str, str] | None = None,
) -> Result:
    environ = {
        "AGENT_HUB_ROOT": str(hub),
        "MARKER": str(marker),
        "AGENT_HUB_DB": str(hub.parent.parent / "events.db"),
        **(env or {}),
    }
    args = ["scenario", "run", "order-walk", "--env", environment, "--input", "ref=T-1"]
    args += ["--run-id", RUN, *(["--mode", mode] if mode else []), *extra]
    return CliRunner().invoke(app, args, env=environ, input="")


def decide_gate(hub: Path, marker: Path, verb: str, *, gate: str) -> Result:
    return run_hub(hub, marker, "workflow", verb, RUN, gate)


def records(hub: Path) -> list[dict[str, Any]]:
    path = hub / ".agent-runs" / "workflows" / RUN / "records.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def stored(hub: Path) -> list[Event]:
    return open_event_store(hub.parent.parent / "events.db").read_all()


def commit_all(hub: Path, message: str) -> None:
    git(hub, "add", "-A")
    git(hub, "commit", "-q", "-m", message)


def a_fake_claude(tmp_path: Path) -> dict[str, str]:
    """A ``claude`` first on PATH that leaves a marker when started."""
    fakes = tmp_path / "bin"
    fakes.mkdir()
    (fakes / "claude").write_text(FAKE_CLAUDE)
    (fakes / "claude").chmod(0o755)
    path = f"{fakes}{os.pathsep}{os.environ.get('PATH', '')}"
    return {"PATH": path, "CLAUDE_MARKER": str(tmp_path / "claude-started")}


def test_refuses_start_when_environment_undeclared(hub: Path, marker: Path) -> None:
    result = run_scenario(hub, marker, "qa")

    assert result.exit_code == 1, result.output
    assert plain(result.stderr).splitlines() == [
        "hub scenario run: environment qa is not declared",
        "hub scenario run: order-walk cannot start in qa; no scenario run was created",
    ]
    assert not (hub / ".agent-runs").exists()
    assert modes(marker) == []
    assert not (hub.parent.parent / "events.db").exists()


def test_refuses_start_when_deny_refuses_start_run(hub: Path, marker: Path) -> None:
    result = run_scenario(hub, marker, "live")

    assert result.exit_code == 1, result.output
    assert plain(result.stderr).splitlines() == [
        "hub scenario run: step send-order: deny (live is a production environment:"
        " writes and destroys are denied)",
        "hub scenario run: order-walk cannot start in live; no scenario run was created",
    ]
    assert not (hub / ".agent-runs").exists()
    assert modes(marker) == []


def test_exits_two_when_no_gate_bypass_flag_given(hub: Path, marker: Path) -> None:
    for flag in ("--yes", "-y", "--auto-approve", "--skip-gates", "--no-gates", "--policy"):
        result = run_scenario(hub, marker, "staging", flag)

        assert result.exit_code == 2, (flag, result.output)
        assert f"No such option: {flag}" in plain(result.output), flag
    assert not (hub / ".agent-runs").exists()
    assert modes(marker) == []


@pytest.mark.xfail(
    strict=True,
    reason="release gate O-6 ended with AGH-360: interactive mode runs, so it no longer exits 2",
)
def test_exits_two_when_interactive_mode_asked(hub: Path, marker: Path) -> None:
    for mode in ("interactive", None):
        result = run_scenario(hub, marker, "local", mode=mode)

        assert result.exit_code == 2, (mode, result.output)
        assert "interactive mode is not available yet" in plain(result.output), mode
    assert not (hub / ".agent-runs").exists()
    assert modes(marker) == []


def test_creates_no_run_when_unordered_gates_run(hub: Path, marker: Path) -> None:
    scenario = hub / "scenarios" / "demo" / "order-walk.yaml"
    scenario.write_text(
        SCENARIO
        + "  - id: send-again\n    type: action\n    action: send-order\n    with: {target: api}\n"
    )

    result = run_scenario(hub, marker, "staging")

    assert result.exit_code == 1, result.output
    assert plain(result.stderr).splitlines()[0] == (
        "hub scenario run: steps send-order and send-again both need a gate and have no order"
        " between them: one must depend on the other"
    )
    assert not (hub / ".agent-runs").exists()
    assert modes(marker) == []


def test_fails_and_prints_step_when_regression_diverges(
    hub: Path, marker: Path, tmp_path: Path
) -> None:
    scenario = hub / "scenarios" / "demo" / "order-walk.yaml"
    scenario.write_text(
        SCENARIO.replace("every: 10s\n    timeout: 5m", "every: 5s\n    timeout: 5s").replace(
            "status == 'ON_HOLD'", "status == 'PROCESSING_COMPLETED'"
        )
    )
    claude = a_fake_claude(tmp_path)

    result = run_scenario(hub, marker, "local", env=claude)

    assert result.exit_code == 1, result.output
    assert plain(result.stdout).splitlines()[-2:] == [
        f"run {RUN}: failed",
        "step order-held: timeout: expect_timeout: until_when did not hold in 5s (1 polls)",
    ]
    assert not Path(claude["CLAUDE_MARKER"]).exists()
    assert modes(marker) == ["run", "run"]
    lines = records(hub)
    assert lines[0]["workflow"] == "scenario:order-walk"
    assert [line["status"] for line in lines if line["event"] == "end"] == ["failed"]
    polls = [line for line in lines if line["event"] == "expect.poll"]
    assert [(p["node"], p["poll"], p["held"]) for p in polls] == [("order-held", 1, False)]
    events = stored(hub)
    assert {event.workflow for event in events} == {"scenario:order-walk"}
    kinds = [event.type for event in events]
    assert kinds.count("policy.decision") == 2
    assert kinds.count("expect.poll") == 1
    ended = [event for event in events if event.type == "run.end"]
    assert [event.payload["status"] for event in ended] == ["failed"]


def test_pauses_at_gate_when_regression_step_asks(hub: Path, marker: Path) -> None:
    result = run_scenario(hub, marker, "staging")

    assert result.exit_code == 0, result.output
    assert plain(result.stdout).splitlines()[-1] == f"run {RUN}: paused at send-order__ask"
    assert modes(marker) == []
    start, *rest = records(hub)
    assert {key: start[key] for key in ("kind", "workflow", "environment", "mode")} == {
        "kind": "scenario",
        "workflow": "scenario:order-walk",
        "environment": "staging",
        "mode": "regression",
    }
    assert start["policy_gates"] == ["send-order"]
    gates = [line for line in rest if line["event"] == "gate"]
    assert [(gate["node"], gate["form"], gate["choices"]) for gate in gates] == [
        ("send-order__ask", "decision", ["approve", "reject"])
    ]
    requested = [event for event in stored(hub) if event.type == "gate.request"]
    assert [(event.workflow, event.payload["name"]) for event in requested] == [
        ("scenario:order-walk", "send-order__ask")
    ]


TWO_WRITES = SCENARIO + (
    "  - id: send-again\n    type: action\n    depends_on: [check-order]\n"
    "    action: send-order\n    with: {target: api, ref: $CTX.order_id}\n"
)


def test_opens_gate_per_write_when_no_gate_bypass_access_ask(hub: Path, marker: Path) -> None:
    (hub / "scenarios" / "demo" / "order-walk.yaml").write_text(TWO_WRITES)

    started = run_scenario(hub, marker, "staging")
    first = decide_gate(hub, marker, "approve", gate="send-order__ask")
    second = decide_gate(hub, marker, "approve", gate="send-again__ask")

    assert plain(started.stdout).splitlines()[-1] == f"run {RUN}: paused at send-order__ask"
    assert first.exit_code == 0, first.output
    assert plain(first.stdout).splitlines()[-1] == f"run {RUN}: paused at send-again__ask"
    assert second.exit_code == 0, second.output
    assert plain(second.stdout).splitlines()[-1] == f"run {RUN}: done"
    gates = [line["node"] for line in records(hub) if line["event"] == "gate"]
    assert gates == ["send-order__ask", "send-again__ask"]
    assert modes(marker) == ["run", "run", "run", "run"]
    started_actions = [event for event in stored(hub) if event.type == "action.start"]
    approvers = {event.step: event.payload.get("approver") for event in started_actions}
    assert approvers["send-order"] is not None
    assert approvers["send-again"] is not None
    assert approvers["order-held"] is None


def test_passes_endpoint_when_service_input_resolved(hub: Path, marker: Path) -> None:
    result = run_scenario(hub, marker, "local")

    assert result.exit_code == 0, result.output
    assert plain(result.stdout).splitlines()[-1] == f"run {RUN}: done"
    calls = [json.loads(line) for line in marker.read_text().splitlines()]
    assert [call["mode"] for call in calls] == ["run", "run", "run"]
    endpoint = {"target": {"url": "http://localhost:8000", "resource": None}}
    assert [call["endpoint"] for call in calls] == [endpoint] * 3
    assert calls[0]["inputs"] == {"target": "api", "ref": "T-1", "count": 1}
    # check-order's ref is the order id order-held captured.
    assert calls[2]["inputs"] == {"target": "api", "ref": "o-1", "count": 1}
    started = [event for event in stored(hub) if event.type == "action.start"]
    assert {event.payload["service"][0] for event in started} == {"demo-api/api"}


def test_resumes_scenario_when_policy_gate_approved(hub: Path, marker: Path) -> None:
    paused = run_scenario(hub, marker, "staging")

    resumed = decide_gate(hub, marker, "approve", gate="send-order__ask")

    assert paused.exit_code == 0, paused.output
    assert resumed.exit_code == 0, resumed.output
    assert plain(resumed.stdout).splitlines()[-1] == f"run {RUN}: done"
    assert modes(marker) == ["run", "run", "run"]
    lines = records(hub)
    assert [line["event"] for line in lines if line["event"] in ("decision", "resume")] == [
        "decision",
        "resume",
    ]
    assert [line["status"] for line in lines if line["event"] == "end"] == ["done"]
    assert [line["name"] for line in lines if line["event"] == "context.capture"] == ["order_id"]
    ends = [event for event in stored(hub) if event.type == "run.end"]
    assert [(event.workflow, event.payload["status"]) for event in ends] == [
        ("scenario:order-walk", "done")
    ]


def test_ends_cancelled_when_policy_gate_rejected(hub: Path, marker: Path) -> None:
    run_scenario(hub, marker, "staging")

    rejected = decide_gate(hub, marker, "reject", gate="send-order__ask")

    assert rejected.exit_code == 1, rejected.output
    assert plain(rejected.stdout).splitlines()[-1] == f"run {RUN}: cancelled"
    assert modes(marker) == []


EDITED_SCRIPT = """\
cat > /dev/null
echo edited >> "$MARKER"
printf '{"order": "o-9"}'
"""


def test_keeps_action_content_hash_when_action_edited_during_run(hub: Path, marker: Path) -> None:
    pinned = content_hash(hub, "send-order")
    run_scenario(hub, marker, "staging")
    (hub / "actions" / "demo" / "scripts" / "send-order.sh").write_text(EDITED_SCRIPT)
    commit_all(hub, "edit send-order")

    resumed = decide_gate(hub, marker, "approve", gate="send-order__ask")

    assert resumed.exit_code == 0, resumed.output
    assert content_hash(hub, "send-order") != pinned
    assert "edited" not in marker.read_text()
    assert modes(marker) == ["run", "run", "run"]
    assert records(hub)[0]["actions"]["demo/send-order"] == pinned
    sent = [
        event.payload["content_hash"]
        for event in stored(hub)
        if event.type == "action.start" and event.step == "send-order"
    ]
    assert sent == [pinned]


def test_copies_only_pinned_files_when_action_content_hash_pinned(hub: Path, marker: Path) -> None:
    scripts = hub / "actions" / "demo" / "scripts"
    (scripts / "lib.sh").write_text("helper=1\n")
    (scripts / ".notes").write_text("not a helper\n")
    (scripts / "__pycache__").mkdir()
    (scripts / "__pycache__" / "x.pyc").write_bytes(b"cache")
    write_action(hub, "unused-order", "read")
    commit_all(hub, "more files")

    result = run_scenario(hub, marker, "staging")

    assert result.exit_code == 0, result.output
    snapshot = hub / ".agent-runs" / "workflows" / RUN / "snapshot"
    copied = sorted(
        path.relative_to(snapshot).as_posix()
        for path in (snapshot / "actions").rglob("*")
        if path.is_file()
    )
    assert copied == [
        "actions/demo/get-order.yaml",
        "actions/demo/scripts/get-order.sh",
        "actions/demo/scripts/lib.sh",
        "actions/demo/scripts/send-order.sh",
        "actions/demo/send-order.yaml",
    ]
    pins = records(hub)[0]["actions"]
    assert pins == {
        "demo/get-order": content_hash(hub, "get-order"),
        "demo/send-order": content_hash(hub, "send-order"),
    }


CONFIRMED = SCENARIO.replace(
    "  - id: send-order\n    type: action\n",
    "  - id: confirm\n    type: approval\n    message: Send the demo order?\n"
    "  - id: send-order\n    type: action\n    depends_on: [confirm]\n",
)


def set_access(hub: Path, environment: str, access: str) -> None:
    document = json.loads((hub / "hub.json").read_text())
    document["environments"][environment]["access"] = access
    (hub / "hub.json").write_text(json.dumps(document, indent=2) + "\n")


def test_fails_step_when_regression_policy_denies_at_resume(hub: Path, marker: Path) -> None:
    (hub / "scenarios" / "demo" / "order-walk.yaml").write_text(CONFIRMED)
    paused = run_scenario(hub, marker, "local")
    set_access(hub, "local", "read")

    resumed = decide_gate(hub, marker, "approve", gate="confirm")

    assert plain(paused.stdout).splitlines()[-1] == f"run {RUN}: paused at confirm"
    assert resumed.exit_code == 1, resumed.output
    assert plain(resumed.stdout).splitlines()[-1] == (
        "step send-order: config: the policy denies demo/send-order (write) in local:"
        " access read in local does not allow write"
    )
    assert modes(marker) == []
    decided = [event for event in stored(hub) if event.type == "policy.decision"]
    assert [(event.step, event.payload["decision"]) for event in decided] == [
        ("send-order", "deny")
    ]


def test_fails_step_when_regression_policy_asks_without_gate_at_resume(
    hub: Path, marker: Path
) -> None:
    (hub / "scenarios" / "demo" / "order-walk.yaml").write_text(CONFIRMED)
    run_scenario(hub, marker, "local")
    set_access(hub, "local", "ask")

    resumed = decide_gate(hub, marker, "approve", gate="confirm")

    assert resumed.exit_code == 1, resumed.output
    assert plain(resumed.stdout).splitlines()[-1] == (
        "step send-order: config: the policy now asks before demo/send-order (write) in local"
        " and this scenario run has no gate for it: start a new scenario run"
    )
    assert modes(marker) == []


def hub_process(hub: Path, marker: Path, *args: str) -> subprocess.Popen[bytes]:
    """The hub as its own process (``python -m agent_hub.cli``), to be signalled or killed."""
    environ = {
        **os.environ,
        "AGENT_HUB_ROOT": str(hub),
        "MARKER": str(marker),
        "AGENT_HUB_DB": str(hub.parent.parent / "events.db"),
    }
    command = [sys.executable, "-m", "agent_hub.cli", *args]
    return subprocess.Popen(  # noqa: S603 - this interpreter, fixed arguments
        command, env=environ, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )


def live_members(group: int) -> list[int]:
    """The processes of ``group`` that are not zombies, read from ``/proc``."""
    members = []
    for stat in Path("/proc").glob("[0-9]*/stat"):
        try:
            fields = stat.read_text().rsplit(")", 1)[1].split()
        except OSError:
            continue
        if int(fields[2]) == group and fields[0] != "Z":
            members.append(int(stat.parent.name))
    return members


SLOW_SCRIPT = """\
cat > /dev/null
echo $$ >> "$MARKER.groups"
sleep 4
echo late >> "$MARKER.late"
printf '{"order": "o-1"}'
"""
SLOW_WALK = """\
version: 1
kind: scenario
name: slow-walk
revision: 1
nodes:
  - id: slow-a
    type: action
    action: slow-order
    with: {target: api}
  - id: slow-b
    type: action
    action: slow-order
    with: {target: api}
"""


@pytest.mark.skipif(not Path("/proc/self/stat").exists(), reason="reads /proc")
def test_kills_action_groups_when_regression_run_interrupted(hub: Path, marker: Path) -> None:
    write_action(hub, "slow-order", "read")
    (hub / "actions" / "demo" / "scripts" / "slow-order.sh").write_text(SLOW_SCRIPT)
    write_scenario(hub, SLOW_WALK)
    commit_all(hub, "slow walk")
    groups_file = Path(f"{marker}.groups")

    process = hub_process(
        hub, marker, "scenario", "run", "slow-walk", "--env", "local", "--mode", "regression"
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and len(_lines(groups_file)) < 2:
        time.sleep(0.05)
    process.send_signal(signal.SIGINT)
    process.communicate(timeout=30)

    groups = [int(line) for line in _lines(groups_file)]
    assert len(groups) == 2
    assert all(live_members(group) == [] for group in groups)


def _lines(path: Path) -> list[str]:
    return path.read_text().splitlines() if path.exists() else []


def test_refuses_resume_when_pinned_action_tampered(hub: Path, marker: Path) -> None:
    run_scenario(hub, marker, "staging")
    folder = hub / ".agent-runs" / "workflows" / RUN
    script = folder / "snapshot" / "actions" / "demo" / "scripts" / "send-order.sh"
    script.write_text(EDITED_SCRIPT)
    lines = records(hub)
    lines[0]["content_hash"] = snapshot_hash(folder / "snapshot")
    (folder / "records.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))

    resumed = decide_gate(hub, marker, "approve", gate="send-order__ask")

    assert resumed.exit_code == 1, resumed.output
    assert "no longer holds demo/send-order as pinned" in plain(resumed.stderr)
    assert not marker.exists()


def test_refuses_resume_when_policy_gates_edited(hub: Path, marker: Path) -> None:
    run_scenario(hub, marker, "staging")
    gates = hub / ".agent-runs" / "workflows" / RUN / "snapshot" / "policy_gates.json"
    gates.write_text("{}")

    resumed = decide_gate(hub, marker, "approve", gate="send-order__ask")

    assert resumed.exit_code == 1, resumed.output
    assert "snapshot no longer matches" in plain(resumed.stderr)
    assert not marker.exists()


CRASH_ONCE = """\
stdin=$(cat)
printf '%s\\n' "$stdin" >> "$MARKER"
if [ ! -e "$MARKER.crashed" ]; then
  touch "$MARKER.crashed"
  kill -9 $PPID
  sleep 5
fi
printf '{"order": "o-1", "status": "ON_HOLD"}'
"""


def crash_once(hub: Path, marker: Path, action: str) -> None:
    """Run order-walk in ``local`` in its own process; ``action``'s first call kills it."""
    (hub / "actions" / "demo" / "scripts" / f"{action}.sh").write_text(CRASH_ONCE)
    commit_all(hub, f"{action} crashes once")
    process = hub_process(
        hub,
        marker,
        *("scenario", "run", "order-walk", "--env", "local", "--input", "ref=T-1"),
        *("--mode", "regression", "--run-id", RUN),
    )
    process.communicate(timeout=60)
    assert process.returncode == -signal.SIGKILL


def test_asks_again_when_write_step_started_and_never_ended(hub: Path, marker: Path) -> None:
    crash_once(hub, marker, "send-order")

    resumed = run_hub(hub, marker, "workflow", "run", "--resume", RUN)
    approved = decide_gate(hub, marker, "approve", gate="send-order__ask")

    assert resumed.exit_code == 0, resumed.output
    assert plain(resumed.stdout).splitlines()[-1] == f"run {RUN}: paused at send-order__ask"
    # The write ran once before the crash, and again only once a person approved it.
    assert modes(marker) == ["run", "run", "run", "run"]
    gates = [line for line in records(hub) if line["event"] == "gate"]
    assert [gate["node"] for gate in gates] == ["send-order__ask"]
    assert "may have run" in gates[0]["message"]
    assert approved.exit_code == 0, approved.output
    assert plain(approved.stdout).splitlines()[-1] == f"run {RUN}: done"


def test_reruns_read_when_read_step_started_and_never_ended(hub: Path, marker: Path) -> None:
    crash_once(hub, marker, "get-order")

    resumed = run_hub(hub, marker, "workflow", "run", "--resume", RUN)

    assert resumed.exit_code == 0, resumed.output
    assert plain(resumed.stdout).splitlines()[-1] == f"run {RUN}: done"
    assert [line for line in records(hub) if line["event"] == "gate"] == []
    # send-order once, the crashed get-order poll, then the poll again and check-order.
    assert modes(marker) == ["run", "run", "run", "run"]


COUNTED_CRASH = """\
cat > /dev/null
n=$(cat "$MARKER.count" 2>/dev/null || echo 0)
n=$((n+1))
echo $n > "$MARKER.count"
echo "call$n" >> "$MARKER.calls"
if [ "$n" = 2 ]; then
  kill -9 $PPID
  sleep 5
fi
printf '{"order": "o-%s"}' "$n"
"""
LOOPED = """\
version: 1
kind: scenario
name: order-walk
revision: 1
inputs:
  ref: {type: string, required: true}
nodes:
  - id: batch
    type: loop_group
    max_iterations: 2
    until_when: "$send.output.order == 'o-4'"
    nodes:
      - id: send
        type: action
        action: send-order
        with: {target: api, ref: $INPUTS.ref}
"""


def crash_in_loop(hub: Path, marker: Path) -> None:
    """Run ``LOOPED`` in ``local`` (access write) in its own process: the body's write runs
    once, then its second call (iteration 2) kills the hub."""
    (hub / "scenarios" / "demo" / "order-walk.yaml").write_text(LOOPED)
    (hub / "actions" / "demo" / "scripts" / "send-order.sh").write_text(COUNTED_CRASH)
    commit_all(hub, "a looped write that crashes once")
    process = hub_process(
        hub,
        marker,
        *("scenario", "run", "order-walk", "--env", "local", "--input", "ref=T-1"),
        *("--mode", "regression", "--run-id", RUN),
    )
    process.communicate(timeout=60)
    assert process.returncode == -signal.SIGKILL
    assert _lines(Path(f"{marker}.calls")) == ["call1", "call2"]


def test_cancels_when_loop_rerun_write_rejected_after_crash(hub: Path, marker: Path) -> None:
    crash_in_loop(hub, marker)

    resumed = run_hub(hub, marker, "workflow", "run", "--resume", RUN)
    approved = decide_gate(hub, marker, "approve", gate="batch__send__ask")
    rejected = decide_gate(hub, marker, "reject", gate="batch__send__ask")

    assert plain(resumed.stdout).splitlines()[-1] == f"run {RUN}: paused at batch__send__ask"
    # The group starts again from its first iteration: each write in it asks first.
    assert plain(approved.stdout).splitlines()[-1] == f"run {RUN}: paused at batch__send__ask"
    assert rejected.exit_code == 1, rejected.output
    assert plain(rejected.stdout).splitlines()[-1] == f"run {RUN}: cancelled"
    assert _lines(Path(f"{marker}.calls")) == ["call1", "call2", "call3"]
    assert [line["status"] for line in records(hub) if line["event"] == "end"] == ["cancelled"]
    resumed_again = run_hub(hub, marker, "workflow", "run", "--resume", RUN)
    assert resumed_again.exit_code == 1
    assert _lines(Path(f"{marker}.calls")) == ["call1", "call2", "call3"]


def test_asks_before_each_loop_rerun_write_when_approved_after_crash(
    hub: Path, marker: Path
) -> None:
    crash_in_loop(hub, marker)

    resumed = run_hub(hub, marker, "workflow", "run", "--resume", RUN)
    first = decide_gate(hub, marker, "approve", gate="batch__send__ask")
    second = decide_gate(hub, marker, "approve", gate="batch__send__ask")

    assert plain(resumed.stdout).splitlines()[-1] == f"run {RUN}: paused at batch__send__ask"
    assert plain(first.stdout).splitlines()[-1] == f"run {RUN}: paused at batch__send__ask"
    assert second.exit_code == 0, second.output
    assert plain(second.stdout).splitlines()[-1] == f"run {RUN}: done"
    assert _lines(Path(f"{marker}.calls")) == ["call1", "call2", "call3", "call4"]
    lines = records(hub)
    resumed_at = next(i for i, line in enumerate(lines) if line["event"] == "resume")
    later = lines[resumed_at:]
    gates = [line for line in later if line["event"] == "gate"]
    assert len(gates) == 2
    assert all("may have run" in gate["message"] for gate in gates)
    # Every write the rerun made came after a decision of its own.
    seen = [line["event"] for line in later if line["event"] in ("decision", "action_start")]
    assert seen == ["decision", "action_start", "decision", "action_start"]


def test_leaves_no_run_folder_when_snapshot_write_fails(
    hub: Path, marker: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        msg = "no space left"
        raise RuntimeError(msg)

    monkeypatch.setattr("agent_hub.cli.scenario_runs.snapshot_run", broken)

    result = run_scenario(hub, marker, "local")

    assert result.exit_code != 0
    assert not (hub / ".agent-runs" / "workflows" / RUN).exists()
    assert modes(marker) == []


# AGH-359 (F2): only a gate the run's record names as a policy gate cancels on a reject; an
# authored body approval recorded ``<group>__ask`` is read like any approval.

AUTHORED_ASK_SCENARIO = """\
version: 1
kind: scenario
name: order-walk
revision: 1
inputs:
  ref: {type: string, required: true}
nodes:
  - id: g
    type: loop_group
    max_iterations: 2
    until_when: "$ask.output.decision == 'reject'"
    nodes:
      - id: ask
        type: approval
        message: Stop looping?
  - id: check-order
    type: action
    depends_on: [g]
    action: get-order
    with: {target: api, ref: $INPUTS.ref}
"""


def test_reads_reject_when_authored_body_approval_named_ask_rejected(
    hub: Path, marker: Path
) -> None:
    write_scenario(hub, AUTHORED_ASK_SCENARIO)

    paused = run_scenario(hub, marker, "local")
    rejected = decide_gate(hub, marker, "reject", gate="g__ask")

    assert plain(paused.stdout).splitlines()[-1] == f"run {RUN}: paused at g__ask"
    assert rejected.exit_code == 0, rejected.output
    assert plain(rejected.stdout).splitlines()[-1] == f"run {RUN}: done"
    assert modes(marker) == ["run"]


# AGH-359 (owner decisions A to C): a process workflow's action nodes, decided like a
# scenario's, its nodes' decisions as policy.decision events, and its until_bash as a read.

FLOW = """\
version: 1
name: ship-flow
revision: 1
environment: {env}
nodes:
  - id: look
    type: shell
    command: [sh, -c, "exit 0"]
    effect: read
  - id: send
    type: action
    action: send-order
    depends_on: [look]
    with: {{target: api, ref: T-1}}
"""


def write_flow(hub: Path, text: str) -> None:
    path = hub / "workflows" / "demo" / "ship-flow.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def run_flow(hub: Path, marker: Path, *extra: str) -> Result:
    args = ("workflow", "run", "ship-flow", "--live", "--run-id", RUN, *extra)
    return run_hub(hub, marker, *args)


def decisions(hub: Path) -> set[tuple[Any, ...]]:
    return {
        (
            event.step,
            event.payload.get("node"),
            event.payload.get("action"),
            event.payload["effect"],
            event.payload["decision"],
            event.payload["reason_kind"],
            event.payload["attempt"],
        )
        for event in stored(hub)
        if event.type == "policy.decision"
    }


def test_runs_action_node_when_workflow_environment_allows_it(hub: Path, marker: Path) -> None:
    write_flow(hub, FLOW.format(env="local"))

    result = run_flow(hub, marker)

    assert result.exit_code == 0, result.output
    assert plain(result.stdout).splitlines()[-1] == f"run {RUN}: done"
    assert modes(marker) == ["run"]
    assert '"endpoint": {"target": {"url": "http://localhost:8000"' in marker.read_text()
    assert records(hub)[0]["actions"] == {"demo/send-order": content_hash(hub, "send-order")}
    started = [event for event in stored(hub) if event.type == "action.start"]
    assert [(event.step, event.workflow) for event in started] == [("send", "ship-flow")]
    assert decisions(hub) == {
        ("look", "look", None, "read", "allow", "table", 0),
        ("send", None, "demo/send-order", "write", "allow", "table", 0),
        ("look", "look", None, "read", "allow", "table", 1),
        ("send", None, "demo/send-order", "write", "allow", "table", 1),
    }


def test_opens_gate_when_workflow_environment_asks_for_action(hub: Path, marker: Path) -> None:
    write_flow(hub, FLOW.format(env="staging"))

    paused = run_flow(hub, marker)
    approved = decide_gate(hub, marker, "approve", gate="send__ask")

    assert plain(paused.stdout).splitlines()[-1] == f"run {RUN}: paused at send__ask"
    assert approved.exit_code == 0, approved.output
    assert plain(approved.stdout).splitlines()[-1] == f"run {RUN}: done"
    assert modes(marker) == ["run"]


def test_refuses_start_when_workflow_environment_denies_action(hub: Path, marker: Path) -> None:
    write_flow(hub, FLOW.format(env="live"))

    result = run_flow(hub, marker)

    assert result.exit_code == 1, result.output
    assert plain(result.stderr).splitlines() == [
        "hub workflow run: step send: deny (live is a production environment: writes and"
        " destroys are denied)"
    ]
    assert not (hub / ".agent-runs" / "workflows" / RUN).exists()
    assert not marker.exists()
    assert ("send", None, "demo/send-order", "write", "deny", "production", 0) in decisions(hub)


def test_keeps_action_content_hash_when_workflow_environment_action_edited(
    hub: Path, marker: Path
) -> None:
    pinned = content_hash(hub, "send-order")
    write_flow(hub, FLOW.format(env="staging"))
    run_flow(hub, marker)
    (hub / "actions" / "demo" / "scripts" / "send-order.sh").write_text(EDITED_SCRIPT)
    commit_all(hub, "edit send-order")

    approved = decide_gate(hub, marker, "approve", gate="send__ask")

    assert approved.exit_code == 0, approved.output
    assert "edited" not in marker.read_text()
    assert records(hub)[0]["actions"]["demo/send-order"] == pinned
    sent = [event.payload["content_hash"] for event in stored(hub) if event.type == "action.start"]
    assert sent == [pinned]


def test_refuses_start_when_action_node_has_no_workflow_environment(
    hub: Path, marker: Path
) -> None:
    write_flow(hub, FLOW.format(env="local").replace("environment: local\n", ""))

    result = run_flow(hub, marker)
    dry = run_hub(hub, marker, "workflow", "run", "ship-flow")

    assert result.exit_code == 1, result.output
    assert plain(result.stderr).splitlines() == [
        "hub workflow run: step send is an action node: actions run only in an environment;"
        " declare environment in ship-flow or give --env"
    ]
    assert (dry.exit_code, plain(dry.stderr)) == (1, plain(result.stderr))
    assert not (hub / ".agent-runs" / "workflows" / RUN).exists()
    assert run_flow(hub, marker, "--env", "local").exit_code == 0


UNTIL_FLOW = """\
version: 1
name: ship-flow
revision: 1
environment: {env}
inputs:
  go: {{type: boolean, default: false}}
nodes:
  - id: hold
    type: approval
    message: Go?
  - id: g
    type: loop_group
    depends_on: [hold]
    max_iterations: 1
    until_bash: [sh, -c, "echo until >> \\"$MARKER\\""]
    nodes:
      - id: look
        type: shell
        command: [sh, -c, "exit 0"]
        effect: read
        when: "$INPUTS.go == true"
"""


def test_runs_until_bash_as_read_when_workflow_environment_read(hub: Path, marker: Path) -> None:
    write_flow(hub, UNTIL_FLOW.format(env="live"))
    run_flow(hub, marker)

    approved = decide_gate(hub, marker, "approve", gate="hold")

    assert approved.exit_code == 0, approved.output
    assert plain(approved.stdout).splitlines()[-1] == f"run {RUN}: done"
    assert marker.read_text() == "until\n"
    assert ("g", "g", None, "read", "allow", "table", 0) in decisions(hub)
    assert ("g", "g", None, "read", "allow", "table", 1) in decisions(hub)


def test_fails_until_bash_when_workflow_environment_removed_before_it_runs(
    hub: Path, marker: Path
) -> None:
    write_flow(hub, UNTIL_FLOW.format(env="local"))
    run_flow(hub, marker)
    document = json.loads((hub / "hub.json").read_text())
    del document["environments"]["local"]
    del document["repos"][0]["services"]["api"]["endpoints"]["local"]
    (hub / "hub.json").write_text(json.dumps(document, indent=2) + "\n")

    approved = decide_gate(hub, marker, "approve", gate="hold")

    assert approved.exit_code == 1, approved.output
    assert plain(approved.stdout).splitlines()[-1] == f"run {RUN}: failed"
    [end] = [r for r in records(hub) if r["event"] == "step_end" and r["node"] == "g"]
    assert end["failure_kind"] == "config"
    assert "until_bash" in end["detail"]
    assert "environment local is not declared" in end["detail"]
    assert not marker.exists()


SLOW_FLOW = """\
version: 1
name: ship-flow
revision: 1
environment: local
nodes:
  - id: slow-a
    type: action
    action: slow-order
    with: {target: api}
  - id: slow-b
    type: script
    runtime: sh
    script: slow.sh
    effect: read
"""
SLOW_NODE = """\
echo $$ >> "$MARKER.groups"
sleep 4
echo late >> "$MARKER.late"
"""


@pytest.mark.skipif(not Path("/proc/self/stat").exists(), reason="reads /proc")
def test_kills_child_groups_when_workflow_environment_run_interrupted(
    hub: Path, marker: Path
) -> None:
    write_action(hub, "slow-order", "read")
    (hub / "actions" / "demo" / "scripts" / "slow-order.sh").write_text(SLOW_SCRIPT)
    commit_all(hub, "slow order")
    write_flow(hub, SLOW_FLOW)
    (hub / "workflows" / "demo" / "scripts").mkdir()
    (hub / "workflows" / "demo" / "scripts" / "slow.sh").write_text(SLOW_NODE)
    groups_file = Path(f"{marker}.groups")
    os.mkfifo(groups_file)
    # Read and write: the reader never sees an end of file between the two children.
    reader = os.open(groups_file, os.O_RDWR | os.O_NONBLOCK)

    process = hub_process(hub, marker, "workflow", "run", "ship-flow", "--live", "--run-id", RUN)
    groups: list[int] = []
    pending = b""
    poller = select.poll()
    poller.register(reader, select.POLLIN)
    while len(groups) < 2 and poller.poll(30_000):
        pending += os.read(reader, 64)
        *done, pending = pending.split(b"\n")
        groups += [int(line) for line in done]
    process.send_signal(signal.SIGINT)
    process.communicate(timeout=30)
    os.close(reader)

    assert len(groups) == 2
    assert all(live_members(group) == [] for group in groups)
    assert not Path(f"{marker}.late").exists()


def test_asks_again_when_workflow_environment_action_write_never_ended(
    hub: Path, marker: Path
) -> None:
    (hub / "actions" / "demo" / "scripts" / "send-order.sh").write_text(CRASH_ONCE)
    commit_all(hub, "send-order crashes once")
    write_flow(hub, FLOW.format(env="local"))
    process = hub_process(hub, marker, "workflow", "run", "ship-flow", "--live", "--run-id", RUN)
    process.communicate(timeout=60)

    resumed = run_hub(hub, marker, "workflow", "run", "--resume", RUN)
    approved = decide_gate(hub, marker, "approve", gate="send__ask")

    assert process.returncode == -signal.SIGKILL
    assert plain(resumed.stdout).splitlines()[-1] == f"run {RUN}: paused at send__ask"
    [gate] = [line for line in records(hub) if line["event"] == "gate"]
    assert "may have run" in gate["message"]
    assert plain(approved.stdout).splitlines()[-1] == f"run {RUN}: done"
    assert modes(marker) == ["run", "run"]


# AGH-359 (R2-F1): the same in a scenario run: an owed group's id is never a policy gate.

GROUP_OWED_SCENARIO = """\
version: 1
kind: scenario
name: order-walk
revision: 1
inputs:
  ref: {type: string, required: true}
nodes:
  - id: g
    type: loop_group
    max_iterations: 3
    until_when: "$ask.output.decision == 'reject'"
    nodes:
      - id: send-order
        type: action
        action: send-order
        with: {target: api, ref: $INPUTS.ref}
      - id: ask
        type: approval
        message: Stop looping?
        depends_on: [send-order]
"""


def test_reads_body_reject_when_owed_group_holds_approval_named_ask(
    hub: Path, marker: Path
) -> None:
    write_scenario(hub, GROUP_OWED_SCENARIO)
    crash_once(hub, marker, "send-order")

    resumed = run_hub(hub, marker, "workflow", "run", "--resume", RUN)
    approved = decide_gate(hub, marker, "approve", gate="g__send-order__ask")
    rejected = decide_gate(hub, marker, "reject", gate="g__ask")

    assert plain(resumed.stdout).splitlines()[-1] == f"run {RUN}: paused at g__send-order__ask"
    assert plain(approved.stdout).splitlines()[-1] == f"run {RUN}: paused at g__ask"
    assert rejected.exit_code == 0, rejected.output
    assert plain(rejected.stdout).splitlines()[-1] == f"run {RUN}: done"


def test_marks_start_decisions_when_workflow_environment_run_starts(
    hub: Path, marker: Path
) -> None:
    write_flow(hub, FLOW.format(env="local"))

    run_flow(hub, marker)

    sources = sorted(
        event.source_id
        for event in stored(hub)
        if event.type == "policy.decision" and event.payload["attempt"] == 0
    )
    assert sources == [
        f"{RUN}:look:0:policy.decision:start",
        f"{RUN}:send:0:policy.decision:start",
    ]


# AGH-360: interactive mode, the investigation and its answers (AC-350.20 to .23).
# ``hold-walk`` has one read step, ``order-held``, whose action fails until the file ``HELD``
# names exists; the write ``release-hold`` creates it. No claude starts (the fake records none).

HELD_SCRIPT = """\
stdin=$(cat)
printf '%s\\n' "$stdin" >> "$MARKER"
if [ ! -e "$HELD" ]; then
  echo "order on hold" >&2
  exit 3
fi
printf '{"order": "o-1", "status": "ON_HOLD"}'
"""
RELEASE_SCRIPT = """\
stdin=$(cat)
printf '%s\\n' "$stdin" >> "$MARKER"
touch "$HELD"
printf '{"order": "o-1"}'
"""
HOLD_WALK = """\
version: 1
kind: scenario
name: hold-walk
revision: 1
nodes:
  - id: order-held
    type: action
    action: held-order
    with: {target: api}
"""
GATE = "order-held__investigation"
PAUSED = f"run {RUN}: paused at order-held (investigation): open /scenarios/hold-walk/runs/{RUN}"


def write_script_action(hub: Path, name: str, *, effect: str, script: str) -> None:
    write_action(hub, name, effect)
    (hub / "actions" / "demo" / "scripts" / f"{name}.sh").write_text(script)


@pytest.fixture
def held(hub: Path, tmp_path: Path) -> Path:
    """``hub`` with ``hold-walk`` and its actions, committed; the file that releases the hold."""
    write_script_action(hub, "held-order", effect="read", script=HELD_SCRIPT)
    write_script_action(hub, "release-hold", effect="write", script=RELEASE_SCRIPT)
    write_scenario(hub, HOLD_WALK)
    commit_all(hub, "hold walk")
    return tmp_path / "released"


def hold_call(hub: Path, marker: Path, held: Path, *args: str, stdin: str = "") -> Result:
    environ = {
        "AGENT_HUB_ROOT": str(hub),
        "MARKER": str(marker),
        "HELD": str(held),
        "AGENT_HUB_DB": str(hub.parent.parent / "events.db"),
        **a_fake_claude_env(hub),
    }
    return CliRunner().invoke(app, list(args), env=environ, input=stdin)


def a_fake_claude_env(hub: Path) -> dict[str, str]:
    """A ``claude`` first on PATH that leaves a marker when started (made once per hub)."""
    fakes = hub.parent.parent / "bin"
    if not fakes.exists():
        fakes.mkdir()
        (fakes / "claude").write_text(FAKE_CLAUDE)
        (fakes / "claude").chmod(0o755)
    path = f"{fakes}{os.pathsep}{os.environ.get('PATH', '')}"
    return {"PATH": path, "CLAUDE_MARKER": str(hub.parent.parent / "claude-started")}


def hold_walk(hub: Path, marker: Path, held: Path, *, environment: str = "local") -> Result:
    args = ("scenario", "run", "hold-walk", "--env", environment, "--run-id", RUN)
    return hold_call(hub, marker, held, *args)


def respond(hub: Path, marker: Path, held: Path, *answer: str) -> Result:
    """``respond`` on the investigation gate: a choice, then its text (an option id) if any."""
    choice, *text = answer
    args = ("workflow", "respond", RUN, "--node", GATE, "--choice", choice)
    return hold_call(hub, marker, held, *args, *(("--text", *text) if text else ()))


def propose(hub: Path, marker: Path, held: Path, *, proposal: dict[str, Any]) -> Result:
    args = ("scenario", "propose", "--run", RUN)
    return hold_call(hub, marker, held, *args, stdin=json.dumps(proposal))


def a_proposal(*options: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "findings": [
            {"title": "Order stays on hold", "text": "The hold flag is set.", "evidence": "x"},
            {"title": "Queue is slow", "text": "It drains in minutes."},
        ],
        "options": [
            {"summary": f"Option {index}", "steps": steps} for index, steps in enumerate(options, 1)
        ],
    }


RELEASE = [{"action": "release-hold", "with": {"target": "api"}}]
LOOK = [{"action": "demo/held-order", "with": {"target": "api"}}]


def test_pauses_with_investigation_gate_when_interactive_diverges(
    hub: Path, marker: Path, held: Path
) -> None:
    result = hold_walk(hub, marker, held)

    assert result.exit_code == 0, result.output
    lines = plain(result.stdout).splitlines()
    assert lines[-1] == f"{PAUSED} in hub web (./hub web)"
    assert lines[-2].startswith('step order-held: exec_failed: "sh exited 3')
    lines_recorded = records(hub)
    assert [line for line in lines_recorded if line["event"] == "end"] == []
    assert lines_recorded[0]["mode"] == "interactive"
    (investigation,) = [line for line in lines_recorded if line["event"] == "investigation"]
    assert {key: investigation[key] for key in ("step", "gate", "number", "failure_kind")} == {
        "step": "order-held",
        "gate": GATE,
        "number": 1,
        "failure_kind": "exec_failed",
    }
    (gate,) = [line for line in lines_recorded if line["event"] == "gate"]
    assert (gate["node"], gate["attempt"], gate["form"], gate["choices"], gate["reason"]) == (
        GATE,
        1,
        "choice",
        ["pick", "retry", "stop"],
        "investigation",
    )
    events = stored(hub)
    requested = [event for event in events if event.type == "gate.request"]
    assert [(e.payload["name"], e.payload["kind"], e.payload["reason"]) for e in requested] == [
        (GATE, "human_gate", "investigation")
    ]
    assert [event for event in events if event.type == "run.end"] == []
    assert not (hub.parent.parent / "claude-started").exists()
    # The gate needs its answer first: a bare resume says how to give it.
    resumed = hold_call(hub, marker, held, "workflow", "run", "--resume", RUN)
    assert resumed.exit_code == 1, resumed.output
    assert f"answer it with hub workflow respond {RUN} --node {GATE}" in plain(resumed.stderr)
    assert modes(marker) == ["run"]


def test_fails_when_investigation_cap_reached(hub: Path, marker: Path, held: Path) -> None:
    hold_walk(hub, marker, held)

    answers = [respond(hub, marker, held, "retry") for _ in range(10)]

    for answer in answers[:-1]:
        assert answer.exit_code == 0, answer.output
        assert plain(answer.stdout).splitlines()[-1].startswith(PAUSED)
    last = answers[-1]
    assert last.exit_code == 1, last.output
    shown = plain(last.stdout).splitlines()
    assert shown[-2] == f"run {RUN}: failed"
    assert shown[-1].startswith('step order-held: exec_failed: "sh exited 3')
    assert shown[-1].endswith(" (investigation limit reached)")
    lines = records(hub)
    assert [line["number"] for line in lines if line["event"] == "investigation"] == list(
        range(1, 11)
    )
    assert [line["status"] for line in lines if line["event"] == "end"] == ["failed"]
    assert modes(marker) == ["run"] * 11


def test_records_findings_and_option_plans_when_propose_runs(
    hub: Path, marker: Path, held: Path
) -> None:
    hold_walk(hub, marker, held)

    result = propose(hub, marker, held, proposal=a_proposal(RELEASE, LOOK))

    assert result.exit_code == 0, result.output
    assert plain(result.stdout).splitlines() == [
        "proposal 1 for step order-held (investigation 1)",
        "finding f1: Order stays on hold",
        "finding f2: Queue is slow",
        "option o1: Option 1",
        "  1  demo/release-hold  write  ask",
        "option o2: Option 2",
        "  1  demo/held-order  read  allow",
    ]
    # No option step runs before a pick, though local's access is write.
    assert modes(marker) == ["run"]
    assert not held.exists()
    (proposal,) = [line for line in records(hub) if line["event"] == "proposal"]
    assert [finding["finding_id"] for finding in proposal["findings"]] == ["f1", "f2"]
    assert [option["option_id"] for option in proposal["options"]] == ["o1", "o2"]
    plan = proposal["options"][0]["plan"][0]
    assert (plan["action"], plan["decision"], plan["reason_kind"]) == (
        "demo/release-hold",
        "ask",
        "agent_origin",
    )
    findings = [event for event in stored(hub) if event.type == "finding"]
    assert [event.payload for event in findings] == [
        {"run": RUN, "attempt": 1, "finding_id": "f1", "step": "order-held"},
        {"run": RUN, "attempt": 1, "finding_id": "f2", "step": "order-held"},
    ]
    # A later proposal replaces the earlier as the investigation's options; ids go on.
    again = propose(hub, marker, held, proposal=a_proposal(LOOK))
    assert again.exit_code == 0, again.output
    assert "finding f3: Order stays on hold" in plain(again.stdout)


def test_refuses_proposal_when_run_not_paused_at_investigation(
    hub: Path, marker: Path, held: Path
) -> None:
    held.touch()
    hold_walk(hub, marker, held)

    result = propose(hub, marker, held, proposal=a_proposal(LOOK))

    assert result.exit_code == 1, result.output
    assert "not paused at an investigation" in plain(result.stderr)
    assert [line for line in records(hub) if line["event"] == "proposal"] == []


RENDER = """\
version: 1
name: render-invoice-pdf
description: Render the invoice again
effect: read
runtime: sh
script: scripts/render-invoice-pdf.sh
inputs:
  target: {type: service, required: true}
output_format: {type: object}
"""


def test_marks_needs_acceptance_when_draft_action_from_agent_in_option(
    hub: Path, marker: Path, held: Path
) -> None:
    hold_walk(hub, marker, held)
    # What the investigation's agent writes under actions/<pack>/: a draft until committed.
    (hub / "actions" / "demo" / "render-invoice-pdf.yaml").write_text(RENDER)
    (hub / "actions" / "demo" / "scripts" / "render-invoice-pdf.sh").write_text(RELEASE_SCRIPT)
    render = [{"action": "render-invoice-pdf", "with": {"target": "api"}}]

    listed = hold_call(hub, marker, held, "action", "list")
    proposed = propose(hub, marker, held, proposal=a_proposal(render))
    picked = respond(hub, marker, held, "pick", "o1")

    assert "demo/render-invoice-pdf  read  target (service)  draft" in plain(listed.stdout)
    shown = plain(proposed.stdout).splitlines()
    assert "option o1: Option 1  (needs acceptance)" in shown
    assert (
        "  cannot be picked: step 1 (demo/render-invoice-pdf): draft action: commit it to run"
        in (shown)
    )
    assert picked.exit_code == 1, picked.output
    assert "option o1 cannot be picked" in plain(picked.stderr)
    assert [line for line in records(hub) if line["event"] == "decision"] == []
    assert modes(marker) == ["run"]
    # Committed, a new plan pins its hash and the option can be picked.
    commit_all(hub, "accept render-invoice-pdf")
    again = propose(hub, marker, held, proposal=a_proposal(render))
    assert "needs acceptance" not in plain(again.stdout)
    accepted = respond(hub, marker, held, "pick", "o1")
    assert accepted.exit_code == 0, accepted.output
    assert plain(accepted.stdout).splitlines()[-1] == f"run {RUN}: done"


def test_runs_workaround_then_retries_step_when_option_picked(
    hub: Path, marker: Path, held: Path
) -> None:
    hold_walk(hub, marker, held)
    propose(hub, marker, held, proposal=a_proposal(RELEASE, LOOK))

    picked = respond(hub, marker, held, "pick", "o1")

    assert picked.exit_code == 0, picked.output
    assert plain(picked.stdout).splitlines()[-1] == f"run {RUN}: done"
    # The step, the workaround's write, then the step again as a new attempt.
    assert modes(marker) == ["run", "run", "run"]
    lines = records(hub)
    (decision,) = [line for line in lines if line["event"] == "decision"]
    assert (decision["node"], decision["choice"], decision["text"]) == (GATE, "pick", "o1")
    assert decision["approver"]
    order = [
        line["event"]
        for line in lines
        if line["event"] in ("decision", "workaround_start", "workaround_end", "end")
    ]
    assert order == ["decision", "workaround_start", "workaround_end", "end"]
    (call,) = [line for line in lines if line["event"] == "action" and line["node"] != "order-held"]
    assert (call["node"], call["origin"], call["decision"], call["status"]) == (
        f"{GATE}.w1",
        "agent",
        "ask",
        "ok",
    )
    ends = [
        (line["attempt"], line["status"])
        for line in lines
        if line["event"] == "step_end" and line["node"] == "order-held"
    ]
    assert ends == [(1, "failed"), (2, "ok")]
    events = stored(hub)
    workaround = [event for event in events if event.type.startswith("workaround.")]
    assert [(event.type, event.payload["status"]) for event in workaround] == [
        ("workaround.start", "started"),
        ("workaround.end", "ok"),
    ]
    assert workaround[0].payload | {"status": "ok"} == workaround[1].payload
    started = [event for event in events if event.type == "action.start"]
    agent = [event for event in started if event.payload["origin"] == "agent"]
    assert [(event.step, event.payload["approver"]) for event in agent] == [
        (f"{GATE}.w1", decision["approver"])
    ]


def test_refuses_pick_with_reason_when_workaround_option_holds_deny(
    hub: Path, marker: Path, held: Path
) -> None:
    hold_walk(hub, marker, held, environment="live")
    proposed = propose(hub, marker, held, proposal=a_proposal(RELEASE))
    before = records(hub)

    picked = respond(hub, marker, held, "pick", "o1")

    assert proposed.exit_code == 0, proposed.output
    assert "  cannot be picked: step 1 (demo/release-hold): live is a production" in plain(
        proposed.stdout
    )
    assert picked.exit_code == 1, picked.output
    assert plain(picked.stderr) == (
        "hub workflow respond: option o1 cannot be picked: step 1 (demo/release-hold): live is"
        " a production environment: writes and destroys are denied\n"
    )
    assert records(hub) == before
    assert not held.exists()
    unknown = respond(hub, marker, held, "pick", "o9")
    assert unknown.exit_code == 1, unknown.output
    assert "one of o1" in plain(unknown.stderr)


def test_opens_new_investigation_when_workaround_step_fails(
    hub: Path, marker: Path, held: Path
) -> None:
    hold_walk(hub, marker, held)
    propose(hub, marker, held, proposal=a_proposal(LOOK))

    picked = respond(hub, marker, held, "pick", "o1")

    assert picked.exit_code == 0, picked.output
    shown = plain(picked.stdout).splitlines()
    assert shown[-2] == "step order-held: workaround w1 step 1 (demo/held-order): exec_failed"
    assert shown[-1].startswith(PAUSED)
    lines = records(hub)
    assert [line["status"] for line in lines if line["event"] == "workaround_end"] == ["failed"]
    assert [line["number"] for line in lines if line["event"] == "investigation"] == [1, 2]
    assert [line for line in lines if line["event"] == "end"] == []
    # The diverged step did not run again: the workaround failed first.
    assert modes(marker) == ["run", "run"]


def test_ends_cancelled_keeping_findings_when_investigation_stop(
    hub: Path, marker: Path, held: Path
) -> None:
    from agent_hub.core.scenarios.run_record import fold_records

    hold_walk(hub, marker, held)
    propose(hub, marker, held, proposal=a_proposal(RELEASE))

    stopped = respond(hub, marker, held, "stop")

    assert stopped.exit_code == 1, stopped.output
    assert plain(stopped.stdout).splitlines()[-1] == f"run {RUN}: cancelled"
    view = fold_records(records(hub))
    assert view.status == "cancelled"
    assert [finding.finding_id for finding in view.findings] == ["f1", "f2"]
    assert modes(marker) == ["run"]
    ends = [event for event in stored(hub) if event.type == "run.end"]
    assert [event.payload["status"] for event in ends] == ["cancelled"]
    again = respond(hub, marker, held, "retry")
    assert again.exit_code == 1, again.output


def test_retries_step_without_workaround_when_investigation_retry(
    hub: Path, marker: Path, held: Path
) -> None:
    hold_walk(hub, marker, held)
    # The system recovered on its own: the step passes when tried again.
    held.touch()

    retried = respond(hub, marker, held, "retry")

    assert retried.exit_code == 0, retried.output
    assert plain(retried.stdout).splitlines()[-1] == f"run {RUN}: done"
    lines = records(hub)
    assert [line for line in lines if line["event"].startswith("workaround")] == []
    ends = [
        (line["attempt"], line["status"])
        for line in lines
        if line["event"] == "step_end" and line["node"] == "order-held"
    ]
    assert ends == [(1, "failed"), (2, "ok")]
    assert modes(marker) == ["run", "run"]


def test_refuses_proposal_when_investigation_already_answered(
    hub: Path, marker: Path, held: Path
) -> None:
    hold_walk(hub, marker, held)
    propose(hub, marker, held, proposal=a_proposal(RELEASE))
    # hub web records the pick and resumes later: the options picked from no longer change.
    decided = hold_call(
        hub,
        marker,
        held,
        "workflow",
        "decide",
        RUN,
        "--gate",
        f"{RUN}:{GATE}:1",
        "--choice",
        "pick",
        "--text-stdin",
        stdin="o1",
    )

    again = propose(hub, marker, held, proposal=a_proposal(LOOK))

    assert decided.exit_code == 0, decided.output
    assert again.exit_code == 1, again.output
    assert "already answered (pick)" in plain(again.stderr)
    assert len([line for line in records(hub) if line["event"] == "proposal"]) == 1
    resumed = hold_call(hub, marker, held, "workflow", "run", "--resume", RUN)
    assert resumed.exit_code == 0, resumed.output
    assert plain(resumed.stdout).splitlines()[-1] == f"run {RUN}: done"


# AGH-360 review round 1: crash points of an answer, a plan edited before the pick, and the
# cap on proposals. A crash is played by the record lines it would leave.


def append_lines(hub: Path, *lines: dict[str, Any]) -> None:
    path = hub / ".agent-runs" / "workflows" / RUN / "records.jsonl"
    with path.open("a") as file:
        for line in lines:
            file.write(json.dumps(line) + "\n")


def decide(hub: Path, marker: Path, held: Path, *answer: str) -> Result:
    """``hub workflow decide`` (hub web): the answer recorded, the run not resumed."""
    choice, *text = answer
    args = ("workflow", "decide", RUN, "--gate", f"{RUN}:{GATE}:1", "--choice", choice)
    stdin = text[0] if text else ""
    return hold_call(hub, marker, held, *args, *(("--text-stdin",) if text else ()), stdin=stdin)


def resume_walk(hub: Path, marker: Path, held: Path) -> Result:
    return hold_call(hub, marker, held, "workflow", "run", "--resume", RUN)


def test_opens_new_investigation_when_workaround_cut_short_by_crash(
    hub: Path, marker: Path, held: Path
) -> None:
    hold_walk(hub, marker, held)
    propose(hub, marker, held, proposal=a_proposal(RELEASE))
    assert decide(hub, marker, held, "pick", "o1").exit_code == 0
    # The crash came once w1 started: its start is recorded, its end is not.
    append_lines(
        hub,
        {"event": "workaround_start", "workaround_id": "w1", "number": 1, "gate": GATE}
        | {"option": "o1", "steps": 1, "approver": "dev"},
    )

    resumed = resume_walk(hub, marker, held)

    assert resumed.exit_code == 0, resumed.output
    assert plain(resumed.stdout).splitlines()[-1].startswith(PAUSED)
    # The write is not run a second time, and the diverged step not either.
    assert modes(marker) == ["run"]
    assert not held.exists()
    lines = records(hub)
    assert [line["status"] for line in lines if line["event"] == "workaround_end"] == [
        "interrupted"
    ]
    opened = [line for line in lines if line["event"] == "investigation"]
    assert [(line["number"], line["failure_kind"]) for line in opened] == [
        (1, "exec_failed"),
        (2, "workaround"),
    ]
    assert [line for line in lines if line["event"] == "end"] == []


def test_ends_cancelled_when_investigation_stop_closed_before_crash(
    hub: Path, marker: Path, held: Path
) -> None:
    hold_walk(hub, marker, held)
    assert decide(hub, marker, held, "stop").exit_code == 0
    # The crash came between the gate's close and the run's end.
    append_lines(
        hub,
        {"event": "step_end", "node": GATE, "attempt": 1, "status": "ok"}
        | {"output": {"choice": "stop", "text": ""}},
    )
    held.touch()

    resumed = resume_walk(hub, marker, held)

    assert resumed.exit_code == 1, resumed.output
    assert plain(resumed.stdout).splitlines()[-1] == f"run {RUN}: cancelled"
    # A stop never turns into a retry.
    assert modes(marker) == ["run"]
    lines = records(hub)
    assert [line["status"] for line in lines if line["event"] == "end"] == ["cancelled"]
    assert [line for line in lines if line["event"] == "step_end" and line["node"] == GATE] == [
        next(line for line in lines if line["event"] == "step_end" and line["node"] == GATE)
    ]


def test_retries_step_when_workaround_ended_ok_before_crash(
    hub: Path, marker: Path, held: Path
) -> None:
    hold_walk(hub, marker, held)
    propose(hub, marker, held, proposal=a_proposal(RELEASE))
    assert decide(hub, marker, held, "pick", "o1").exit_code == 0
    # w1 ran and ended ok (its write released the hold); the crash came before the gate closed.
    held.touch()
    append_lines(
        hub,
        {"event": "workaround_start", "workaround_id": "w1", "number": 1, "gate": GATE}
        | {"option": "o1", "steps": 1, "approver": "dev"},
        {"event": "workaround_end", "workaround_id": "w1", "number": 1, "status": "ok"},
    )

    resumed = resume_walk(hub, marker, held)

    assert resumed.exit_code == 0, resumed.output
    assert plain(resumed.stdout).splitlines()[-1] == f"run {RUN}: done"
    # The write is not run again; the diverged step runs again as a new attempt.
    assert modes(marker) == ["run", "run"]
    lines = records(hub)
    assert [line["status"] for line in lines if line["event"] == "workaround_end"] == ["ok"]
    assert [line["number"] for line in lines if line["event"] == "investigation"] == [1]


def test_refuses_pick_when_workaround_action_edited_after_propose(
    hub: Path, marker: Path, held: Path
) -> None:
    hold_walk(hub, marker, held)
    propose(hub, marker, held, proposal=a_proposal(RELEASE))
    script = hub / "actions" / "demo" / "scripts" / "release-hold.sh"
    script.write_text(RELEASE_SCRIPT + "# edited\n")
    commit_all(hub, "edit release-hold")

    picked = respond(hub, marker, held, "pick", "o1")

    assert picked.exit_code == 1, picked.output
    assert plain(picked.stderr) == (
        "hub workflow respond: option o1 cannot be picked: the plan of step 1"
        " (demo/release-hold) changed since it was shown; ask for a new proposal\n"
    )
    assert [line for line in records(hub) if line["event"] == "decision"] == []
    assert modes(marker) == ["run"]


def test_opens_new_investigation_when_workaround_action_edited_after_decide(
    hub: Path, marker: Path, held: Path
) -> None:
    hold_walk(hub, marker, held)
    propose(hub, marker, held, proposal=a_proposal(RELEASE))
    assert decide(hub, marker, held, "pick", "o1").exit_code == 0
    script = hub / "actions" / "demo" / "scripts" / "release-hold.sh"
    script.write_text(RELEASE_SCRIPT + "# edited\n")
    commit_all(hub, "edit release-hold")

    resumed = resume_walk(hub, marker, held)

    assert resumed.exit_code == 0, resumed.output
    shown = plain(resumed.stdout).splitlines()
    assert shown[-2] == (
        "step order-held: workaround w1 step 1 (demo/release-hold): its plan changed since it"
        " was shown"
    )
    assert shown[-1].startswith(PAUSED)
    assert modes(marker) == ["run"]
    lines = records(hub)
    assert [line["status"] for line in lines if line["event"] == "workaround_end"] == ["failed"]


def test_refuses_eleventh_proposal_when_investigation_proposal_cap_reached(
    hub: Path, marker: Path, held: Path
) -> None:
    hold_walk(hub, marker, held)
    proposed = [propose(hub, marker, held, proposal=a_proposal(LOOK)) for _ in range(10)]

    eleventh = propose(hub, marker, held, proposal=a_proposal(LOOK))

    assert all(result.exit_code == 0 for result in proposed), proposed[-1].output
    assert eleventh.exit_code == 1, eleventh.output
    assert plain(eleventh.stderr) == (
        "hub scenario propose: the investigation of step order-held already has 10 proposals\n"
    )
    assert len([line for line in records(hub) if line["event"] == "proposal"]) == 10
    assert len([event for event in stored(hub) if event.type == "finding"]) == 20


def test_opens_new_investigation_when_failed_workaround_closed_before_crash(
    hub: Path, marker: Path, held: Path
) -> None:
    hold_walk(hub, marker, held)
    propose(hub, marker, held, proposal=a_proposal(RELEASE))
    assert decide(hub, marker, held, "pick", "o1").exit_code == 0
    # w1 failed, the gate closed, then the crash came before the new investigation opened.
    append_lines(
        hub,
        {"event": "workaround_start", "workaround_id": "w1", "number": 1, "gate": GATE}
        | {"option": "o1", "steps": 1, "approver": "dev"},
        {"event": "workaround_end", "workaround_id": "w1", "number": 1, "status": "failed"},
        {"event": "step_end", "node": GATE, "attempt": 1, "status": "ok"}
        | {"output": {"choice": "pick", "text": "o1"}},
    )

    resumed = resume_walk(hub, marker, held)

    assert resumed.exit_code == 0, resumed.output
    assert plain(resumed.stdout).splitlines()[-1].startswith(PAUSED)
    # A failed workaround never turns into a silent retry of the diverged step.
    assert modes(marker) == ["run"]
    lines = records(hub)
    opened = [line for line in lines if line["event"] == "investigation"]
    assert [(line["number"], line["failure_kind"]) for line in opened] == [
        (1, "exec_failed"),
        (2, "workaround"),
    ]
    assert [line["status"] for line in lines if line["event"] == "workaround_end"] == ["failed"]
    assert (
        len([line for line in lines if line["event"] == "step_end" and line["node"] == GATE]) == 1
    )
    assert [line for line in lines if line["event"] == "end"] == []


def test_opens_gate_when_investigation_recorded_without_gate_before_crash(
    hub: Path, marker: Path, held: Path
) -> None:
    hold_walk(hub, marker, held)
    propose(hub, marker, held, proposal=a_proposal(RELEASE))
    assert decide(hub, marker, held, "pick", "o1").exit_code == 0
    # Investigation 2 was recorded, then the crash came before its gate was.
    append_lines(
        hub,
        {"event": "workaround_start", "workaround_id": "w1", "number": 1, "gate": GATE}
        | {"option": "o1", "steps": 1, "approver": "dev"},
        {"event": "workaround_end", "workaround_id": "w1", "number": 1, "status": "failed"},
        {"event": "step_end", "node": GATE, "attempt": 1, "status": "ok"}
        | {"output": {"choice": "pick", "text": "o1"}},
        {"event": "investigation", "step": "order-held", "gate": GATE, "number": 2}
        | {"step_attempt": 0, "failure_kind": "workaround"},
    )

    resumed = resume_walk(hub, marker, held)

    assert resumed.exit_code == 0, resumed.output
    assert plain(resumed.stdout).splitlines()[-1].startswith(PAUSED)
    assert modes(marker) == ["run"]
    lines = records(hub)
    gates = [(line["node"], line["attempt"]) for line in lines if line["event"] == "gate"]
    assert gates == [(GATE, 1), (GATE, 2)]
    assert [line["number"] for line in lines if line["event"] == "investigation"] == [1, 2]
    retried = respond(hub, marker, held, "stop")
    assert retried.exit_code == 1, retried.output
    assert plain(retried.stdout).splitlines()[-1] == f"run {RUN}: cancelled"


def test_opens_investigation_when_divergence_recorded_before_crash(
    hub: Path, marker: Path, held: Path
) -> None:
    hold_walk(hub, marker, held)
    # The crash came after the step's failed end and before its investigation was recorded.
    path = hub / ".agent-runs" / "workflows" / RUN / "records.jsonl"
    kept = path.read_text().splitlines(keepends=True)
    cut = next(i for i, line in enumerate(kept) if json.loads(line)["event"] == "investigation")
    path.write_text("".join(kept[:cut]))

    resumed = resume_walk(hub, marker, held)

    assert resumed.exit_code == 0, resumed.output
    assert plain(resumed.stdout).splitlines()[-1].startswith(PAUSED)
    # The diverged step is not run again with nobody asked.
    assert modes(marker) == ["run"]
    lines = records(hub)
    opened = [line for line in lines if line["event"] == "investigation"]
    assert [(line["number"], line["failure_kind"]) for line in opened] == [(1, "exec_failed")]
    assert [(line["node"], line["attempt"]) for line in lines if line["event"] == "gate"] == [
        (GATE, 1)
    ]
    assert [line for line in lines if line["event"] == "end"] == []


def test_refuses_proposal_when_answered_after_ten_proposals(
    hub: Path, marker: Path, held: Path
) -> None:
    hold_walk(hub, marker, held)
    proposed = [propose(hub, marker, held, proposal=a_proposal(RELEASE)) for _ in range(10)]
    assert decide(hub, marker, held, "pick", "o1").exit_code == 0

    eleventh = propose(hub, marker, held, proposal=a_proposal(LOOK))

    assert all(result.exit_code == 0 for result in proposed), proposed[-1].output
    assert eleventh.exit_code == 1, eleventh.output
    assert "already answered (pick)" in plain(eleventh.stderr)
    assert len([line for line in records(hub) if line["event"] == "proposal"]) == 10


# AGH-360 review round 4: a divergence and a policy pause in one pass. ``hold-send`` runs
# ``order-held`` (failing until released) beside the write ``send-order``, which staging's
# access ``ask`` gates; the pass pauses at that gate with the divergence recorded.

HOLD_SEND = HOLD_WALK.replace("name: hold-walk", "name: hold-send") + (
    "  - id: send-order\n    type: action\n    action: send-order\n    with: {target: api}\n"
)


def hold_send(hub: Path, marker: Path, held: Path) -> Result:
    write_scenario(hub, HOLD_SEND)
    commit_all(hub, "hold send")
    args = ("scenario", "run", "hold-send", "--env", "staging", "--run-id", RUN)
    started = hold_call(hub, marker, held, *args)
    assert started.exit_code == 0, started.output
    assert plain(started.stdout).splitlines()[-1] == f"run {RUN}: paused at send-order__ask"
    return started


def calls_of(hub: Path, node: str) -> int:
    return len(
        [line for line in records(hub) if line["event"] == "action" and line["node"] == node]
    )


def test_ends_cancelled_when_policy_gate_rejected_beside_owed_investigation(
    hub: Path, marker: Path, held: Path
) -> None:
    hold_send(hub, marker, held)

    rejected = hold_call(hub, marker, held, "workflow", "reject", RUN, "send-order__ask")

    assert rejected.exit_code == 1, rejected.output
    assert plain(rejected.stdout).splitlines()[-1] == f"run {RUN}: cancelled"
    lines = records(hub)
    assert [line["status"] for line in lines if line["event"] == "end"] == ["cancelled"]
    assert [line for line in lines if line["event"] == "investigation"] == []
    assert modes(marker) == ["run"]


def test_opens_investigation_when_policy_gate_approved_beside_divergence(
    hub: Path, marker: Path, held: Path
) -> None:
    hold_send(hub, marker, held)

    approved = hold_call(hub, marker, held, "workflow", "approve", RUN, "send-order__ask")

    assert approved.exit_code == 0, approved.output
    assert (
        plain(approved.stdout)
        .splitlines()[-1]
        .startswith(
            f"run {RUN}: paused at order-held (investigation): open /scenarios/hold-send/runs/{RUN}"
        )
    )
    # Nothing runs again before the person answers the investigation.
    assert modes(marker) == ["run"]
    assert (calls_of(hub, "order-held"), calls_of(hub, "send-order")) == (1, 0)
    held.touch()
    retried = respond(hub, marker, held, "retry")
    assert retried.exit_code == 0, retried.output
    assert plain(retried.stdout).splitlines()[-1] == f"run {RUN}: done"
    # The retry runs order-held once more; the approved write runs once.
    assert (calls_of(hub, "order-held"), calls_of(hub, "send-order")) == (2, 1)


def test_ends_cancelled_when_policy_gate_rejected_while_investigation_open(
    hub: Path, marker: Path, held: Path
) -> None:
    hold_send(hub, marker, held)
    # A bare resume opens the owed investigation; the policy gate stays open beside it.
    opened = resume_walk(hub, marker, held)
    assert opened.exit_code == 0, opened.output
    assert plain(opened.stdout).splitlines()[-1].startswith(f"run {RUN}: paused at order-held")

    rejected = hold_call(hub, marker, held, "workflow", "reject", RUN, "send-order__ask")

    assert rejected.exit_code == 1, rejected.output
    assert plain(rejected.stdout).splitlines()[-1] == f"run {RUN}: cancelled"
    ends = [line for line in records(hub) if line["event"] == "end"]
    assert [(line["status"], line["reason"]) for line in ends] == [("cancelled", "send-order__ask")]
    assert modes(marker) == ["run"]


# AGH-362: hub scenario findings (AC-350.27, .28). ``tracker.transport`` is "mcp", so the tracker
# is a ``claude`` first on PATH that plays Linear's MCP server: it records each request in the file
# ``TRACKER_CALLS`` names and answers a create with DEM-42. Nothing reaches the network.

TRACKER_CLAUDE = """\
import json
import os
import sys

request = json.loads(sys.argv[2].splitlines()[-1])
with open(os.environ["TRACKER_CALLS"], "a") as calls:
    calls.write(json.dumps(request) + "\\n")
given = request["arguments"]
issue = {
    "id": "DEM-42",
    "title": given["title"],
    "description": given["description"],
    "url": "https://linear.example.com/demo/issue/DEM-42",
    "state": "Todo",
    "labels": [],
}
reply = {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.01}
print(json.dumps(reply | {"result": json.dumps({"issue": issue})}))
"""
# A secret shape built at run time: the proposal's evidence holds it, redacted when proposed.
FINDING_KEY = "AKIA" + "SYNTHETIC0000000"


def a_tracker(hub: Path) -> dict[str, str]:
    """``hub``'s tracker through the fake MCP ``claude``; the environment that reaches it."""
    document = json.loads((hub / "hub.json").read_text())
    document["tracker"]["transport"] = "mcp"
    (hub / "hub.json").write_text(json.dumps(document, indent=2) + "\n")
    fakes = hub.parent.parent / "tracker-bin"
    fakes.mkdir()
    (fakes / "claude").write_text(f"#!{sys.executable}\n{TRACKER_CLAUDE}")
    (fakes / "claude").chmod(0o755)
    return {
        "PATH": f"{fakes}{os.pathsep}{os.environ.get('PATH', '')}",
        "TRACKER_CALLS": str(hub.parent.parent / "tracker-calls"),
    }


def tracker_calls(hub: Path) -> list[dict[str, Any]]:
    calls = hub.parent.parent / "tracker-calls"
    if not calls.exists():
        return []
    return [json.loads(line) for line in calls.read_text().splitlines()]


def found_run(hub: Path, marker: Path, held: Path) -> None:
    """``hold-walk`` paused at its investigation, with the findings f1 and f2 proposed."""
    proposal = a_proposal(RELEASE)
    proposal["findings"][0]["evidence"] = f"status ON_HOLD; key {FINDING_KEY}"
    hold_walk(hub, marker, held)
    proposed = propose(hub, marker, held, proposal=proposal)
    assert proposed.exit_code == 0, proposed.output


def findings(hub: Path, marker: Path, held: Path, *args: str, **env: str) -> Result:
    environ = {
        "AGENT_HUB_ROOT": str(hub),
        "MARKER": str(marker),
        "HELD": str(held),
        "AGENT_HUB_DB": str(hub.parent.parent / "events.db"),
        **env,
    }
    return CliRunner().invoke(app, ["scenario", "findings", *args], env=environ, input="")


def findings_in_terminal(
    hub: Path, env: dict[str, str], *args: str, answer: str
) -> tuple[int, str]:
    """``hub scenario findings`` in a pseudo-terminal: ``answer`` is typed once a ``[y/N]``
    prompt shows; the exit code and everything the terminal showed."""
    environ = {**os.environ, "AGENT_HUB_ROOT": str(hub), **env}
    main, child = pty.openpty()
    argv = [sys.executable, "-m", "agent_hub.cli", "scenario", "findings", *args]
    process = subprocess.Popen(  # noqa: S603 - this interpreter, fixed arguments
        argv, stdin=child, stdout=child, stderr=child, env=environ, close_fds=True
    )
    os.close(child)
    shown, answered = b"", False
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        ready, _, _ = select.select([main], [], [], 0.2)
        if ready:
            try:
                chunk = os.read(main, 4096)
            except OSError:
                break
            if not chunk:
                break
            shown += chunk
        if not answered and b"[y/N]" in shown:
            os.write(main, answer.encode() + b"\n")
            answered = True
        if process.poll() is not None and not ready:
            break
    os.close(main)
    return process.wait(timeout=30), shown.decode(errors="replace")


def test_lists_findings_when_findings_run(hub: Path, marker: Path, held: Path) -> None:
    found_run(hub, marker, held)

    result = findings(hub, marker, held, RUN)

    assert result.exit_code == 0, result.output
    assert plain(result.stdout).splitlines() == [
        "f1  order-held  Order stays on hold",
        "f2  order-held  Queue is slow",
    ]
    as_json = findings(hub, marker, held, RUN, "--json")
    assert as_json.exit_code == 0, as_json.output
    listed = json.loads(as_json.stdout)
    assert (listed["run"], listed["scenario"], listed["environment"]) == (
        RUN,
        "hold-walk",
        "local",
    )
    assert [item["finding_id"] for item in listed["findings"]] == ["f1", "f2"]
    assert listed["findings"][0] == {
        "finding_id": "f1",
        "step": "order-held",
        "title": "Order stays on hold",
        "text": "The hold flag is set.",
        "evidence": "status ON_HOLD; key [redacted: AWS access key]",
    }


def test_creates_issue_once_after_yes_when_findings_issue_on_terminal(
    hub: Path, marker: Path, held: Path
) -> None:
    found_run(hub, marker, held)
    env = a_tracker(hub)

    declined, shown_declined = findings_in_terminal(hub, env, RUN, "--issue", "f1", answer="n")
    code, shown = findings_in_terminal(hub, env, RUN, "--issue", "f1", answer="y")

    assert declined == 0, shown_declined
    assert "the issue was not created" in plain(shown_declined)
    assert code == 0, shown
    text = plain(shown).replace("\r\n", "\n")
    assert "title: Scenario hold-walk: Order stays on hold" in text
    assert "The scenario hold-walk found this in run walk-1, at step order-held," in text
    assert "created DEM-42  https://linear.example.com/demo/issue/DEM-42" in text
    (call,) = tracker_calls(hub)
    assert call["operation"] == "create_issue"
    assert call["arguments"]["team"] == "DEM"
    assert call["arguments"]["title"] == "Scenario hold-walk: Order stays on hold"
    description = call["arguments"]["description"]
    assert "Record: /scenarios/hold-walk/runs/walk-1 in hub web" in description
    assert FINDING_KEY not in description


def test_creates_nothing_when_findings_issue_without_terminal(
    hub: Path, marker: Path, held: Path
) -> None:
    found_run(hub, marker, held)
    env = a_tracker(hub)

    result = findings(hub, marker, held, RUN, "--issue", "f2", **env)

    assert result.exit_code == 0, result.output
    shown = plain(result.stdout).splitlines()
    assert shown[0] == "title: Scenario hold-walk: Queue is slow"
    assert shown[-1] == (
        "no terminal: the issue was not created; run this command on a terminal to create it"
    )
    assert tracker_calls(hub) == []


def test_writes_inbox_note_when_findings_inbox(hub: Path, marker: Path, held: Path) -> None:
    found_run(hub, marker, held)

    result = findings(hub, marker, held, RUN, "--inbox", "f1")

    name = f"{date.today().isoformat()}-scenario-hold-walk-f1.md"
    assert result.exit_code == 0, result.output
    assert plain(result.stdout).splitlines() == [f"wrote brain/_inbox/{name}"]
    (note,) = (hub / "brain" / "_inbox").iterdir()
    assert note.name == name
    text = note.read_text()
    assert "\nprovenance: agent-from-external\n" in text
    assert "## Order stays on hold" in text
    assert "Evidence: status ON_HOLD; key [redacted: AWS access key]" in text
    assert FINDING_KEY not in text
    # One note per finding: a second write is refused and the note kept.
    again = findings(hub, marker, held, RUN, "--inbox", "f1")
    assert again.exit_code == 1, again.output
    assert f"brain/_inbox/{name} already exists" in plain(again.stderr)
    assert note.read_text() == text


def test_exits_one_when_findings_run_or_finding_unknown(
    hub: Path, marker: Path, held: Path
) -> None:
    found_run(hub, marker, held)

    unknown_run = findings(hub, marker, held, "walk-9")
    unknown_finding = findings(hub, marker, held, RUN, "--issue", "f9")

    assert unknown_run.exit_code == 1, unknown_run.output
    assert plain(unknown_run.stderr).splitlines() == [
        "hub scenario findings: no scenario run walk-9"
    ]
    assert unknown_finding.exit_code == 1, unknown_finding.output
    assert plain(unknown_finding.stderr).splitlines() == [
        f"hub scenario findings: run {RUN} has no finding f9"
    ]


@pytest.mark.parametrize(
    "args",
    [("Walk_1",), (RUN, "--issue", "f1", "--inbox", "f1"), (RUN, "--json", "--inbox", "f1")],
    ids=["run-id", "issue-and-inbox", "json-and-inbox"],
)
def test_exits_two_when_findings_usage_wrong(
    hub: Path, marker: Path, held: Path, *, args: tuple[str, ...]
) -> None:
    result = findings(hub, marker, held, *args)

    assert result.exit_code == 2, result.output
    assert not (hub / "brain").exists()


def test_lists_four_subcommands_when_scenario_help(hub: Path, marker: Path) -> None:
    result = run_hub(hub, marker, "scenario", "--help")

    assert result.exit_code == 0, result.output
    help_text = plain(result.stdout)
    # propose (T9) is listed too; the four of AC-350.28 must be there.
    for command in ("list", "plan", "run", "findings"):
        # A line of the commands panel: the name, then its help after two or more spaces.
        assert re.search(rf"^\W+{command}\s{{2,}}\S", help_text, re.MULTILINE), command
