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
``done`` exits 0, any other end 1; a bad input exits 2. It makes no tracker write: issue-to-pr's
writes stay ``hub run``'s.

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

from agent_hub.cli.collect import hub_project_name
from agent_hub.cli.command_exits import FAILURE, fail
from agent_hub.cli.hub_config_reader import FILE_LABEL, load_hub_config_or_exit
from agent_hub.cli.hub_root import hub_checkout, hub_root_or_exit
from agent_hub.cli.init_report import shown_path, shown_text
from agent_hub.cli.run_children import CHILD_HIDDEN, shown_command, without
from agent_hub.cli.run_log import new_run_id, now
from agent_hub.cli.workflow_executors import WorkflowExecutors
from agent_hub.cli.workflow_runs import (
    DOCUMENT,
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
    snapshot_run,
)
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
from agent_hub.core.workflows.nodes import ScriptNode, ShellNode
from agent_hub.core.workflows.plan import WorkflowPlan, plan_workflow
from agent_hub.core.workflows.ports import RunEnd
from agent_hub.core.workflows.run_state import RunState
from agent_hub.generator.workflow_discovery import (
    BUILTIN_WORKFLOWS,
    HUB_WORKFLOWS,
    WorkflowDiscovery,
    discover_workflows,
)
from agent_hub.generator.workflow_fixtures import (
    FIXTURE_SUFFIX,
    FIXTURES,
    run_fixtures,
    skeleton_yaml,
)
from agent_hub.generator.workflow_outputs import JsonSchemaOutputs
from agent_hub.generator.workflow_source import DiscoveredWorkflowSource

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
    try:
        if abandon is not None:
            _abandon(hub, abandon)
        elif resume is not None:
            raise typer.Exit(_resume(hub, resume))
        else:
            raise typer.Exit(_start(hub, name or "", given or [], live=live, run_id=run_id))
    except (WorkflowRunError, WorkflowEngineError) as error:
        fail(f"{_PREFIX}: {error}")


def _start(hub: Path, name: str, given: list[str], *, live: bool, run_id: str | None) -> int:
    source = DiscoveredWorkflowSource(hub, only=name, builtin_root=BUILTIN_WORKFLOWS)
    catalog = check_workflows(source)
    _exit_on_problems(catalog)
    if not catalog.plans:
        fail(f"no workflow named {shown_path(name)} in {HUB_WORKFLOWS}/ or the built-ins")
    plan, found = catalog.plans[0], source.found[name]
    inputs = _inputs(plan, given)
    if not live:
        _print_plan(plan)
        return 0
    run_id = run_id or new_run_id()
    folder = run_folder(hub, run_id)
    make_run(folder)
    with run_lock(folder):
        try:
            pack, content_hash = snapshot_run(
                folder, document=dict(found.document), plan=plan, pack_root=found.pack_root
            )
        except WorkflowRunError:
            # Nothing ran: a half-made run is not left to resume.
            shutil.rmtree(folder, ignore_errors=True)
            raise
        return _begin(hub, folder, plan=plan, inputs=inputs, pack=pack, content_hash=content_hash)


def _begin(
    hub: Path,
    folder: Path,
    *,
    plan: WorkflowPlan,
    inputs: dict[str, JsonValue],
    pack: Path,
    content_hash: str,
) -> int:
    run_id, name = folder.name, plan.document.name
    header: dict[str, JsonValue] = {"event": "start", "run": run_id, "workflow": name}
    append_record(
        folder, {**header, "revision": plan.document.revision, "content_hash": content_hash}
    )
    append_record(folder, {"event": "inputs", "inputs": inputs})
    return _execute(hub, folder, plan=plan, inputs=inputs, pack=pack, content_hash=content_hash)


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
        plan = plan_workflow(parse_workflow(_json(document)))
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
) -> int:
    config = load_hub_config_or_exit(hub / FILE_LABEL)
    header: dict[str, JsonValue] = {
        "workflow": plan.document.name,
        "revision": plan.document.revision,
        "content_hash": content_hash,
    }
    recorder = RecordedRun(
        folder=folder,
        events=_events(hub, folder.name, header, end_index=end_index, issue=_issue(inputs)),
        sink=EventSink(),
    )
    runner = WorkflowExecutors(
        hub=hub,
        config=config,
        run_id=folder.name,
        pack_root=pack,
        environ=os.environ,
        hub_program=own_hub_program(),
    )
    ports = EnginePorts(runner, recorder, SystemClock(), JsonSchemaOutputs(), _JITTER.random)
    report = run_workflow(plan, inputs, ports, prior=prior)
    append_record(folder, {"event": "sessions", "sessions": dict(report.state.sessions)})
    outcome = "" if report.outcome is None else f", outcome {report.outcome}"
    typer.echo(f"run {folder.name}: {report.status}{outcome}")
    return 0 if report.status == "done" else 1


def _issue(inputs: dict[str, JsonValue]) -> str | None:
    """The run's ``issue`` input when it is a tracker key: its events carry it, so hub web
    finds an issue's live run."""
    return issue_key(inputs.get("issue"))


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


def _inputs(plan: WorkflowPlan, given: list[str]) -> dict[str, JsonValue]:
    """``NAME=VALUE`` pairs typed by the declared inputs, with the defaults; else exit 2."""
    values: dict[str, JsonValue] = {}
    declared = plan.document.inputs
    for pair in given:
        key, sep, text = pair.partition("=")
        if not sep:
            raise typer.BadParameter(f"{pair!r} is not NAME=VALUE", param_hint="--input")
        kind = declared[key].type if key in declared else "string"
        values[key] = _typed(text, kind, key)
    try:
        return start_inputs(plan, values)
    except WorkflowEngineError as error:
        raise typer.BadParameter(str(error), param_hint="--input") from None


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
            typer.echo(f"{line}: {shown_command(argv)}" if argv else line)


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
        skeleton = skeleton_yaml(plan_workflow(parse_workflow(found.document)))
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
