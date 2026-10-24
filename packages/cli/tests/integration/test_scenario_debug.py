"""``hub scenario run --break``, ``break``, ``step`` and ``continue`` (AC-507.7, .8, .9, .11, .12,
.13; docs/design/scenarios.md § Debugging, ADR 0049).

Each test builds a hub under ``tmp_path`` as ``test_scenario_command.py`` does (``hub.json`` with
the environments of ``an_environments_document``, a git checkout), holding the fixture actions
of ``packages/core/tests/data/scenarios/blocks/actions/fixture`` and the tree scenarios beside
them, committed, so no action is a draft. Nothing reaches a system: the write actions print
``{"ok": true}`` and the read action prints the file ``FIXTURE_ORDER_STATE`` names, which a test
writes before each poll so every Wait until holds at its first poll (no real wait). The
commands run in process with ``AGENT_HUB_ROOT`` naming the hub.
"""

import getpass
import json
import os
import re
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner, Result

from agent_hub.cli import scenario_debug
from agent_hub.cli.main import app
from agent_hub.cli.workflow_runs import WorkflowRunError, snapshot_hash
from agent_hub.core.events.event import Event
from agent_hub.core.testing.builders import an_environments_document
from agent_hub.storage.event_store import open_event_store

BLOCKS = Path(__file__).resolve().parents[3] / "core/tests/data/scenarios/blocks"
REFERENCE = "demo-order-roundtrip"
RUN = "debug-1"
ORDER = "SO-1001"
VALUES = {"personal_name": "dev-stack", "aws_account_id": "111122223333"}
ACCOUNT = "dev"
# What the order-state read prints, as the reference run goes: each state holds the conditions of
# the Wait untils that poll it.
STATES: dict[str, dict[str, Any]] = {
    "fetched": {"order_id": "o-1", "order_status": "ON_HOLD", "review_status": "PENDING"},
    "reviewed": {"review_status": "REVIEWED", "payment_status": "CONFIRMED", "open_tasks": 2},
    "processed": {
        "order_status": "PROCESSED",
        "invoice_status": "CREATED",
        "invoice_number": "I-1",
    },
    "invoiced": {
        "invoice_status": "SENT",
        "invoice_update_job_id": "j-1",
        "approval_job_id": "a-1",
        "review_status": "APPROVED",
    },
    "paid": {"paid": True, "payment_job_id": "p-1", "review_status": "CLOSED"},
    # Every condition of the small samples (blocks-together, blocks-repeat).
    "sample": {"order_id": "o-1", "approval_job_id": "a-1", "review_status": "APPROVED"},
}
# The reference scenario's node ids, by block address.
NODES = {
    "1": "fetch-order--1",
    "1.1": "fetch-order--1",
    "1.2": "fetch-order--2",
    "2": "review--1",
    "2.1": "review--1",
    "2.2": "review--2",
}


def git(hub: Path, *args: str) -> None:
    found = shutil.which("git")
    assert found is not None
    identity = ("-c", "user.name=Demo Dev", "-c", "user.email=dev@example.com")
    command = [found, *identity, *args]
    subprocess.run(command, cwd=hub, check=True, capture_output=True)  # noqa: S603 - absolute git, fixed arguments


