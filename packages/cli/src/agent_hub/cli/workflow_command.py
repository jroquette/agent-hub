"""``hub workflow list|validate|run|test``: the hub's workflows, loaded, planned, run and tested.

The generator's ``discover_workflows`` finds the hub's ``workflows/<pack>/`` files, then the
built-ins (a hub workflow overrides a built-in of its name), through the strict YAML loader; core's
``check_workflows`` loads and plans each one. ``list`` prints one line per workflow that loads,
``<name>  <nodes> nodes  <description>``; ``validate [NAME]`` prints ``<name>: valid (<nodes> nodes
in <layers> layers)``. Each problem is one stderr line, ``<file>[:<line>]: <key>: <message>`` (the
key is ``$`` for a file that does not read), and any problem exits 1. A folder that is not a hub
exits 2. Nothing is written and no network is used.

``run NAME [--input name=value]...`` prints each node a run would start, layer by layer; with
``--live`` the engine runs it through ``workflow_executors`` (``--run-id`` names the run, else a
fresh id), recording it with ``workflow_runs``. ``--resume RUN`` continues a failed or unended run
on its snapshot, reusing what completed; ``--abandon RUN`` ends it ``cancelled``. A run that
reaches an ``approval`` or ``wait`` without its answer or time pauses there (``run <id>: paused at
<node>``, exit 0); its resume takes the gate up again, and pauses again until the gate's decision
is recorded or its time has come. A run that ends ``done`` exits 0, any other end 1; a bad input
exits 2. It makes no tracker write, except for
the workflow named ``issue-to-pr``, whose parent is ``hub run``'s (``workflow_delivery``): the
issue read before, ``hub run``'s records (and so its events) during, ADR 0030's writes after,
and ``hub run``'s exit codes; there ``issue_text`` comes from the tracker, never from ``--input``,
the workflow must declare ``issue``, ``repo`` and ``issue_text``, and ``--resume`` or
``--abandon`` of such a run exits 2. ``hub run --live`` is that run (``run_delivery``), without
a workflow folder: ``hub run``'s records are its only record.
``approve|reject|respond RUN [NODE] [TEXT]`` decide a paused run's open gate (``DecideGate``)
under the run's lock, then resume it as ``--resume`` does. NODE may be left out while the run has
one open gate; a single word after RUN that names no open gate is the TEXT. ``approve`` and
``reject`` give those decisions; ``respond`` answers with ``--choice`` (a declared decision or
option) and/or TEXT. The decision and its text go to the run's record, a ``control_plane``
``gate.result`` to the events; a gate that is not open, already decided or cannot take the
answer is refused (exit 1). ``decide RUN --gate GATE`` (hidden: hub web's decisions) records one
decision for that exact open gate, ``--choice`` and the text read from stdin with ``--text-stdin``
(UTF-8, at most 64 KiB), as taken in ``web``, and does not resume the run.

``test [NAME]...`` dry-runs each fixture of the discovered packs (or the NAMEs', each file once)
in memory through the engine (generator's ``run_fixtures``): one ``<file>: ok|FAILED`` line
each, its problems and warnings indented, then a count; a failed fixture, or a NAME with none,
exits 1. ``--stubs-init`` writes one NAME's skeleton fixture to ``<pack>/fixtures/<NAME>.yaml``,
never over an existing file nor through a linked folder, and notes when the skeleton's own dry
run did not end ``done``.
"""

import getpass
import json
import os
import random
import shutil
import sys
from pathlib import Path
from typing import Annotated, Final

import typer
from typer._click.exceptions import ClickException

