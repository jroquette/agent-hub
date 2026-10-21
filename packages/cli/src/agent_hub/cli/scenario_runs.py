"""A scenario run: ``hub scenario run``'s start, the engine's action runner, and the resume
(docs/design/scenarios.md § Plan and modes; ADR 0041).

A scenario run is a WorkflowRun of a ``kind: scenario`` document (``workflow_runs``): its folder
is ``.agent-runs/workflows/<run>/``, its events are labelled ``workflow: scenario:<name>``. The
caller plans the scenario first and starts nothing on a ``deny``, an undeclared environment or
any other plan problem. ``start`` then writes the snapshot: the document and its includes,
``policy_gates.json`` (each step the policy answered ``ask``, with its action, effect and
environment), and exactly the files each used action's ``content_hash`` pinned (its document,
script and pack helpers, as read: E-4) at their hub paths, ``actions/<pack>/…``. The start
record names the run's kind, label, environment and mode, and pins each action's hash
(``actions``) and the gated steps (``policy_gates``).

The run (and every resume, from ``hub workflow run --resume|approve|reject``) is planned from
the snapshot alone: the document with a ``<step>__ask`` approval before each gated step
(``policy_gates``), the actions read back from the snapshot and checked against their pins. So
an action edited during the run changes neither what runs nor its hash, and a resume takes up
the gates as recorded.

``action_runs.ActionExecutors`` is the engine's ``NodeRunner``: each ``action`` or ``expect`` call
is decided again (the effective config as loaded when this process started or resumed the run),
then runs from the pinned files with its credentials; its trace and events are ``ActionLog``'s.

A call that may have run is never repeated silently. The ``action_start`` line of a write or
destroy is synced to disk before its process starts; on resume, the re-asks it owes and a
recorded reject of a policy gate are ``workflow_policy``'s rules, shared with process workflows.

The run's folder is removed when anything fails before its start record is written; the
snapshot keeps the includes the plan resolved, not a second read.

Only ``regression`` mode runs here: no agent starts, and a divergence (a failed action, an
``expect`` timeout, an output contract failure) fails the scenario run, printing ``step <id>:
<kind>: <detail>``; a policy ask or an ``approval`` still pauses it.
"""

import json
import os
import random
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import typer

from agent_hub.cli.action_runs import (
    ActionExecutors,
    ActionLog,
    action_effects,
    approvers,
    pinned_actions,
    pinned_files,
)
from agent_hub.cli.collect import hub_project_name
from agent_hub.cli.effective_config import load_effective_config_or_exit
from agent_hub.cli.init_report import shown_text
from agent_hub.cli.run_log import now
from agent_hub.cli.workflow_command import own_hub_program
from agent_hub.cli.workflow_executors import WorkflowExecutors
from agent_hub.cli.workflow_policy import (
    GATES,
    Owed,
    gated_run_plan,
    gates_file,
    read_gates,
    record_asks,
    rejected,
    resumed_prior,
)
from agent_hub.cli.workflow_policy import owed as _owed
from agent_hub.cli.workflow_runs import (
    DOCUMENT,
    SNAPSHOT,
    EventSink,
    RecordedAnswers,
    RecordedRun,
    SystemClock,
    WorkflowRunError,
    append_record,
    ends_of,
    held_record,
    make_run,
    read_records,
    run_folder,
    run_lock,
    snapshot_includes,
    snapshot_run,
)
from agent_hub.core.hub_config.effective_environments import (
    effective_environments,
)
from agent_hub.core.json_form import JsonValue
from agent_hub.core.scenarios.credentials import CredentialNames
from agent_hub.core.scenarios.policy_gates import (
    PolicyAsk,
)
from agent_hub.core.scenarios.scenario_events import ScenarioEvents
from agent_hub.core.scenarios.scenario_plan import ScenarioPlan
from agent_hub.core.workflows.document import WorkflowDocument, WorkflowLoadError, parse_workflow
from agent_hub.core.workflows.engine import EnginePorts, run_workflow
from agent_hub.core.workflows.events import WorkflowEvents
from agent_hub.core.workflows.includes import IncludeResolver
from agent_hub.core.workflows.plan import WorkflowPlan, plan_workflow
from agent_hub.core.workflows.ports import (
    RunEnd,
)
from agent_hub.generator.action_discovery import ActionDiscovery
from agent_hub.generator.scenario_discovery import discover_scenarios
from agent_hub.generator.workflow_discovery import DiscoveredWorkflow, pack_resolver
from agent_hub.generator.workflow_outputs import JsonSchemaOutputs
from agent_hub.generator.workflow_yaml import WorkflowMapping

