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

``run NAME --env ENV [--input name=value]...`` runs it for a person (origin ``human``): a
``deny`` exits 1 before any prompt; with no terminal on stdin only ``read`` actions run (a write
or destroy exits 1, ``write and destroy actions need a terminal or a scenario run``, and is
recorded as a ``deny`` with ``reason_kind: read_only``); an ``ask`` prompts ``y/N`` and ``n``
runs nothing. The output is printed as the script gave it. Each decision is a
``policy.decision`` event, a run is ``action.start`` and ``action.end``, under the session
``action:<uuid>`` (metadata only).

``run NAME --run RUN [--input name=value]...`` is an investigation's read (P-10, AM-12): scenario
run RUN must be paused at an open, unanswered investigation (else exit 1), and the call runs in
its environment (``--env`` may be left out; another one exits 1), decided for origin ``agent``,
read-only whatever the terminal: a write or destroy exits 1 and is recorded as a ``deny`` with
``reason_kind: read_only``. The env file is loaded here, by the one loader, so the action gets
``AWS_PROFILE`` and the env file's variables even when the caller's environment (an agent
session's) has none of them. The call is an ``agent_action`` line in the run's record (its
inputs, its output redacted, its status) and its events are the run's (session ``run:<id>``, step
the investigation's gate), all under the run's lock; no credential value reaches either.
"""

import getpass
import os
import sys
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final

import typer

from agent_hub.cli.action_process import ActionCall, plan_action, run_action
from agent_hub.cli.collect import hub_project_name
from agent_hub.cli.command_exits import FAILURE, fail
from agent_hub.cli.effective_config import load_effective_config_or_exit
from agent_hub.cli.env_files_loader import EnvFileLoadError, load_env_file
from agent_hub.cli.hub_root import hub_checkout, hub_root_or_exit
from agent_hub.cli.run_children import CHILD_HIDDEN, without
from agent_hub.cli.run_log import now, open_default_event_store
from agent_hub.cli.workflow_runs import (
    RUN_ID_PATTERN,
    WorkflowRunError,
    append_record,
    drop_torn_tail,
    read_records,
    run_folder,
    run_lock,
)
from agent_hub.core.errors import AgentHubError
from agent_hub.core.hub_config.effective_environments import (
    EffectiveEnvironments,
    SourcedEnvironment,
    effective_environments,
)
from agent_hub.core.hub_config.environments import Endpoint
from agent_hub.core.ingestion.ingest_events import IngestEvents
from agent_hub.core.json_form import JsonValue, dump_json
from agent_hub.core.scenarios.access_policy import (
    DRAFT_REASON,
    NEEDS_TERMINAL,
    Origin,
    PolicyDecision,
    decide,
    deny_reason,
    find_environment,
)
from agent_hub.core.scenarios.action_call import ActionCallError, ActionCallPlan, plan_action_call
from agent_hub.core.scenarios.action_catalog import ActionEntry, ActionRefError, resolve_action
from agent_hub.core.scenarios.action_document import ActionDocument
from agent_hub.core.scenarios.credentials import (
    CredentialNames,
    CredentialsError,
    action_credentials,
    credentials_for,
)
from agent_hub.core.scenarios.run_record import AGENT_ACTION, fold_records
from agent_hub.core.scenarios.scenario_events import ActionFacts, ScenarioEvents
from agent_hub.core.workflows.failures import NodeFailedError
from agent_hub.generator.action_discovery import ActionDiscovery, discover_actions

COMMAND: Final = "action"
MAX_INPUTS: Final = 64
MAX_INPUT_BYTES: Final = 64 * 1024
INVESTIGATION_READS: Final = "an investigation runs read actions only"
_RUN_PREFIX: Final = "hub action run"

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
    # The folders an env file may be in, relative to the workspace: the hub's and each repo's.
    roots: tuple[str, ...]

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
    found = discover_actions(action_hub())
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


RunEnvironment = Annotated[
    str | None,
    typer.Option(
        "--env", metavar="ENV", help="The environment the action runs in (with --run, the run's)."
    ),
]
InvestigationRun = Annotated[
    str | None,
    typer.Option(
        "--run",
        metavar="RUN",
        help="A scenario run paused at an investigation: a read for it, origin agent.",
    ),
]


@action_app.command("run")
def run_command(
    name: Name,
    *,
    environment: RunEnvironment = None,
    given: Inputs = None,
    run: InvestigationRun = None,
) -> None:
    """Run one action for a person: reads anywhere declared, writes only on a terminal."""
    if run is not None:
        _investigation_read(name, run=run, environment=environment, given=given or [])
        return
    if environment is None:
        raise typer.BadParameter("give the environment the action runs in", param_hint="--env")
    resolved = resolve_call(name, environment=environment, given=given or [])
    entry, decision = resolved.entry, resolved.decision
    events = ScenarioEvents(
        project=hub_project_name(resolved.hub) or resolved.hub.name,
        run_id=None,
        workflow=None,
        session=f"action:{uuid.uuid4()}",
    )
    facts = ActionFacts(
        step=entry.ref,
        attempt=1,
        action=entry.ref,
        content_hash=entry.content_hash,
        environment=resolved.environment_name,
        services=resolved.plan.services,
        effect=entry.document.effect,
        origin="human",
        decision=decision.decision,
    )
    if decision.decision == "deny":
        events.policy_decided(facts, reason_kind=decision.reason_kind, at=now())
        _send(events)
        fail(
            f"{_RUN_PREFIX}: {entry.ref} in {resolved.environment_name}: {decision_text(resolved)}"
        )
    if entry.document.effect != "read" and not has_terminal():
        refused = facts.model_copy(update={"decision": "deny"})
        events.policy_decided(refused, reason_kind="read_only", at=now())
        _send(events)
        fail(f"{_RUN_PREFIX}: {NEEDS_TERMINAL}")
    events.policy_decided(facts, reason_kind=decision.reason_kind, at=now())
    if decision.decision == "ask":
        question = f"run {entry.ref} ({entry.document.effect}) in {resolved.environment_name}?"
        if not confirmed(question):
            _send(events)
            fail(f"{_RUN_PREFIX}: {entry.ref}: not run")
        facts = facts.model_copy(update={"approver": getpass.getuser()})
    events.action_started(facts, at=now())
    try:
        injected = credentials(resolved)
        output = run_action(
            resolved.call, environ=os.environ, hidden=resolved.hidden, credentials=injected
        )
    except NodeFailedError as error:
        events.action_ended(facts, status="failed", failure_kind=error.kind, at=now())
        _send(events)
        fail(f"{_RUN_PREFIX}: {entry.ref}: {error.kind}: {error}")
    events.action_ended(facts, status="ok", failure_kind=None, at=now())
    _send(events)
    typer.echo(dump_json(output).decode(), nl=False)


def _investigation_read(name: str, *, run: str, environment: str | None, given: list[str]) -> None:
    """``run NAME --run RUN``: an investigation's read, under the scenario run's lock."""
    if not RUN_ID_PATTERN.fullmatch(run):
        hint = "use 1 to 32 of a-z 0-9 -, starting with a letter or digit"
        raise typer.BadParameter(hint, param_hint="--run")
    folder = run_folder(action_hub(), run)
    if not folder.is_dir() or folder.is_symlink():
        fail(f"{_RUN_PREFIX}: no scenario run {run}")
    try:
        with run_lock(folder):
            drop_torn_tail(folder)
            records = read_records(folder)
            pending = fold_records(records).open_investigation
            header = records[0] if records else {}
            if header.get("kind") != "scenario" or pending is None or pending.choice is not None:
                fail(f"{_RUN_PREFIX}: scenario run {run} is not paused at an open investigation")
            where = str(header.get("environment"))
            if environment is not None and environment != where:
                fail(f"{_RUN_PREFIX}: scenario run {run} runs in {where}, not {environment}")
            resolved = resolve_call(name, environment=where, given=given, origin="agent")
            reads = sum(1 for record in records if record.get("event") == AGENT_ACTION)
            _AgentRead(
                folder=folder,
                resolved=resolved,
                gate=pending.gate,
                number=pending.number,
                item=f"read{reads + 1}",
                workflow=str(header.get("workflow")),
            ).execute()
    except WorkflowRunError as error:
        fail(f"{_RUN_PREFIX}: {error}")


@dataclass(frozen=True, kw_only=True, slots=True)
class _AgentRead:
    """One investigation read: decided for origin ``agent``, run only when it is a read the
    policy allows, recorded in the scenario run and as its events."""

    folder: Path
    resolved: ResolvedCall
    gate: str
    number: int
    item: str
    workflow: str

    def execute(self) -> None:
        resolved = self.resolved
        entry, decision = resolved.entry, resolved.decision
        events = ScenarioEvents(
            project=hub_project_name(resolved.hub) or resolved.hub.name,
            run_id=self.folder.name,
            workflow=self.workflow,
        )
        facts = ActionFacts(
            step=self.gate,
            attempt=self.number,
            action=entry.ref,
            content_hash=entry.content_hash,
            environment=resolved.environment_name,
            services=resolved.plan.services,
            effect=entry.document.effect,
            origin="agent",
            decision=decision.decision,
        )
        if entry.document.effect != "read":
            # Read-only whatever the policy decided (P-10): the reason is always read_only.
            decision = PolicyDecision(decision="deny", reason_kind="read_only")
            facts = facts.model_copy(update={"decision": "deny"})
        events.policy_decided(facts, reason_kind=decision.reason_kind, at=now(), item=self.item)
        if decision.decision != "allow":
            self._record(decision, status="refused", failure_kind=None, output=None)
            _send(events)
            reason = INVESTIGATION_READS if decision.reason_kind == "read_only" else None
            shown = reason or decision_text(resolved)
            fail(f"{_RUN_PREFIX}: {entry.ref} in {resolved.environment_name}: {shown}")
        events.action_started(facts, at=now(), item=self.item)
        try:
            output = run_action(
                resolved.call,
                environ=os.environ,
                hidden=resolved.hidden,
                credentials=credentials(resolved),
            )
        except NodeFailedError as error:
            events.action_ended(
                facts, status="failed", failure_kind=error.kind, at=now(), item=self.item
            )
            self._record(decision, status="failed", failure_kind=error.kind, output=None)
            _send(events)
            fail(f"{_RUN_PREFIX}: {entry.ref}: {error.kind}: {error}")
        events.action_ended(facts, status="ok", failure_kind=None, at=now(), item=self.item)
        self._record(decision, status="ok", failure_kind=None, output=output)
        _send(events)
        typer.echo(dump_json(output).decode(), nl=False)

    def _record(
        self,
        decision: PolicyDecision,
        *,
        status: str,
        failure_kind: str | None,
        output: JsonValue,
    ) -> None:
        resolved = self.resolved
        line: dict[str, JsonValue] = {"event": AGENT_ACTION, "gate": self.gate}
        line |= {"number": self.number, "item": self.item, "action": resolved.entry.ref}
        line |= {"effect": resolved.entry.document.effect, "origin": "agent"}
        line |= {"decision": decision.decision, "reason_kind": decision.reason_kind}
        line |= {"inputs": dict(resolved.plan.inputs), "status": status}
        append_record(self.folder, line | {"failure_kind": failure_kind, "output": output})


def credentials(resolved: ResolvedCall) -> dict[str, str]:
    """What the call's process gets on top of its plain environment (``call_credentials``)."""
    if resolved.environment is None:
        return {}
    return call_credentials(
        resolved.hub,
        resolved.environment,
        endpoints=resolved.plan.endpoints,
        roots=resolved.roots,
        environ=os.environ,
    )


def call_credentials(
    hub: Path,
    environment: SourcedEnvironment,
    *,
    endpoints: Sequence[Endpoint],
    roots: Sequence[str],
    environ: Mapping[str, str],
) -> dict[str, str]:
    """What an action call's process gets on top of its plain environment, for ``hub action
    run`` and a scenario run's steps alike: its env file's variables (read now, through the one
    loader), ``AWS_PROFILE`` and the declared names from ``environ``; raises
    ``NodeFailedError`` (``config``) when they cannot be had, before any process."""
    try:
        chosen = credentials_for(environment, endpoints)
        env_file = chosen.env_file if chosen is not None else None
        values = (
            {}
            if env_file is None
            else load_env_file(hub.parent, env_file, roots=roots, environment=environment.name)
        )
    except (CredentialsError, EnvFileLoadError) as error:
        raise NodeFailedError("config", str(error)) from None
    return action_credentials(chosen, environ=environ, env_file_values=values)


def resolve_call(
    name: str, *, environment: str, given: list[str], origin: Origin = "human"
) -> ResolvedCall:
    """The call of action ``name`` in ``environment`` with ``given`` inputs, decided for
    ``origin``; exit 2 on a malformed ``--input``, 1 on anything that cannot be resolved."""
    values = given_texts(given)
    hub = action_hub()
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
        decision=decide(declared, entry.document.effect, origin, draft=entry.draft),
        roots=(hub.name, *(repo.dir for repo in effective.config.repos)),
    )


