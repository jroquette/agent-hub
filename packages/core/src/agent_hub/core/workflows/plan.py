"""Planning a workflow: Kahn layers and the load checks that need the whole graph.

The graph checks run in order and stop at the first that fails: a repeated id, a ``depends_on``
naming no node, a cycle. Then every reference (``substitution``'s grammar) must be well formed
and name a declared input, a ``with`` value of its node or an upstream node, its path following
that node's ``output_format``; argv lists follow ``check_argv`` (a whole element, never the
program nor a ``-c`` script); a ``stdin`` is a literal or one whole reference; a hub step node's
``cwd`` holds none; ``context.resume`` names an
upstream agent; and ``returns``/``outcome_field`` name a node and a required boolean or enum
string of its output.

A ``loop_group``'s body is planned the same way inside the group: its ids unique and new to the
document, its ``depends_on`` inside the body, no cycle. A body node reads body nodes upstream of
it, outer nodes upstream of the group, and ``$LOOP_PREV.<body id>``; ``until_when`` and
``until_bash`` read any body node. ``$<group>.output.<body id>[.path]`` follows that body node's
``output_format``. The planned document records body ids as ``<group>__<id>`` (``loops``), and
``WorkflowPlan.bodies`` holds each body's layers.
"""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Final

from pydantic import JsonValue

from agent_hub.core.workflows.document import (
    Loc,
    WorkflowDocument,
    WorkflowLoadError,
    WorkflowProblem,
)
from agent_hub.core.workflows.includes import IncludeResolver, expand_includes
from agent_hub.core.workflows.loops import local_id, record_body
from agent_hub.core.workflows.nodes import (
    AgentNode,
    ApprovalNode,
    FromBinding,
    HaltNode,
    LoopGroupNode,
    LoopNode,
    Node,
    ScriptNode,
    ShellNode,
    required_property,
)
from agent_hub.core.workflows.rewrite import SEPARATOR
from agent_hub.core.workflows.scope import RefScope, ScopeStep
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
    parse_ref,
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
    # Each loop_group's body layers, by group id, body ids as recorded.
    bodies: Mapping[str, tuple[tuple[str, ...], ...]] = field(default_factory=dict)
    # Each node's reference scope when it has one, by recorded id, for its prompt file.
    scopes: Mapping[str, RefScope] = field(default_factory=dict)

    def all_nodes(self) -> Iterator[Node]:
        """Every node the run may record, in declaration order: a group, then its body."""
        for node in self.document.nodes:
            yield node
            if isinstance(node, LoopGroupNode):
                yield from node.nodes


def plan_workflow(
    document: WorkflowDocument, *, includes: IncludeResolver | None = None
) -> WorkflowPlan:
    """The plan of ``document``, its includes expanded through ``includes`` (``includes.py``);
    raises ``WorkflowLoadError`` naming every problem found, on the document's own nodes."""
    expansion = expand_includes(document, includes)
    try:
        plan = _plan(expansion.document)
    except WorkflowLoadError as error:
        raise WorkflowLoadError([expansion.locate(p) for p in error.problems]) from None
    scopes = dict(expansion.scopes)
    for group in plan.document.nodes:
        if isinstance(group, LoopGroupNode):
            # The body's ids as recorded: the step ``record_body`` took at load.
            step = ScopeStep(names={local_id(group, body.id): body.id for body in group.nodes})
            for body in group.nodes:
                scopes[body.id] = scopes.get(body.id, RefScope()).then(step)
    return replace(plan, scopes=scopes) if scopes else plan


def _plan(document: WorkflowDocument) -> WorkflowPlan:
    nodes = document.nodes
    graph_problems = [*_repeated_ids(nodes), *_unknown_dependencies(nodes)]
    if graph_problems:
        raise WorkflowLoadError(graph_problems)
    layers, leftover = _kahn_layers(nodes)
    if leftover:
        raise WorkflowLoadError([_cycle_problem(nodes, leftover)])
    graph = _Graph(document, _Upstream(nodes, layers), {node.id: node for node in nodes})
    problems = [
        *_reference_problems(graph, nodes),
        *_resume_problems(graph, nodes),
        *_outcome_problems(document),
        *_group_problems(graph),
    ]
    if problems:
        raise WorkflowLoadError(problems)
    return _recorded(document, layers)


