"""``hub scenario list|plan|run|break|step|continue|migrate|propose|findings``: the hub's
scenarios, listed, planned, run, debugged and written as blocks, and their scenario runs'
findings (docs/design/scenarios.md § Contract, § Tree format, § Debugging, § Plan and modes,
§ Investigation; ADR 0041, ADR 0049).

``list`` prints one line per scenario that loads, ``<name>  <pack>  <nodes> nodes
[<description>]``; each problem is one stderr line, ``<file>[:<line>]: <key>: <message>``, and
exits 1; a hub without scenarios prints ``no scenarios yet``. Scenarios live in
``scenarios/<pack>/`` only: ``hub workflow list`` never shows one.

``plan NAME --env ENV [--input name=value]... [--json]`` plans each ``action`` and ``expect``
step (core's ``plan_scenario``) and prints, per step, ``<step>  <type>  <action>  <effect>
<decision>`` then its args (a value known only at run time as ``<$CTX.<name> from <node>>``),
endpoints (``<input> → <repo>/<service> <url> <resource>``), an expect's polls, its content hash,
its draft state and its plan: the script's ``summary`` in ``plan`` mode (no credential, the env
file never read), called only when every arg is known (else ``runs with values known at run
time``) and never for a draft. It writes nothing: no run-mode process, agent, event or run. Each
problem (an undeclared environment, an action or endpoint that cannot be resolved, a path an
action's output lacks, two unordered gates) is a stderr line; a problem or a ``deny`` exits 1.
A declared input no ``--input`` gives takes ENV's value of that name (``values`` in ``hub.json``
or ``hub.local.json``), before its default; the same holds for ``run``.

``--json`` prints one object with the same data, its keys stable: ``scenario``, ``environment``,
``access`` (``null`` when undeclared), ``production``, ``denied``, ``problems`` (lines) and
``rows``, each with ``step``, ``type``, ``action``, ``effect``, ``args`` (input → text),
``endpoints`` (input → ``{service, url, resource}``), ``every``, ``timeout`` (``null`` but on an
expect), ``content_hash``, ``draft``, ``decision``, ``reason_kind``, ``reason`` (a deny's, else
``null``) and ``plan`` (the summary, or why there is none).

``run NAME --env ENV [--input name=value]... [--mode interactive|regression] [--run-id RUN]``
plans the scenario as ``plan`` does, without plan-mode calls; any problem or ``deny`` is one
stderr line (an undeclared environment once, not per step) and exits 1 with no scenario run.
Otherwise ``scenario_runs`` starts it: a policy ``ask`` is a ``<step>__ask`` approval, answered
with ``hub workflow approve|reject``. In ``interactive`` mode, the default, a divergence pauses
the scenario run at ``<step>__investigation`` and prints where hub web shows it. No option
removes a gate: ``--yes`` and its kind are unknown options (exit 2). A required input that no
``--input``, environment value or default fills exits 2 naming the input and ENV. A plan problem
of a scenario written as blocks (``version: 2``) names its block, ``block <address> (<key
path>)``, not a generated node id.

``run … --break ADDR`` (repeatable) starts a scenario written as blocks with breakpoints, block
addresses of its tree (``scenario_debug``; docs/design/scenarios.md § Debugging). ``break RUN
ADDR... [--off]`` adds or removes a run's breakpoints and ``break RUN --set [ADDR...]`` replaces
them (none clears them), printing the set written (``run <id>: breakpoints 2, 3.1`` or ``run
<id>: no breakpoints``); a run that runs takes them at its next layer of nodes. ``step RUN`` and
``continue RUN`` resume a run in a debug pause, recorded with who sent them. A debug pause prints
``run <id>: paused before <address> (breakpoint|step)`` and exits 0. Each is refused, exit 1 and
nothing recorded, on a ``production: true`` environment (clearing excepted), for a version-1
scenario, which has no addresses, and for an address its tree does not hold.

``migrate [NAME]... [--check]`` writes each graph-format scenario named (``version: 1``; every
one when none is named) again in place as blocks (``version: 2``, ``scenario_migrate``): one
stage named after the scenario, each id kept where it differs from the one its address derives,
in canonical form, the revision kept; it prints ``migrated <file> to blocks (version 2): stage
<name>, <n> blocks`` per file, or ``no scenario in the graph format (version 1)``. When anything
cannot be migrated (no such scenario, a file that does not load, one already at version 2, a
JSON file, a link, a node a tree cannot hold) it writes nothing: one stderr line per problem,
naming the file and the node, then ``... cannot be written as blocks; nothing was written``,
exit 1. ``--check`` writes nothing and prints ``would migrate ...`` instead.

``propose --run RUN`` records an investigation's findings and options, the fixed schema as JSON
on stdin (at most 256 KiB, bounds and secret-shape redaction in core's ``investigation``), for
scenario run RUN paused at an open investigation (else exit 1, nothing recorded): each option's
steps are planned with origin ``agent`` and printed with their plan, ``needs acceptance`` when
one runs a draft action, and why an option cannot be picked; one ``finding`` event per finding.
A later proposal replaces the earlier one as the investigation's options.

``findings RUN [--json]`` lists scenario run RUN's findings, read from its record through core's
``run_record`` fold: one line each, ``<finding-id>  <step>  <title>``, or ``no findings in run
RUN``; ``--json`` prints ``run``, ``scenario``, ``environment`` and ``findings`` (each
``finding_id``, ``step``, ``title``, ``text``, ``evidence``), in ASCII so no control is shown
raw. ``--issue F`` prints finding F's tracker issue draft (core's ``findings``: title, then the
description) and, on a terminal, asks
``create this issue in <team>?``: after a ``y`` it calls the tracker's ``create_issue`` once, in
``tracker.team`` (the first of ``tracker.teams``), and prints ``created <id>  <url>``; the
question is asked only once the tracker's key is there and its client resolved, and only while
no issue of that finding was claimed: the marker ``finding-<id>.issue`` in the run folder,
shared with hub web (generator's ``finding_issues``), is claimed before the create, so the
terminal and hub web together create at most one issue per finding: a marker naming an issue
exits 1 before the question; after a failed or unfinished create (which hub web refuses), the
terminal says so, warns that the issue may already exist in the tracker, and asks again; a
``y`` takes the marker again atomically, then creates and records the issue. Without a
terminal it creates nothing and says so (exit 0: the draft is the output). ``--inbox F`` writes
``brain/_inbox/<date>-scenario-<name>-<F>.md`` in the hub, never over an existing note (exit 1).
An unknown run or finding id exits 1; ``--issue`` with ``--inbox``, or ``--json`` with either,
exits 2.
"""

