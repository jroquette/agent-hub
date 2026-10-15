"""``include``: another workflow's nodes copied in at load (docs/design/workflow-schema.md § Nodes).

``expand_includes`` replaces each ``include`` node by the nodes of the workflow it names, which an
``IncludeResolver`` returns (``generator`` resolves names through discovery; core stays pure). The
included workflow is expanded first, so includes nest, at most ``MAX_INCLUDE_DEPTH`` levels deep
and never in a cycle (checked first).

In the block, node ``n`` becomes ``<include>__n`` and each reference to it is rewritten; each
``$INPUTS.<name>`` is replaced by its ``with`` value (a value, or a parent reference, which then
reads the parent's node) or the input's default, in the same single pass, never rescanned. A
block is hermetic: a reference to a node it does not hold, or to an input it does not declare, is
refused. ``with`` is checked as at run start: no unknown name, every required input given. The
include's ``depends_on`` becomes that of each root (a block node with no ``depends_on``), its
``when:`` joins a root's own as ``A && B`` (refused when either holds ``||``: no parentheses), and
its ``trigger_rule`` goes to the roots that set none. A ``when:`` that parsed before ``with`` was
filled in and no longer does is refused: in a block's ``when:``, an input must be given a
reference, since the grammar compares a reference with a literal.

In the parent, ``depends_on: [I]`` waits on every sink of the block, and ``$I.output`` (and
``returns: I``, a binding's ``from``, ``context.resume: I``) reads its primary sink: the included
workflow's ``returns``, else its single sink. With several sinks and no ``returns`` that reading is
refused. Planning runs on the expanded document; ``Expansion.locate`` puts its problems back on
the parent's node (an included node's problem on its ``include``, naming the namespaced id).
"""

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Final

from pydantic import JsonValue

from agent_hub.core.features.output_shape import output_path
from agent_hub.core.workflows.conditions import ConditionParseError, parse_condition
from agent_hub.core.workflows.document import (
    Loc,
    WorkflowDocument,
    WorkflowLoadError,
    WorkflowProblem,
)
from agent_hub.core.workflows.nodes import IncludeNode, LoopGroupNode, Node
from agent_hub.core.workflows.rewrite import SEPARATOR, Rewrite, RewriteError, map_node
from agent_hub.core.workflows.scope import RefScope, ScopeStep
from agent_hub.core.workflows.substitution import (
    InputRef,
    LoopPrevRef,
    NodeRef,
    Ref,
    SubstitutionError,
    canonical_text,
    echo,
    find_refs,
    spell,
)

type IncludeResolver = Callable[[str], WorkflowDocument | None]

MAX_INCLUDE_DEPTH: Final = 3
# The most nodes an expanded document may hold, group bodies included: a few small includes
# cannot grow past it.
MAX_EXPANDED_NODES: Final = 512


@dataclass(frozen=True)
class Expansion:
    """The expanded document, and for each of its nodes the parent node it comes from (its
    index, and whether that node is an ``include``)."""

    document: WorkflowDocument
    origins: tuple[tuple[int, bool], ...]
    # Each included node's reference scope, by its expanded id (``scope.py``).
    scopes: Mapping[str, RefScope] = field(default_factory=dict)

    def locate(self, problem: WorkflowProblem) -> WorkflowProblem:
        """``problem``, found in the expanded document, on the parent node it comes from."""
        loc = problem.loc
        if len(loc) < 2 or loc[0] != "nodes" or not isinstance(loc[1], int):
            return problem
        index, included = self.origins[loc[1]]
        if not included:
            return WorkflowProblem(("nodes", index, *loc[2:]), problem.message)
        node_id = self.document.nodes[loc[1]].id
        message = f"{echo(node_id)}: {output_path(loc[2:])}: {problem.message}"
        return WorkflowProblem(("nodes", index, "include"), message)


def expand_includes(document: WorkflowDocument, resolve: IncludeResolver | None) -> Expansion:
    """``document`` with every ``include`` replaced; raises ``WorkflowLoadError``."""
    return _expand(document, _Resolver(resolve), (document.name,))


