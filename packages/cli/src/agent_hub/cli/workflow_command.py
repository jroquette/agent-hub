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
on its snapshot, reusing what completed; ``--abandon RUN`` ends it ``cancelled``. A run that ends
``done`` exits 0, any other end 1; a bad input exits 2. It makes no tracker write, except for
the workflow named ``issue-to-pr``, whose parent is ``hub run``'s (``workflow_delivery``): the
issue read before, ``hub run``'s records (and so its events) during, ADR 0030's writes after,
and ``hub run``'s exit codes; there ``issue_text`` comes from the tracker, never from ``--input``,
the workflow must declare ``issue``, ``repo`` and ``issue_text``, and ``--resume`` or
``--abandon`` of such a run exits 2. ``hub run --live`` is that run (``run_delivery``), without
a workflow folder: ``hub run``'s records are its only record.

``test [NAME]`` dry-runs each fixture of the discovered packs (or NAME's) in memory through the
engine (generator's ``run_fixtures``): one ``<file>: ok|FAILED`` line each, its problems and
warnings indented, then a count; a failed fixture exits 1. ``--stubs-init`` writes NAME's
skeleton fixture to ``<pack>/fixtures/<NAME>.yaml``, never over an existing file nor through a
linked folder, and notes when the skeleton's own dry run did not end ``done``.
"""

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
from agent_hub.cli.run_log import new_run_id, now
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
    RecordedRun,
    SystemClock,
    WorkflowRunError,
    append_record,
    drop_torn_tail,
    ends_of,
    make_run,
    prior_state,
    read_records,
    run_folder,
    run_lock,
    snapshot_hash,
    snapshot_includes,
    snapshot_run,
)
from agent_hub.core.hub_config.model import HubConfig
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
from agent_hub.core.workflows.events import WorkflowEvents
from agent_hub.core.workflows.nodes import ScriptNode, ShellNode
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
    runner: WorkflowExecutors, recorder: RunRecorder, checkout: GitCheckoutProbe | None
) -> EnginePorts:
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
    )


def _abandon(hub: Path, run_id: str) -> None:
    folder = _existing_run(hub, run_id)
    with run_lock(folder):
        drop_torn_tail(folder)
        records = _ended_check(folder)
        events = _events(hub, folder.name, records[0], end_index=len(ends_of(records)))
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
) -> int:
    config = load_hub_config_or_exit(hub / FILE_LABEL)
    header: dict[str, JsonValue] = {
        "workflow": plan.document.name,
        "revision": plan.document.revision,
        "content_hash": content_hash,
    }
    recorded = RecordedRun(
        folder=folder,
        events=_events(hub, folder.name, header, end_index=end_index),
        # issue-to-pr's events are hub run's, from the parent's records.
        sink=EventSink() if parent is None else None,
    )
    runner = _executors(hub, config, run_id=folder.name, pack=pack, parent=parent)
    recorder = recorded if parent is None else parent.recorder(recorded)
    roots, _ = _checkouts(hub, config)
    checkout = GitCheckoutProbe(roots=roots, environ=os.environ)
    ports = _ports(runner, recorder, checkout)
    try:
        report = run_workflow(plan, inputs, ports, prior=prior)
    except RunLogError as error:
        if parent is None:
            raise
        # hub run's record could not be written: the run stops there, as hub run does.
        append_record(folder, {"event": "end", "status": "failed", "outcome": None})
        return parent.live.stop_on_log_error(error)
    append_record(folder, {"event": "sessions", "sessions": dict(report.state.sessions)})
    outcome = "" if report.outcome is None else f", outcome {report.outcome}"
    typer.echo(f"run {folder.name}: {report.status}{outcome}")
    if parent is not None:
        return parent.finish(report)
    return 0 if report.status == "done" else 1


def _checkouts(hub: Path, config: HubConfig) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """The hub and the repos next to it, as git checkouts (watched) and other folders (not)."""
    folders = (hub, *(hub.parent / repo.dir for repo in config.repos))
    watched = tuple(folder for folder in folders if (folder / ".git").exists())
    return watched, tuple(folder for folder in folders if folder not in watched)


def _events(
    hub: Path, run_id: str, header: dict[str, JsonValue], *, end_index: int
) -> WorkflowEvents:
    revision = header.get("revision")
    return WorkflowEvents(
        project=hub_project_name(hub) or hub.name,
        run_id=run_id,
        workflow=str(header.get("workflow")),
        revision=revision if isinstance(revision, int) else 0,
        content_hash=str(header.get("content_hash")),
        end_index=end_index,
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
    nodes = {node.id: node for node in plan.document.nodes}
    for layer in plan.layers:
        for node_id in layer:
            node = nodes[node_id]
            argv = node.command if isinstance(node, ShellNode) else ()
            if isinstance(node, ScriptNode):
                argv = (node.runtime, f"scripts/{node.script}", *node.args)
            line = f"would run: {node_id} ({node.type})"
            line = f"{line}: {shown_command(argv)}" if argv else line
            stdin = node.stdin if isinstance(node, ShellNode | ScriptNode) else None
            typer.echo(line if stdin is None else f"{line}   stdin: {shown_text(stdin)}")


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
    name: Annotated[str | None, typer.Argument(help="Run only this workflow's fixtures.")] = None,
    *,
    stubs_init: Annotated[
        bool, typer.Option("--stubs-init", help="Write a skeleton fixture for NAME.")
    ] = False,
) -> None:
    """Run each pack's fixtures/*.yaml in memory, no child or event; exit 1 on a failure."""
    root = hub_root_or_exit(os.environ, command="workflow")
    discovery = discover_workflows(root, builtin_root=BUILTIN_WORKFLOWS)
    if stubs_init:
        _write_skeleton(root, discovery, name)
        return
    runs = run_fixtures(discovery, only=name)
    if name is not None and not runs:
        fail(f"no fixture for the workflow {name!r} in its pack's {FIXTURES}/")
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