import contextlib
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Annotated, Final, NoReturn

import typer

from agent_hub.cli.action_command import (
    Environment,
    Inputs,
    action_hub,
    confirmed,
    given_texts,
    has_terminal,
)
from agent_hub.cli.action_process import ActionCall, plan_action
from agent_hub.cli.collect import hub_project_name
from agent_hub.cli.command_exits import FAILURE, fail
from agent_hub.cli.effective_config import load_effective_config_or_exit
from agent_hub.cli.exclusive_write import write_exclusive
from agent_hub.cli.init_report import shown_path, shown_text
from agent_hub.cli.run_log import new_run_id, now
from agent_hub.cli.scenario_debug import (
    NO_ADDRESSES,
    Change,
    DebugCommand,
    addresses_in,
    change_breakpoints,
    refuse_on_production,
    send_command,
)
from agent_hub.cli.scenario_investigation import Planned, option_lines, record_proposal
from agent_hub.cli.scenario_migrate import MigrationPlan, plan_migration, write_migration
from agent_hub.cli.scenario_runs import (
    INTERACTIVE,
    MODES,
    ScenarioStart,
    load_scenario,
    start,
)
from agent_hub.cli.tracker_client import missing_key_line, resolve_tracker_client, transport_line
from agent_hub.cli.workflow_command import problem_line, typed_input
from agent_hub.cli.workflow_runs import (
    RECORDS,
    RUN_ID_PATTERN,
    RUNS_ROOT,
    EventSink,
    WorkflowRunError,
    drop_torn_tail,
    read_records,
    run_folder,
    run_lock,
)
from agent_hub.core.errors import TrackerError
from agent_hub.core.hub_config.effective_environments import (
    EffectiveEnvironments,
    effective_environments,
)
from agent_hub.core.json_form import JsonValue, dump_json
from agent_hub.core.scenarios.access_policy import DRAFT_REASON, PolicyDecision, deny_reason
from agent_hub.core.scenarios.action_catalog import resolve_action
from agent_hub.core.scenarios.credentials import CredentialNames
from agent_hub.core.scenarios.environment_values import with_environment_values
from agent_hub.core.scenarios.findings import (
    FindingsError,
    IssueDraft,
    finding_of,
    inbox_note,
    issue_draft,
)
from agent_hub.core.scenarios.investigation import (
    MAX_PROPOSAL_BYTES,
    ProposalError,
    parse_proposal,
)
from agent_hub.core.scenarios.run_record import FindingView, ScenarioRunView, fold_records
from agent_hub.core.scenarios.scenario_events import ScenarioEvents
from agent_hub.core.scenarios.scenario_plan import PlanRow, ScenarioPlan, plan_scenario
from agent_hub.core.scenarios.tree_translate import BlockMap, block_map
from agent_hub.core.tracker.tracker_client import Issue, TrackerClient
from agent_hub.core.workflows.catalog import WorkflowCatalog, check_workflows
from agent_hub.core.workflows.document import is_tree
from agent_hub.core.workflows.engine import WorkflowEngineError, start_inputs
from agent_hub.core.workflows.launch import RunInputError
from agent_hub.core.workflows.plan import WorkflowPlan
from agent_hub.core.workflows.substitution import echo
from agent_hub.generator.action_discovery import ActionDiscovery, discover_actions
from agent_hub.generator.finding_issues import (
    HeldIssue,
    IssueMarked,
    claim_issue,
    marked_issue,
    retake_issue,
)
from agent_hub.generator.scenario_discovery import HUB_SCENARIOS, DiscoveredScenarioSource
from agent_hub.generator.workflow_discovery import DiscoveredWorkflow