@dataclass(frozen=True)
class _Block:
    """An included workflow, expanded, its sinks and primary sink (not namespaced), and its
    nodes' scopes."""

    name: str
    document: WorkflowDocument
    sinks: tuple[str, ...]
    primary: str | None
    scopes: Mapping[str, RefScope]


@dataclass
class _Resolver:
    """One expansion's resolver: each workflow is expanded once per depth, then reused."""

    resolve: IncludeResolver | None
    cache: dict[tuple[str, int], _Block | RewriteError] = field(default_factory=dict)


def _expand(document: WorkflowDocument, resolver: _Resolver, stack: tuple[str, ...]) -> Expansion:
    nodes = document.nodes
    if not any(isinstance(node, IncludeNode) for node in nodes):
        return Expansion(document, tuple((index, False) for index in range(len(nodes))))
    if problems := list(_repeated_ids(nodes)):
        raise WorkflowLoadError(problems)
    parent = _Parent(_blocks(nodes, resolver, stack))
    expanded: list[Node] = []
    origins: list[tuple[int, bool]] = []
    # Every node the expanded document holds, a loop group's body included.
    count = 0
    for index, node in enumerate(nodes):
        try:
            copies = parent.place(node)
            count += sum(_size(copy) for copy in copies)
            if count > MAX_EXPANDED_NODES:
                message = f"the expanded workflow passes {MAX_EXPANDED_NODES} nodes"
                raise RewriteError(("include",) if isinstance(node, IncludeNode) else (), message)
        except RewriteError as error:
            problems.append(WorkflowProblem(("nodes", index, *error.loc), error.message))
            break
        expanded.extend(copies)
        origins.extend((index, isinstance(node, IncludeNode)) for _ in copies)
    returns = document.returns
    try:
        returns = None if returns is None else parent.resume(returns, ("returns",))
    except RewriteError as error:
        problems.append(WorkflowProblem(error.loc, error.message))
    if problems:
        raise WorkflowLoadError(problems)
    update = {"nodes": tuple(expanded), "returns": returns}
    step = parent.step()
    scopes = {
        key: parent.scopes.get(key, RefScope()).then(replace(step, keep=keep))
        for node in expanded
        for key, keep in scope_keys(node)
    }
    return Expansion(document.model_copy(update=update), tuple(origins), scopes)


def scope_keys(node: Node) -> Iterator[tuple[str, frozenset[str]]]:
    """The scope keys of ``node``: its id, and a group's body ids as they will be recorded
    (``<group>__<id>``), with the body ids a body node's scope leaves as written."""
    yield node.id, frozenset()
    if isinstance(node, LoopGroupNode):
        body = frozenset(child.id for child in node.nodes)
        for child in node.nodes:
            yield f"{node.id}{SEPARATOR}{child.id}", body


def _size(node: Node) -> int:
    """The nodes ``node`` stands for: itself, and a loop group's body."""
    return 1 + len(node.nodes) if isinstance(node, LoopGroupNode) else 1


def _repeated_ids(nodes: Sequence[Node]) -> Iterator[WorkflowProblem]:
    seen: set[str] = set()
    for index, node in enumerate(nodes):
        if node.id in seen:
            yield WorkflowProblem(("nodes", index, "id"), f"the id {echo(node.id)} is repeated")
        seen.add(node.id)


def _blocks(
    nodes: Sequence[Node], resolver: _Resolver, stack: tuple[str, ...]
) -> dict[str, _Block]:
    blocks: dict[str, _Block] = {}
    problems: list[WorkflowProblem] = []
    for index, node in enumerate(nodes):
        if isinstance(node, IncludeNode):
            try:
                blocks[node.id] = _cached_block(node.include, resolver, stack)
            except RewriteError as error:
                problems.append(WorkflowProblem(("nodes", index, *error.loc), error.message))
    if problems:
        raise WorkflowLoadError(problems)
    return blocks


def _cached_block(name: str, resolver: _Resolver, stack: tuple[str, ...]) -> _Block:
    key = (name, len(stack))
    if key not in resolver.cache:
        try:
            resolver.cache[key] = _block(name, resolver, stack)
        except RewriteError as error:
            resolver.cache[key] = error
    found = resolver.cache[key]
    if isinstance(found, RewriteError):
        raise found
    return found