from agent_hub.cli.collect import hub_project_name
from agent_hub.cli.command_exits import FAILURE, fail
from agent_hub.cli.errors import RunLogError
from agent_hub.cli.hub_config_reader import FILE_LABEL, load_hub_config_or_exit
from agent_hub.cli.hub_root import hub_checkout, hub_root_or_exit
from agent_hub.cli.init_report import shown_path, shown_text
from agent_hub.cli.run_children import CHILD_HIDDEN, shown_command, without
from agent_hub.cli.run_log import new_run_id, now, open_default_event_store
from agent_hub.cli.workflow_checkout import GitCheckoutProbe
from agent_hub.cli.workflow_delivery import (
    ISSUE_TEXT,
    ISSUE_TO_PR,
    IssueToPr,
    begin_delivery,
    delivery_problem,
)
from agent_hub.cli.workflow_executors import WorkflowExecutors
from agent_hub.cli.workflow_runs import (
    DOCUMENT,
    RECORDS,
    RUN_ID_PATTERN,
    SNAPSHOT,
    EventSink,
    RecordedAnswers,
    RecordedGates,
    RecordedRun,
    SystemClock,
    WorkflowRunError,
    append_record,
    drop_torn_tail,
    ends_of,
    held_record,
    make_run,
    prior_state,
    read_records,
    run_folder,
    run_lock,
    snapshot_hash,
    snapshot_includes,
    snapshot_run,
)
from agent_hub.core.approvals.decide_gate import (
    MAX_TEXT_BYTES,
    DecideGate,
    GateDecision,
    GateDecisionError,
    RequestedGate,
)
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.ingestion.ingest_events import IngestEvents
from agent_hub.core.json_form import JsonValue
from agent_hub.core.workflows.catalog import (
    LoadProblem,
    WorkflowCatalog,
    check_workflows,
)
from agent_hub.core.workflows.document import WorkflowLoadError, parse_workflow
from agent_hub.core.workflows.engine import (
    EnginePorts,
    WorkflowEngineError,
    run_workflow,
    start_inputs,
)
from agent_hub.core.workflows.events import WorkflowEvents, issue_key
from agent_hub.core.workflows.gates import GateAnswer, GateAnswers
from agent_hub.core.workflows.nodes import Node, ScriptNode, ShellNode
from agent_hub.core.workflows.plan import WorkflowPlan, plan_workflow
from agent_hub.core.workflows.ports import RunEnd, RunRecorder
from agent_hub.core.workflows.run_state import RunState
from agent_hub.generator.workflow_discovery import (
    BUILTIN_WORKFLOWS,
    HUB_WORKFLOWS,
    DiscoveredWorkflow,
    WorkflowDiscovery,
    discover_workflows,
    pack_resolver,
)
from agent_hub.generator.workflow_fixtures import (
    FIXTURE_SUFFIX,
    FIXTURES,
    FixtureRun,
    run_fixtures,
    skeleton_yaml,
)
from agent_hub.generator.workflow_outputs import JsonSchemaOutputs
from agent_hub.generator.workflow_source import DiscoveredWorkflowSource
from agent_hub.generator.workflow_yaml import WorkflowMapping

COMMAND: Final = "workflow"
_PREFIX: Final = "hub workflow run"
_ENDED: Final = frozenset({"done", "cancelled"})
# A retry's jitter: spread, not secrecy; drawn from the system source all the same.
_JITTER: Final = random.SystemRandom()

workflow_app = typer.Typer(
    name="workflow", no_args_is_help=True, help="List, check and run workflows."
)


@workflow_app.command("list")
def list_workflows() -> None:
    """List the hub's workflows; a file that does not load is one stderr line."""
    catalog = _catalog(name=None)
    for plan in catalog.plans:
        document = plan.document
        typer.echo(
            f"{document.name}  {len(document.nodes)} nodes  {document.description or ''}".rstrip()
        )
    _exit_on_problems(catalog)


@workflow_app.command("validate")
def validate(
    name: Annotated[str | None, typer.Argument(help="Check only this workflow.")] = None,
) -> None:
    """Load and plan the hub's workflows (or one): every problem, one per line."""
    catalog = _catalog(name=name)
    if name is not None and not catalog.plans and not catalog.problems:
        fail(f"no workflow named {shown_path(name)} in {HUB_WORKFLOWS}/ or the built-ins")
    for plan in catalog.plans:
        nodes, layers = len(plan.document.nodes), len(plan.layers)
        typer.echo(f"{plan.document.name}: valid ({nodes} nodes in {layers} layers)")
    _exit_on_problems(catalog)