COMMAND: Final = "scenario"
RUN_TIME: Final = "runs with values known at run time"
NOT_PLANNED: Final = "not planned"
_PLAN_PREFIX: Final = "hub scenario plan"
_RUN_PREFIX: Final = "hub scenario run"
_PROPOSE_PREFIX: Final = "hub scenario propose"
_FINDINGS_PREFIX: Final = "hub scenario findings"
_BREAK_PREFIX: Final = "hub scenario break"
_MIGRATE_PREFIX: Final = "hub scenario migrate"
NO_GRAPH_SCENARIO: Final = "no scenario in the graph format (version 1)"
NO_TERMINAL: Final = (
    "no terminal: the issue was not created; run this command on a terminal to create it"
)
INBOX_FOLDER: Final = Path("brain", "_inbox")
MARK_FAILED: Final = "cannot mark the finding's issue"
RETRY_WARNING: Final = (
    "the issue may already exist in the tracker; check it before creating it again"
)

scenario_app = typer.Typer(
    name=COMMAND, no_args_is_help=True, help="List, plan and run the hub's scenarios."
)


@scenario_app.command("list")
def list_command() -> None:
    """List every scenario with its pack, node count and description."""
    source = DiscoveredScenarioSource(action_hub())
    catalog = check_workflows(source)
    if not catalog.plans and not catalog.problems:
        typer.echo("no scenarios yet")
    for plan in catalog.plans:
        document = plan.document
        pack = source.found[document.name].pack
        line = f"{document.name}  {pack}  {len(document.nodes)} nodes"
        typer.echo(f"{line}  {document.description}" if document.description else line)
    _exit_on_problems(catalog)


Name = Annotated[str, typer.Argument(metavar="NAME", help="The scenario.")]
AsJson = Annotated[bool, typer.Option("--json", help="Print one JSON object instead of lines.")]


@scenario_app.command("plan")
def plan_command(
    name: Name, *, environment: Environment, given: Inputs = None, as_json: AsJson = False
) -> None:
    """Show what each step would do in ENV, and the policy's decision; nothing runs."""
    texts = given_texts(given or [])
    hub = action_hub()
    plan, scenario = _scenario(hub, name, prefix=_PLAN_PREFIX)
    found = discover_actions(hub)
    effective = load_effective_config_or_exit(hub)
    view = effective_environments(effective.config, effective.local)
    planned = plan_scenario(
        plan,
        pack=scenario.pack,
        actions=found.actions,
        view=view,
        environment=environment,
        inputs=_inputs(plan, texts, view=view, environment=environment),
        blocks=_blocks(scenario),
    )
    hidden = CredentialNames.of(view)
    summaries = [_summary(row, found, hidden) for row in planned.rows]
    if as_json:
        typer.echo(dump_json(_planned_json(planned, summaries)).decode(), nl=False)
    else:
        _print_plan(planned, summaries)
    for problem in planned.problems:
        typer.echo(f"{_PLAN_PREFIX}: {problem}", err=True)
    if any(row.decision == "deny" for row in planned.rows):
        typer.echo(
            f"{_PLAN_PREFIX}: {name} cannot start in {environment}: a step is denied", err=True
        )
    if planned.denied:
        raise typer.Exit(FAILURE)


Mode = Annotated[
    str,
    typer.Option(
        "--mode",
        metavar="MODE",
        help="interactive (the default: a divergence pauses for an investigation in hub web)"
        " or regression (no agent; a divergence fails the scenario run).",
    ),
]
RunId = Annotated[str | None, typer.Option("--run-id", help="The new scenario run's id.")]
Breaks = Annotated[
    list[str] | None,
    typer.Option(
        "--break",
        metavar="ADDR",
        help="Pause before this block (its address, e.g. 2.1; repeat for more): version 2 only,"
        " never on production.",
    ),
]


