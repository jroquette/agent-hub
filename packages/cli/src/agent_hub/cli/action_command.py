"""``hub action list|plan|run``: the hub's actions, one call planned or run by a person
(docs/design/scenarios.md § Actions and the script contract, § Policy; ADR 0041).

``list [--json]`` prints one line per action that loads, ``<pack>/<name>  <effect>  <inputs>``
and ``draft`` when its files are not committed as they are on disk; each load problem is one
stderr line and exits 1; a hub without actions prints ``no actions yet``.

``plan NAME --env ENV [--input name=value]...`` resolves the call (its inputs, each ``service``
input's endpoint in ENV, its content hash and draft state), calls the script in ``plan`` mode
with no credential (never for a draft), and prints the policy's decision for origin ``human``;
exit 1 on a ``deny`` or a call that cannot be resolved. It writes nothing: no run-mode process,
no event.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final

import typer

from agent_hub.cli.action_process import ActionCall, plan_action
from agent_hub.cli.command_exits import FAILURE, fail
from agent_hub.cli.effective_config import load_effective_config_or_exit
from agent_hub.cli.hub_root import hub_checkout, hub_root_or_exit
from agent_hub.cli.run_children import CHILD_HIDDEN, without
from agent_hub.core.hub_config.effective_environments import (
    EffectiveEnvironments,
    SourcedEnvironment,
    effective_environments,
)
from agent_hub.core.json_form import JsonValue, dump_json
from agent_hub.core.scenarios.access_policy import PolicyDecision, decide, find_environment
from agent_hub.core.scenarios.action_call import ActionCallError, ActionCallPlan, plan_action_call
from agent_hub.core.scenarios.action_catalog import ActionEntry, ActionRefError, resolve_action
from agent_hub.core.scenarios.action_document import ActionDocument
from agent_hub.core.scenarios.credentials import CredentialNames
from agent_hub.generator.action_discovery import ActionDiscovery, discover_actions

COMMAND: Final = "action"
MAX_INPUTS: Final = 64
MAX_INPUT_BYTES: Final = 64 * 1024
DRAFT_REASON: Final = "draft action: commit it to run"

action_app = typer.Typer(
    name=COMMAND, no_args_is_help=True, help="List, plan and run the hub's actions."
)

Name = Annotated[str, typer.Argument(metavar="NAME", help="The action: <pack>/<name> or <name>.")]
Environment = Annotated[
    str, typer.Option("--env", metavar="ENV", help="The environment the action runs in.")
]
Inputs = Annotated[
    list[str] | None,
    typer.Option("--input", metavar="NAME=VALUE", help="An input of the action."),
]
AsJson = Annotated[bool, typer.Option("--json", help="Print one JSON object instead of lines.")]


@dataclass(frozen=True, kw_only=True, slots=True)
class ResolvedCall:
    """One action call, resolved in the hub's checkout: what plan prints and run runs."""

    hub: Path
    entry: ActionEntry
    files: tuple[tuple[str, bytes], ...]
    view: EffectiveEnvironments
    environment: SourcedEnvironment | None
    environment_name: str
    plan: ActionCallPlan
    decision: PolicyDecision

    @property
    def call(self) -> ActionCall:
        return ActionCall(
            entry=self.entry,
            files=self.files,
            inputs=self.plan.inputs,
            endpoint=self.plan.endpoint,
        )

    @property
    def hidden(self) -> CredentialNames:
        return CredentialNames.of(self.view)


@action_app.command("list")
def list_command(*, as_json: AsJson = False) -> None:
    """List every action with its pack, effect, inputs and draft state."""
    found = discover_actions(_hub())
    if as_json:
        actions: list[JsonValue] = [_listed(entry) for entry in found.actions]
        typer.echo(dump_json({"actions": actions}).decode(), nl=False)
    elif not found.actions and not found.problems:
        typer.echo("no actions yet")
    for entry in [] if as_json else found.actions:
        line = f"{entry.ref}  {entry.document.effect}  {_inputs_text(entry.document)}"
        typer.echo(f"{line}  draft" if entry.draft else line)
    _exit_on_problems(found)


@action_app.command("plan")
def plan_command(name: Name, *, environment: Environment, given: Inputs = None) -> None:
    """Show one call's resolved plan and the policy's decision for a person."""
    resolved = resolve_call(name, environment=environment, given=given or [])
    entry, plan = resolved.entry, resolved.plan
    shown_inputs = ", ".join(f"{key}={_shown_value(value)}" for key, value in plan.inputs.items())
    typer.echo(f"action: {entry.ref} ({entry.document.effect})")
    access = resolved.environment.access if resolved.environment is not None else "undeclared"
    typer.echo(f"environment: {resolved.environment_name} (access {access})")
    typer.echo(f"inputs: {shown_inputs or '-'}")
    typer.echo(f"endpoints: {_endpoints_text(plan) or '-'}")
    typer.echo(f"content hash: {entry.content_hash}")
    typer.echo(f"draft: {'yes' if entry.draft else 'no'}")
    summary = (
        DRAFT_REASON
        if entry.draft
        else plan_action(resolved.call, environ=os.environ, hidden=resolved.hidden)
    )
    typer.echo(f"plan: {summary}")
    typer.echo(f"decision: {decision_text(resolved)}")
    if resolved.decision.decision == "deny":
        raise typer.Exit(FAILURE)