@workflow_app.command("run")
def run(
    context: typer.Context,
    name: Annotated[str | None, typer.Argument(help="The workflow to run.")] = None,
    *,
    given: Annotated[
        list[str] | None,
        typer.Option("--input", metavar="NAME=VALUE", help="An input of the workflow."),
    ] = None,
    live: Annotated[
        bool, typer.Option("--live", help="Run it; without it, print what would run.")
    ] = False,
    run_id: Annotated[str | None, typer.Option("--run-id", help="The new run's id.")] = None,
    resume: Annotated[
        str | None, typer.Option("--resume", metavar="RUN", help="Continue this run.")
    ] = None,
    abandon: Annotated[
        str | None, typer.Option("--abandon", metavar="RUN", help="End this run cancelled.")
    ] = None,
) -> None:
    """Run a workflow, or resume or abandon a run of one."""
    if [name, resume, abandon].count(None) != 2:
        raise typer.BadParameter("give one of NAME, --resume RUN or --abandon RUN")
    for option, value in (("--run-id", run_id), ("--resume", resume), ("--abandon", abandon)):
        # A run id names a folder and is the events' session: checked before anything runs.
        if value is not None and not RUN_ID_PATTERN.fullmatch(value):
            hint = "use 1 to 32 of a-z 0-9 -, starting with a letter or digit"
            raise typer.BadParameter(hint, param_hint=option)
    root = hub_root_or_exit(os.environ, command=COMMAND)
    hub = hub_checkout(root, command=COMMAND, environ=without(os.environ, CHILD_HIDDEN))
    _refuse_delivery_resume(hub, resume or abandon)
    try:
        if abandon is not None:
            _abandon(hub, abandon)
        elif resume is not None:
            raise typer.Exit(_resume(hub, resume))
        else:
            started = _start(context, hub, name or "", given=given or [], live=live, run_id=run_id)
            raise typer.Exit(started)
    except (WorkflowRunError, WorkflowEngineError) as error:
        fail(f"{_PREFIX}: {error}")


_RUN_ARG = typer.Argument(help="The paused run.")
_NODE_ARG = typer.Argument(help="The gate's node (optional with one open gate).")
_TEXT_ARG = typer.Argument(help="The answer's text.")


@workflow_app.command("approve")
def approve(
    run_id: Annotated[str, _RUN_ARG],
    node: Annotated[str | None, _NODE_ARG] = None,
    text: Annotated[str | None, _TEXT_ARG] = None,
) -> None:
    """Approve a paused run's gate, then resume the run."""
    raise typer.Exit(_decide("approve", run_id, node=node, text=text, choice="approve"))


@workflow_app.command("reject")
def reject(
    run_id: Annotated[str, _RUN_ARG],
    node: Annotated[str | None, _NODE_ARG] = None,
    text: Annotated[str | None, _TEXT_ARG] = None,
) -> None:
    """Reject a paused run's gate, then resume the run."""
    raise typer.Exit(_decide("reject", run_id, node=node, text=text, choice="reject"))


@workflow_app.command("respond")
def respond(
    run_id: Annotated[str, _RUN_ARG],
    node: Annotated[str | None, _NODE_ARG] = None,
    text: Annotated[str | None, _TEXT_ARG] = None,
    *,
    choice: Annotated[
        str | None, typer.Option("--choice", help="A declared decision or option id.")
    ] = None,
) -> None:
    """Answer a paused run's gate with a choice and/or a text, then resume the run."""
    raise typer.Exit(_decide("respond", run_id, node=node, text=text, choice=choice))


def _decide(
    command: str, run_id: str, *, node: str | None, text: str | None, choice: str | None
) -> int:
    hub = _decision_hub(run_id)
    try:
        folder = _existing_run(hub, run_id)
        with run_lock(folder):
            drop_torn_tail(folder)
            book = RecordedGates(folder, _ended_check(folder))
            gate, text = _gate_of(book, node, text)
            _record_decision(
                command, hub, book=book, gate=gate, answer=GateAnswer(choice, text), where="cli"
            )
            return _continue(hub, folder)
    except (WorkflowRunError, WorkflowEngineError, GateDecisionError) as error:
        fail(f"hub workflow {command}: {error}")


@workflow_app.command("decide", hidden=True)
def decide(
    run_id: Annotated[str, _RUN_ARG],
    *,
    gate_id: Annotated[str, typer.Option("--gate", help="The open gate's id.")],
    choice: Annotated[
        str | None, typer.Option("--choice", help="A declared decision or option id.")
    ] = None,
    text_stdin: Annotated[
        bool, typer.Option("--text-stdin", help="Read the answer's text from stdin.")
    ] = False,
) -> None:
    """Record one decision for the open gate GATE of a paused run, without resuming it (hub
    web's decisions: the text comes on stdin, never in argv)."""
    if gate_id.split(":", 1)[0] != run_id:
        raise typer.BadParameter(f"give a gate of run {run_id}", param_hint="--gate")
    hub = _decision_hub(run_id)
    try:
        text = _stdin_text() if text_stdin else None
        folder = _existing_run(hub, run_id)
        with run_lock(folder):
            drop_torn_tail(folder)
            book = RecordedGates(folder, _ended_check(folder))
            gate = book.open_gate(gate_id)
            if gate is None:
                raise GateDecisionError(f"no open gate {gate_id}")
            answer = GateAnswer(choice, text)
            _record_decision("decide", hub, book=book, gate=gate, answer=answer, where="web")
    except (WorkflowRunError, WorkflowEngineError, GateDecisionError) as error:
        fail(f"hub workflow decide: {error}")