KIND: Final = "scenario"
REGRESSION: Final = "regression"
INTERACTIVE: Final = "interactive"
MODES: Final = (INTERACTIVE, REGRESSION)
# Release gate (O-6): interactive mode lands with the investigation (T9).
INTERACTIVE_NOT_YET: Final = "interactive mode is not available yet: use --mode regression"
CONTEXT_CAPTURE: Final = "context.capture"
ACTION_CALL: Final = "action"
# A retry's jitter: spread, not secrecy.
_JITTER: Final = random.SystemRandom()


def scenario_label(name: str) -> str:
    """The ``workflow`` a scenario run's records and events carry: ``scenario:<name>``."""
    return f"{KIND}:{name}"


@dataclass(frozen=True, kw_only=True, slots=True)
class ScenarioStart:
    """What a scenario run starts from: the scenario as discovered and planned, its plan in the
    environment (no problem, no deny), the hub's actions and the inputs, defaults filled."""

    plan: WorkflowPlan
    found: DiscoveredWorkflow
    planned: ScenarioPlan
    actions: ActionDiscovery
    inputs: dict[str, JsonValue]
    mode: str
    # Each scenario the plan included, as resolved while planning: the snapshot keeps them.
    included: Mapping[str, WorkflowMapping]


def load_scenario(
    hub: Path, name: str
) -> tuple[WorkflowPlan, DiscoveredWorkflow, dict[str, WorkflowMapping]] | None:
    """The scenario ``name`` planned from one read of ``scenarios/``, with the includes that
    plan resolved (what a scenario run snapshots); ``None`` when there is no such scenario."""
    discovery = discover_scenarios(hub)
    found = next((item for item in discovery.workflows if item.name == name), None)
    if found is None:
        return None
    included: dict[str, WorkflowMapping] = {}
    resolver = pack_resolver(discovery, found.pack_root, used=included)
    try:
        plan = plan_workflow(parse_workflow(found.document), includes=resolver)
    except WorkflowLoadError as error:
        raise WorkflowRunError(f"cannot plan the scenario {name}: {error}") from None
    return plan, found, included


def start(hub: Path, run_id: str, begin: ScenarioStart) -> int:
    """Make the scenario run ``run_id``: its snapshot and start record, then run it; the exit
    code (0 done or paused, 1 otherwise). A snapshot that cannot be written leaves no run."""
    folder = run_folder(hub, run_id)
    make_run(folder)
    begun = False
    try:
        with run_lock(folder):
            header = _begin(folder, begin)
            begun = True
            inputs: dict[str, JsonValue] = {"event": "inputs", "inputs": begin.inputs}
            append_record(folder, inputs)
            return execute(hub, folder, [header, inputs], resumed=False)
    except BaseException:
        if not begun:
            # Nothing ran: a half-made run is not left to resume.
            shutil.rmtree(folder, ignore_errors=True)
        raise


def _begin(folder: Path, begin: ScenarioStart) -> dict[str, JsonValue]:
    """Write the snapshot, then the start record; the start record."""
    content_hash = _snapshot(folder, begin)
    planned, document = begin.planned, begin.plan.document
    header: dict[str, JsonValue] = {
        "event": "start",
        "run": folder.name,
        "workflow": scenario_label(document.name),
        "kind": KIND,
        "scenario": document.name,
        "pack": begin.found.pack,
        "revision": document.revision,
        "content_hash": content_hash,
        "environment": planned.environment,
        "mode": begin.mode,
        "actions": {row.action: row.content_hash for row in planned.rows},
        "policy_gates": list[JsonValue](sorted(_asks(planned))),
    }
    append_record(folder, header)
    return header


def resume(hub: Path, folder: Path, records: list[dict[str, JsonValue]]) -> int:
    """Continue a scenario run from its snapshot and records (the caller holds its lock and
    checked its snapshot's hash); its gates' answers are the recorded decisions."""
    append_record(folder, {"event": "resume"})
    return execute(hub, folder, records, resumed=True)


