"""``hub scenario list|plan`` (AC-350.8, .13, .17, .18, .28, .42; docs/design/scenarios.md).

Each test builds a workspace under ``tmp_path``: a hub (``hub.json`` with the environments of
``an_environments_document``) holding the ``demo`` action pack and the ``orders`` scenario pack,
a git checkout with its own identity, and runs the command in process with ``AGENT_HUB_ROOT``
naming the hub. Every action script appends its stdin to the file ``MARKER`` names, so a test
sees which mode ran, if any. Output is read without colour codes (CI forces a terminal).
"""

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
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
