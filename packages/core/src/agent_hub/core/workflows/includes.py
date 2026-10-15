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

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
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
from agent_hub.core.workflows.nodes import (
    AgentNode,
    ApprovalNode,
    FromBinding,
    HaltNode,
    IncludeNode,
    LoopNode,
    Node,
    ResumeContext,
    ScriptNode,
    ShellNode,
    read_only,
)
from agent_hub.core.workflows.substitution import (
    InputRef,
    LoopPrevRef,
    NodeRef,
    Ref,
    SubstitutionError,
    canonical_text,
    echo,
    find_refs,
    rewrite_refs,
    spell,
)

type IncludeResolver = Callable[[str], WorkflowDocument | None]
# Rewrites one text at a key path of its node; may raise ``_IncludeError``.
type _TextMap = Callable[[Loc, str], str]
type _Replace = Callable[[Ref, str], str]

MAX_INCLUDE_DEPTH: Final = 3
SEPARATOR: Final = "__"


class _IncludeError(Exception):
    """A problem at ``loc`` inside the node being expanded."""

    def __init__(self, loc: Loc, message: str) -> None:
        super().__init__(message)
        self.loc, self.message = loc, message


@dataclass(frozen=True)
class Expansion:
    """The expanded document, and for each of its nodes the parent node it comes from (its
    index, and whether that node is an ``include``)."""

    document: WorkflowDocument
    origins: tuple[tuple[int, bool], ...]

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
    return _expand(document, resolve, (document.name,))


@dataclass(frozen=True)
class _Block:
    """An included workflow, expanded, and its sinks and primary sink (not namespaced)."""

    name: str
    document: WorkflowDocument
    sinks: tuple[str, ...]
    primary: str | None


def _expand(
    document: WorkflowDocument, resolve: IncludeResolver | None, stack: tuple[str, ...]
) -> Expansion:
    nodes = document.nodes
    if not any(isinstance(node, IncludeNode) for node in nodes):
        return Expansion(document, tuple((index, False) for index in range(len(nodes))))
    if problems := list(_repeated_ids(nodes)):
        raise WorkflowLoadError(problems)
    parent = _Parent(_blocks(nodes, resolve, stack))
    expanded: list[Node] = []
    origins: list[tuple[int, bool]] = []
    for index, node in enumerate(nodes):
        try:
            copies = parent.place(node)
        except _IncludeError as error:
            problems.append(WorkflowProblem(("nodes", index, *error.loc), error.message))
            continue
        expanded.extend(copies)
        origins.extend((index, isinstance(node, IncludeNode)) for _ in copies)
    returns = document.returns
    try:
        returns = None if returns is None else parent.resume(returns, ("returns",))
    except _IncludeError as error:
        problems.append(WorkflowProblem(error.loc, error.message))
    if problems:
        raise WorkflowLoadError(problems)
    update = {"nodes": tuple(expanded), "returns": returns}
    return Expansion(document.model_copy(update=update), tuple(origins))


def _repeated_ids(nodes: Sequence[Node]) -> Iterator[WorkflowProblem]:
    seen: set[str] = set()
    for index, node in enumerate(nodes):
        if node.id in seen:
            yield WorkflowProblem(("nodes", index, "id"), f"the id {echo(node.id)} is repeated")
        seen.add(node.id)


def _blocks(
    nodes: Sequence[Node], resolve: IncludeResolver | None, stack: tuple[str, ...]
) -> dict[str, _Block]:
    blocks: dict[str, _Block] = {}
    problems: list[WorkflowProblem] = []
    for index, node in enumerate(nodes):
        if isinstance(node, IncludeNode):
            try:
                blocks[node.id] = _block(node.include, resolve, stack)
            except _IncludeError as error:
                problems.append(WorkflowProblem(("nodes", index, *error.loc), error.message))
    if problems:
        raise WorkflowLoadError(problems)
    return blocks