def execute(hub: Path, folder: Path, records: list[dict[str, JsonValue]], *, resumed: bool) -> int:
    """Run the scenario run in ``folder`` on the engine, as its snapshot pins it."""
    header, snapshot = records[0], folder / SNAPSHOT
    environment, pack = str(header.get("environment")), str(header.get("pack"))
    pinned = pinned_actions(snapshot, header)
    document, includes, recorded = _snapshot_parts(snapshot)
    owed = Owed()
    if resumed:
        base = _planned(document, includes, {})
        owed = _owed(
            folder,
            records,
            plan=base,
            effects=action_effects(base, pinned, pack),
            environment=environment,
        )
    record_asks(folder, owed.steps)
    asks = recorded | owed.steps
    plan = _planned(document, includes, asks)
    effective = load_effective_config_or_exit(hub)
    view = effective_environments(effective.config, effective.local)
    hidden = CredentialNames.of(view)
    run_id, label = folder.name, str(header.get("workflow"))
    project = hub_project_name(hub) or hub.name
    revision = header.get("revision")
    events = WorkflowEvents(
        project=project,
        run_id=run_id,
        workflow=label,
        revision=revision if isinstance(revision, int) else 0,
        content_hash=str(header.get("content_hash")),
        end_index=len(ends_of(records)),
    )
    log = ActionLog(
        folder=folder,
        events=ScenarioEvents(project=project, run_id=run_id, workflow=label),
        sink=EventSink(),
    )
    inner = WorkflowExecutors(
        hub=hub,
        config=effective.config,
        run_id=run_id,
        pack_root=snapshot,
        environ=os.environ,
        hub_program=own_hub_program(),
        hidden=hidden,
    )
    runner = ActionExecutors(
        hub=hub,
        environment=environment,
        view=view,
        roots=(hub.name, *(repo.dir for repo in effective.config.repos)),
        pack=pack,
        pinned=pinned,
        asks=frozenset(asks),
        approvers=approvers(records),
        log=log,
        inner=inner,
        environ=os.environ,
    )
    ports = EnginePorts(
        runner,
        RecordedRun(folder=folder, events=events, sink=EventSink()),
        SystemClock(),
        JsonSchemaOutputs(),
        _JITTER.random,
        None,
        max_parallel=inner.max_parallel,
        interrupt=runner.stop_children,
        gates=RecordedAnswers(records),
        trace=log,
    )
    if resumed and (cancelled := rejected(records)) is not None:
        # A recorded reject of a policy gate ends the run, whatever the plan holds now.
        ports.recorder.run_ended(RunEnd("cancelled", now(), reason=cancelled))
        typer.echo(f"run {run_id}: cancelled")
        return 1
    inputs = next((r["inputs"] for r in records if r.get("event") == "inputs"), {})
    report = run_workflow(
        plan,
        inputs if isinstance(inputs, dict) else {},
        ports,
        prior=resumed_prior(records, owed.reopen) if resumed else None,
    )
    append_record(folder, {"event": "sessions", "sessions": dict(report.state.sessions)})
    if report.status == "paused":
        append_record(folder, held_record(report.state))
        typer.echo(f"run {run_id}: paused at {report.reason}")
        return 0
    typer.echo(f"run {run_id}: {report.status}")
    if report.status == "failed" and report.reason is not None:
        typer.echo(_divergence(folder, report.reason))
    return 0 if report.status == "done" else 1


def _divergence(folder: Path, step: str) -> str:
    """``step <id>: <kind>: <detail>`` from the step's last failed end in the record."""
    ends = [
        record
        for record in read_records(folder)
        if record.get("event") == "step_end"
        and record.get("node") == step
        and record.get("status") == "failed"
    ]
    last = ends[-1] if ends else {}
    kind, detail = str(last.get("failure_kind") or "failed"), last.get("detail")
    shown = shown_text(detail) if isinstance(detail, str) and detail else ""
    return f"step {step}: {kind}" + (f": {shown}" if shown else "")


def _asks(planned: ScenarioPlan) -> dict[str, PolicyAsk]:
    """Each step the policy asks before, by its id as recorded."""
    return {
        row.step: PolicyAsk(action=row.action, effect=row.effect, environment=planned.environment)
        for row in planned.rows
        if row.decision == "ask"
    }


def _snapshot(folder: Path, begin: ScenarioStart) -> str:
    """Write the snapshot (document, includes, gates and the pinned action files); its hash."""
    pinned = pinned_files(begin.actions, frozenset(row.action for row in begin.planned.rows))
    pinned[GATES] = gates_file(_asks(begin.planned))
    _, content_hash = snapshot_run(
        folder,
        document=dict(begin.found.document),
        plan=begin.plan,
        pack_root=begin.found.pack_root,
        includes=dict(begin.included),
        pinned=pinned,
    )
    return content_hash


def _snapshot_parts(
    snapshot: Path,
) -> tuple[WorkflowDocument, IncludeResolver, dict[str, PolicyAsk]]:
    """The snapshot's document, its includes and the gates ``policy_gates.json`` names."""
    try:
        document = parse_workflow(json.loads((snapshot / DOCUMENT).read_bytes()))
        asks = read_gates(json.loads((snapshot / GATES).read_bytes()))
    except (OSError, ValueError, WorkflowLoadError) as error:
        raise WorkflowRunError(f"cannot load the scenario run's snapshot: {error}") from None
    return document, snapshot_includes(snapshot), asks


def _planned(
    document: WorkflowDocument, includes: IncludeResolver, asks: Mapping[str, PolicyAsk]
) -> WorkflowPlan:
    """The run's plan, a gate before each step of ``asks``."""
    return gated_run_plan(document, includes, asks)
