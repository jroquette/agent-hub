"""Planning a workflow: Kahn layers and the load checks that need the whole graph.

The graph checks run in order and stop at the first that fails: a repeated id, a ``depends_on``
naming no node, a cycle. Then every reference must name a declared input or an upstream node
(``$<node>.output`` paths follow its ``output_format``), argv elements hold a whole reference or
none, a hub step node's ``cwd`` holds none, ``context.resume`` names an upstream agent, and
``returns``/``outcome_field`` name a node and a required boolean or enum string of its output.
"""

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Final

from pydantic import JsonValue

from agent_hub.core.workflows.document import (
    Loc,
    WorkflowDocument,
    WorkflowLoadError,
    WorkflowProblem,
)
from agent_hub.core.workflows.nodes import (
    AgentNode,
    ApprovalNode,
    FromBinding,
    LoopNode,
    Node,
    ScriptNode,
    ShellNode,
    required_property,
)

# The reference forms of the contract, scanned here only to check where they point; the
# substitution module owns resolving them.
_NODE_REF: Final = re.compile(r"\$([a-z][a-z0-9_-]*)\.output((?:\.[A-Za-z0-9_-]+)*)")
_INPUT_REF: Final = re.compile(r"\$INPUTS\.([A-Za-z0-9_]+)")
_ANY_REF: Final = re.compile(rf"{_NODE_REF.pattern}|\$(?:INPUTS|WITH|LOOP_PREV)\.[A-Za-z0-9_.-]+")
# An approval's output is ``{decision}`` (plus ``text``), whatever its schema.
_APPROVAL_FIELDS: Final = frozenset({"decision", "text"})


@dataclass(frozen=True)
class WorkflowPlan:
    """A loaded workflow and its layers: node ids, in declaration order inside a layer."""

    document: WorkflowDocument
    layers: tuple[tuple[str, ...], ...]


def plan_workflow(document: WorkflowDocument) -> WorkflowPlan:
    """The plan of ``document``; raises ``WorkflowLoadError`` naming every problem found."""
    nodes = document.nodes
    graph_problems = [*_repeated_ids(nodes), *_unknown_dependencies(nodes)]
    if graph_problems:
        raise WorkflowLoadError(graph_problems)
    layers, leftover = _kahn_layers(nodes)
    if leftover:
        index = next(i for i, node in enumerate(nodes) if node.id in leftover)
        names = ", ".join(sorted(leftover))
        message = f"a cycle runs through the nodes {names}"
        raise WorkflowLoadError([WorkflowProblem(("nodes", index, "depends_on"), message)])
    upstream = _upstream(nodes)
    problems = [
        *_reference_problems(document, upstream),
        *_resume_problems(nodes, upstream),
        *_outcome_problems(document),
    ]
    if problems:
        raise WorkflowLoadError(problems)
    return WorkflowPlan(document, layers)


def _repeated_ids(nodes: Sequence[Node]) -> Iterator[WorkflowProblem]:
    seen: set[str] = set()
    for index, node in enumerate(nodes):
        if node.id in seen:
            yield WorkflowProblem(("nodes", index, "id"), f"the id {node.id!r} is repeated")
        seen.add(node.id)


def _unknown_dependencies(nodes: Sequence[Node]) -> Iterator[WorkflowProblem]:
    ids = {node.id for node in nodes}
    for index, node in enumerate(nodes):
        for position, target in enumerate(node.depends_on):
            if target not in ids:
                loc = ("nodes", index, "depends_on", position)
                yield WorkflowProblem(loc, f"no node has the id {target!r}")


def _kahn_layers(nodes: Sequence[Node]) -> tuple[tuple[tuple[str, ...], ...], set[str]]:
    order = {node.id: index for index, node in enumerate(nodes)}
    waiting = {node.id: len(node.depends_on) for node in nodes}
    dependants: dict[str, list[str]] = {node.id: [] for node in nodes}
    for node in nodes:
        for target in node.depends_on:
            dependants[target].append(node.id)
    layers: list[tuple[str, ...]] = []
    layer = [node.id for node in nodes if not node.depends_on]
    while layer:
        layers.append(tuple(layer))
        ready: list[str] = []
        for node_id in layer:
            del waiting[node_id]
            for dependant in dependants[node_id]:
                waiting[dependant] -= 1
                if not waiting[dependant]:
                    ready.append(dependant)
        layer = sorted(ready, key=order.__getitem__)
    return tuple(layers), set(waiting)


def _upstream(nodes: Sequence[Node]) -> dict[str, frozenset[str]]:
    # Called on an acyclic graph, so a node's dependencies are always resolved first.
    by_id = {node.id: node for node in nodes}
    result: dict[str, frozenset[str]] = {}

    def ancestors(node_id: str) -> frozenset[str]:
        if node_id not in result:
            direct = by_id[node_id].depends_on
            result[node_id] = frozenset(direct).union(*(ancestors(item) for item in direct))
        return result[node_id]

    for node in nodes:
        ancestors(node.id)
    return result


