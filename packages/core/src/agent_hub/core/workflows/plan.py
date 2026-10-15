"""Planning a workflow: Kahn layers and the load checks that need the whole graph.

The graph checks run in order and stop at the first that fails: a repeated id, a ``depends_on``
naming no node, a cycle. Then every reference (``substitution``'s grammar) must be well formed
and name a declared input, a ``with`` value of its node or an upstream node, its path following
that node's ``output_format``; argv lists follow ``check_argv`` (a whole element, never the
program nor a ``-c`` script); a hub step node's ``cwd`` holds none; ``context.resume`` names an
upstream agent; and ``returns``/``outcome_field`` name a node and a required boolean or enum
string of its output.
"""

from collections.abc import Iterator, Mapping, Sequence
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
from agent_hub.core.workflows.substitution import (
    InputRef,
    LoopPrevRef,
    NodeRef,
    Ref,
    SubstitutionError,
    WithRef,
    check_argv,
    echo,
    find_refs,
)

# An approval's output is ``{decision}`` (plus ``text``), whatever its schema.
_APPROVAL_FIELDS: Final = frozenset({"decision", "text"})
# A cycle message names at most this many nodes, then how many more.
_MAX_CYCLE_NAMES: Final = 10


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
        raise WorkflowLoadError([_cycle_problem(nodes, leftover)])
    graph = _Graph(document, _Upstream(nodes, layers), {node.id: node for node in nodes})
    problems = [
        *_reference_problems(graph),
        *_resume_problems(graph),
        *_outcome_problems(document),
    ]
    if problems:
        raise WorkflowLoadError(problems)
    return WorkflowPlan(document, layers)


def _repeated_ids(nodes: Sequence[Node]) -> Iterator[WorkflowProblem]:
    seen: set[str] = set()
    for index, node in enumerate(nodes):
        if node.id in seen:
            yield WorkflowProblem(("nodes", index, "id"), f"the id {echo(node.id)} is repeated")
        seen.add(node.id)


def _unknown_dependencies(nodes: Sequence[Node]) -> Iterator[WorkflowProblem]:
    ids = {node.id for node in nodes}
    for index, node in enumerate(nodes):
        for position, target in enumerate(node.depends_on):
            if target not in ids:
                loc = ("nodes", index, "depends_on", position)
                yield WorkflowProblem(loc, f"no node has the id {echo(target)}")


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


def _cycle_problem(nodes: Sequence[Node], leftover: set[str]) -> WorkflowProblem:
    """One cycle among the nodes Kahn left: each of them waits on another one left."""
    by_id = {node.id: node for node in nodes}
    order = {node.id: index for index, node in enumerate(nodes)}
    path: list[str] = []
    seen: set[str] = set()
    current = min(leftover, key=order.__getitem__)
    while current not in seen:
        path.append(current)
        seen.add(current)
        current = next(item for item in by_id[current].depends_on if item in leftover)
    cycle = sorted(path[path.index(current) :], key=order.__getitem__)
    names = ", ".join(echo(node_id)[1:-1] for node_id in cycle[:_MAX_CYCLE_NAMES])
    if len(cycle) > _MAX_CYCLE_NAMES:
        names += f" and {len(cycle) - _MAX_CYCLE_NAMES} more"
    loc = ("nodes", order[cycle[0]], "depends_on")
    return WorkflowProblem(loc, f"a cycle runs through the nodes {names}")


class _Upstream:
    """Which nodes are upstream of which: one bitset over declaration indexes per node.

    Built in layer order, so each node's dependencies are complete before it: no recursion,
    and an int of at most one bit per node for each.
    """

    def __init__(self, nodes: Sequence[Node], layers: Sequence[Sequence[str]]) -> None:
        self.index = {node.id: position for position, node in enumerate(nodes)}
        by_id = {node.id: node for node in nodes}
        self.ancestors: dict[str, int] = {}
        for layer in layers:
            for node_id in layer:
                bits = 0
                for target in by_id[node_id].depends_on:
                    bits |= self.ancestors[target] | (1 << self.index[target])
                self.ancestors[node_id] = bits

    def contains(self, producer: str, node: str) -> bool:
        """Whether ``producer`` is a transitive dependency of ``node``."""
        return bool(self.ancestors[node] >> self.index[producer] & 1)


@dataclass(frozen=True)
class _Graph:
    document: WorkflowDocument
    upstream: _Upstream
    producers: Mapping[str, Node]

    def problems(self, node: Node, text: str) -> Iterator[str]:
        """What is wrong with the references ``text`` holds, read in ``node``."""
        try:
            refs = find_refs(text)
        except SubstitutionError as error:
            yield str(error)
            return
        for ref in refs:
            message = self._ref_problem(node, ref)
            if message is not None:
                yield message

    def _ref_problem(self, node: Node, ref: Ref) -> str | None:
        if isinstance(ref, InputRef):
            known = ref.name in self.document.inputs
            return None if known else f"the input {echo(ref.name)} is not declared"
        if isinstance(ref, WithRef):
            names = node.with_ if isinstance(node, AgentNode | LoopNode) else {}
            return None if ref.name in names else f"no 'with' value is named {echo(ref.name)}"
        if isinstance(ref, LoopPrevRef):
            return "$LOOP_PREV reads only inside a loop_group body"
        return self._node_ref_problem(node, ref)

    def _node_ref_problem(self, node: Node, ref: NodeRef) -> str | None:
        producer = self.producers.get(ref.node)
        if producer is None:
            return f"no node has the id {echo(ref.node)}"
        if not self.upstream.contains(ref.node, node.id):
            return f"the node {echo(ref.node)} is not upstream"
        if ref.path and not _has_path(producer, ref.path):
            path = ".".join(ref.path)
            return f"the path {echo(path)} is not in the output of {echo(ref.node)}"
        return None