def _decision_hub(run_id: str) -> Path:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        hint = "use 1 to 32 of a-z 0-9 -, starting with a letter or digit"
        raise typer.BadParameter(hint, param_hint="RUN")
    root = hub_root_or_exit(os.environ, command=COMMAND)
    return hub_checkout(root, command=COMMAND, environ=without(os.environ, CHILD_HIDDEN))


def _stdin_text() -> str:
    """The answer's text from stdin: UTF-8, at most ``MAX_TEXT_BYTES`` (read one byte past)."""
    data = sys.stdin.buffer.read(MAX_TEXT_BYTES + 1)
    if len(data) > MAX_TEXT_BYTES:
        raise GateDecisionError(f"the text is longer than {MAX_TEXT_BYTES} bytes")
    try:
        return data.decode()
    except UnicodeDecodeError:
        raise GateDecisionError("the text on stdin is not UTF-8") from None


def _record_decision(
    command: str,
    hub: Path,
    *,
    book: RecordedGates,
    gate: RequestedGate,
    answer: GateAnswer,
    where: str,
) -> None:
    """``DecideGate`` under the run's lock (held by the caller); one stdout line."""
    decision = GateDecision(gate.gate_id, answer, _approver(), where, now())
    project = hub_project_name(hub) or hub.name
    decided = DecideGate(book, _ingest, project=project).execute(decision)
    if decided.event_error is not None:
        unavailable = f"hub workflow {command}: event store unavailable"
        typer.echo(f"{unavailable}: {decided.event_error}", err=True)
    typer.echo(f"run {gate.run}: {gate.node} {answer.choice or 'answered'}")


def _gate_of(
    book: RecordedGates, node: str | None, text: str | None
) -> tuple[RequestedGate, str | None]:
    """The open gate NODE names, else the one open gate; a lone word naming none is the text."""
    gates = {gate.node: gate for gate in book.open.values()}
    if node is not None and text is None and node not in gates:
        node, text = None, node
    if node is not None:
        if node not in gates:
            raise GateDecisionError(f"the run has no open gate at {node}")
        return gates[node], text
    if len(gates) != 1:
        open_nodes = ", ".join(sorted(gates)) or "none"
        raise GateDecisionError(f"name the gate's node; open gates: {open_nodes}")
    return next(iter(gates.values())), text


def _approver() -> str:
    try:
        return getpass.getuser()
    except KeyError, OSError:
        return "unknown"


def _ingest() -> IngestEvents:
    return IngestEvents(open_default_event_store())


def _refuse_delivery_resume(hub: Path, run_id: str | None) -> None:
    """Exit 2 when ``run_id`` is an issue-to-pr run: its tracker side (the issue read, the
    records, ADR 0030's writes) belongs to one process, so a resume or an abandon could not
    report it. Only the start record is read; nothing is written or locked."""
    if run_id is None:
        return
    folder = run_folder(hub, run_id)
    try:
        with (folder / RECORDS).open("rb") as file:
            first = json.loads(file.readline() or b"{}")
    except OSError, ValueError:
        return
    if isinstance(first, dict) and first.get("workflow") == ISSUE_TO_PR:
        message = f"resume and abandon are not supported for {ISSUE_TO_PR}; start a new run"
        raise typer.BadParameter(message, param_hint="--resume/--abandon")


def _start(
    context: typer.Context,
    hub: Path,
    name: str,
    *,
    given: list[str],
    live: bool,
    run_id: str | None,
) -> int:
    plan, found = discovered(hub, name)
    included = _included(hub, found)
    values = _given_values(plan, given)
    delivery = name == ISSUE_TO_PR
    # A hub's own issue-to-pr overrides the built-in: the parent needs its inputs to run it.
    if delivery and (problem := delivery_problem(plan)):
        raise typer.BadParameter(problem, param_hint="NAME")
    if delivery and ISSUE_TEXT in values:
        raise typer.BadParameter(f"{ISSUE_TEXT} is read from the tracker", param_hint="--input")
    # Checked before the tracker is read; the parent fills issue_text from the issue.
    inputs = _inputs(plan, {**values, ISSUE_TEXT: ""} if delivery else values)
    if not live:
        _print_plan(plan)
        return 0
    run_id = run_id or new_run_id()
    folder = run_folder(hub, run_id)
    make_run(folder)
    with run_lock(folder):
        parent = None
        try:
            pack, content_hash = snapshot_run(
                folder,
                document=dict(found.document),
                plan=plan,
                pack_root=found.pack_root,
                includes=included,
            )
            if delivery:
                # After the snapshot, so the picked record names a run that can start.
                parent = begin_delivery(context, hub, plan=plan, inputs=inputs, run_id=run_id)
                inputs[ISSUE_TEXT] = parent.issue_text
        except WorkflowRunError, typer.Exit, ClickException:
            # Nothing ran: a half-made run is not left to resume.
            shutil.rmtree(folder, ignore_errors=True)
            raise
        return _begin(
            hub,
            folder,
            plan=plan,
            inputs=inputs,
            pack=pack,
            content_hash=content_hash,
            parent=parent,
        )


