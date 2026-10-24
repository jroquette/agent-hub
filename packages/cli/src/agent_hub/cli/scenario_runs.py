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

No agent starts here. In ``regression`` mode a divergence (a failed action, an ``expect``
timeout, an output contract failure) fails the scenario run, printing ``step <id>: <kind>:
<detail>``; a policy ask or an ``approval`` still pauses it. In ``interactive`` mode (the
default) a divergence pauses it at an investigation gate instead (``scenario_investigation``),
at most ``MAX_INVESTIGATIONS`` times; the resume first acts on the gate's answer (``stop``,
``pick`` with its workaround, ``retry``), and refuses while the gate has none. A resume whose
record holds a divergence and no investigation after it (a crash came between) opens that
investigation instead of running the step again.
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
from agent_hub.cli.scenario_debug import on_production, record_breakpoints, run_control
from agent_hub.cli.scenario_investigation import (
    LIMIT_REACHED,
    AnswerPorts,
    Divergence,
    HeldEnd,
    answer,
    gate_recorded,
    investigations,
    open_investigation,
    owed_investigation,
    paused_line,
)
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
from agent_hub.core.runs.workflow_run import scenario_label
from agent_hub.core.scenarios.credentials import CredentialNames
from agent_hub.core.scenarios.investigation import CHOICES, MAX_INVESTIGATIONS, PICK, STOP
from agent_hub.core.scenarios.policy_gates import (
    PolicyAsk,
)
from agent_hub.core.scenarios.run_record import (
    DEBUG_PAUSE,
    DebugResume,
    InvestigationView,
    RunRecordError,
    ScenarioRunView,
    debug_pause_line,
    debug_resume,
    fold_records,
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
from agent_hub.core.workflows.run_control import DebugPause
from agent_hub.core.workflows.run_state import RunReport, RunState
from agent_hub.generator.action_discovery import ActionDiscovery
from agent_hub.generator.scenario_discovery import discover_scenarios
from agent_hub.generator.workflow_discovery import DiscoveredWorkflow, pack_resolver
from agent_hub.generator.workflow_outputs import JsonSchemaOutputs
from agent_hub.generator.workflow_yaml import WorkflowMapping

KIND: Final = "scenario"
REGRESSION: Final = "regression"
INTERACTIVE: Final = "interactive"
MODES: Final = (INTERACTIVE, REGRESSION)
CONTEXT_CAPTURE: Final = "context.capture"
ACTION_CALL: Final = "action"
# A retry's jitter: spread, not secrecy.
_JITTER: Final = random.SystemRandom()


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
    # The run's breakpoints from its start, addresses of its tree (``scenario_debug``).
    breakpoints: tuple[str, ...] = ()


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
    code (0 done or paused, 1 otherwise). A snapshot, start record, inputs or breakpoints that
    cannot be written leave no run."""
    folder = run_folder(hub, run_id)
    make_run(folder)
    begun = False
    try:
        with run_lock(folder):
            header = _begin(folder, begin)
            inputs: dict[str, JsonValue] = {"event": "inputs", "inputs": begin.inputs}
            append_record(folder, inputs)
            if begin.breakpoints:
                record_breakpoints(hub, folder, begin.breakpoints, header=header)
            begun = True
            return execute(hub, folder, read_records(folder), resumed=False)
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
    checked its snapshot's hash); its gates' answers are the recorded decisions. A recorded
    reject of a policy gate cancels it before anything else; otherwise an open investigation
    must have its answer first."""
    view = fold_records(records)
    pending = view.open_investigation
    last = view.investigations[-1] if view.investigations else None
    if pending is None and last is not None and view.status is None and _unfinished(view, last):
        # A stop, or a pick whose workaround did not end ok, closed its gate and the run
        # stopped before what follows: it still cancels, or opens the next investigation.
        pending = last
    waiting = pending is not None and pending.choice is None and gate_recorded(records, pending)
    if pending is not None and waiting and rejected(records) is None:
        raise WorkflowRunError(
            f"the scenario run {folder.name} is paused at the investigation of step"
            f" {pending.step}: answer it with hub workflow respond {folder.name} --node"
            f" {pending.gate} --choice {'|'.join(CHOICES)}"
        )
    try:
        # Read before the resume line: after it, the pause is no longer the run's.
        debug = debug_resume(records)
    except RunRecordError as error:
        raise WorkflowRunError(f"cannot resume the run {folder.name}: {error}") from None
    append_record(folder, {"event": "resume"})
    return execute(hub, folder, records, resumed=True, answered=pending, debug=debug)


def _unfinished(view: ScenarioRunView, last: InvestigationView) -> bool:
    """Whether the closed ``last`` investigation's answer still owes its outcome: a stop owes
    the run's end, a pick whose workaround ended other than ``ok`` owes a new investigation."""
    if last.choice == STOP:
        return True
    ended = next(
        (item.status for item in view.workarounds if item.workaround_id == f"w{last.number}"),
        None,
    )
    return last.choice == PICK and ended is not None and ended != "ok"


def execute(
    hub: Path,
    folder: Path,
    records: list[dict[str, JsonValue]],
    *,
    resumed: bool,
    answered: InvestigationView | None = None,
    debug: DebugResume | None = None,
) -> int:
    """Run the scenario run in ``folder`` on the engine, as its snapshot pins it, after acting
    on ``answered``, the answered investigation it was paused at; ``debug`` is the debug pause
    it resumes from, whose pass it goes on with."""
    header, snapshot = records[0], folder / SNAPSHOT
    environment, pack = str(header.get("environment")), str(header.get("pack"))
    pinned = pinned_actions(snapshot, header)
    content = _pinned(snapshot)
    document, includes, recorded = _snapshot_parts(snapshot, content)
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
    recorder = RecordedRun(folder=folder, events=events, sink=EventSink())
    roots = (hub.name, *(repo.dir for repo in effective.config.repos))
    if resumed and (cancelled := rejected(records)) is not None:
        # A recorded reject of a policy gate ends the run first, whatever else the record
        # owes (an investigation's answer, a divergence) or the plan holds now.
        recorder.run_ended(RunEnd("cancelled", now(), reason=cancelled))
        typer.echo(f"run {run_id}: cancelled")
        return 1
    base = _planned(document, includes, {}) if resumed else None
    if answered is not None:
        given = AnswerPorts(
            hub=hub,
            folder=folder,
            header=header,
            records=records,
            recorded=recorder,
            log=log,
            inner=inner,
            roots=roots,
        )
        if (code := answer(given, answered)) is not None:
            return code
        records = read_records(folder)
    elif base is not None and header.get("mode") == INTERACTIVE:
        if (owed_by := owed_investigation(base, records)) is not None:
            # A crash came between a divergence and its investigation: it opens now.
            return _owed_divergence(
                folder, header, recorder, divergence=owed_by, opened=investigations(records)
            )
    owed = Owed()
    if base is not None:
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
    runner = ActionExecutors(
        hub=hub,
        environment=environment,
        view=view,
        roots=roots,
        pack=pack,
        pinned=pinned,
        asks=frozenset(asks),
        approvers=approvers(records),
        log=log,
        inner=inner,
        environ=os.environ,
    )
    held = None
    if header.get("mode") == INTERACTIVE:
        held = HeldEnd(recorder=recorder, plan=plan, opened=investigations(records))
    control = run_control(
        folder,
        content,
        plan,
        records=records,
        resumed=None if debug is None else debug.pause,
        production=on_production(view, environment),
        note=lambda line: _noted(log, line),
    )
    ports = EnginePorts(
        runner,
        held or recorder,
        SystemClock(),
        JsonSchemaOutputs(),
        _JITTER.random,
        None,
        max_parallel=inner.max_parallel,
        interrupt=runner.stop_children,
        gates=RecordedAnswers(records),
        trace=log,
        control=control,
    )
    inputs = next((r["inputs"] for r in records if r.get("event") == "inputs"), {})
    report = run_workflow(
        plan,
        inputs if isinstance(inputs, dict) else {},
        ports,
        prior=_prior(records, owed, debug) if resumed else None,
    )
    append_record(folder, {"event": "sessions", "sessions": dict(report.state.sessions)})
    pauses = sum(1 for record in records if record.get("event") == DEBUG_PAUSE)
    return _reported(folder, header, report, held=held, recorder=recorder, log=log, pauses=pauses)


def _prior(records: list[dict[str, JsonValue]], owed: Owed, debug: DebugResume | None) -> RunState:
    """The state a resume starts from: the records', with the pass a debug pause stopped."""
    prior = resumed_prior(records, owed.reopen)
    return prior if debug is None else debug.applied_to(prior)


def _noted(log: ActionLog, line: dict[str, JsonValue]) -> None:
    """Append ``line`` beside the action lines a run writes from its threads."""
    with log.lock:
        append_record(log.folder, line)


def _debug_paused(
    folder: Path, state: RunState, *, pause: DebugPause, log: ActionLog, number: int
) -> int:
    """Record the run's ``number``-th debug pause, ``state``'s ``pause`` (the pass it stopped in
    the ``debug.pause`` line; its groups are in the ``held`` line) and its event; exit 0."""
    with log.lock:
        append_record(folder, debug_pause_line(state, number=number))
        log.events.debug_paused(pause, number=number, at=now())
        log.sink.flush(log.events)
    typer.echo(f"run {folder.name}: paused before {pause.block} ({pause.reason})")
    return 0


def _owed_divergence(
    folder: Path,
    header: Mapping[str, JsonValue],
    recorder: RecordedRun,
    *,
    divergence: Divergence,
    opened: int,
) -> int:
    """Open the investigation ``divergence`` is owed, or past the limit end the run
    ``failed`` as the engine's pass would have; the exit code."""
    run_id, step = folder.name, divergence.step
    if opened >= MAX_INVESTIGATIONS:
        recorder.run_ended(RunEnd("failed", now(), reason=step))
        typer.echo(f"run {run_id}: failed")
        typer.echo(f"{_divergence(folder, step)} {LIMIT_REACHED}")
        return 1
    typer.echo(_divergence(folder, step))
    open_investigation(
        folder,
        recorder,
        step=step,
        step_attempt=divergence.attempt,
        failure_kind=divergence.failure_kind,
        number=opened + 1,
    )
    typer.echo(paused_line(run_id, str(header.get("scenario")), step))
    return 0


def _reported(
    folder: Path,
    header: Mapping[str, JsonValue],
    report: RunReport,
    *,
    held: HeldEnd | None,
    recorder: RecordedRun,
    log: ActionLog,
    pauses: int,
) -> int:
    """Print how the pass ended (an investigation it opened, or a debug pause, the run's
    ``pauses + 1``-th, included); its exit code."""
    run_id = folder.name
    if report.status == "paused":
        append_record(folder, held_record(report.state))
        if (pause := report.state.pause) is not None:
            return _debug_paused(folder, report.state, pause=pause, log=log, number=pauses + 1)
        typer.echo(f"run {run_id}: paused at {report.reason}")
        return 0
    if held is not None and held.held is not None and (step := held.held.reason) is not None:
        attempt, kind = held.failed[step]
        typer.echo(_divergence(folder, step))
        open_investigation(
            folder,
            recorder,
            step=step,
            step_attempt=attempt,
            failure_kind=kind,
            number=held.opened + 1,
        )
        typer.echo(paused_line(run_id, str(header.get("scenario")), step))
        return 0
    typer.echo(f"run {run_id}: {report.status}")
    if report.status == "failed" and report.reason is not None:
        capped = held is not None and held.capped
        typer.echo(_divergence(folder, report.reason) + (f" {LIMIT_REACHED}" if capped else ""))
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


def _pinned(snapshot: Path) -> object:
    """The snapshot's document as written: a tree for a version-2 scenario."""
    try:
        return json.loads((snapshot / DOCUMENT).read_bytes())
    except (OSError, ValueError) as error:
        raise WorkflowRunError(f"cannot load the scenario run's snapshot: {error}") from None


def _snapshot_parts(
    snapshot: Path, content: object
) -> tuple[WorkflowDocument, IncludeResolver, dict[str, PolicyAsk]]:
    """The snapshot's document, ``content`` parsed, its includes and the gates
    ``policy_gates.json`` names."""
    try:
        document = parse_workflow(content)
        asks = read_gates(json.loads((snapshot / GATES).read_bytes()))
    except (OSError, ValueError, WorkflowLoadError) as error:
        raise WorkflowRunError(f"cannot load the scenario run's snapshot: {error}") from None
    return document, snapshot_includes(snapshot), asks


def _planned(
    document: WorkflowDocument, includes: IncludeResolver, asks: Mapping[str, PolicyAsk]
) -> WorkflowPlan:
    """The run's plan, a gate before each step of ``asks``."""
    return gated_run_plan(document, includes, asks)