def _repeated_ids(nodes: Sequence[Node]) -> Iterator[WorkflowProblem]:
    seen: set[str] = set()
    for index, node in enumerate(nodes):
        if node.id in seen:
            yield WorkflowProblem(("nodes", index, "id"), f"the id {echo(node.id)} is repeated")
        seen.add(node.id)


def _unknown_dependencies(nodes: Sequence[Node], kind: str = "node") -> Iterator[WorkflowProblem]:
    ids = {node.id for node in nodes}
    for index, node in enumerate(nodes):
        for position, target in enumerate(node.depends_on):
            if target not in ids:
                loc = ("nodes", index, "depends_on", position)
                yield WorkflowProblem(loc, f"no {kind} has the id {echo(target)}")


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
        return _path_problem(producer, ref)

    def resumable(self, target: str, node: Node) -> bool:
        """Whether ``node`` may resume the session of the agent ``target``."""
        producer = self.producers.get(target)
        is_agent = isinstance(producer, AgentNode | LoopNode)
        return is_agent and self.upstream.contains(target, node.id)


@dataclass(frozen=True)
class _BodyGraph(_Graph):
    """A ``loop_group``'s body: body nodes first, then the outer graph upstream of the group.
    Read in the group itself (its ``until`` channels), every body node is upstream."""

    outer: _Graph
    group: LoopGroupNode

    def _ref_problem(self, node: Node, ref: Ref) -> str | None:
        if isinstance(ref, LoopPrevRef):
            producer = self.producers.get(ref.node)
            if producer is None:
                return f"no body node has the id {echo(ref.node)}"
            return _path_problem(producer, NodeRef(ref.node, ref.path))
        return super()._ref_problem(node, ref)

    def _node_ref_problem(self, node: Node, ref: NodeRef) -> str | None:
        producer = self.producers.get(ref.node)
        if producer is None:
            return self.outer._node_ref_problem(self.group, ref)
        if node is not self.group and not self.upstream.contains(ref.node, node.id):
            return f"the node {echo(ref.node)} is not upstream"
        return _path_problem(producer, ref)

    def resumable(self, target: str, node: Node) -> bool:
        if target in self.producers:
            return super().resumable(target, node)
        return self.outer.resumable(target, self.group)


def _path_problem(producer: Node, ref: NodeRef) -> str | None:
    if ref.path and not _has_path(producer, ref.path):
        path = ".".join(ref.path)
        return f"the path {echo(path)} is not in the output of {echo(ref.node)}"
    return None


def _group_problems(graph: _Graph) -> Iterator[WorkflowProblem]:
    for index, group in enumerate(graph.document.nodes):
        if not isinstance(group, LoopGroupNode):
            continue
        where: Loc = ("nodes", index)
        body = group.nodes
        # An included group's body is checked against its own block's ids.
        head, separator, _ = group.id.rpartition(SEPARATOR)
        namespace = head + separator
        problems = [*_repeated_ids(body), *_unknown_dependencies(body, "body node")]
        problems += [
            WorkflowProblem(("nodes", position, "id"), message)
            for position, node in enumerate(body)
            if namespace + node.id in graph.producers
            for message in [f"the body id {echo(node.id)} is already a node id"]
        ]
        if not problems:
            layers, leftover = _kahn_layers(body)
            if leftover:
                problems.append(_cycle_problem(body, leftover))
        if problems:
            yield from (WorkflowProblem((*where, *p.loc), p.message) for p in problems)
            continue
        producers = {node.id: node for node in body}
        upstream = _Upstream(body, layers)
        inside = _BodyGraph(graph.document, upstream, producers, graph, group)
        yield from _reference_problems(inside, body, (*where, "nodes"))
        yield from _resume_problems(inside, body, (*where, "nodes"))
        yield from _reference_problems(inside, [group], where, until=True)