def discovered(hub: Path, name: str) -> tuple[WorkflowPlan, DiscoveredWorkflow]:
    """The workflow ``name``, the hub's own over the built-in, loaded and planned; else exit 1."""
    source = DiscoveredWorkflowSource(hub, only=name, builtin_root=BUILTIN_WORKFLOWS)
    catalog = check_workflows(source)
    _exit_on_problems(catalog)
    if not catalog.plans:
        fail(f"no workflow named {shown_path(name)} in {HUB_WORKFLOWS}/ or the built-ins")
    return catalog.plans[0], source.found[name]


def run_delivery(
    hub: Path, parent: IssueToPr, *, plan: WorkflowPlan, inputs: dict[str, JsonValue], pack: Path
) -> int:
    """``hub run``'s run of issue-to-pr: the engine around ``parent``, no workflow folder (no
    resume); ``hub run``'s exit."""
    config = load_hub_config_or_exit(hub / FILE_LABEL)
    runner = _executors(hub, config, run_id=parent.live.log.run_id, pack=pack, parent=parent)
    recorder = parent.recorder(None)
    ports = _ports(runner, recorder, None)
    try:
        report = run_workflow(plan, inputs, ports)
    except RunLogError as error:
        return parent.live.stop_on_log_error(error)
    return parent.finish(report)


def _ports(
    runner: WorkflowExecutors,
    recorder: RunRecorder,
    checkout: GitCheckoutProbe | None,
    *,
    gates: GateAnswers | None = None,
) -> EnginePorts:
    """The engine's ports for a live run; ``gates`` answers its gates (a resume's decisions)."""
    return EnginePorts(
        runner,
        recorder,
        SystemClock(),
        JsonSchemaOutputs(),
        _JITTER.random,
        checkout,
        # In-process hub steps share this process's streams: they never run side by side.
        max_parallel=runner.max_parallel,
        interrupt=runner.stop_children,
        gates=gates or RecordedAnswers([]),
    )


def _included(hub: Path, found: DiscoveredWorkflow) -> dict[str, WorkflowMapping]:
    """Each workflow ``found`` includes, as read: the run's snapshot keeps them for a resume."""
    included: dict[str, WorkflowMapping] = {}
    discovery = discover_workflows(hub, builtin_root=BUILTIN_WORKFLOWS)
    resolver = pack_resolver(discovery, found.pack_root, used=included)
    plan_workflow(parse_workflow(found.document), includes=resolver)
    return included


def _executors(
    hub: Path, config: HubConfig, *, run_id: str, pack: Path, parent: IssueToPr | None
) -> WorkflowExecutors:
    return WorkflowExecutors(
        hub=hub,
        config=config,
        run_id=run_id,
        pack_root=pack,
        environ=os.environ,
        hub_program=own_hub_program(),
        **({} if parent is None else parent.executor_options()),
    )


def _begin(
    hub: Path,
    folder: Path,
    *,
    plan: WorkflowPlan,
    inputs: dict[str, JsonValue],
    pack: Path,
    content_hash: str,
    parent: IssueToPr | None,
) -> int:
    run_id, name = folder.name, plan.document.name
    header: dict[str, JsonValue] = {"event": "start", "run": run_id, "workflow": name}
    header |= {"revision": plan.document.revision, "content_hash": content_hash}
    _, unwatched = _checkouts(hub, load_hub_config_or_exit(hub / FILE_LABEL))
    if unwatched:
        # Noted once: a read-only node's git status check does not see these folders.
        header["checkout_unwatched"] = [str(path) for path in unwatched]
    append_record(folder, header)
    append_record(folder, {"event": "inputs", "inputs": inputs})
    return _execute(
        hub, folder, plan=plan, inputs=inputs, pack=pack, content_hash=content_hash, parent=parent
    )


def _resume(hub: Path, run_id: str) -> int:
    folder = _existing_run(hub, run_id)
    with run_lock(folder):
        drop_torn_tail(folder)
        return _continue(hub, folder)