def plain(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


@dataclass
class DebugHub:
    """A committed hub with the fixture actions and the tree scenarios, and its order state."""

    hub: Path
    state: Path

    def run(self, *args: str) -> Result:
        environ = {
            "AGENT_HUB_ROOT": str(self.hub),
            "AGENT_HUB_DB": str(self.hub.parent / "events.db"),
            "FIXTURE_ORDER_STATE": str(self.state),
        }
        return CliRunner().invoke(app, list(args), env=environ, input="")

    def start(self, *extra: str, name: str = REFERENCE, environment: str = "local") -> Result:
        args = ["scenario", "run", name, "--env", environment, "--input", f"shop_order_id={ORDER}"]
        return self.run(*args, "--mode", "regression", "--run-id", RUN, *extra)

    def order(self, state: str) -> None:
        self.state.write_text(json.dumps(STATES[state]) + "\n")

    @property
    def folder(self) -> Path:
        return self.hub / ".agent-runs" / "workflows" / RUN

    def records(self) -> list[dict[str, Any]]:
        lines = (self.folder / "records.jsonl").read_text().splitlines()
        return [json.loads(line) for line in lines]

    def stored(self) -> list[Event]:
        return open_event_store(self.hub.parent / "events.db").read_all()

    def hub_json(self) -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads((self.hub / "hub.json").read_text())
        return loaded

    def write_hub_json(self, document: dict[str, Any]) -> None:
        (self.hub / "hub.json").write_text(json.dumps(document, indent=2) + "\n")


@pytest.fixture
def debug_hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DebugHub:
    root = tmp_path / "workspace" / "hub"
    root.mkdir(parents=True)
    document = an_environments_document()
    document["platform"]["version"] = version_of_cli()
    document["environments"]["local"]["values"] = dict(VALUES)
    document["environments"]["staging"]["values"] = {"personal_name": VALUES["personal_name"]}
    (root / "hub.json").write_text(json.dumps(document, indent=2) + "\n")
    shutil.copytree(BLOCKS / "actions" / "fixture", root / "actions" / "fixture")
    scenarios = root / "scenarios" / "fixture"
    scenarios.mkdir(parents=True)
    for name in (REFERENCE, "blocks-together", "blocks-repeat", "blocks-if-else"):
        shutil.copy(BLOCKS / "tree" / f"{name}.yaml", scenarios / f"{name}.yaml")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "fixture hub")
    monkeypatch.setattr(getpass, "getuser", lambda: ACCOUNT)
    return DebugHub(hub=root, state=tmp_path / "order-state.json")


def version_of_cli() -> str:
    from importlib.metadata import version

    return version("agent-hub-cli")


def last_line(result: Result) -> str:
    return plain(result.stdout).splitlines()[-1]


def ended(lines: list[dict[str, Any]]) -> list[str]:
    """The nodes that ended ok or failed, in order (not the reused or skipped ones)."""
    return [
        line["node"]
        for line in lines
        if line["event"] == "step_end" and line["status"] in ("ok", "failed")
    ]


def passes(lines: list[dict[str, Any]]) -> list[list[str]]:
    """The nodes each pass ended, from the start and from each resume."""
    found: list[list[str]] = []
    for line in lines:
        if line["event"] in ("start", "resume"):
            found.append([])
        elif line["event"] == "step_end" and line["status"] in ("ok", "failed") and found:
            found[-1].append(line["node"])
    return found


def steps_of(content: Any) -> Iterator[dict[str, Any]]:
    """Every step of a tree, containers' steps included."""
    if isinstance(content, dict):
        if "stages" in content:
            for stage in content["stages"]:
                yield from steps_of(stage["steps"])
            return
        yield content
        for key in ("then", "else", "steps"):
            yield from steps_of(content.get(key, []))
        yield from steps_of(content.get("repeat", {}).get("steps", []))
        for path in content.get("together", []):
            yield from steps_of(path)
    elif isinstance(content, list):
        for item in content:
            yield from steps_of(item)


# AC-507.7, .8: the environment's values reach every action; a missing one refuses the plan.


def test_gives_every_action_the_environment_values_when_the_reference_scenario_runs(
    debug_hub: DebugHub,
) -> None:
    tree = yaml.safe_load((BLOCKS / "tree" / f"{REFERENCE}.yaml").read_text())
    planned = debug_hub.run(
        "scenario", "plan", REFERENCE, "--env", "local", "--input", f"shop_order_id={ORDER}"
    )
    as_json = debug_hub.run(
        "scenario",
        "plan",
        REFERENCE,
        "--env",
        "local",
        "--input",
        f"shop_order_id={ORDER}",
        "--json",
    )
    debug_hub.order("fetched")

    started = debug_hub.start("--break", "2.2", "--break", "3.5")
    debug_hub.order("reviewed")
    second = debug_hub.run("scenario", "continue", RUN)
    debug_hub.order("processed")
    third = debug_hub.run("scenario", "continue", RUN)
    debug_hub.order("invoiced")
    invoice = debug_hub.run("workflow", "approve", RUN)
    debug_hub.order("paid")
    paid = debug_hub.run("workflow", "approve", RUN)

    assert planned.exit_code == 0, planned.output
    assert as_json.exit_code == 0, as_json.output
    rows = json.loads(as_json.stdout)["rows"]
    assert len(rows) == 20
    for row in rows:
        assert {key: row["args"][key] for key in VALUES} == VALUES, row["step"]
    assert last_line(started) == f"run {RUN}: paused before 2.2 (breakpoint)", started.output
    assert last_line(second) == f"run {RUN}: paused before 3.5 (breakpoint)", second.output
    assert last_line(third) == f"run {RUN}: paused at invoice-pdf--1", third.output
    assert last_line(invoice) == f"run {RUN}: paused at payment--1", invoice.output
    assert (paid.exit_code, last_line(paid)) == (0, f"run {RUN}: done"), paid.output
    lines = debug_hub.records()
    inputs = next(line["inputs"] for line in lines if line["event"] == "inputs")
    assert {key: inputs[key] for key in VALUES} == VALUES
    calls = [line for line in lines if line["event"] == "action"]
    assert len(calls) == 20
    for call in calls:
        assert {key: call["inputs"][key] for key in VALUES} == VALUES, call["node"]
    for step in steps_of(tree):
        assert not set(step.get("with", {})) & set(VALUES), step


