"""Policy asks as approvals the planner inserts: ``<step>__ask`` (P-4, AM-14;
docs/design/scenarios.md § Policy).

A step the policy answers ``ask`` for gets an ``approval`` node with the default decisions right
before it, ``<step>__ask``, in the step's own list (a ``loop_group``'s body when the step is
there, recorded ``<group>__<step>__ask``). The gate takes the step's ``depends_on``,
``trigger_rule`` and ``when``, so it opens exactly when the step would run; the step then depends
on the gate alone with ``all_success``, so it runs only once the gate is approved (a reject
cancels the run: no document reads the gate's decision). No key or flag removes a gate.

``asks`` names each step by its id as recorded (``scenario_plan``'s rows): a top-level id, or
``<group>__<id>`` for a body step; an ask that names no step is refused (``PolicyGateError``),
so a gate is never silently left out. ``gated_plan`` plans a document with its gates, its
includes expanded first, so a step an include brought is gated too.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from agent_hub.core.errors import AgentHubError
from agent_hub.core.scenarios.access_policy import Effect
from agent_hub.core.workflows.document import WorkflowDocument
from agent_hub.core.workflows.includes import IncludeResolver, expand_includes
from agent_hub.core.workflows.nodes import ApprovalNode, LoopGroupNode, Node
from agent_hub.core.workflows.plan import WorkflowPlan, plan_workflow
from agent_hub.core.workflows.rewrite import SEPARATOR

ASK_SUFFIX: Final = "__ask"


class PolicyGateError(AgentHubError):
    """An ask that names no step of the document."""


@dataclass(frozen=True, kw_only=True, slots=True)
class PolicyAsk:
    """Why a step asks: its action (``<pack>/<name>``), effect and environment; ``again`` when
    an earlier attempt of it started and never ended, so it may have run already."""

    action: str
    effect: Effect
    environment: str
    again: bool = False


def ask_gate(step: str) -> str:
    """The id of the gate before ``step`` (both as recorded)."""
    return f"{step}{ASK_SUFFIX}"


def with_policy_gates(
    document: WorkflowDocument, asks: Mapping[str, PolicyAsk]
) -> WorkflowDocument:
    """``document`` with a ``<step>__ask`` approval before each step of ``asks``; the same
    document when there is none. Raises ``PolicyGateError`` when an ask names no step."""
    if not asks:
        return document
    placed: set[str] = set()
    nodes: list[Node] = []
    for node in document.nodes:
        top: Node = node
        if isinstance(node, LoopGroupNode):
            scope = f"{node.id}{SEPARATOR}"
            body = _gated(node.nodes, asks, scope=scope, placed=placed)
            if len(body) != len(node.nodes):
                top = node.model_copy(update={"nodes": tuple(body)})
        nodes.extend(_gated((top,), asks, scope="", placed=placed))
    if unplaced := sorted(set(asks) - placed):
        raise PolicyGateError(f"a policy ask names no step {unplaced[0]}")
    return document.model_copy(update={"nodes": tuple(nodes)})


def gated_plan(
    document: WorkflowDocument,
    *,
    includes: IncludeResolver | None,
    asks: Mapping[str, PolicyAsk],
) -> WorkflowPlan:
    """The plan of ``document`` with the gates of ``asks``, its includes expanded first."""
    if not asks:
        return plan_workflow(document, includes=includes)
    expanded = expand_includes(document, includes).document
    return plan_workflow(with_policy_gates(expanded, asks))


def _gated(
    nodes: Sequence[Node], asks: Mapping[str, PolicyAsk], *, scope: str, placed: set[str]
) -> list[Node]:
    """``nodes`` (one list: the document's, or one body) with a gate before each asked step."""
    gated: list[Node] = []
    for node in nodes:
        ask = asks.get(f"{scope}{node.id}")
        if ask is None:
            gated.append(node)
            continue
        placed.add(f"{scope}{node.id}")
        gate = _approval(node, ask, step=f"{scope}{node.id}")
        step = node.model_copy(update={"depends_on": (gate.id,), "trigger_rule": "all_success"})
        gated.extend((gate, step))
    return gated


def _approval(node: Node, ask: PolicyAsk, *, step: str) -> ApprovalNode:
    """The gate before ``node``: built valid under a plain id, then given its reserved one."""
    message = f"policy ask: step {step} runs {ask.action} ({ask.effect}) in {ask.environment};"
    message += (
        " an earlier attempt started and never ended, so it may have run: approve to run it again"
        if ask.again
        else " approve to run it"
    )
    gate = ApprovalNode.model_validate({"id": "gate", "type": "approval", "message": message})
    return gate.model_copy(
        update={
            "id": ask_gate(node.id),
            "depends_on": node.depends_on,
            "trigger_rule": node.trigger_rule,
            "when": node.when,
        }
    )