@scenario_app.command("run")
def run_command(
    name: Name,
    *,
    environment: Environment,
    given: Inputs = None,
    mode: Mode = INTERACTIVE,
    run_id: RunId = None,
    breaks: Breaks = None,
) -> None:
    """Run a scenario in ENV once its plan holds no deny; an ask is a gate to approve."""
    if mode not in MODES:
        raise typer.BadParameter(f"give one of {', '.join(MODES)}", param_hint="--mode")
    if run_id is not None and not RUN_ID_PATTERN.fullmatch(run_id):
        hint = "use 1 to 32 of a-z 0-9 -, starting with a letter or digit"
        raise typer.BadParameter(hint, param_hint="--run-id")
    texts = given_texts(given or [])
    hub = action_hub()
    # Load problems are reported as for plan; then one read gives the plan that is decided
    # and the includes the scenario run snapshots.
    _scenario(hub, name, prefix=_RUN_PREFIX)
    try:
        loaded = load_scenario(hub, name)
    except WorkflowRunError as error:
        fail(f"{_RUN_PREFIX}: {error}")
    if loaded is None:
        fail(f"{_RUN_PREFIX}: no scenario named {shown_path(name)} in {HUB_SCENARIOS}/")
    plan, scenario, included = loaded
    breakpoints = _start_breakpoints(hub, scenario, breaks or [], environment=environment)
    found = discover_actions(hub)
    effective = load_effective_config_or_exit(hub)
    view = effective_environments(effective.config, effective.local)
    inputs = _inputs(plan, texts, view=view, environment=environment)
    planned = plan_scenario(
        plan,
        pack=scenario.pack,
        actions=found.actions,
        view=view,
        environment=environment,
        inputs=inputs,
        blocks=_blocks(scenario),
    )
    if planned.denied:
        _refuse_start(planned)
    begin = ScenarioStart(
        plan=plan,
        found=scenario,
        planned=planned,
        actions=found,
        inputs=inputs,
        mode=mode,
        included=included,
        breakpoints=breakpoints,
    )
    try:
        code = start(hub, run_id or new_run_id(), begin)
    except (WorkflowRunError, WorkflowEngineError) as error:
        fail(f"{_RUN_PREFIX}: {error}")
    raise typer.Exit(code)


def _start_breakpoints(
    hub: Path, scenario: DiscoveredWorkflow, given: list[str], *, environment: str
) -> tuple[str, ...]:
    """The breakpoints a start asks, in the tree's order; else exit 1 (no run is created):
    none on production or on a version-1 scenario, and only addresses of its tree."""
    if not given:
        return ()
    name = shown_path(scenario.name)
    try:
        refuse_on_production(hub, environment, what="a start with breakpoints")
        if not is_tree(scenario.document):
            raise WorkflowRunError(f"{name} is a version 1 scenario, which {NO_ADDRESSES}")
        return addresses_in(block_map(scenario.document), given, whose=f"the scenario {name}")
    except WorkflowRunError as error:
        fail(f"{_RUN_PREFIX}: {error}; no scenario run was created")


def _blocks(scenario: DiscoveredWorkflow) -> BlockMap | None:
    """The block map of a scenario written as blocks, which its plan's problems name."""
    return block_map(scenario.document) if is_tree(scenario.document) else None


Addresses = Annotated[
    list[str] | None, typer.Argument(metavar="[ADDR]...", help="Block addresses, e.g. 2 or 2.1.")
]
Off = Annotated[bool, typer.Option("--off", help="Remove these breakpoints instead.")]
Replace = Annotated[
    bool, typer.Option("--set", help="Replace every breakpoint with these (none clears them).")
]


@scenario_app.command("break")
def break_command(
    run: Annotated[str, typer.Argument(metavar="RUN", help="The scenario run.")],
    addresses: Addresses = None,
    *,
    off: Off = False,
    replace: Replace = False,
) -> None:
    """Add breakpoints to a scenario run before the blocks named (--off, --set)."""
    _run_id(run)
    given = addresses or []
    if off and replace:
        raise typer.BadParameter("give --off or --set, not both", param_hint="--set")
    if not given and not replace:
        raise typer.BadParameter("give a block address, or --set alone to clear", param_hint="ADDR")
    change: Change = "set" if replace else "off" if off else "add"
    try:
        written = change_breakpoints(action_hub(), run, given, change=change)
    except WorkflowRunError as error:
        fail(f"{_BREAK_PREFIX}: {error}")
    typer.echo(
        f"run {run}: " + (f"breakpoints {', '.join(written)}" if written else "no breakpoints")
    )