def _block(name: str, resolve: IncludeResolver | None, stack: tuple[str, ...]) -> _Block:
    if resolve is None:
        raise _IncludeError(("include",), "this workflow cannot include others here")
    if name in stack:
        cycle = " → ".join((*stack[stack.index(name) :], name))
        raise _IncludeError(("include",), f"an include cycle: {cycle}")
    if len(stack) > MAX_INCLUDE_DEPTH:
        raise _IncludeError(("include",), f"more than {MAX_INCLUDE_DEPTH} levels of include")
    try:
        found = resolve(name)
        if found is None:
            raise _IncludeError(("include",), f"no workflow is named {echo(name)}")
        expanded = _expand(found, resolve, (*stack, name)).document
    except WorkflowLoadError as error:
        details = "; ".join(f"{problem.key}: {problem.message}" for problem in error.problems)
        raise _IncludeError(("include",), f"{echo(name)} does not load: {details}") from None
    waited = {target for node in expanded.nodes for target in node.depends_on}
    sinks = tuple(node.id for node in expanded.nodes if node.id not in waited)
    primary = expanded.returns or (sinks[0] if len(sinks) == 1 else None)
    return _Block(name, expanded, sinks, primary)


class _Rewrite(ABC):
    """How one node's ids and references are rewritten as it is copied."""

    def text(self, loc: Loc, text: str) -> str:
        return _rewritten(loc, text, lambda ref, spelling: self.reference(loc, ref, spelling))

    @abstractmethod
    def reference(self, loc: Loc, ref: Ref, spelling: str) -> str: ...

    @abstractmethod
    def ids(self, targets: Sequence[str]) -> tuple[str, ...]: ...

    @abstractmethod
    def resume(self, target: str, loc: Loc) -> str: ...


class _Parent(_Rewrite):
    """The parent's references to its includes: every sink of one, or its primary sink."""

    def __init__(self, blocks: Mapping[str, _Block]) -> None:
        self.blocks = blocks

    def place(self, node: Node) -> list[Node]:
        """``node`` as the expanded document holds it: an include's block, or a copy."""
        if isinstance(node, IncludeNode):
            return _Inside(node, self.blocks[node.id], self).nodes()
        return [_map_node(node, self)]

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
            raise _IncludeError(loc, message)
        return f"{include}{SEPARATOR}{block.primary}"


class _Inside(_Rewrite):
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
            copied = _map_node(node, self)
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
                raise _IncludeError(("include",), message)
            return self.values[ref.name]
        if isinstance(ref, NodeRef | LoopPrevRef):
            if ref.node not in self.own:
                message = f"{name} reads {echo(spelling)}, which is not one of its nodes"
                raise _IncludeError(("include",), message)
            return spell(type(ref)(self.prefix + ref.node, ref.path))
        return spelling

    def ids(self, targets: Sequence[str]) -> tuple[str, ...]:
        return tuple(self.prefix + target for target in targets)

    def resume(self, target: str, loc: Loc) -> str:
        return self.prefix + target


def _input_texts(include: IncludeNode, block: _Block, parent: _Parent) -> dict[str, str]:
    """The text each ``$INPUTS.<name>`` of the block becomes: its ``with`` value or default."""
    declared = block.document.inputs
    if unknown := sorted(set(include.with_) - set(declared)):
        message = f"{echo(block.name)} has no input named {echo(unknown[0])}"
        raise _IncludeError(("with",), message)
    texts: dict[str, str] = {}
    for name, spec in declared.items():
        if name not in include.with_:
            if spec.required:
                message = f"the input {echo(name)} of {echo(block.name)} is required"
                raise _IncludeError(("with",), message)
            texts[name] = canonical_text(spec.default)
            continue
        value: JsonValue = include.with_[name]
        if isinstance(value, str):
            _check_with_refs(("with", name), value)
            texts[name] = parent.text(("with", name), value)
        else:
            texts[name] = canonical_text(value)
    return texts