def decision_text(resolved: ResolvedCall) -> str:
    """``allow``, ``ask``, or ``deny (<why, in plain words>)``."""
    environment = resolved.environment
    reason = deny_reason(
        resolved.decision,
        effect=resolved.entry.document.effect,
        environment=resolved.environment_name,
        access=environment.access if environment is not None else None,
    )
    return resolved.decision.decision if reason is None else f"deny ({reason})"


def action_hub() -> Path:
    """The hub's main checkout: where actions are read and their drafts told apart."""
    root = hub_root_or_exit(os.environ, command=COMMAND)
    return hub_checkout(root, command=COMMAND, environ=without(os.environ, CHILD_HIDDEN))


def given_texts(given: list[str]) -> dict[str, str]:
    """``NAME=VALUE`` pairs as texts, at most ``MAX_INPUTS`` of ``MAX_INPUT_BYTES``; else exit 2."""
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


def has_terminal() -> bool:
    try:
        return sys.stdin.isatty()
    except ValueError:
        # A closed stdin is no terminal.
        return False


def _send(events: ScenarioEvents) -> None:
    """Append the call's events; a store that cannot take them is one stderr line, not a
    failure of the call."""
    try:
        IngestEvents(open_default_event_store()).execute(events.events)
    except (AgentHubError, OSError) as error:
        reason = " ".join(str(error).split()) or type(error).__name__
        typer.echo(f"{_RUN_PREFIX}: event store unavailable: {reason}", err=True)


def confirmed(question: str) -> bool:
    """A ``y`` to ``question``; the end of input (or Ctrl-C) at the prompt is a ``n``."""
    try:
        return typer.confirm(question, default=False)
    except typer.Abort:
        typer.echo("", err=True)
        return False