def _reference_problems(
    document: WorkflowDocument, upstream: dict[str, frozenset[str]]
) -> Iterator[WorkflowProblem]:
    graph = _Graph(document, {node.id: node for node in document.nodes}, upstream)
    for index, node in enumerate(document.nodes):
        for loc, text, in_argv in _texts(node):
            where: Loc = ("nodes", index, *loc)
            if in_argv and _ANY_REF.search(text) and not _ANY_REF.fullmatch(text):
                yield WorkflowProblem(where, "a reference must fill the whole argv element")
            yield from (WorkflowProblem(where, message) for message in graph.problems(node, text))
        if isinstance(node, ShellNode) and node.is_hub_step and _ANY_REF.search(node.cwd or ""):
            message = "a hub step node's cwd takes no reference"
            yield WorkflowProblem(("nodes", index, "cwd"), message)


@dataclass(frozen=True)
class _Graph:
    document: WorkflowDocument
    producers: dict[str, Node]
    upstream: dict[str, frozenset[str]]

    def problems(self, node: Node, text: str) -> Iterator[str]:
        """What is wrong with the references ``text`` holds, read in ``node``."""
        for name in _INPUT_REF.findall(text):
            if name not in self.document.inputs:
                yield f"the input {name!r} is not declared"
        for match in _NODE_REF.finditer(text):
            producer, path = match.group(1), match.group(2)
            if producer not in self.producers:
                yield f"no node has the id {producer!r}"
            elif producer not in self.upstream[node.id]:
                yield f"the node {producer!r} is not upstream"
            elif path and not _has_path(self.producers[producer], path.split(".")[1:]):
                yield f"{match.group(0)} is not in the output of {producer!r}"


def _texts(node: Node) -> Iterator[tuple[Loc, str, bool]]:
    """Each text of ``node`` that may hold a reference: its key path, and whether it is argv."""
    if node.when is not None:
        yield ("when",), node.when, False
    if isinstance(node, AgentNode | LoopNode):
        yield from _agent_texts(node)
    elif isinstance(node, ShellNode | ScriptNode):
        yield from _command_texts(node)
    elif isinstance(node, ApprovalNode):
        yield ("message",), node.message, False
    else:
        yield ("reason",), node.reason, False


def _agent_texts(node: AgentNode | LoopNode) -> Iterator[tuple[Loc, str, bool]]:
    if node.prompt is not None:
        yield ("prompt",), node.prompt, False
    for name, binding in node.with_.items():
        if isinstance(binding, FromBinding):
            yield ("with", name, "from"), binding.from_, False
        else:
            yield from ((("with", name), text, False) for text in _strings(binding))
    if isinstance(node, LoopNode) and node.until_bash is not None:
        yield from ((("until_bash", i), item, True) for i, item in enumerate(node.until_bash))


def _command_texts(node: ShellNode | ScriptNode) -> Iterator[tuple[Loc, str, bool]]:
    key, argv = ("command", node.command) if isinstance(node, ShellNode) else ("args", node.args)
    yield from (((key, i), item, True) for i, item in enumerate(argv))
    if node.cwd is not None:
        yield ("cwd",), node.cwd, False
    yield from ((("env", name), value, False) for name, value in node.env.items())


def _strings(value: JsonValue) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)


def _has_path(producer: Node, segments: Sequence[str]) -> bool:
    if isinstance(producer, ApprovalNode):
        return len(segments) == 1 and segments[0] in _APPROVAL_FIELDS
    schema: JsonValue = getattr(producer, "output_format", None)
    for segment in segments:
        if not isinstance(schema, dict):
            return False
        properties, items = schema.get("properties"), schema.get("items")
        if isinstance(properties, dict) and segment in properties:
            schema = properties[segment]
        elif segment.isdigit() and isinstance(items, dict):
            schema = items
        else:
            return False
    return True


def _resume_problems(
    nodes: Sequence[Node], upstream: dict[str, frozenset[str]]
) -> Iterator[WorkflowProblem]:
    agents = {node.id for node in nodes if isinstance(node, AgentNode | LoopNode)}
    for index, node in enumerate(nodes):
        if isinstance(node, AgentNode | LoopNode) and not isinstance(node.context, str):
            target = node.context.resume
            if target not in agents or target not in upstream[node.id]:
                loc = ("nodes", index, "context", "resume")
                yield WorkflowProblem(loc, f"{target!r} is not an upstream agent or loop node")


def _outcome_problems(document: WorkflowDocument) -> Iterator[WorkflowProblem]:
    if document.returns is None:
        if document.outcome_field is not None:
            yield WorkflowProblem(("outcome_field",), "'outcome_field' needs 'returns'")
        return
    returned = next((node for node in document.nodes if node.id == document.returns), None)
    if returned is None:
        yield WorkflowProblem(("returns",), f"no node has the id {document.returns!r}")
        return
    if document.outcome_field is None:
        return
    output_format = getattr(returned, "output_format", None)
    schema = required_property(output_format, document.outcome_field)
    if schema is None or not _is_outcome_type(schema):
        message = (
            f"must be a required boolean, or a string with an enum, of the output_format of"
            f" {returned.id!r}"
        )
        yield WorkflowProblem(("outcome_field",), message)


def _is_outcome_type(schema: dict[str, JsonValue]) -> bool:
    if schema.get("type") == "boolean":
        return True
    enum = schema.get("enum")
    return (
        schema.get("type") == "string"
        and isinstance(enum, list)
        and bool(enum)
        and all(isinstance(item, str) for item in enum)
    )