DebugRun = Annotated[str, typer.Argument(metavar="RUN", help="The run, in a debug pause.")]


@scenario_app.command("step")
def step_command(run: DebugRun) -> None:
    """Run the next block of a run in a debug pause, then pause before the one after it."""
    raise typer.Exit(_debug(run, "step"))


@scenario_app.command("continue")
def continue_command(run: DebugRun) -> None:
    """Run a run in a debug pause to its next breakpoint, or its end."""
    raise typer.Exit(_debug(run, "continue"))


def _debug(run: str, command: DebugCommand) -> int:
    _run_id(run)
    hub = action_hub()
    try:
        return send_command(hub, run, command)
    except (WorkflowRunError, WorkflowEngineError) as error:
        fail(f"hub scenario {command}: {error}")


def _run_id(run: str) -> None:
    if not RUN_ID_PATTERN.fullmatch(run):
        hint = "use 1 to 32 of a-z 0-9 -, starting with a letter or digit"
        raise typer.BadParameter(hint, param_hint="RUN")


MigrateNames = Annotated[
    list[str] | None,
    typer.Argument(
        metavar="[NAME]...", help="The scenarios (every graph-format one when none is given)."
    ),
]
Check = Annotated[bool, typer.Option("--check", help="Write nothing; say what would be written.")]


@scenario_app.command("migrate")
def migrate_command(names: MigrateNames = None, *, check: Check = False) -> None:
    """Write graph-format scenarios (version 1) again in place as blocks (version 2)."""
    hub = action_hub()
    plan = plan_migration(hub, names or [])
    if plan.refused:
        _refuse_migration(plan)
    if not plan.migrated:
        typer.echo(NO_GRAPH_SCENARIO)
        return
    for item in plan.migrated:
        if not check:
            try:
                write_migration(hub, item)
            except WorkflowRunError as error:
                fail(f"{_MIGRATE_PREFIX}: {error}")
        verb = "would migrate" if check else "migrated"
        blocks = "1 block" if item.blocks == 1 else f"{item.blocks} blocks"
        typer.echo(
            f"{verb} {shown_path(item.file)} to blocks (version 2): stage"
            f" {shown_text(item.stage)}, {blocks}"
        )


def _refuse_migration(plan: MigrationPlan) -> NoReturn:
    """Exit 1, naming each problem; nothing was written."""
    count = sum(1 for refused in plan.refused if refused.name is not None)
    noun = "scenario" if count == 1 else "scenarios"
    end = f"{count} {noun} cannot be written as blocks; " if count else ""
    lines = [f"{_MIGRATE_PREFIX}: {line}" for refused in plan.refused for line in refused.lines]
    fail(*lines, f"{_MIGRATE_PREFIX}: {end}nothing was written")


ProposeRun = Annotated[
    str, typer.Option("--run", metavar="RUN", help="The scenario run paused at an investigation.")
]


@scenario_app.command("propose")
def propose_command(*, run: ProposeRun) -> None:
    """Record an investigation's findings and options, as JSON on stdin."""
    if not RUN_ID_PATTERN.fullmatch(run):
        hint = "use 1 to 32 of a-z 0-9 -, starting with a letter or digit"
        raise typer.BadParameter(hint, param_hint="--run")
    data = sys.stdin.buffer.read(MAX_PROPOSAL_BYTES + 1)
    hub = action_hub()
    try:
        proposal = parse_proposal(data)
    except ProposalError as error:
        fail(f"{_PROPOSE_PREFIX}: {error}")
    folder = run_folder(hub, run)
    if not folder.is_dir() or folder.is_symlink():
        fail(f"{_PROPOSE_PREFIX}: no scenario run {run}")
    try:
        with run_lock(folder):
            drop_torn_tail(folder)
            records = read_records(folder)
            header = records[0] if records else {}
            if header.get("kind") != "scenario":
                fail(f"{_PROPOSE_PREFIX}: {run} is not a scenario run")
            planned = Planned.of(hub, header)
            project = hub_project_name(hub) or hub.name
            label = str(header.get("workflow"))
            events = ScenarioEvents(project=project, run_id=run, workflow=label)
            recorded = record_proposal(
                folder, records, proposal, planned=planned, events=events, at=now()
            )
            EventSink().flush(events)
    except WorkflowRunError as error:
        fail(f"{_PROPOSE_PREFIX}: {error}")
    investigation = recorded.investigation
    typer.echo(
        f"proposal {recorded.proposal} for step {investigation.step}"
        f" (investigation {investigation.number})"
    )
    for ident, finding in zip(recorded.finding_ids, proposal.findings, strict=True):
        typer.echo(f"finding {ident}: {shown_text(finding.title)}")
    for line in option_lines(planned, recorded, proposal):
        typer.echo(shown_text(line))


