"""``hub scenario list|plan``: the hub's scenarios, listed and planned
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
"""

import os
from typing import Annotated, Final

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
from agent_hub.cli.command_exits import FAILURE, fail
from agent_hub.cli.effective_config import load_effective_config_or_exit
from agent_hub.cli.init_report import shown_path, shown_text
from agent_hub.cli.workflow_command import problem_line, typed_input
from agent_hub.core.hub_config.effective_environments import effective_environments
from agent_hub.core.json_form import JsonValue, dump_json
from agent_hub.core.scenarios.access_policy import PolicyDecision
from agent_hub.core.scenarios.action_catalog import resolve_action
from agent_hub.core.scenarios.credentials import CredentialNames
from agent_hub.core.scenarios.scenario_plan import PlanRow, ScenarioPlan, plan_scenario
from agent_hub.core.workflows.catalog import WorkflowCatalog, check_workflows
from agent_hub.core.workflows.engine import WorkflowEngineError, start_inputs
from agent_hub.core.workflows.plan import WorkflowPlan
from agent_hub.generator.action_discovery import ActionDiscovery, discover_actions
from agent_hub.generator.scenario_discovery import HUB_SCENARIOS, DiscoveredScenarioSource

COMMAND: Final = "scenario"
RUN_TIME: Final = "runs with values known at run time"
NOT_PLANNED: Final = "not planned"
_PLAN_PREFIX: Final = "hub scenario plan"

scenario_app = typer.Typer(
    name=COMMAND, no_args_is_help=True, help="List and plan the hub's scenarios."
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
    source = DiscoveredScenarioSource(hub, only=name)
    catalog = check_workflows(source)
    _exit_on_problems(catalog)
    if not catalog.plans:
        fail(f"{_PLAN_PREFIX}: no scenario named {shown_path(name)} in {HUB_SCENARIOS}/")
    [plan] = catalog.plans
    found = discover_actions(hub)
    effective = load_effective_config_or_exit(hub)
    view = effective_environments(effective.config, effective.local)
    planned = plan_scenario(
        plan,
        pack=source.found[name].pack,
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