def test_refuses_the_plan_naming_input_and_environment_when_a_value_is_missing(
    debug_hub: DebugHub,
) -> None:
    result = debug_hub.run(
        "scenario", "plan", REFERENCE, "--env", "staging", "--input", f"shop_order_id={ORDER}"
    )

    assert result.exit_code == 2, result.output
    shown = " ".join(re.sub("[\u2500-\u257f]", " ", plain(result.output)).split())
    assert '"aws_account_id"' in shown
    assert '"staging"' in shown


# AC-507.9: a breakpoint pauses before its block, nothing of the block started.


@pytest.mark.parametrize("address", ["1", "1.1", "1.2", "2", "2.1", "2.2"])
def test_pauses_before_the_block_when_a_breakpoint_holds_its_address(
    debug_hub: DebugHub, address: str
) -> None:
    debug_hub.order("fetched")

    result = debug_hub.start("--break", address)

    assert result.exit_code == 0, result.output
    assert last_line(result) == f"run {RUN}: paused before {address} (breakpoint)"
    node = NODES[address]
    lines = debug_hub.records()
    assert not [
        line
        for line in lines
        if line.get("node") == node and not line["event"].startswith("debug.")
    ]
    assert [line["event"] for line in lines if line["event"] == "end"] == []
    [marked] = [line for line in lines if line["event"] == "debug.breakpoints"]
    assert marked["addresses"] == [address]
    [pause] = [line for line in lines if line["event"] == "debug.pause"]
    assert (pause["node"], pause["block"], pause["reason"], pause["number"]) == (
        node,
        address,
        "breakpoint",
        1,
    )
    before = list(NODES.values())[: list(NODES.values()).index(node)]
    assert ended(lines) == list(dict.fromkeys(before))
    assert json.loads((debug_hub.folder / "breakpoints.json").read_text()) == {
        "addresses": [address]
    }
    events = debug_hub.stored()
    [paused] = [event for event in events if event.type == "debug.pause"]
    assert (paused.step, paused.payload["block"], paused.payload["reason"]) == (
        node,
        address,
        "breakpoint",
    )
    [counted] = [event for event in events if event.type == "debug.breakpoints"]
    assert counted.payload["count"] == 1


def test_refuses_the_start_naming_the_address_when_the_tree_has_no_such_block(
    debug_hub: DebugHub,
) -> None:
    result = debug_hub.start("--break", "2.1", "--break", "9.9")

    assert result.exit_code == 1, result.output
    assert '"9.9"' in plain(result.output)
    assert not debug_hub.folder.exists()