def _continue(hub: Path, folder: Path) -> int:
    records = _ended_check(folder)
    header = records[0]
    if snapshot_hash(folder / SNAPSHOT) != header.get("content_hash"):
        raise WorkflowRunError(
            f"the run {folder.name}'s snapshot no longer matches its content_hash"
        )
    try:
        document = (folder / SNAPSHOT / DOCUMENT).read_bytes()
        includes = snapshot_includes(folder / SNAPSHOT)
        plan = plan_workflow(parse_workflow(_json(document)), includes=includes)
    except (OSError, WorkflowLoadError) as error:
        raise WorkflowRunError(f"cannot load the run's snapshot: {error}") from None
    inputs = next((r["inputs"] for r in records if r.get("event") == "inputs"), {})
    append_record(folder, {"event": "resume"})
    return _execute(
        hub,
        folder,
        plan=plan,
        inputs=inputs if isinstance(inputs, dict) else {},
        pack=folder / SNAPSHOT,
        content_hash=str(header.get("content_hash")),
        prior=prior_state(records),
        end_index=len(ends_of(records)),
        answers=RecordedAnswers(records),
    )


def _abandon(hub: Path, run_id: str) -> None:
    folder = _existing_run(hub, run_id)
    with run_lock(folder):
        drop_torn_tail(folder)
        records = _ended_check(folder)
        inputs = next((r["inputs"] for r in records if r.get("event") == "inputs"), {})
        events = _events(
            hub,
            folder.name,
            records[0],
            end_index=len(ends_of(records)),
            issue=_issue(inputs if isinstance(inputs, dict) else {}),
        )
        RecordedRun(folder=folder, events=events, sink=EventSink()).run_ended(
            RunEnd("cancelled", now())
        )
    typer.echo(f"run {run_id}: cancelled")


def _existing_run(hub: Path, run_id: str) -> Path:
    folder = run_folder(hub, run_id)
    if not folder.is_dir() or folder.is_symlink():
        raise WorkflowRunError(f"no run {run_id}")
    return folder


def _ended_check(folder: Path) -> list[dict[str, JsonValue]]:
    """The run's records; refused when it already ended done or cancelled."""
    run_id = folder.name
    records = read_records(folder)
    ends = ends_of(records)
    if not records or records[0].get("event") != "start":
        raise WorkflowRunError(f"the run {run_id} has no start record")
    if ends and ends[-1].get("status") in _ENDED:
        raise WorkflowRunError(f"the run {run_id} already ended {ends[-1].get('status')}")
    return records


def _execute(
    hub: Path,
    folder: Path,
    *,
    plan: WorkflowPlan,
    inputs: dict[str, JsonValue],
    pack: Path,
    content_hash: str,
    prior: RunState | None = None,
    end_index: int = 0,
    parent: IssueToPr | None = None,
    answers: RecordedAnswers | None = None,
) -> int:
    config = load_hub_config_or_exit(hub / FILE_LABEL)
    header: dict[str, JsonValue] = {
        "workflow": plan.document.name,
        "revision": plan.document.revision,
        "content_hash": content_hash,
    }
    recorded = RecordedRun(
        folder=folder,
        events=_events(hub, folder.name, header, end_index=end_index, issue=_issue(inputs)),
        # issue-to-pr's events are hub run's, from the parent's records.
        sink=EventSink() if parent is None else None,
    )
    runner = _executors(hub, config, run_id=folder.name, pack=pack, parent=parent)
    recorder = recorded if parent is None else parent.recorder(recorded)
    roots, _ = _checkouts(hub, config)
    checkout = GitCheckoutProbe(roots=roots, environ=os.environ)
    ports = _ports(runner, recorder, checkout, gates=answers)
    try:
        report = run_workflow(plan, inputs, ports, prior=prior)
    except RunLogError as error:
        if parent is None:
            raise
        # hub run's record could not be written: the run stops there, as hub run does.
        append_record(folder, {"event": "end", "status": "failed", "outcome": None})
        return parent.live.stop_on_log_error(error)
    append_record(folder, {"event": "sessions", "sessions": dict(report.state.sessions)})
    if report.status == "paused":
        append_record(folder, held_record(report.state))
        gate = report.state.gates.get(report.reason or "")
        due = "" if gate is None or gate.due is None else f" until {gate.due.isoformat()}"
        typer.echo(f"run {folder.name}: paused at {report.reason}{due}")
        return 0
    outcome = "" if report.outcome is None else f", outcome {report.outcome}"
    typer.echo(f"run {folder.name}: {report.status}{outcome}")
    if parent is not None:
        return parent.finish(report)
    return 0 if report.status == "done" else 1


