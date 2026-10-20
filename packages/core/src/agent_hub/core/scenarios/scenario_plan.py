"""A scenario's plan: what each step will do, where, with which effect, and whether the policy
lets it (docs/design/scenarios.md § Plan and modes; AC-350.17, .18, .42).

``plan_scenario`` takes a planned scenario (``plan_workflow``), the hub's actions, the effective
environments and the inputs (defaults filled), and returns one ``PlanRow`` per ``action`` or
``expect`` step, a ``loop_group``'s body included, plus the problems that refuse a start. It
reads no file and starts nothing: the plan-mode call of a row whose args are all known is the
caller's (``PlanRow.call``).

A ``with`` value known before the run (a literal, or text reading only ``$INPUTS``) is resolved
as the engine resolves it; any other is shown with each run-time reference as ``<$CTX.<name>
from <node>>`` or ``<$<node>.output[.path] from <node>>``, and that input is left out of the
call (``action_call``'s ``pending``). Each step is decided for origin ``author``.

Problems, in step order: an undeclared environment; an action no step can resolve; a call that
cannot be planned (a ``service`` with no endpoint in the environment, a missing input); a path
into an action's output that its ``output_format`` does not name (``$<node>.output.<path>`` or
``$self.output.<path>``, the check core's planner leaves to the action, E-6); two steps that both
need a gate (a policy ``ask``, an ``approval`` or a ``wait``) with no order between them
(AC-350.42). A plan is ``denied`` when it has a problem or a ``deny`` row.
"""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from agent_hub.core.hub_config.effective_environments import EffectiveEnvironments
from agent_hub.core.hub_config.environments import Access
from agent_hub.core.json_form import JsonValue
from agent_hub.core.scenarios.access_policy import (
    Decision,
    Effect,
    PolicyDecision,
    ReasonKind,
    decide,
    find_environment,
)
from agent_hub.core.scenarios.action_call import ActionCallError, ActionCallPlan, plan_action_call
from agent_hub.core.scenarios.action_catalog import ActionEntry, ActionRefError, resolve_action
from agent_hub.core.workflows.document import Loc
from agent_hub.core.workflows.nodes import (
    ActionNode,
    ApprovalNode,
    ExpectNode,
    LoopGroupNode,
    Node,
    WaitNode,
)
from agent_hub.core.workflows.plan import WorkflowPlan, node_texts, schema_has_path
from agent_hub.core.workflows.substitution import (
    CtxRef,
    InputRef,
    NodeRef,
    Ref,
    RefContext,
    SelfRef,
    SubstitutionError,
    canonical_text,
    echo,
    find_refs,
    parse_ref,
    render,
    resolve,
    rewrite_refs,
)

UNORDERED_GATES = (
    "steps {first} and {second} both need a gate and have no order between them:"
    " one must depend on the other"
)


class PlanRow(BaseModel):
    """One action step: its action, args as shown, endpoints, pinned content and decision.

    ``args`` holds each input the call gets, as text; ``endpoints`` each ``service`` input whose
    value is known, as ``(<repo>/<service>, url, resource)``; ``call`` the call a plan-mode run
    takes, ``None`` unless every arg is known (``known``) and it could be planned."""

    model_config = ConfigDict(frozen=True)

    step: str
    type: str
    action: str
    effect: Effect
    args: Mapping[str, str]
    endpoints: Mapping[str, tuple[str, str | None, str | None]]
    content_hash: str
    draft: bool
    decision: Decision
    reason_kind: ReasonKind
    known: bool
    call: ActionCallPlan | None
    # An expect's polling: ``every`` and ``timeout`` as written.
    every: str | None = None
    timeout: str | None = None


class ScenarioPlan(BaseModel):
    """A scenario planned in one environment: its rows and the problems that refuse a start."""

    model_config = ConfigDict(frozen=True)

    scenario: str
    environment: str
    # ``None`` when no config file declares the environment.
    access: Access | None
    production: bool
    rows: tuple[PlanRow, ...]
    problems: tuple[str, ...]

    @property
    def denied(self) -> bool:
        """Whether the scenario may not start: a problem, or a step the policy denies."""
        return bool(self.problems) or any(row.decision == "deny" for row in self.rows)