def resolve_call(name: str, *, environment: str, given: list[str]) -> ResolvedCall:
    """The call of action ``name`` in ``environment`` with ``given`` inputs, decided for origin
    ``human``; exit 2 on a malformed ``--input``, 1 on anything that cannot be resolved."""
    values = _given_texts(given)
    hub = _hub()
    found = discover_actions(hub)
    try:
        entry = resolve_action(found.actions, name)
    except ActionRefError as error:
        for problem in found.problems:
            typer.echo(str(problem), err=True)
        fail(f"hub action: {error}")
    effective = load_effective_config_or_exit(hub)
    view = effective_environments(effective.config, effective.local)
    declared = find_environment(view, environment)
    if declared is None:
        fail(f"hub action: environment {environment} is not declared")
    try:
        typed = {key: _typed(entry.document, key, text) for key, text in values.items()}
        plan = plan_action_call(entry.document, typed, environment=environment, view=view)
    except ActionCallError as error:
        fail(f"hub action: {entry.ref}: {error}")
    return ResolvedCall(
        hub=hub,
        entry=entry,
        files=found.files[entry.document_path],
        view=view,
        environment=declared,
        environment_name=environment,
        plan=plan,
        decision=decide(declared, entry.document.effect, "human", draft=entry.draft),
    )


def decision_text(resolved: ResolvedCall) -> str:
    """``allow``, ``ask``, or ``deny (<why, in plain words>)``."""
    decision = resolved.decision
    if decision.decision != "deny":
        return decision.decision
    effect, name = resolved.entry.document.effect, resolved.environment_name
    reasons = {
        "draft": DRAFT_REASON,
        "undeclared": f"environment {name} is not declared",
        "production": f"{name} is a production environment: writes and destroys are denied",
        "table": f"access {resolved.environment.access if resolved.environment else ''}"
        f" in {name} does not allow {effect}",
        "read_only": "write and destroy actions need a terminal or a scenario run",
    }
    return f"deny ({reasons.get(decision.reason_kind, decision.reason_kind)})"


def _hub() -> Path:
    root = hub_root_or_exit(os.environ, command=COMMAND)
    return hub_checkout(root, command=COMMAND, environ=without(os.environ, CHILD_HIDDEN))


def _given_texts(given: list[str]) -> dict[str, str]:
    if len(given) > MAX_INPUTS:
        raise typer.BadParameter(f"at most {MAX_INPUTS} inputs", param_hint="--input")
    values: dict[str, str] = {}
    for item in given:
        key, sep, text = item.partition("=")
        if not sep or not key:
            raise typer.BadParameter("give NAME=VALUE", param_hint="--input")
        if len(text.encode(errors="surrogatepass")) > MAX_INPUT_BYTES:
            raise typer.BadParameter(
                f"{key}: at most {MAX_INPUT_BYTES} bytes", param_hint="--input"
            )
        values[key] = text
    return values


def _typed(action: ActionDocument, key: str, text: str) -> JsonValue:
    """``text`` as the declared input's type; a value that does not read as it is kept as text,
    so the call's check names the input and never echoes the value."""
    declared = action.inputs.get(key)
    kind = declared.type if declared is not None else "string"
    if kind == "boolean" and text in ("true", "false"):
        return text == "true"
    if kind in ("integer", "number"):
        try:
            return int(text)
        except ValueError:
            pass
        if kind == "number":
            try:
                return float(text)
            except ValueError:
                pass
    return text


def _listed(entry: ActionEntry) -> dict[str, JsonValue]:
    return {
        "action": entry.ref,
        "pack": entry.pack,
        "name": entry.document.name,
        "effect": entry.document.effect,
        "inputs": {key: value.type for key, value in entry.document.inputs.items()},
        "content_hash": entry.content_hash,
        "draft": entry.draft,
    }


def _inputs_text(action: ActionDocument) -> str:
    inputs = ", ".join(f"{key} ({value.type})" for key, value in action.inputs.items())
    return inputs or "no inputs"


def _endpoints_text(plan: ActionCallPlan) -> str:
    parts = []
    for (key, endpoint), service in zip(plan.endpoint.items(), plan.services, strict=True):
        where = " ".join(str(value) for value in endpoint.values() if value is not None)
        parts.append(f"{key} → {service} {where}".rstrip())
    return ", ".join(parts)


def _shown_value(value: JsonValue) -> str:
    return value if isinstance(value, str) else dump_json(value).decode().strip()


def _exit_on_problems(found: ActionDiscovery) -> None:
    for problem in found.problems:
        typer.echo(str(problem), err=True)
    if found.problems:
        raise typer.Exit(FAILURE)
