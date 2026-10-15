"""A run's state: each node's end, the trigger rules over them, and what a run leaves for resume.

Trigger rules read the ends of a node's dependencies; a dependency with no end counts as failed.
A node a rule does not let run is skipped with the first blocking cause, in ``depends_on``
order: a failed dependency (``upstream_failed``, origin that node), else one skipped for
``upstream_failed`` (its origin), else a skipped one (``upstream_skipped``, the origin it carried
or its own id), so the root origin survives a chain.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

from agent_hub.core.json_form import JsonValue
from agent_hub.core.workflows.failures import FailureKind
from agent_hub.core.workflows.gates import OpenGate
from agent_hub.core.workflows.nodes import Node
from agent_hub.core.workflows.ports import ReportStatus, RunStatus, SkipCause
from agent_hub.core.workflows.substitution import NodeResult, NodeState

_FAILED = NodeResult("failed")


@dataclass(frozen=True)
class NodeEnd:
    """How a node ended in this run; a ``prior_success`` reuse reads as completed."""

    result: NodeResult
    cause: SkipCause | None = None
    origin: str | None = None
    failure_kind: FailureKind | None = None


@dataclass(frozen=True)
class HeldGroup:
    """A ``loop_group`` paused inside an iteration: its attempt, that iteration, the results of
    the iteration before (``$LOOP_PREV``) and the body nodes this one already ended."""

    attempt: int
    iteration: int
    previous: Mapping[str, NodeResult] = field(default_factory=dict)
    current: Mapping[str, NodeResult] = field(default_factory=dict)


@dataclass(frozen=True)
class RunState:
    """What a run leaves for its resume: each node's result, its attempts, agent sessions and
    the gates it paused on, with the groups paused around one."""

    nodes: Mapping[str, NodeResult] = field(default_factory=dict)
    attempts: Mapping[str, int] = field(default_factory=dict)
    sessions: Mapping[str, str] = field(default_factory=dict)
    gates: Mapping[str, OpenGate] = field(default_factory=dict)
    groups: Mapping[str, HeldGroup] = field(default_factory=dict)


@dataclass(frozen=True)
class RunReport:
    """The run's end, or its pause: ``status`` apart from the authored ``outcome``; ``reason``
    is a node id (the failed, halting or gate node)."""

    status: ReportStatus
    outcome: JsonValue
    reason: str | None
    state: RunState


def trigger_skip(node: Node, ends: Mapping[str, NodeEnd]) -> tuple[SkipCause, str] | None:
    """The cause and origin that skip ``node``, or ``None`` when its rule lets it run."""
    upstream = [(dep, ends[dep] if dep in ends else NodeEnd(_FAILED)) for dep in node.depends_on]
    if not upstream or _lets_run(node, [end for _, end in upstream]):
        return None
    blocking = [(dep, end) for dep, end in upstream if end.result.state != "completed"]
    for dep, end in blocking:
        if end.result.state == "failed":
            return "upstream_failed", dep
    for dep, end in blocking:
        if end.cause == "upstream_failed":
            return "upstream_failed", end.origin or dep
    dep, end = blocking[0]
    return "upstream_skipped", (end.origin if end.cause == "upstream_skipped" else None) or dep


def _lets_run(node: Node, upstream: list[NodeEnd]) -> bool:
    states: list[NodeState] = [end.result.state for end in upstream]
    match node.trigger_rule:
        case "all_success":
            return all(state == "completed" for state in states)
        case "one_success":
            return "completed" in states
        case "none_failed_min_one_success":
            failed = any(
                end.result.state == "failed" or end.cause == "upstream_failed" for end in upstream
            )
            return not failed and "completed" in states
        case "all_done":
            return True


def run_status(ends: Mapping[str, NodeEnd], halted_by: str | None) -> tuple[RunStatus, str | None]:
    """``cancelled`` after a halt, ``failed`` when a node failed (the first one), else ``done``."""
    if halted_by is not None:
        return "cancelled", halted_by
    failed = next((node for node, end in ends.items() if end.result.state == "failed"), None)
    return ("failed", failed) if failed is not None else ("done", None)


def authored_outcome(
    returns: str | None, outcome_field: str | None, ends: Mapping[str, NodeEnd]
) -> JsonValue:
    """``outcome_field``'s value in the output of ``returns``, when that node completed."""
    end = ends.get(returns) if returns is not None else None
    if end is None or outcome_field is None or end.result.state != "completed":
        return None
    output = end.result.output
    return output.get(outcome_field) if isinstance(output, dict) else None