RunArgument = Annotated[str, typer.Argument(metavar="RUN", help="The scenario run.")]
IssueFinding = Annotated[
    str | None,
    typer.Option(
        "--issue",
        metavar="FINDING",
        help="Print the finding's tracker issue draft; create it after a y on a terminal.",
    ),
]
InboxFinding = Annotated[
    str | None,
    typer.Option(
        "--inbox", metavar="FINDING", help="Write the finding as a note in brain/_inbox/."
    ),
]


@scenario_app.command("findings")
def findings_command(
    run: RunArgument,
    *,
    as_json: AsJson = False,
    issue: IssueFinding = None,
    inbox: InboxFinding = None,
) -> None:
    """List a scenario run's findings; draft a tracker issue or an inbox note from one."""
    if not RUN_ID_PATTERN.fullmatch(run):
        hint = "use 1 to 32 of a-z 0-9 -, starting with a letter or digit"
        raise typer.BadParameter(hint, param_hint="RUN")
    if issue is not None and inbox is not None:
        raise typer.BadParameter("give --issue or --inbox, not both", param_hint="--issue")
    if as_json and (issue is not None or inbox is not None):
        raise typer.BadParameter("--json only lists the findings", param_hint="--json")
    hub = action_hub()
    view = _scenario_run(hub, run)
    if issue is not None:
        _issue(hub, view, _finding(view, run, issue), run=run)
    elif inbox is not None:
        _inbox(hub, view, _finding(view, run, inbox), run=run)
    elif as_json:
        # ASCII only: agent-written findings may hold C1 or bidi controls, never shown raw.
        typer.echo(json.dumps(_findings_json(view), indent=2, sort_keys=True, ensure_ascii=True))
    else:
        _print_findings(run, view)


def _print_findings(run: str, view: ScenarioRunView) -> None:
    if not view.findings:
        typer.echo(f"no findings in run {run}")
    for finding in view.findings:
        step, title = shown_text(finding.step), shown_text(finding.title)
        typer.echo(f"{shown_text(finding.finding_id)}  {step}  {title}")


def _scenario_run(hub: Path, run: str) -> ScenarioRunView:
    """Scenario run ``run``, folded from its record; else exit 1."""
    folder = run_folder(hub, run)
    if not folder.is_dir() or folder.is_symlink():
        fail(f"{_FINDINGS_PREFIX}: no scenario run {run}")
    try:
        records = read_records(folder)
    except WorkflowRunError as error:
        fail(f"{_FINDINGS_PREFIX}: {error}")
    if not records or records[0].get("kind") != "scenario":
        fail(f"{_FINDINGS_PREFIX}: {run} is not a scenario run")
    return fold_records(records)


def _finding(view: ScenarioRunView, run: str, finding_id: str) -> FindingView:
    found = finding_of(view, finding_id)
    if found is None:
        fail(f"{_FINDINGS_PREFIX}: run {run} has no finding {shown_path(finding_id)}")
    return found


def _record(run: str) -> str:
    """The run's record file, relative to the hub."""
    return (RUNS_ROOT / run / RECORDS).as_posix()


def _issue(hub: Path, view: ScenarioRunView, finding: FindingView, *, run: str) -> None:
    """Print the draft; on a terminal, create it after a ``y``, once."""
    try:
        draft = issue_draft(view, finding, record=_record(run))
    except FindingsError as error:
        fail(f"{_FINDINGS_PREFIX}: {error}")
    typer.echo(f"title: {draft.title}")
    typer.echo("")
    typer.echo(draft.description, nl=False)
    typer.echo("")
    if not has_terminal():
        typer.echo(NO_TERMINAL)
        return
    # One marker per finding, shared with hub web: an issue it names refuses every create; a
    # failed or unfinished create may be taken again here only, after the warning (E-14).
    folder = run_folder(hub, run)
    earlier = _earlier(folder, finding.finding_id)
    config = load_effective_config_or_exit(hub).config
    team = config.tracker.team_keys[0]
    # The question is asked only when a create can run: the key is there, the client resolved.
    missing = missing_key_line(config, os.environ, command="scenario findings")
    if missing is not None:
        fail(missing)
    client = resolve_tracker_client(config, os.environ, hub_root=hub)
    if earlier is not None:
        typer.echo(f"{earlier.state}: {RETRY_WARNING}")
    if not confirmed(f"create this issue in {team}?"):
        typer.echo("the issue was not created")
        return
    # The claim's lock is held across the create, so nothing retakes a running create.
    claim = _claim(folder, finding.finding_id, earlier)
    try:
        typer.echo(transport_line(config), err=True)
        created = _create(claim, client, team=team, draft=draft)
    finally:
        claim.release()
    typer.echo(f"created {shown_text(created.id)}  {shown_text(created.url)}")