def _issue(inputs: dict[str, JsonValue]) -> str | None:
    """The run's ``issue`` input when it is a tracker key: its events carry it, so hub web
    finds an issue's live run."""
    return issue_key(inputs.get("issue"))


def _checkouts(hub: Path, config: HubConfig) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """The hub and the repos next to it, as git checkouts (watched) and other folders (not)."""
    folders = (hub, *(hub.parent / repo.dir for repo in config.repos))
    watched = tuple(folder for folder in folders if (folder / ".git").exists())
    return watched, tuple(folder for folder in folders if folder not in watched)


def _events(
    hub: Path,
    run_id: str,
    header: dict[str, JsonValue],
    *,
    end_index: int,
    issue: str | None = None,
) -> WorkflowEvents:
    revision = header.get("revision")
    return WorkflowEvents(
        project=hub_project_name(hub) or hub.name,
        run_id=run_id,
        workflow=str(header.get("workflow")),
        revision=revision if isinstance(revision, int) else 0,
        content_hash=str(header.get("content_hash")),
        end_index=end_index,
        issue=issue,
    )


def own_hub_program() -> tuple[str, ...]:
    """This hub, by absolute path: what a ``hub step`` node runs. ``-I`` keeps the cwd (a
    checkout an agent can write) and ``PYTHON*`` variables off the module path, so a planted
    ``typer/`` or ``agent_hub/`` never runs with the GitHub tokens."""
    return (sys.executable, "-I", "-m", "agent_hub.cli")