def plan_scenario(
    plan: WorkflowPlan,
    *,
    pack: str,
    actions: Sequence[ActionEntry],
    view: EffectiveEnvironments,
    environment: str,
    inputs: Mapping[str, JsonValue],
) -> ScenarioPlan:
    """The plan of the scenario ``plan`` (of ``pack``) in ``environment`` with ``inputs``."""
    declared = find_environment(view, environment)
    problems = [] if declared is not None else [f"environment {environment} is not declared"]
    entries: dict[str, ActionEntry] = {}
    rows: list[PlanRow] = []
    for node in plan.all_nodes():
        if not isinstance(node, ActionNode | ExpectNode):
            continue
        try:
            entry = resolve_action(actions, node.action, pack=pack)
        except ActionRefError as error:
            problems.append(f"step {node.id}: {error}")
            continue
        entries[node.id] = entry
        decision = decide(declared, entry.document.effect, "author", draft=entry.draft)
        row, problem = _row(
            node,
            entry,
            decision=decision,
            where=_Context(plan, inputs, view if declared is not None else None, environment),
        )
        rows.append(row)
        if problem is not None:
            problems.append(f"step {node.id}: {problem}")
    problems += _path_problems(plan, entries)
    asks = frozenset(row.step for row in rows if row.decision == "ask")
    problems += _unordered_gates(plan.document.nodes, asks)
    return ScenarioPlan(
        scenario=plan.document.name,
        environment=environment,
        access=declared.access if declared is not None else None,
        production=declared.production if declared is not None else False,
        rows=tuple(rows),
        problems=tuple(problems),
    )


@dataclass(frozen=True)
class _Context:
    """What every row is planned against; ``view`` is ``None`` for an undeclared environment."""

    plan: WorkflowPlan
    inputs: Mapping[str, JsonValue]
    view: EffectiveEnvironments | None
    environment: str


def _row(
    node: ActionNode | ExpectNode,
    entry: ActionEntry,
    *,
    decision: PolicyDecision,
    where: _Context,
) -> tuple[PlanRow, str | None]:
    """The step's row, and why its call cannot be planned (or ``None``)."""
    plan, inputs, view, environment = where.plan, where.inputs, where.view, where.environment
    context = RefContext(inputs=inputs, nodes={}, scenario=True)
    known: dict[str, JsonValue] = {}
    shown: dict[str, str] = {}
    for name, value in node.with_.items():
        if _is_known(value):
            known[name] = _known_value(value, context)
            shown[name] = canonical_text(known[name])
        else:
            shown[name] = canonical_text(_placeholders(value, plan, inputs))
    pending = frozenset(shown) - frozenset(known)
    call: ActionCallPlan | None = None
    problem: str | None = None
    if view is not None:
        try:
            call = plan_action_call(
                entry.document, known, environment=environment, view=view, pending=pending
            )
        except ActionCallError as error:
            problem = str(error)
    if call is not None:
        # Defaults the call filled in are args too.
        shown |= {name: canonical_text(value) for name, value in call.inputs.items()}
    endpoints = {} if call is None else _endpoints(call)
    row = PlanRow(
        step=node.id,
        type=node.type,
        action=entry.ref,
        effect=entry.document.effect,
        args={name: shown[name] for name in entry.document.inputs if name in shown}
        | {name: text for name, text in shown.items() if name not in entry.document.inputs},
        endpoints=endpoints,
        content_hash=entry.content_hash,
        draft=entry.draft,
        decision=decision.decision,
        reason_kind=decision.reason_kind,
        known=not pending,
        call=call if not pending else None,
        every=node.every if isinstance(node, ExpectNode) else None,
        timeout=node.timeout if isinstance(node, ExpectNode) else None,
    )
    return row, problem


def _endpoints(call: ActionCallPlan) -> dict[str, tuple[str, str | None, str | None]]:
    found: dict[str, tuple[str, str | None, str | None]] = {}
    for (name, endpoint), service in zip(call.endpoint.items(), call.services, strict=True):
        url, resource = endpoint.get("url"), endpoint.get("resource")
        found[name] = (
            service,
            url if isinstance(url, str) else None,
            resource if isinstance(resource, str) else None,
        )
    return found


def _is_known(value: JsonValue) -> bool:
    """Whether ``value`` reads nothing but ``$INPUTS`` (so it is known before the run)."""
    return all(isinstance(ref, InputRef) for text in _strings(value) for ref in _refs(text))