def _earlier(folder: Path, finding_id: str) -> IssueMarked | None:
    """The finding's earlier claim, read as hub web reads it; exit 1 when it names an issue
    or a create runs now (E-14: never taken again), or when it cannot be read."""
    try:
        earlier = marked_issue(folder, finding_id)
    except OSError as error:
        fail(f"{_FINDINGS_PREFIX}: {MARK_FAILED}: {error.strerror or error}")
    if earlier is not None and (earlier.issue_id is not None or earlier.running or earlier.busy):
        fail(f"{_FINDINGS_PREFIX}: {earlier.reason}")
    return earlier


def _create(claim: HeldIssue, client: TrackerClient, *, team: str, draft: IssueDraft) -> Issue:
    """Create the issue under ``claim`` and record it; exit 1 when the tracker refuses (the
    failure recorded) or when the created issue cannot be recorded (do not create it again)."""
    try:
        created = client.create_issue(team, draft.title, draft.description)
    except TrackerError as error:
        with contextlib.suppress(OSError):
            claim.fail()
        fail(f"{_FINDINGS_PREFIX}: {error}")
    try:
        claim.record(issue_id=created.id, url=created.url)
    except OSError as error:
        fail(
            f"{_FINDINGS_PREFIX}: the issue {shown_text(created.id)} was created but could"
            f" not be recorded: {error.strerror or error}; do not create it again"
        )
    return created


def _claim(folder: Path, finding_id: str, earlier: IssueMarked | None) -> HeldIssue:
    """Claim the finding's issue marker before the create (take a failed or unfinished one
    again when ``earlier`` names it); else exit 1 naming the claim that stands."""
    try:
        if earlier is None:
            standing = claim_issue(folder, finding_id)
        else:
            standing = retake_issue(folder, earlier)
    except OSError as error:
        fail(f"{_FINDINGS_PREFIX}: {MARK_FAILED}: {error.strerror or error}")
    if isinstance(standing, IssueMarked):
        fail(f"{_FINDINGS_PREFIX}: {standing.reason}")
    return standing


def _inbox(hub: Path, view: ScenarioRunView, finding: FindingView, *, run: str) -> None:
    """Write the finding's note in the hub's ``brain/_inbox/``, never over another."""
    try:
        note = inbox_note(view, finding, record=_record(run), day=date.today())
    except FindingsError as error:
        fail(f"{_FINDINGS_PREFIX}: {error}")
    shown = (INBOX_FOLDER / note.name).as_posix()
    folder = hub / INBOX_FOLDER
    try:
        folder.mkdir(parents=True, exist_ok=True)
        written = write_exclusive(folder, note.name, note.text.encode())
    except OSError as error:
        fail(f"{_FINDINGS_PREFIX}: cannot write {shown}: {error.strerror or error}")
    if not written:
        fail(f"{_FINDINGS_PREFIX}: {shown} already exists; nothing written")
    typer.echo(f"wrote {shown}")


def _findings_json(view: ScenarioRunView) -> dict[str, JsonValue]:
    return {
        "run": view.run,
        "scenario": view.scenario,
        "environment": view.environment,
        "findings": [
            {
                "finding_id": finding.finding_id,
                "step": finding.step,
                "title": finding.title,
                "text": finding.text,
                "evidence": finding.evidence,
            }
            for finding in view.findings
        ],
    }


def _refuse_start(planned: ScenarioPlan) -> NoReturn:
    """Exit 1, naming each problem and each denied step; no scenario run is made."""
    for problem in planned.problems:
        typer.echo(f"{_RUN_PREFIX}: {problem}", err=True)
    for row in planned.rows:
        # An undeclared environment is one problem line already, not one per step.
        if row.decision == "deny" and row.reason_kind != "undeclared":
            reason = _reason(planned, row)
            typer.echo(f"{_RUN_PREFIX}: step {row.step}: deny ({reason})", err=True)
    where = f"{planned.scenario} cannot start in {planned.environment}"
    fail(f"{_RUN_PREFIX}: {where}; no scenario run was created")


def _scenario(hub: Path, name: str, *, prefix: str) -> tuple[WorkflowPlan, DiscoveredWorkflow]:
    """The scenario ``name``, loaded and planned, as discovered; else exit 1."""
    source = DiscoveredScenarioSource(hub, only=name)
    catalog = check_workflows(source)
    _exit_on_problems(catalog)
    if not catalog.plans:
        fail(f"{prefix}: no scenario named {shown_path(name)} in {HUB_SCENARIOS}/")
    return catalog.plans[0], source.found[name]