def _inputs(plan: WorkflowPlan, values: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """``values`` with the defaults; else exit 2."""
    try:
        return start_inputs(plan, values)
    except WorkflowEngineError as error:
        raise typer.BadParameter(str(error), param_hint="--input") from None


def _given_values(plan: WorkflowPlan, given: list[str]) -> dict[str, JsonValue]:
    """``NAME=VALUE`` pairs typed by the declared inputs; else exit 2."""
    values: dict[str, JsonValue] = {}
    declared = plan.document.inputs
    for pair in given:
        key, sep, text = pair.partition("=")
        if not sep:
            raise typer.BadParameter(f"{pair!r} is not NAME=VALUE", param_hint="--input")
        kind = declared[key].type if key in declared else "string"
        values[key] = _typed(text, kind, key)
    return values


def _typed(text: str, kind: str, key: str) -> JsonValue:
    try:
        if kind == "integer":
            return int(text)
        if kind == "number":
            return float(text)
    except ValueError:
        pass
    else:
        if kind != "boolean":
            return text
        if text in {"true", "false"}:
            return text == "true"
    raise typer.BadParameter(f"{key} must be of type {kind}", param_hint="--input")


def _print_plan(plan: WorkflowPlan) -> None:
    """Each node a run would start, layer by layer; a group's body, indented, under it."""
    nodes = {node.id: node for node in plan.all_nodes()}
    for layer in plan.layers:
        for node_id in layer:
            typer.echo(_plan_line(nodes[node_id]))
            for body_layer in plan.bodies.get(node_id, ()):
                for body_id in body_layer:
                    typer.echo(f"  {_plan_line(nodes[body_id])}")


def _plan_line(node: Node) -> str:
    argv = node.command if isinstance(node, ShellNode) else ()
    if isinstance(node, ScriptNode):
        argv = (node.runtime, f"scripts/{node.script}", *node.args)
    line = f"would run: {node.id} ({node.type})"
    line = f"{line}: {shown_command(argv)}" if argv else line
    stdin = node.stdin if isinstance(node, ShellNode | ScriptNode) else None
    return line if stdin is None else f"{line}   stdin: {shown_text(stdin)}"


def _json(data: bytes) -> object:
    return json.loads(data)


def _catalog(*, name: str | None) -> WorkflowCatalog:
    root = hub_root_or_exit(os.environ, command=COMMAND)
    return check_workflows(
        DiscoveredWorkflowSource(root, only=name, builtin_root=BUILTIN_WORKFLOWS)
    )


def _exit_on_problems(catalog: WorkflowCatalog) -> None:
    if catalog.problems:
        fail(*(_problem_line(problem) for problem in catalog.problems))


def _problem_line(problem: LoadProblem) -> str:
    where = shown_path(problem.file) + ("" if problem.line is None else f":{problem.line}")
    return f"{where}: {problem.key}: {problem.message}"


# ``hub workflow test`` (AGH-222): the packs' fixtures, dry-run in memory through the engine.


@workflow_app.command("test")
def test_workflows(
    names: Annotated[
        list[str] | None, typer.Argument(help="Run only these workflows' fixtures.")
    ] = None,
    *,
    stubs_init: Annotated[
        bool, typer.Option("--stubs-init", help="Write a skeleton fixture for NAME.")
    ] = False,
) -> None:
    """Run each pack's fixtures/*.yaml in memory, no child or event; exit 1 on a failure."""
    root = hub_root_or_exit(os.environ, command="workflow")
    discovery = discover_workflows(root, builtin_root=BUILTIN_WORKFLOWS)
    wanted = list(dict.fromkeys(names or ()))
    if stubs_init:
        if len(names or ()) > 1:
            fail("--stubs-init needs one workflow name")
        _write_skeleton(root, discovery, wanted[0] if wanted else None)
        return
    runs = _fixture_runs(discovery, wanted)
    for fixture_run in runs:
        where = shown_text(_shown_fixture(root, fixture_run.path))
        typer.echo(f"{where}: {'FAILED' if fixture_run.problems else 'ok'}")
        for problem in fixture_run.problems:
            typer.echo(f"  {shown_text(problem)}")
        for warning in fixture_run.warnings:
            typer.echo(f"  warning: {shown_text(warning)}")
    failed = sum(1 for fixture_run in runs if fixture_run.problems)
    noun = "fixture" if len(runs) == 1 else "fixtures"
    typer.echo(f"{len(runs)} {noun}: {len(runs) - failed} passed, {failed} failed")
    if failed:
        raise typer.Exit(FAILURE)


def _fixture_runs(discovery: WorkflowDiscovery, names: list[str]) -> list[FixtureRun]:
    """Every fixture's run, or those of ``names``, each file once; exit 1 on a name with none."""
    if not names:
        return list(run_fixtures(discovery))
    runs: list[FixtureRun] = []
    for name in names:
        named = run_fixtures(discovery, only=name)
        if not named:
            fail(f"no fixture for the workflow {name!r} in its pack's {FIXTURES}/")
        # Two names of one pack share its unreadable fixtures: each file runs once.
        seen = {run.path for run in runs}
        runs.extend(item for item in named if item.path not in seen)
    return runs


def _write_skeleton(root: Path, discovery: WorkflowDiscovery, name: str | None) -> None:
    if name is None:
        fail("--stubs-init needs a workflow name")
    found = next((w for w in discovery.workflows if w.name == name), None)
    if found is None:
        fail(f"no workflow named {shown_path(name)} in {HUB_WORKFLOWS}/ or the built-ins")
    if found.origin != "hub":
        fail(f"{name!r} is a built-in workflow; its fixtures ship with it")
    try:
        includes = pack_resolver(discovery, found.pack_root)
        skeleton = skeleton_yaml(plan_workflow(parse_workflow(found.document), includes=includes))
    except (WorkflowLoadError, WorkflowEngineError) as error:
        fail(f"{_shown_fixture(root, found.path)}: {error}")
    target = _skeleton_target(root, found.pack_root, name)
    try:
        with target.open("x", encoding="utf-8") as file:
            file.write(skeleton.text)
    except FileExistsError:
        fail(f"{_shown_fixture(root, target)} already exists; it is not overwritten")
    except OSError as error:
        fail(f"{_shown_fixture(root, target)}: {error.strerror or error}")
    typer.echo(f"wrote {_shown_fixture(root, target)}")
    if skeleton.status != "done":
        typer.echo(
            f"note: its own dry run ended {skeleton.status}; fill in the stubs the placeholders"
            " could not satisfy"
        )


def _skeleton_target(root: Path, pack_root: Path, name: str) -> Path:
    """``<pack>/fixtures/<name>.yaml``, its folder made and checked: not a link, inside the pack."""
    folder = pack_root / FIXTURES
    if folder.is_symlink():
        fail(f"{_shown_fixture(root, folder)} is a link; nothing is written")
    try:
        folder.mkdir(exist_ok=True)
        inside = folder.resolve(strict=True).is_relative_to(pack_root.resolve(strict=True))
    except OSError as error:
        fail(f"{_shown_fixture(root, folder)}: {error.strerror or error}")
    if not inside or not folder.is_dir():
        fail(f"{_shown_fixture(root, folder)} is not a folder inside its pack; nothing is written")
    return folder / f"{name}{FIXTURE_SUFFIX}"


def _shown_fixture(root: Path, path: Path) -> str:
    return DiscoveredWorkflowSource(root, builtin_root=BUILTIN_WORKFLOWS)._shown(path)