def _block(name: str, resolver: _Resolver, stack: tuple[str, ...]) -> _Block:
    resolve = resolver.resolve
    if resolve is None:
        raise RewriteError(("include",), "this workflow cannot include others here")
    if name in stack:
        cycle = " → ".join((*stack[stack.index(name) :], name))
        raise RewriteError(("include",), f"an include cycle: {cycle}")
    if len(stack) > MAX_INCLUDE_DEPTH:
        raise RewriteError(("include",), f"more than {MAX_INCLUDE_DEPTH} levels of include")
    try:
        found = resolve(name)
        if found is None:
            raise RewriteError(("include",), f"no workflow is named {echo(name)}")
        expansion = _expand(found, resolver, (*stack, name))
    except WorkflowLoadError as error:
        details = "; ".join(f"{problem.key}: {problem.message}" for problem in error.problems)
        raise RewriteError(("include",), f"{echo(name)} does not load: {details}") from None
    expanded = expansion.document
    waited = {target for node in expanded.nodes for target in node.depends_on}
    sinks = tuple(node.id for node in expanded.nodes if node.id not in waited)
    primary = expanded.returns or (sinks[0] if len(sinks) == 1 else None)
    return _Block(name, expanded, sinks, primary, expansion.scopes)


class _Parent(Rewrite):
    """The parent's references to its includes: every sink of one, or its primary sink."""

    def __init__(self, blocks: Mapping[str, _Block]) -> None:
        self.blocks = blocks
        # The scopes of the block nodes placed so far, by expanded id.
        self.scopes: dict[str, RefScope] = {}

    def place(self, node: Node) -> list[Node]:
        """``node`` as the expanded document holds it: an include's block, or a copy."""
        if isinstance(node, IncludeNode):
            inside = _Inside(node, self.blocks[node.id], self)
            nodes = inside.nodes()
            self.scopes |= inside.scopes()
            return nodes
        return [map_node(node, self)]

    def step(self) -> ScopeStep:
        """This rewrite as a scope step: an include's id to its primary sink."""
        names = {
            include: f"{include}{SEPARATOR}{block.primary}"
            for include, block in self.blocks.items()
            if block.primary is not None
        }
        refused = frozenset(self.blocks) - set(names)
        return ScopeStep(names=names, refused=refused)

    def reference(self, loc: Loc, ref: Ref, spelling: str) -> str:
        if isinstance(ref, NodeRef | LoopPrevRef) and ref.node in self.blocks:
            return spell(type(ref)(self._primary(ref.node, loc, spelling), ref.path))
        return spelling

    def ids(self, targets: Sequence[str]) -> tuple[str, ...]:
        found: dict[str, None] = {}
        for target in targets:
            block = self.blocks.get(target)
            sinks = [f"{target}{SEPARATOR}{sink}" for sink in block.sinks] if block else [target]
            found.update(dict.fromkeys(sinks))
        return tuple(found)

    def resume(self, target: str, loc: Loc) -> str:
        return self._primary(target, loc) if target in self.blocks else target

    def _primary(self, include: str, loc: Loc, spelling: str | None = None) -> str:
        block = self.blocks[include]
        if block.primary is None:
            where = "" if spelling is None else f"{echo(spelling)}: "
            message = f"{where}{echo(block.name)} has several sinks and no 'returns'"
            raise RewriteError(loc, message)
        return f"{include}{SEPARATOR}{block.primary}"