def _inputs(
    plan: WorkflowPlan,
    texts: dict[str, str],
    *,
    view: EffectiveEnvironments,
    environment: str,
) -> dict[str, JsonValue]:
    """The scenario's inputs typed as declared, then the environment's values, then the
    defaults (core's ``with_environment_values``); else exit 2, a required input that none
    gives named with the environment."""
    declared = plan.document.inputs
    typed = {
        key: typed_input(text, declared[key].type if key in declared else "string", key)
        for key, text in texts.items()
    }
    try:
        filled = with_environment_values(plan, typed, view=view, environment=environment)
    except RunInputError as error:
        # A value from hub.json or hub.local.json, not from --input.
        raise typer.BadParameter(str(error), param_hint="--env") from None
    missing = next(
        (key for key, spec in declared.items() if spec.required and key not in filled), None
    )
    if missing is not None:
        message = (
            f"the input {echo(missing)} is required: give it with --input, or as a value of"
            f" environment {echo(environment)}"
        )
        raise typer.BadParameter(message, param_hint="--input")
    try:
        return start_inputs(plan, filled)
    except (RunInputError, WorkflowEngineError) as error:
        raise typer.BadParameter(str(error), param_hint="--input") from None


def _summary(row: PlanRow, found: ActionDiscovery, hidden: CredentialNames) -> str:
    """The row's plan: its script's summary in ``plan`` mode, or why it is not called."""
    if row.draft:
        return DRAFT_REASON
    if not row.known:
        return RUN_TIME
    if row.call is None:
        return NOT_PLANNED
    entry = resolve_action(found.actions, row.action)
    call = ActionCall(
        entry=entry,
        files=found.files[entry.document_path],
        inputs=row.call.inputs,
        endpoint=row.call.endpoint,
    )
    return plan_action(call, environ=os.environ, hidden=hidden)


def _print_plan(planned: ScenarioPlan, summaries: list[str]) -> None:
    where = f"environment {planned.environment}"
    if planned.access is not None:
        where += f", access {planned.access}" + (", production" if planned.production else "")
    typer.echo(f"scenario: {planned.scenario} ({where})")
    for row, summary in zip(planned.rows, summaries, strict=True):
        reason = _reason(planned, row)
        decision = row.decision if reason is None else f"deny ({reason})"
        typer.echo(f"{row.step}  {row.type}  {row.action}  {row.effect}  {decision}")
        args = ", ".join(f"{key}={text}" for key, text in row.args.items())
        typer.echo(f"  args: {shown_text(args) if args else '-'}")
        endpoints = ", ".join(
            " ".join(part for part in (f"{key} → {service}", url, resource) if part)
            for key, (service, url, resource) in row.endpoints.items()
        )
        typer.echo(f"  endpoints: {endpoints or '-'}")
        if row.every is not None:
            typer.echo(f"  polls: every {row.every}, timeout {row.timeout}")
        typer.echo(f"  content hash: {row.content_hash}")
        typer.echo(f"  draft: {'yes' if row.draft else 'no'}")
        typer.echo(f"  plan: {shown_text(summary)}")


def _planned_json(planned: ScenarioPlan, summaries: list[str]) -> dict[str, JsonValue]:
    rows: list[JsonValue] = [
        {
            "step": row.step,
            "type": row.type,
            "action": row.action,
            "effect": row.effect,
            "args": dict(row.args),
            "endpoints": {
                key: {"service": service, "url": url, "resource": resource}
                for key, (service, url, resource) in row.endpoints.items()
            },
            "every": row.every,
            "timeout": row.timeout,
            "content_hash": row.content_hash,
            "draft": row.draft,
            "decision": row.decision,
            "reason_kind": row.reason_kind,
            "reason": _reason(planned, row),
            "plan": summary,
        }
        for row, summary in zip(planned.rows, summaries, strict=True)
    ]
    return {
        "scenario": planned.scenario,
        "environment": planned.environment,
        "access": planned.access,
        "production": planned.production,
        "denied": planned.denied,
        "problems": list(planned.problems),
        "rows": rows,
    }


def _reason(planned: ScenarioPlan, row: PlanRow) -> str | None:
    return deny_reason(
        PolicyDecision(decision=row.decision, reason_kind=row.reason_kind),
        effect=row.effect,
        environment=planned.environment,
        access=planned.access,
    )


def _exit_on_problems(catalog: WorkflowCatalog) -> None:
    if catalog.problems:
        fail(*(problem_line(problem) for problem in catalog.problems))