def _recorded(document: WorkflowDocument, layers: tuple[tuple[str, ...], ...]) -> WorkflowPlan:
    """The plan, each ``loop_group``'s body recorded as ``<group>__<id>``."""
    groups = [node for node in document.nodes if isinstance(node, LoopGroupNode)]
    if not groups:
        return WorkflowPlan(document, layers)
    recorded = {group.id: record_body(group) for group in groups}
    nodes = tuple(recorded.get(node.id, node) for node in document.nodes)
    bodies = {group_id: _kahn_layers(group.nodes)[0] for group_id, group in recorded.items()}
    return WorkflowPlan(document.model_copy(update={"nodes": nodes}), layers, bodies)


def _reference_problems(
    graph: _Graph, nodes: Sequence[Node], prefix: Loc = ("nodes",), *, until: bool = False
) -> Iterator[WorkflowProblem]:
    """The reference problems of ``nodes``; ``until``: those of a group's ``until`` channels."""
    for index, node in enumerate(nodes):
        where_node: Loc = prefix if until else (*prefix, index)
        texts = _until_texts(node) if until else _texts(node)
        lists = _until_argv(node) if until else _argv_lists(node)
        for loc, text in texts:
            where: Loc = (*where_node, *loc)
            yield from (WorkflowProblem(where, message) for message in graph.problems(node, text))
        for key, argv, offset in lists:
            problems = check_argv([*([""] * offset), *argv])
            refused = {problem.index - offset: problem.error for problem in problems}
            for position, element in enumerate(argv):
                where = (*where_node, key, position)
                if position in refused:
                    yield WorkflowProblem(where, str(refused[position]))
                else:
                    messages = graph.problems(node, element)
                    yield from (WorkflowProblem(where, message) for message in messages)
        stdin = node.stdin if isinstance(node, ShellNode | ScriptNode) else None
        if stdin is not None and _has_ref(stdin) and not _is_whole_ref(stdin):
            message = "a reference fills the whole stdin, or none is used"
            yield WorkflowProblem((*where_node, "stdin"), message)
        if isinstance(node, ShellNode) and node.is_hub_step and node.cwd and _has_ref(node.cwd):
            message = "a hub step node's cwd takes no reference"
            yield WorkflowProblem((*where_node, "cwd"), message)


def _until_texts(node: Node) -> Iterator[tuple[Loc, str]]:
    if isinstance(node, LoopGroupNode) and node.until_when is not None:
        yield ("until_when",), node.until_when


def _until_argv(node: Node) -> Iterator[tuple[str, Sequence[str], int]]:
    if isinstance(node, LoopGroupNode) and node.until_bash is not None:
        yield "until_bash", node.until_bash, 0


def _has_ref(text: str) -> bool:
    try:
        return bool(find_refs(text))
    except SubstitutionError:
        return True


def _is_whole_ref(text: str) -> bool:
    try:
        parse_ref(text)
    except SubstitutionError:
        return False
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
        if node.stdin is not None:
            yield ("stdin",), node.stdin
        yield from ((("env", name), value) for name, value in node.env.items())
    elif isinstance(node, ApprovalNode):
        yield ("message",), node.message
    elif isinstance(node, HaltNode):
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
    if isinstance(producer, LoopGroupNode):
        # The output maps body id → that body node's output.
        body = {node.id: node for node in producer.nodes}
        return segments[0] in body and _has_path(body[segments[0]], segments[1:])
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


def _resume_problems(
    graph: _Graph, nodes: Sequence[Node], prefix: Loc = ("nodes",)
) -> Iterator[WorkflowProblem]:
    for index, node in enumerate(nodes):
        if isinstance(node, AgentNode | LoopNode) and not isinstance(node.context, str):
            target = node.context.resume
            if not graph.resumable(target, node):
                loc = (*prefix, index, "context", "resume")
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