def test_leaves_no_run_when_the_start_cannot_write_its_breakpoints(
    debug_hub: DebugHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(folder: Path, addresses: object) -> None:
        raise WorkflowRunError(f"cannot write the run {folder.name}'s breakpoints: disk full")

    monkeypatch.setattr(scenario_debug, "write_breakpoints", refused)
    debug_hub.order("fetched")

    result = debug_hub.start("--break", "2.1")

    assert result.exit_code == 1, result.output
    assert "disk full" in plain(result.output)
    assert not debug_hub.folder.exists()


# AC-507.10: a breakpoint before an asked step answers no gate.

ASKED = """\
version: 2
kind: scenario
name: asked-write
revision: 1
inputs:
  shop_order_id: {required: true}
  personal_name: {required: true}
  aws_account_id: {required: true}
stages:
- name: Fix
  steps:
  - wait_until: order-state
    until: $self.output.order_id != ''
    every: 15s
    timeout: 10m
    capture:
      order_id: $self.output.order_id
  - do: order-set-carrier
    with: {order_id: $CTX.order_id}
"""


def test_opens_the_ask_and_runs_the_action_only_once_approved_when_a_breakpoint_holds_it(
    debug_hub: DebugHub,
) -> None:
    (debug_hub.hub / "scenarios" / "fixture" / "asked-write.yaml").write_text(ASKED)
    git(debug_hub.hub, "add", "-A")
    git(debug_hub.hub, "commit", "-q", "-m", "a scenario with an asked write")
    debug_hub.order("sample")
    account = f"aws_account_id={VALUES['aws_account_id']}"

    started = debug_hub.start(
        "--break", "1.2", "--input", account, name="asked-write", environment="staging"
    )
    stepped = debug_hub.run("scenario", "step", RUN)
    asked = [line for line in debug_hub.records() if line["event"] == "action"]
    refused = debug_hub.run("scenario", "continue", RUN)
    approved = debug_hub.run("workflow", "approve", RUN)

    assert last_line(started) == f"run {RUN}: paused before 1.2 (breakpoint)", started.output
    assert last_line(stepped) == f"run {RUN}: paused at fix--2__ask", stepped.output
    assert [line["node"] for line in asked] == ["fix--1"]
    assert refused.exit_code == 1, refused.output
    assert "not in a debug pause" in plain(refused.output)
    assert (approved.exit_code, last_line(approved)) == (0, f"run {RUN}: done"), approved.output
    lines = debug_hub.records()
    [pause] = [line for line in lines if line["event"] == "debug.pause"]
    assert (pause["node"], pause["block"]) == ("fix--2__ask", "1.2")
    events = [line["event"] for line in lines]
    decided = events.index("decision")
    [ran] = [
        index
        for index, line in enumerate(lines)
        if line.get("node") == "fix--2" and line["event"] == "action"
    ]
    assert decided < ran
    assert [line["command"] for line in lines if line["event"] == "debug.command"] == ["step"]


# AC-507.11: Step runs exactly the next leaf block; Continue runs to the next breakpoint.


def test_runs_one_block_per_step_and_to_the_next_breakpoint_when_continued(
    debug_hub: DebugHub,
) -> None:
    debug_hub.order("fetched")
    started = debug_hub.start("--break", "2.1")

    stepped = debug_hub.run("scenario", "step", RUN)
    debug_hub.order("reviewed")
    added = debug_hub.run("scenario", "break", RUN, "3.3")
    continued = debug_hub.run("scenario", "continue", RUN)
    again = debug_hub.run("scenario", "step", RUN)

    assert last_line(started) == f"run {RUN}: paused before 2.1 (breakpoint)", started.output
    assert stepped.exit_code == 0, stepped.output
    assert last_line(stepped) == f"run {RUN}: paused before 2.2 (step)"
    assert added.exit_code == 0, added.output
    assert last_line(added) == f"run {RUN}: breakpoints 2.1, 3.3"
    assert last_line(continued) == f"run {RUN}: paused before 3.3 (breakpoint)", continued.output
    assert last_line(again) == f"run {RUN}: paused before 3.4 (step)", again.output
    lines = debug_hub.records()
    assert passes(lines) == [
        ["fetch-order--1", "fetch-order--2"],
        ["review--1"],
        ["review--2", "switch-carrier--1", "switch-carrier--2"],
        ["switch-carrier--3"],
    ]
    commands = [line for line in lines if line["event"] == "debug.command"]
    assert [(c["command"], c["approver"], c["node"], c["number"]) for c in commands] == [
        ("step", ACCOUNT, "review--1", 1),
        ("continue", ACCOUNT, "review--2", 2),
        ("step", ACCOUNT, "switch-carrier--3", 3),
    ]
    pauses = [line for line in lines if line["event"] == "debug.pause"]
    assert [(p["block"], p["reason"], p["number"]) for p in pauses] == [
        ("2.1", "breakpoint", 1),
        ("2.2", "step", 2),
        ("3.3", "breakpoint", 3),
        ("3.4", "step", 4),
    ]
    marked = [line["addresses"] for line in lines if line["event"] == "debug.breakpoints"]
    assert marked == [["2.1"], ["2.1", "3.3"]]
    events = debug_hub.stored()
    sent = [event for event in events if event.type == "debug.command"]
    assert [(e.payload["command"], e.payload["approver"], e.step) for e in sent] == [
        ("step", ACCOUNT, "review--1"),
        ("continue", ACCOUNT, "review--2"),
        ("step", ACCOUNT, "switch-carrier--3"),
    ]


def test_steps_one_path_block_at_a_time_when_a_together_is_stepped(debug_hub: DebugHub) -> None:
    debug_hub.order("sample")
    started = debug_hub.start("--break", "1.2", name="blocks-together")

    stepped = debug_hub.run("scenario", "step", RUN)
    continued = debug_hub.run("scenario", "continue", RUN)

    assert last_line(started) == f"run {RUN}: paused before 1.2 (breakpoint)", started.output
    assert last_line(stepped) == f"run {RUN}: paused before 1.2.p2.1 (step)", stepped.output
    assert (continued.exit_code, last_line(continued)) == (0, f"run {RUN}: done")
    assert passes(debug_hub.records()) == [
        ["fix-shipping--1"],
        ["fix-shipping--2-p1-1"],
        ["fix-shipping--2-p2-1", "fix-shipping--2-p2-2", "fix-shipping--3"],
    ]


TWO_PATHS = """\
version: 2
kind: scenario
name: two-paths
revision: 1
inputs:
  shop_order_id: {required: true}
  personal_name: {required: true}
  aws_account_id: {required: true}
stages:
- name: Fix
  steps:
  - wait_until: order-state
    until: $self.output.order_id != ''
    every: 15s
    timeout: 10m
    capture:
      order_id: $self.output.order_id
  - together:
    - - do: order-set-carrier
        with: {order_id: $CTX.order_id}
      - do: queue-send
        with: {message: demo.first-path, order_id: $CTX.order_id}
    - - do: shipments-regenerate
        with: {order_id: $CTX.order_id}
      - do: shipments-mark-in-transit
        with: {order_id: $CTX.order_id}
  - do: queue-send
    with: {message: demo.process-order, order_id: $CTX.order_id}
"""


def test_steps_the_paths_layer_by_layer_when_a_together_holds_two_blocks_per_path(
    debug_hub: DebugHub,
) -> None:
    (debug_hub.hub / "scenarios" / "fixture" / "two-paths.yaml").write_text(TWO_PATHS)
    git(debug_hub.hub, "add", "-A")
    git(debug_hub.hub, "commit", "-q", "-m", "a together of two blocks per path")
    debug_hub.order("sample")
    started = debug_hub.start("--break", "1.2", name="two-paths")

    stepped = [debug_hub.run("scenario", "step", RUN) for _ in range(5)]

    assert last_line(started) == f"run {RUN}: paused before 1.2 (breakpoint)", started.output
    assert [last_line(result) for result in stepped] == [
        f"run {RUN}: paused before 1.2.p2.1 (step)",
        f"run {RUN}: paused before 1.2.p1.2 (step)",
        f"run {RUN}: paused before 1.2.p2.2 (step)",
        f"run {RUN}: paused before 1.3 (step)",
        f"run {RUN}: done",
    ]
    assert passes(debug_hub.records()) == [
        ["fix--1"],
        ["fix--2-p1-1"],
        ["fix--2-p2-1"],
        ["fix--2-p1-2"],
        ["fix--2-p2-2"],
        ["fix--3"],
    ]


def test_pauses_once_before_a_together_when_continued_from_a_step_into_it(
    debug_hub: DebugHub,
) -> None:
    debug_hub.order("sample")
    started = debug_hub.start("--break", "1.1", "--break", "1.2", name="blocks-together")

    stepped = debug_hub.run("scenario", "step", RUN)
    continued = debug_hub.run("scenario", "continue", RUN)

    assert last_line(started) == f"run {RUN}: paused before 1.1 (breakpoint)", started.output
    assert last_line(stepped) == f"run {RUN}: paused before 1.2.p1.1 (step)", stepped.output
    assert (continued.exit_code, last_line(continued)) == (0, f"run {RUN}: done")
    pauses = [line for line in debug_hub.records() if line["event"] == "debug.pause"]
    assert [pause["block"] for pause in pauses] == ["1.1", "1.2.p1.1"]


def test_runs_the_first_body_block_when_a_repeat_is_stepped(debug_hub: DebugHub) -> None:
    debug_hub.order("sample")
    started = debug_hub.start("--break", "1.2", name="blocks-repeat")

    stepped = debug_hub.run("scenario", "step", RUN)
    continued = debug_hub.run("scenario", "continue", RUN)

    assert last_line(started) == f"run {RUN}: paused before 1.2 (breakpoint)", started.output
    assert last_line(stepped) == f"run {RUN}: paused before 1.2.2 (step)", stepped.output
    assert (continued.exit_code, last_line(continued)) == (0, f"run {RUN}: done")
    assert passes(debug_hub.records()) == [
        ["poll-review--1"],
        ["poll-review--2__poll-review--2-1"],
        ["poll-review--2__poll", "poll-review--2"],
    ]


def test_pauses_before_the_next_block_when_a_gate_met_while_stepping_is_answered(
    debug_hub: DebugHub,
) -> None:
    debug_hub.state.write_text(json.dumps({"order_id": "o-1", "order_status": "SHIPPED"}))
    started = debug_hub.start("--break", "1.2", name="blocks-if-else")

    into = debug_hub.run("scenario", "step", RUN)
    gate = debug_hub.run("scenario", "step", RUN)
    refused = debug_hub.run("scenario", "continue", RUN)
    answered = debug_hub.run("workflow", "approve", RUN)

    assert last_line(started) == f"run {RUN}: paused before 1.2 (breakpoint)", started.output
    assert last_line(into) == f"run {RUN}: paused before 1.2.else.1 (step)", into.output
    assert last_line(gate) == f"run {RUN}: paused at check--2-else-1", gate.output
    assert refused.exit_code == 1, refused.output
    assert "not in a debug pause" in plain(refused.output)
    assert last_line(answered) == f"run {RUN}: paused before 1.3 (step)", answered.output
    commands = [line for line in debug_hub.records() if line["event"] == "debug.command"]
    assert [line["command"] for line in commands] == ["step", "step"]


def test_records_no_command_when_the_resume_is_refused_by_a_changed_snapshot(
    debug_hub: DebugHub,
) -> None:
    debug_hub.order("fetched")
    started = debug_hub.start("--break", "2.1")
    snapshot = debug_hub.folder / "snapshot" / "workflow.json"
    snapshot.write_bytes(snapshot.read_bytes() + b" ")
    record = (debug_hub.folder / "records.jsonl").read_bytes()
    stored = debug_hub.stored()

    refused = [debug_hub.run("scenario", command, RUN) for command in ("step", "continue")]

    assert last_line(started) == f"run {RUN}: paused before 2.1 (breakpoint)", started.output
    for result in refused:
        assert result.exit_code == 1, result.output
        assert "content_hash" in plain(result.output)
    assert (debug_hub.folder / "records.jsonl").read_bytes() == record
    assert debug_hub.stored() == stored


# AC-507.12: edits during a pause change nothing of the run.


def test_runs_the_pinned_content_when_the_scenario_and_an_action_are_edited_during_a_pause(
    debug_hub: DebugHub,
) -> None:
    debug_hub.order("fetched")
    started = debug_hub.start("--break", "2.1")
    header = debug_hub.records()[0]
    pinned = (debug_hub.folder / "snapshot" / "workflow.json").read_bytes()
    scenario = debug_hub.hub / "scenarios" / "fixture" / f"{REFERENCE}.yaml"
    edited = scenario.read_text().replace("demo.review-orders", "demo.edited")
    scenario.write_text(
        edited + "- name: Extra\n  steps:\n  - do: queue-send\n    with:\n"
        "      message: demo.extra\n"
    )
    script = debug_hub.hub / "actions" / "fixture" / "scripts" / "fixture_write.sh"
    script.write_text("exit 3\n")
    git(debug_hub.hub, "commit", "-q", "-am", "edit the scenario and an action")

    unknown = debug_hub.run("scenario", "break", RUN, "9.1")
    stepped = debug_hub.run("scenario", "step", RUN)
    debug_hub.order("reviewed")
    added = debug_hub.run("scenario", "break", RUN, "3.5")
    continued = debug_hub.run("scenario", "continue", RUN)

    assert last_line(started) == f"run {RUN}: paused before 2.1 (breakpoint)", started.output
    assert unknown.exit_code == 1, unknown.output
    assert '"9.1"' in plain(unknown.output)
    assert last_line(stepped) == f"run {RUN}: paused before 2.2 (step)", stepped.output
    assert added.exit_code == 0, added.output
    assert last_line(continued) == f"run {RUN}: paused before 3.5 (breakpoint)", continued.output
    lines = debug_hub.records()
    [review] = [line for line in lines if line["event"] == "action" and line["node"] == "review--1"]
    assert review["inputs"]["message"] == "demo.review-orders"
    assert [
        line["status"]
        for line in lines
        if line.get("node") == "review--1" and line["event"] == "step_end"
    ] == ["ok"]
    assert (debug_hub.folder / "snapshot" / "workflow.json").read_bytes() == pinned
    assert snapshot_hash(debug_hub.folder / "snapshot") == header["content_hash"]
    calls = [line for line in lines if line["event"] == "action"]
    assert calls
    assert all(line["content_hash"] == header["actions"][line["action"]] for line in calls)
    assert all(line["status"] == "ok" for line in calls)
    sent = {line["inputs"].get("message") for line in calls}
    assert not sent & {"demo.edited", "demo.extra"}


# AC-507.13: production refuses the debugger and records nothing; clearing stays allowed.


def test_refuses_a_start_with_breakpoints_and_creates_no_run_when_the_environment_is_production(
    debug_hub: DebugHub,
) -> None:
    result = debug_hub.start("--break", "1.1", environment="live")

    assert result.exit_code == 1, result.output
    assert "production" in plain(result.output)
    assert "debug" in plain(result.output)
    assert not debug_hub.folder.exists()


def test_refuses_debug_commands_and_records_nothing_when_the_environment_became_production(
    debug_hub: DebugHub,
) -> None:
    debug_hub.order("fetched")
    started = debug_hub.start("--break", "2.1")
    document = debug_hub.hub_json()
    document["environments"]["local"]["production"] = True
    debug_hub.write_hub_json(document)
    record = (debug_hub.folder / "records.jsonl").read_bytes()
    marked = (debug_hub.folder / "breakpoints.json").read_bytes()
    stored = debug_hub.stored()

    refused = [
        debug_hub.run("scenario", "break", RUN, "3.1"),
        debug_hub.run("scenario", "break", RUN, "--set", "3.1"),
        debug_hub.run("scenario", "step", RUN),
        debug_hub.run("scenario", "continue", RUN),
    ]
    unchanged = (debug_hub.folder / "records.jsonl").read_bytes()
    kept = (debug_hub.folder / "breakpoints.json").read_bytes()
    emitted = debug_hub.stored()
    removed = debug_hub.run("scenario", "break", RUN, "2.1", "--off")
    cleared = debug_hub.run("scenario", "break", RUN, "--set")

    assert last_line(started) == f"run {RUN}: paused before 2.1 (breakpoint)", started.output
    for result in refused:
        assert result.exit_code == 1, result.output
        assert "production" in plain(result.output)
    assert unchanged == record
    assert kept == marked
    assert emitted == stored
    for result in (removed, cleared):
        assert result.exit_code == 0, result.output
        assert last_line(result) == f"run {RUN}: no breakpoints"
    assert json.loads((debug_hub.folder / "breakpoints.json").read_text()) == {"addresses": []}
    lines = debug_hub.records()
    assert [line["addresses"] for line in lines if line["event"] == "debug.breakpoints"] == [
        ["2.1"],
        [],
        [],
    ]
    assert [line for line in lines if line["event"] == "debug.command"] == []


READS = """\
version: 2
kind: scenario
name: two-reads
revision: 1
inputs:
  shop_order_id: {required: true}
  personal_name: {required: true}
  aws_account_id: {required: true}
stages:
- name: Read
  steps:
  - wait_until: order-state
    until: $self.output.order_id != ''
    every: 15s
    timeout: 10m
  - wait_until: order-state
    until: $self.output.approval_job_id != ''
    every: 15s
    timeout: 10m
"""


def test_pauses_at_no_breakpoint_when_a_run_resumes_on_an_environment_now_production(
    debug_hub: DebugHub,
) -> None:
    (debug_hub.hub / "scenarios" / "fixture" / "two-reads.yaml").write_text(READS)
    git(debug_hub.hub, "add", "-A")
    git(debug_hub.hub, "commit", "-q", "-m", "a read-only scenario")
    debug_hub.order("sample")
    started = debug_hub.start("--break", "1.1", "--break", "1.2", name="two-reads")
    document = debug_hub.hub_json()
    document["environments"]["local"]["production"] = True
    debug_hub.write_hub_json(document)

    resumed = debug_hub.run("workflow", "run", "--resume", RUN)

    assert last_line(started) == f"run {RUN}: paused before 1.1 (breakpoint)", started.output
    assert (resumed.exit_code, last_line(resumed)) == (0, f"run {RUN}: done"), resumed.output
    pauses = [line for line in debug_hub.records() if line["event"] == "debug.pause"]
    assert [pause["block"] for pause in pauses] == ["1.1"]


# breakpoints.json: replaced whole, read through no link; a bad one is no breakpoint.


def test_adds_removes_and_replaces_breakpoints_when_break_runs(debug_hub: DebugHub) -> None:
    debug_hub.order("fetched")
    debug_hub.start("--break", "2.2")

    added = debug_hub.run("scenario", "break", RUN, "2.1", "1")
    removed = debug_hub.run("scenario", "break", RUN, "2.2", "--off")
    replaced = debug_hub.run("scenario", "break", RUN, "--set", "3", "2")
    both = debug_hub.run("scenario", "break", RUN, "--set", "--off", "3")
    none = debug_hub.run("scenario", "break", RUN)

    assert last_line(added) == f"run {RUN}: breakpoints 1, 2.1, 2.2", added.output
    assert last_line(removed) == f"run {RUN}: breakpoints 1, 2.1", removed.output
    assert last_line(replaced) == f"run {RUN}: breakpoints 2, 3", replaced.output
    assert both.exit_code == 2, both.output
    assert none.exit_code == 2, none.output
    assert json.loads((debug_hub.folder / "breakpoints.json").read_text()) == {
        "addresses": ["2", "3"]
    }
    assert not [path.name for path in debug_hub.folder.iterdir() if path.name.endswith(".tmp")]


# Each bad breakpoints file, and a word of the reason it counts as none.
BAD_FILES = {
    "junk": "is not an object",
    "link": "cannot be read",
    "unknown": 'names "9.9"',
    "large": "regular file",
    "fifo": "regular file",
}


@pytest.mark.parametrize("kind", sorted(BAD_FILES))
def test_counts_no_breakpoint_and_records_why_when_the_breakpoints_file_is_bad(
    debug_hub: DebugHub, tmp_path: Path, kind: str
) -> None:
    debug_hub.order("sample")
    started = debug_hub.start("--break", "1.2", name="blocks-together")
    marked = debug_hub.folder / "breakpoints.json"
    marked.unlink()
    if kind == "junk":
        marked.write_text("{not json")
    elif kind == "link":
        elsewhere = tmp_path / "elsewhere.json"
        elsewhere.write_text(json.dumps({"addresses": ["1.3"]}))
        marked.symlink_to(elsewhere)
    elif kind == "unknown":
        marked.write_text(json.dumps({"addresses": ["1.3", "9.9"]}))
    elif kind == "large":
        marked.write_text(json.dumps({"addresses": ["1.3"], "pad": "x" * (64 << 10)}))
    else:
        os.mkfifo(marked)

    continued = debug_hub.run("scenario", "continue", RUN)

    assert last_line(started) == f"run {RUN}: paused before 1.2 (breakpoint)", started.output
    assert (continued.exit_code, last_line(continued)) == (0, f"run {RUN}: done"), continued.output
    lines = debug_hub.records()
    unreadable = [line for line in lines if line["event"] == "debug.breakpoints_unreadable"]
    assert len(unreadable) == 1
    assert BAD_FILES[kind] in unreadable[0]["reason"]
    assert [line for line in lines if line["event"] == "debug.pause"][1:] == []


# A version-1 run has no addresses; Step and Continue only in a debug pause.

GRAPH = """\
version: 1
kind: scenario
name: graph-walk
revision: 1
inputs:
  shop_order_id: {required: true}
  personal_name: {required: true}
  aws_account_id: {required: true}
nodes:
  - id: read-order
    type: expect
    action: order-state
    every: 15s
    timeout: 10m
    until_when: "$self.output.order_id != ''"
"""


def test_refuses_debugging_with_a_plain_reason_when_the_scenario_is_a_graph(
    debug_hub: DebugHub,
) -> None:
    (debug_hub.hub / "scenarios" / "fixture" / "graph-walk.yaml").write_text(GRAPH)
    git(debug_hub.hub, "add", "-A")
    git(debug_hub.hub, "commit", "-q", "-m", "a graph scenario")
    debug_hub.order("sample")

    refused_start = debug_hub.start("--break", "1.1", name="graph-walk")
    ran = debug_hub.start(name="graph-walk")
    refused = [
        debug_hub.run("scenario", "break", RUN, "1.1"),
        debug_hub.run("scenario", "step", RUN),
        debug_hub.run("scenario", "continue", RUN),
    ]

    assert refused_start.exit_code == 1, refused_start.output
    assert "version 1" in plain(refused_start.output)
    assert (ran.exit_code, last_line(ran)) == (0, f"run {RUN}: done"), ran.output
    for result in refused:
        assert result.exit_code == 1, result.output
        assert "version 1" in plain(result.output)
    assert not (debug_hub.folder / "breakpoints.json").exists()
    assert [line for line in debug_hub.records() if line["event"].startswith("debug.")] == []