def _reference_problems(graph: _Graph) -> Iterator[WorkflowProblem]:
    for index, node in enumerate(graph.document.nodes):
        for loc, text in _texts(node):
            where: Loc = ("nodes", index, *loc)
            yield from (WorkflowProblem(where, message) for message in graph.problems(node, text))
        for key, argv, offset in _argv_lists(node):
            problems = check_argv([*([""] * offset), *argv])
            refused = {problem.index - offset: problem.error for problem in problems}
            for position, element in enumerate(argv):
                where = ("nodes", index, key, position)
                if position in refused:
                    yield WorkflowProblem(where, str(refused[position]))
                else:
                    messages = graph.problems(node, element)
                    yield from (WorkflowProblem(where, message) for message in messages)
        if isinstance(node, ShellNode) and node.is_hub_step and node.cwd and _has_ref(node.cwd):
            message = "a hub step node's cwd takes no reference"
            yield WorkflowProblem(("nodes", index, "cwd"), message)


def _has_ref(text: str) -> bool:
    try:
        return bool(find_refs(text))
    except SubstitutionError:
        return True


def _texts(node: Node) -> Iterator[tuple[Loc, str]]:
    """Each text of ``node`` outside argv lists that may hold a reference, with its key path."""
    if node.when is not None:
        yield ("when",), node.when
    if isinstance(node, AgentNode | LoopNode):
        yield from _agent_texts(node)
    elif isinstance(node, ShellNode | ScriptNode):
        if node.cwd is not None:
            yield ("cwd",), node.cwd
        yield from ((("env", name), value) for name, value in node.env.items())
    elif isinstance(node, ApprovalNode):
        yield ("message",), node.message
    else:
        yield ("reason",), node.reason


def _agent_texts(node: AgentNode | LoopNode) -> Iterator[tuple[Loc, str]]:
    if node.prompt is not None:
        yield ("prompt",), node.prompt
    if node.cwd is not None:
        yield ("cwd",), node.cwd
    for name, binding in node.with_.items():
        if isinstance(binding, FromBinding):
            yield ("with", name, "from"), binding.from_
        else:
            yield from ((("with", name), text) for text in _strings(binding))


def _argv_lists(node: Node) -> Iterator[tuple[str, Sequence[str], int]]:
    """Each argv list of ``node``, and how many elements run before it (a script's program)."""
    if isinstance(node, ShellNode):
        yield "command", node.command, 0
    elif isinstance(node, ScriptNode):
        # The engine runs ``<runtime> <script> <args...>``: the args are never the program.
        yield "args", node.args, 2
    elif isinstance(node, LoopNode) and node.until_bash is not None:
        yield "until_bash", node.until_bash, 0


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
    schema: object = getattr(producer, "output_format", None)
    for segment in segments:
        if not isinstance(schema, Mapping):
            return False
        properties, items = schema.get("properties"), schema.get("items")
        if isinstance(properties, Mapping) and segment in properties:
            schema = properties[segment]
        elif segment.isdigit() and isinstance(items, Mapping):
            schema = items
        else:
            return False
    return True


def _resume_problems(graph: _Graph) -> Iterator[WorkflowProblem]:
    nodes = graph.document.nodes
    agents = {node.id for node in nodes if isinstance(node, AgentNode | LoopNode)}
    for index, node in enumerate(nodes):
        if isinstance(node, AgentNode | LoopNode) and not isinstance(node.context, str):
            target = node.context.resume
            if target not in agents or not graph.upstream.contains(target, node.id):
                loc = ("nodes", index, "context", "resume")
                yield WorkflowProblem(loc, f"{echo(target)} is not an upstream agent or loop node")


def _outcome_problems(document: WorkflowDocument) -> Iterator[WorkflowProblem]:
    if document.returns is None:
        if document.outcome_field is not None:
            yield WorkflowProblem(("outcome_field",), "'outcome_field' needs 'returns'")
        return
    returned = next((node for node in document.nodes if node.id == document.returns), None)
    if returned is None:
        yield WorkflowProblem(("returns",), f"no node has the id {echo(document.returns)}")
        return
    if document.outcome_field is None:
        return
    output_format = getattr(returned, "output_format", None)
    schema = required_property(output_format, document.outcome_field)
    if schema is None or not _is_outcome_type(schema):
        message = (
            f"must be a required boolean, or a string with an enum, of the output_format of"
            f" {echo(returned.id)}"
        )
        yield WorkflowProblem(("outcome_field",), message)


def _is_outcome_type(schema: Mapping[str, JsonValue]) -> bool:
    if schema.get("type") == "boolean":
        return True
    enum = schema.get("enum")
    return (
        schema.get("type") == "string"
        and isinstance(enum, list)
        and bool(enum)
        and all(isinstance(item, str) for item in enum)
    )
