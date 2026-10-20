"""``hub scenario list|plan`` (AC-350.8, .13, .17, .18, .28, .42; docs/design/scenarios.md).

Each test builds a workspace under ``tmp_path``: a hub (``hub.json`` with the environments of
``an_environments_document``) holding the ``demo`` action pack and the ``orders`` scenario pack,
a git checkout with its own identity, and runs the command in process with ``AGENT_HUB_ROOT``
naming the hub. Every action script appends its stdin to the file ``MARKER`` names, so a test
sees which mode ran, if any. Output is read without colour codes (CI forces a terminal).
"""

import json
import re
import shutil
import subprocess
from importlib.metadata import version
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from agent_hub.cli.main import app
from agent_hub.core.testing.builders import an_environments_document

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