def _known_value(value: JsonValue, context: RefContext) -> JsonValue:
    """``value`` as the engine gives it to the action: a whole reference's value as is, other
    text rendered (``engine._action_value``)."""
    if isinstance(value, str):
        try:
            ref = parse_ref(value, scenario=True)
        except SubstitutionError:
            return render(value, context)
        return resolve(ref, context, value)
    if isinstance(value, list):
        return [_known_value(item, context) for item in value]
    if isinstance(value, dict):
        return {key: _known_value(item, context) for key, item in value.items()}
    return value


def _placeholders(
    value: JsonValue, plan: WorkflowPlan, inputs: Mapping[str, JsonValue]
) -> JsonValue:
    """``value`` with each ``$INPUTS`` reference rendered and every other one shown as the
    placeholder of a value known at run time."""
    if isinstance(value, list):
        return [_placeholders(item, plan, inputs) for item in value]
    if isinstance(value, dict):
        return {key: _placeholders(item, plan, inputs) for key, item in value.items()}
    if not isinstance(value, str):
        return value

    def shown(ref: Ref, spelling: str) -> str:
        if isinstance(ref, InputRef):
            return canonical_text(inputs.get(ref.name))
        if isinstance(ref, CtxRef):
            capture = plan.captures.get(ref.name)
            return f"<{spelling} from {capture.node}>" if capture else f"<{spelling}>"
        if isinstance(ref, NodeRef):
            return f"<{spelling} from {ref.node}>"
        return f"<{spelling}>"

    return rewrite_refs(value, shown, scenario=True)


def _path_problems(plan: WorkflowPlan, entries: Mapping[str, ActionEntry]) -> Iterator[str]:
    """Each path into an action step's output that its action's ``output_format`` lacks."""
    for node in plan.all_nodes():
        own = entries.get(node.id)
        for loc, text in node_texts(node):
            for ref in _refs(text):
                if isinstance(ref, SelfRef):
                    producer, path = own, ref.path
                elif isinstance(ref, NodeRef):
                    producer, path = entries.get(ref.node), ref.path
                else:
                    continue
                if producer is None or not path:
                    continue
                if not schema_has_path(producer.document.output_format, path):
                    yield (
                        f"step {node.id}: {_key(loc)}: the path {echo('.'.join(path))}"
                        f" is not in the output of {producer.ref}"
                    )


def _unordered_gates(nodes: Sequence[Node], asks: frozenset[str]) -> Iterator[str]:
    """Two gate-needing steps with no order between them, among ``nodes`` and in each body."""
    ancestors = _ancestors(nodes)
    seen: list[str] = []
    for node in nodes:
        if isinstance(node, LoopGroupNode):
            yield from _unordered_gates(node.nodes, asks)
        if not _needs_gate(node, asks):
            continue
        for earlier in seen:
            if earlier not in ancestors[node.id] and node.id not in ancestors[earlier]:
                yield UNORDERED_GATES.format(first=earlier, second=node.id)
                break
        seen.append(node.id)


def _needs_gate(node: Node, asks: frozenset[str]) -> bool:
    if isinstance(node, LoopGroupNode):
        return any(_needs_gate(body, asks) for body in node.nodes)
    return isinstance(node, ApprovalNode | WaitNode) or node.id in asks


def _ancestors(nodes: Sequence[Node]) -> dict[str, frozenset[str]]:
    """Each node's ``depends_on`` closure among ``nodes`` (planned: no cycle)."""
    direct = {node.id: tuple(node.depends_on) for node in nodes}
    found: dict[str, frozenset[str]] = {}

    def of(node_id: str) -> frozenset[str]:
        if node_id not in found:
            parents = direct.get(node_id, ())
            found[node_id] = frozenset(parents).union(*(of(parent) for parent in parents))
        return found[node_id]

    return {node.id: of(node.id) for node in nodes}


def _strings(value: JsonValue) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)


def _refs(text: str) -> list[Ref]:
    """The references of ``text`` in the scenario grammar (planning already refused a malformed
    one)."""
    return find_refs(text, scenario=True)


def _key(loc: Loc) -> str:
    return ".".join(str(part) for part in loc)
