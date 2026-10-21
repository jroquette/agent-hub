"""``hub scenario list|plan|run``: the hub's scenarios, listed, planned and run
(docs/design/scenarios.md § Contract, § Plan and modes; ADR 0041).

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
removes a gate: ``--yes`` and its kind are unknown options (exit 2).

``propose --run RUN`` records an investigation's findings and options, the fixed schema as JSON
on stdin (at most 256 KiB, bounds and secret-shape redaction in core's ``investigation``), for
scenario run RUN paused at an open investigation (else exit 1, nothing recorded): each option's
steps are planned with origin ``agent`` and printed with their plan, ``needs acceptance`` when
one runs a draft action, and why an option cannot be picked; one ``finding`` event per finding.
A later proposal replaces the earlier one as the investigation's options.
"""

import os
import sys
from pathlib import Path
from typing import Annotated, Final, NoReturn

import typer

from agent_hub.cli.action_command import (
    DRAFT_REASON,
    Environment,
    Inputs,
    action_hub,
    deny_reason,
    given_texts,
)
from agent_hub.cli.action_process import ActionCall, plan_action
from agent_hub.cli.collect import hub_project_name
from agent_hub.cli.command_exits import FAILURE, fail
from agent_hub.cli.effective_config import load_effective_config_or_exit
from agent_hub.cli.init_report import shown_path, shown_text
from agent_hub.cli.run_log import new_run_id, now
from agent_hub.cli.scenario_investigation import Planned, option_lines, record_proposal
from agent_hub.cli.scenario_runs import (
    INTERACTIVE,
    MODES,
    ScenarioStart,
    load_scenario,
    start,
)
from agent_hub.cli.workflow_command import problem_line, typed_input
from agent_hub.cli.workflow_runs import (
    RUN_ID_PATTERN,
    EventSink,
    WorkflowRunError,
    drop_torn_tail,
    read_records,
    run_folder,
    run_lock,
)
from agent_hub.core.hub_config.effective_environments import effective_environments
from agent_hub.core.json_form import JsonValue, dump_json
from agent_hub.core.scenarios.access_policy import PolicyDecision
from agent_hub.core.scenarios.action_catalog import resolve_action
from agent_hub.core.scenarios.credentials import CredentialNames
from agent_hub.core.scenarios.investigation import (
    MAX_PROPOSAL_BYTES,
    ProposalError,
    parse_proposal,
)
from agent_hub.core.scenarios.scenario_events import ScenarioEvents
from agent_hub.core.scenarios.scenario_plan import PlanRow, ScenarioPlan, plan_scenario
from agent_hub.core.workflows.catalog import WorkflowCatalog, check_workflows
from agent_hub.core.workflows.engine import WorkflowEngineError, start_inputs
from agent_hub.core.workflows.plan import WorkflowPlan
from agent_hub.generator.action_discovery import ActionDiscovery, discover_actions
from agent_hub.generator.scenario_discovery import HUB_SCENARIOS, DiscoveredScenarioSource
from agent_hub.generator.workflow_discovery import DiscoveredWorkflow

COMMAND: Final = "scenario"
RUN_TIME: Final = "runs with values known at run time"
NOT_PLANNED: Final = "not planned"
_PLAN_PREFIX: Final = "hub scenario plan"
_RUN_PREFIX: Final = "hub scenario run"
_PROPOSE_PREFIX: Final = "hub scenario propose"

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
        inputs=_inputs(plan, texts),
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


@scenario_app.command("run")
def run_command(
    name: Name,
    *,
    environment: Environment,
    given: Inputs = None,
    mode: Mode = INTERACTIVE,
    run_id: RunId = None,
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
    found = discover_actions(hub)
    effective = load_effective_config_or_exit(hub)
    view = effective_environments(effective.config, effective.local)
    inputs = _inputs(plan, texts)
    planned = plan_scenario(
        plan,
        pack=scenario.pack,
        actions=found.actions,
        view=view,
        environment=environment,
        inputs=inputs,
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
    )
    try:
        code = start(hub, run_id or new_run_id(), begin)
    except (WorkflowRunError, WorkflowEngineError) as error:
        fail(f"{_RUN_PREFIX}: {error}")
    raise typer.Exit(code)


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


def _inputs(plan: WorkflowPlan, texts: dict[str, str]) -> dict[str, JsonValue]:
    """The scenario's inputs typed as declared, defaults filled; else exit 2."""
    declared = plan.document.inputs
    typed = {
        key: typed_input(text, declared[key].type if key in declared else "string", key)
        for key, text in texts.items()
    }
    try:
        return start_inputs(plan, typed)
    except WorkflowEngineError as error:
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