def _check_with_refs(loc: Loc, value: str) -> None:
    try:
        refs = find_refs(value)
    except SubstitutionError as error:
        raise _IncludeError(loc, str(error)) from None
    if any(not isinstance(ref, InputRef | NodeRef) for ref in refs):
        raise _IncludeError(loc, "an include's 'with' reads only $INPUTS and node outputs")


def _rewritten(loc: Loc, text: str, replace: _Replace) -> str:
    try:
        return rewrite_refs(text, replace)
    except SubstitutionError as error:
        raise _IncludeError(loc, str(error)) from None


def _check_when(before: str | None, after: str | None, node_id: str) -> None:
    if before is None or after is None or before == after or not _parses(before):
        return
    try:
        parse_condition(after)
    except ConditionParseError as error:
        message = f'{echo(node_id)}: when: no longer parses once "with" is filled in: {error}'
        raise _IncludeError(("include",), message) from None


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
            raise _IncludeError(("when",), message)
    return f"{include_when} && {own}"


def _map_node(node: Node, rewrite: _Rewrite) -> Node:
    """``node`` with its ids and the references in its texts rewritten."""
    update: dict[str, object] = {"depends_on": rewrite.ids(node.depends_on)}
    if node.when is not None:
        update["when"] = rewrite.text(("when",), node.when)
    if isinstance(node, AgentNode | LoopNode):
        update |= _agent_update(node, rewrite)
    elif isinstance(node, ShellNode | ScriptNode):
        update |= _command_update(node, rewrite)
    elif isinstance(node, ApprovalNode):
        update["message"] = rewrite.text(("message",), node.message)
    elif isinstance(node, HaltNode):
        update["reason"] = rewrite.text(("reason",), node.reason)
    return node.model_copy(update=update)


def _agent_update(node: AgentNode | LoopNode, rewrite: _Rewrite) -> dict[str, object]:
    update: dict[str, object] = {"with_": read_only(_bindings(node, rewrite))}
    if node.prompt is not None:
        update["prompt"] = rewrite.text(("prompt",), node.prompt)
    if isinstance(node.context, ResumeContext):
        target = rewrite.resume(node.context.resume, ("context", "resume"))
        update["context"] = ResumeContext(resume=target)
    if isinstance(node, LoopNode) and node.until_bash is not None:
        update["until_bash"] = _argv(("until_bash",), node.until_bash, rewrite)
    return update


def _bindings(node: AgentNode | LoopNode, rewrite: _Rewrite) -> dict[str, object]:
    bindings: dict[str, object] = {}
    for name, binding in node.with_.items():
        if isinstance(binding, FromBinding):
            source = rewrite.text(("with", name, "from"), binding.from_)
            bindings[name] = binding.model_copy(update={"from_": source})
        else:
            bindings[name] = _json_texts(("with", name), binding, rewrite)
    return bindings


def _command_update(node: ShellNode | ScriptNode, rewrite: _Rewrite) -> dict[str, object]:
    update: dict[str, object] = {
        "env": read_only({name: rewrite.text(("env", name), v) for name, v in node.env.items()})
    }
    if isinstance(node, ShellNode):
        update["command"] = _argv(("command",), node.command, rewrite)
    else:
        update["args"] = _argv(("args",), node.args, rewrite)
    if node.cwd is not None:
        update["cwd"] = rewrite.text(("cwd",), node.cwd)
    return update


def _argv(key: Loc, argv: Sequence[str], rewrite: _Rewrite) -> tuple[str, ...]:
    return tuple(rewrite.text((*key, index), element) for index, element in enumerate(argv))


def _json_texts(loc: Loc, value: JsonValue, rewrite: _Rewrite) -> JsonValue:
    if isinstance(value, str):
        return rewrite.text(loc, value)
    if isinstance(value, list):
        return [_json_texts((*loc, index), item, rewrite) for index, item in enumerate(value)]
    if isinstance(value, dict):
        return {key: _json_texts((*loc, key), item, rewrite) for key, item in value.items()}
    return value