class _Inside(Rewrite):
    """A block's references, as ``include`` places it: its own nodes namespaced, its inputs
    replaced by their values."""

    def __init__(self, include: IncludeNode, block: _Block, parent: _Parent) -> None:
        self.include, self.block, self.parent = include, block, parent
        self.prefix = f"{include.id}{SEPARATOR}"
        self.own = {node.id for node in block.document.nodes}
        self.values = _input_texts(include, block, parent)

    def nodes(self) -> list[Node]:
        include = self.include
        when = None if include.when is None else self.parent.text(("when",), include.when)
        nodes: list[Node] = []
        for node in self.block.document.nodes:
            copied = map_node(node, self)
            _check_when(node.when, copied.when, self.prefix + node.id)
            update: dict[str, object] = {"id": self.prefix + node.id}
            if not node.depends_on:
                update |= self._root_keys(node, when, copied.when)
            nodes.append(copied.model_copy(update=update))
        return nodes

    def _root_keys(self, node: Node, when: str | None, own: str | None) -> dict[str, object]:
        """The include's graph keys on a root of the block."""
        keys: dict[str, object] = {
            "depends_on": self.parent.ids(self.include.depends_on),
            "when": _joined(when, own),
        }
        explicit = "trigger_rule" in self.include.model_fields_set
        if explicit and "trigger_rule" not in node.model_fields_set:
            keys["trigger_rule"] = self.include.trigger_rule
        return keys

    def reference(self, loc: Loc, ref: Ref, spelling: str) -> str:
        name = echo(self.block.name)
        if isinstance(ref, InputRef):
            if ref.name not in self.values:
                message = f"{name} reads {echo(spelling)}, an input it does not declare"
                raise RewriteError(("include",), message)
            return self.values[ref.name]
        if isinstance(ref, NodeRef | LoopPrevRef):
            if ref.node not in self.own:
                message = f"{name} reads {echo(spelling)}, which is not one of its nodes"
                raise RewriteError(("include",), message)
            return spell(type(ref)(self.prefix + ref.node, ref.path))
        return spelling

    def ids(self, targets: Sequence[str]) -> tuple[str, ...]:
        return tuple(self.prefix + target for target in targets)

    def resume(self, target: str, loc: Loc) -> str:
        return self.prefix + target

    def scopes(self) -> dict[str, RefScope]:
        """Each block node's scope: the block's own, then this include's step."""
        step = ScopeStep(
            names={own: self.prefix + own for own in self.own}, inputs=self.values, hermetic=True
        )
        inner = self.block.scopes
        return {
            self.prefix + key: inner.get(key, RefScope()).then(replace(step, keep=keep))
            for node in self.block.document.nodes
            for key, keep in scope_keys(node)
        }


def _input_texts(include: IncludeNode, block: _Block, parent: _Parent) -> dict[str, str]:
    """The text each ``$INPUTS.<name>`` of the block becomes: its ``with`` value or default."""
    declared = block.document.inputs
    if unknown := sorted(set(include.with_) - set(declared)):
        message = f"{echo(block.name)} has no input named {echo(unknown[0])}"
        raise RewriteError(("with",), message)
    texts: dict[str, str] = {}
    for name, spec in declared.items():
        if name not in include.with_:
            if spec.required:
                message = f"the input {echo(name)} of {echo(block.name)} is required"
                raise RewriteError(("with",), message)
            texts[name] = _literal(spec.default)
            continue
        value: JsonValue = include.with_[name]
        if isinstance(value, str):
            _check_with_refs(("with", name), value)
            texts[name] = parent.text(("with", name), value)
        else:
            texts[name] = _literal(value)
    return texts


def _literal(value: JsonValue) -> str:
    """A value put in place of a reference, its ``$`` escaped: it stays text, never a reference."""
    return canonical_text(value).replace("$", "$$")


def _check_with_refs(loc: Loc, value: str) -> None:
    try:
        refs = find_refs(value)
    except SubstitutionError as error:
        raise RewriteError(loc, str(error)) from None
    if any(not isinstance(ref, InputRef | NodeRef) for ref in refs):
        raise RewriteError(loc, "an include's 'with' reads only $INPUTS and node outputs")


def _check_when(before: str | None, after: str | None, node_id: str) -> None:
    if before is None or after is None or before == after or not _parses(before):
        return
    try:
        parse_condition(after)
    except ConditionParseError as error:
        message = f'{echo(node_id)}: when: no longer parses once "with" is filled in: {error}'
        raise RewriteError(("include",), message) from None


def _parses(expr: str) -> bool:
    try:
        parse_condition(expr)
    except ConditionParseError:
        return False
    return True


def _joined(include_when: str | None, own: str | None) -> str | None:
    if include_when is None or own is None:
        return include_when or own
    for expr in (include_when, own):
        if _parses(expr) and len(parse_condition(expr).clauses) > 1:
            message = (
                "cannot join a 'when:' holding '||' with a root's own: there are no parentheses"
            )
            raise RewriteError(("when",), message)
    return f"{include_when} && {own}"
