"""A version-2 scenario translated to the node graph, and its block map (docs/design/scenarios.md
§ Tree format, ADR 0049).

``translate_tree`` parses a tree (``tree_document``) and returns the ``WorkflowDocument`` that
planning and the engine read, a version-1 document with the tree's name, description, revision
and inputs and the nodes its blocks become, with the ``BlockMap``. It is pure and deterministic:
ids come from positions and stage names, so a resume translates a run's snapshot to the same
graph.

- **Addresses and ids.** A stage is ``<s>`` (from 1), a block in it ``<s>.<n>``; inside a block,
  ``then.<n>`` and ``else.<n>`` (an If), ``p<k>.<n>`` (path k of a Together) and ``<n>`` (a
  Repeat's steps). A block without ``id`` gets ``<stage slug>--<address in the stage, dots as
  ->``; a slug (``stage_slug``) never holds ``--``, so only an explicit id can meet another.
- **Step lists.** The stages' steps form one list, and each branch, path and Repeat body is a
  list of its own. A block's entry nodes depend on the exit nodes of the block before it in its
  list; a list's first block on what its container's depend on (a Repeat body's on nothing).
- **If.** Its condition goes on every entry node of the first block of ``then``, its complement
  (each operator's opposite, ``&&`` and ``||`` swapped, expanded to or-of-ands) on those of
  ``else``; on a node that already holds a condition the two are joined by distributing ``&&``.
  Its exit nodes are both branches' last ones or, with no ``else``, the last of ``then`` and the
  exit nodes of the block before it, so an If with no ``else`` never opens a list. The block
  after one whose exit nodes a run may skip (an If, or a Together a path of which ends in one)
  takes ``none_failed_min_one_success``.
- **Together.** Each path starts on the block before; its exit nodes are each path's last.
- **Repeat.** One ``loop_group``: ``max`` is ``max_iterations``, ``until`` its ``until_when``,
  its steps the body, which holds no Repeat or Include.

Bounds: ``MAX_TREE_NODES`` nodes, containers ``MAX_DEPTH`` deep, ``MAX_TERMS`` terms in a joined
condition. A problem on a generated node, found here or by planning, is
put back on the tree's key path by the document's ``TreeLocator`` (``WorkflowDocument.located``).
"""

import itertools
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from types import MappingProxyType
from typing import Final, Literal

from pydantic import ValidationError

from agent_hub.core.features.output_shape import output_path
from agent_hub.core.scenarios.policy_gates import ASK_SUFFIX, ask_gate
from agent_hub.core.scenarios.tree_document import (
    DoStep,
    IfStep,
    IncludeStep,
    RepeatStep,
    Step,
    StepKind,
    TogetherStep,
    TreeDocument,
    WaitStep,
    WaitUntilStep,
    YouStep,
    parse_tree,
)
from agent_hub.core.workflows.conditions import Atom, Condition, Op, parse_condition
from agent_hub.core.workflows.document import (
    Loc,
    WorkflowDocument,
    WorkflowLoadError,
    WorkflowProblem,
    kind_problems,
    load_error,
    with_locator,
)
from agent_hub.core.workflows.includes import MAX_EXPANDED_NODES
from agent_hub.core.workflows.nodes import LoopGroupNode, Node
from agent_hub.core.workflows.plan import WorkflowPlan
from agent_hub.core.workflows.rewrite import SEPARATOR
from agent_hub.core.workflows.substitution import echo

type BlockKind = Literal[
    "stage", "do", "wait_until", "you", "wait", "include", "repeat", "if", "together"
]
type _Leaf = DoStep | WaitUntilStep | YouStep | WaitStep | IncludeStep
type _NodeSpec = dict[str, object]

# Today's cap on an expanded document, already reached by the translation alone.
MAX_TREE_NODES: Final = MAX_EXPANDED_NODES
MAX_DEPTH: Final = 3
MAX_TERMS: Final = 64
JOIN_RULE: Final = "none_failed_min_one_success"
_OPPOSITE: Final[Mapping[Op, Op]] = {
    "==": "!=",
    "!=": "==",
    "<": ">=",
    ">=": "<",
    ">": "<=",
    "<=": ">",
}
_SLUG_RUN: Final = re.compile(r"[^a-z0-9]+")
_NODE_TYPES: Final[Mapping[StepKind, str]] = {
    "do": "action",
    "wait_until": "expect",
    "you": "approval",
    "wait": "wait",
    "include": "include",
}
# A leaf's keys its node spells otherwise.
_NODE_KEYS: Final[Mapping[StepKind, Mapping[str, str]]] = {
    "do": {"do": "action"},
    "wait_until": {"wait_until": "action", "until": "until_when"},
    "you": {"you": "message"},
}
# A node's keys as its block spells them (any other key is spelled alike).
_TREE_KEYS: Final[Mapping[StepKind, Mapping[str, Loc]]] = {
    "do": {"action": ("do",)},
    "wait_until": {"action": ("wait_until",), "until_when": ("until",)},
    "you": {"message": ("you",)},
    "wait": {key: ("wait", key) for key in ("duration", "until", "attention", "options")},
    "repeat": {
        "max_iterations": ("repeat", "max"),
        "until_when": ("repeat", "until"),
        "nodes": ("repeat", "steps"),
    },
}
# The keys translation writes: a problem there is its block's.
_WRITTEN: Final = frozenset({"depends_on", "trigger_rule", "type"})
_OPENS_A_LIST: Final = (
    "an If with no else cannot open a step list (the scenario, a branch, a path or a Repeat"
    " body): write the else, or put a block before it"
)
_CONTAINED: Final[Mapping[StepKind, str]] = {"repeat": "Repeat", "include": "Include"}


@dataclass(frozen=True)
class Block:
    """One block of a tree: its address, kind, label and key path; its nodes, entry nodes (the
    first it runs) and exit nodes (what the block after it depends on), each id as the run
    records it (a Repeat body's ``<group>__<id>``)."""

    address: str
    kind: BlockKind
    label: str
    key: Loc
    nodes: tuple[str, ...]
    entry_nodes: tuple[str, ...]
    exit_nodes: tuple[str, ...]


@dataclass(frozen=True)
class BlockMap:
    """Every block of a tree, in declaration order: a stage, then its blocks, a container before
    the blocks it holds."""

    blocks: tuple[Block, ...]

    def block(self, address: str) -> Block | None:
        """The block at ``address``, if the tree holds one."""
        return next((block for block in self.blocks if block.address == address), None)

    def run_entries(self, plan: WorkflowPlan) -> dict[str, tuple[str, ...]]:
        """Each block's entry nodes as ``plan`` runs them, by address: an include's by the roots
        of what it includes, a gated step's by its ``<step>__ask`` gate."""
        recorded = frozenset(node.id for node in plan.all_nodes())
        roots = plan.document.nodes
        return {
            block.address: _run_entries(block.entry_nodes, recorded, roots) for block in self.blocks
        }


@dataclass(frozen=True)
class NodeOrigin:
    """Where a translated node comes from: its block's kind and key path, and the ``if`` key of
    the If whose condition its ``when`` holds first."""

    kind: StepKind
    key: Loc
    when: Loc | None = None


# Each top-level node's id, and its body's ids when it is a loop group.
type _Ids = Sequence[tuple[str, Sequence[str]]]


@dataclass(frozen=True)
class TreeLocator:
    """Puts a problem found on a translated document's nodes (or its expansion, or its policy
    gates) back on the tree's key path."""

    origins: Mapping[str, NodeOrigin]

    def locate(self, document: WorkflowDocument, problem: WorkflowProblem) -> WorkflowProblem:
        """``problem``, found on ``document``, at the tree's key path."""
        ids = [(node.id, _body_ids(node)) for node in document.nodes]
        return self.locate_in(ids, problem)

    def locate_in(self, ids: _Ids, problem: WorkflowProblem) -> WorkflowProblem:
        """``problem``, found on the nodes ``ids`` names in order, at the tree's key path."""
        loc = problem.loc
        if len(loc) < 2 or loc[0] != "nodes" or not isinstance(loc[1], int) or loc[1] >= len(ids):
            return problem
        node_id, body = ids[loc[1]]
        rest = loc[2:]
        if (
            len(rest) > 1
            and rest[0] == "nodes"
            and isinstance(rest[1], int)
            and rest[1] < len(body)
        ):
            node_id, rest = body[rest[1]], rest[2:]
        return self._on_node(node_id, rest, problem)

    def _on_node(self, node_id: str, rest: Loc, problem: WorkflowProblem) -> WorkflowProblem:
        origin = self.origins.get(node_id) or self.origins.get(node_id.removesuffix(ASK_SUFFIX))
        if origin is not None:
            return WorkflowProblem(_tree_loc(origin, rest), problem.message)
        include = self.origins.get(node_id.split(SEPARATOR, 1)[0])
        if include is None:
            return problem
        message = f"{echo(node_id)}: {output_path(rest)}: {problem.message}"
        return WorkflowProblem((*include.key, "include"), message)


@dataclass(frozen=True)
class Translation:
    """A tree's graph, as planning reads it, and its block map."""

    document: WorkflowDocument
    blocks: BlockMap


def translate_tree(content: object) -> Translation:
    """The graph and block map of the tree ``content`` holds; raises ``WorkflowLoadError``
    naming every problem at the tree's key path."""
    return _Translator(parse_tree(content)).translate()


def block_map(content: object) -> BlockMap:
    """The block map of the tree ``content`` holds (translated again: never stored)."""
    return translate_tree(content).blocks


def stage_slug(name: str) -> str:
    """A stage name's slug: lowercase, each run of other characters one ``-``."""
    return _SLUG_RUN.sub("-", name.lower())


def complement(condition: Condition) -> Condition:
    """``condition``'s complement in the grammar's or-of-ands form: one opposite atom from each
    clause, per term (an If's condition of at most 8 atoms gives at most 18 terms)."""
    negated = [
        tuple(replace(atom, op=_OPPOSITE[atom.op]) for atom in clause)
        for clause in condition.clauses
    ]
    return Condition(tuple(itertools.product(*negated)))


def conjoin(outer: Condition, inner: Condition) -> Condition | None:
    """``outer && inner``, ``&&`` distributed over both or-of-ands forms, ``outer``'s atoms
    first; ``None`` past ``MAX_TERMS`` terms."""
    if len(outer.clauses) * len(inner.clauses) > MAX_TERMS:
        return None
    return Condition(
        tuple((*first, *second) for first in outer.clauses for second in inner.clauses)
    )


def condition_text(condition: Condition) -> str:
    """``condition`` written in the ``when:`` grammar."""
    clauses = (" && ".join(_atom_text(atom) for atom in clause) for clause in condition.clauses)
    return " || ".join(clauses)


def _atom_text(atom: Atom) -> str:
    return f"{atom.ref_text} {atom.op} {_literal_text(atom.literal)}"


def _literal_text(literal: str | Decimal) -> str:
    if isinstance(literal, Decimal):
        return format(literal, "f")
    # A quoted 'true' and a bare true read the same text: the bare one reads better.
    if literal in ("true", "false"):
        return literal
    return "'" + literal.replace("'", "''") + "'"


def _tree_loc(origin: NodeOrigin, rest: Loc) -> Loc:
    """A node's key path ``rest`` as its block spells it."""
    head = rest[0] if rest else None
    if not isinstance(head, str) or head in _WRITTEN:
        return (*origin.key, "wait") if origin.kind == "wait" and not rest else origin.key
    if head == "when":
        return origin.when or origin.key
    spelled = _TREE_KEYS.get(origin.kind, {}).get(head, (head,))
    return (*origin.key, *spelled, *rest[1:])


def _body_ids(node: Node) -> list[str]:
    return [child.id for child in node.nodes] if isinstance(node, LoopGroupNode) else []


def _run_entries(
    entry: Iterable[str], recorded: frozenset[str], roots: Sequence[Node]
) -> tuple[str, ...]:
    found: dict[str, None] = {}
    for node_id in entry:
        if node_id in recorded:
            gate = ask_gate(node_id)
            found[gate if gate in recorded else node_id] = None
            continue
        # An include, expanded: the nodes of its block that depend on none of the block.
        prefix = f"{node_id}{SEPARATOR}"
        found |= {
            root.id: None
            for root in roots
            if root.id.startswith(prefix)
            and not any(target.startswith(prefix) for target in root.depends_on)
        }
    return tuple(found)


def _unique(ids: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(ids))


@dataclass(frozen=True)
class _Span:
    """What one block, or one list, starts with and ends with; ``branching`` when a run may skip
    some of its exit nodes."""

    entry: tuple[str, ...]
    exits: tuple[str, ...]
    branching: bool = False


@dataclass(frozen=True)
class _Flow:
    """What the next block of a list follows: the exit nodes of the block before it, whether a
    run may skip some of them, and whether no block came yet."""

    exits: tuple[str, ...] = ()
    branching: bool = False
    opening: bool = True


@dataclass(frozen=True)
class _List:
    """A step list: its stage's slug, its address and key path, the containers around it, and
    where its nodes go (a Repeat body's list, with its group, or the document's)."""

    slug: str
    address: str
    key: Loc
    sink: list[_NodeSpec]
    depth: int = 0
    group: str | None = None

    def at(self, index: int) -> _At:
        return _At(f"{self.address}.{index + 1}", (*self.key, index), self)

    def inner(self, address: str, key: Loc) -> _List:
        return replace(self, address=address, key=key, depth=self.depth + 1)


@dataclass(frozen=True)
class _At:
    """A block's place: its address, key path and list."""

    address: str
    key: Loc
    within: _List

    def derived_id(self) -> str:
        in_stage = self.address.partition(".")[2]
        return f"{self.within.slug}--{in_stage.replace('.', '-')}"


@dataclass
class _Made:
    """A node made: its content, its block's kind and key path, its id as recorded, and the
    ``if`` key its condition came from."""

    node: _NodeSpec
    kind: StepKind
    key: Loc
    recorded: str
    when: Loc | None = None


@dataclass
class _Translator:
    tree: TreeDocument
    top: list[_NodeSpec] = field(default_factory=list)
    bodies: dict[str, list[_NodeSpec]] = field(default_factory=dict)
    made: dict[str, _Made] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    # In declaration order: a container's slot is taken before the blocks inside it.
    blocks: list[Block | None] = field(default_factory=list)
    ids: dict[str, tuple[str, Loc, bool]] = field(default_factory=dict)
    problems: list[WorkflowProblem] = field(default_factory=list)

    def translate(self) -> Translation:
        flow = _Flow()
        for index, slug in enumerate(self._slugs()):
            flow = self._stage(index, slug, flow)
        if self.problems:
            raise WorkflowLoadError(_unique_problems(self.problems))
        blocks = BlockMap(tuple(block for block in self.blocks if block is not None))
        return Translation(self._document(), blocks)

    def _refuse(self, loc: Loc, message: str) -> None:
        self.problems.append(WorkflowProblem(loc, message))

    def _slugs(self) -> list[str]:
        slugs = [stage_slug(stage.name) for stage in self.tree.stages]
        seen: dict[str, int] = {}
        for index, slug in enumerate(slugs):
            where = ("stages", index, "name")
            if not "a" <= slug[:1] <= "z":
                self._refuse(where, f"its slug {echo(slug)} must start with a letter")
            elif slug in seen:
                message = (
                    f"its slug {echo(slug)} is stage {seen[slug] + 1}'s: stage names must"
                    " differ in more than case, blanks and punctuation"
                )
                self._refuse(where, message)
            seen.setdefault(slug, index)
        return slugs

    def _stage(self, index: int, slug: str, flow: _Flow) -> _Flow:
        stage = self.tree.stages[index]
        slot, start = self._slot(), len(self.order)
        within = _List(slug, str(index + 1), ("stages", index, "steps"), self.top)
        flow, entry = self._steps(stage.steps, within, flow)
        at = _At(within.address, ("stages", index), within)
        self._record(
            slot, at, shown=("stage", stage.name), start=start, span=_Span(entry, flow.exits)
        )
        return flow

    def _slot(self) -> int:
        self.blocks.append(None)
        return len(self.blocks) - 1

    def _record(
        self, slot: int, at: _At, *, shown: tuple[BlockKind, str], start: int, span: _Span
    ) -> None:
        kind, label = shown
        nodes = tuple(self.order[start:])
        entry, exits = self._recorded(span.entry), self._recorded(span.exits)
        self.blocks[slot] = Block(at.address, kind, label, at.key, nodes, entry, exits)

    def _recorded(self, ids: Iterable[str]) -> tuple[str, ...]:
        return tuple(self.made[node_id].recorded for node_id in ids)

    def _steps(
        self, steps: Sequence[Step], within: _List, flow: _Flow
    ) -> tuple[_Flow, tuple[str, ...]]:
        """The blocks of one list in order, each after ``flow``: the list's end, and the entry
        nodes of its first block."""
        entry: tuple[str, ...] = ()
        for index, step in enumerate(steps):
            at = within.at(index)
            if flow.opening and isinstance(step, IfStep) and step.else_ is None:
                self._refuse((*at.key, "if"), _OPENS_A_LIST)
            span = self._block(step, at, flow.exits)
            if flow.branching:
                for node_id in span.entry:
                    self.made[node_id].node["trigger_rule"] = JOIN_RULE
            if index == 0:
                entry = span.entry
            flow = _Flow(span.exits, span.branching, opening=False)
        return flow, entry

    def _block(self, step: Step, at: _At, before: tuple[str, ...]) -> _Span:
        self._check(step, at)
        slot, start = self._slot(), len(self.order)
        if isinstance(step, IfStep):
            span = self._if(step, at, before)
        elif isinstance(step, TogetherStep):
            span = self._together(step, at, before)
        elif isinstance(step, RepeatStep):
            span = self._repeat(step, at, before)
        else:
            span = self._leaf(step, at, before)
        self._record(slot, at, shown=(step.kind, step.label), start=start, span=span)
        return span

    def _check(self, step: Step, at: _At) -> None:
        within = at.within
        container = isinstance(step, IfStep | TogetherStep | RepeatStep)
        if container and within.depth >= MAX_DEPTH:
            self._refuse((*at.key, step.kind), f"containers nest at most {MAX_DEPTH} deep")
        contained = _CONTAINED.get(step.kind)
        if within.group is not None and contained is not None:
            self._refuse((*at.key, step.kind), f"a Repeat holds no {contained}")

    def _leaf(self, step: _Leaf, at: _At, before: tuple[str, ...]) -> _Span:
        node_id = self._id(step.id, at)
        node: _NodeSpec = {"id": node_id, **_node_keys(step)}
        if before:
            node["depends_on"] = list(before)
        self._make(node, step.kind, at)
        return _Span((node_id,), (node_id,))

    def _repeat(self, step: RepeatStep, at: _At, before: tuple[str, ...]) -> _Span:
        group = self._id(step.id, at)
        body: list[_NodeSpec] = []
        self.bodies[group] = body
        spec = step.repeat
        node: _NodeSpec = {"id": group, "type": "loop_group", "max_iterations": spec.max}
        node |= {"until_when": spec.until, "nodes": body}
        if step.description is not None:
            node["description"] = step.description
        if before:
            node["depends_on"] = list(before)
        self._make(node, step.kind, at)
        inner = at.within.inner(at.address, (*at.key, "repeat", "steps"))
        self._steps(spec.steps, replace(inner, sink=body, group=group), _Flow())
        return _Span((group,), (group,))

    def _if(self, step: IfStep, at: _At, before: tuple[str, ...]) -> _Span:
        condition = parse_condition(step.if_, scenario=True)
        then = at.within.inner(f"{at.address}.then", (*at.key, "then"))
        flow, entry = self._steps(step.then, then, _Flow(before))
        self._condition(entry, (condition, step.if_), at)
        if step.else_ is None:
            return _Span(entry, _unique((*flow.exits, *before)), branching=True)
        otherwise = at.within.inner(f"{at.address}.else", (*at.key, "else"))
        other, other_entry = self._steps(step.else_, otherwise, _Flow(before))
        negated = complement(condition)
        self._condition(other_entry, (negated, condition_text(negated)), at)
        exits = _unique((*flow.exits, *other.exits))
        return _Span((*entry, *other_entry), exits, branching=True)

    def _together(self, step: TogetherStep, at: _At, before: tuple[str, ...]) -> _Span:
        entry: list[str] = []
        exits: list[str] = []
        branching = False
        for number, path in enumerate(step.together, start=1):
            key = (*at.key, "together", number - 1)
            flow, first = self._steps(
                path, at.within.inner(f"{at.address}.p{number}", key), _Flow(before)
            )
            entry += first
            exits += flow.exits
            branching = branching or flow.branching
        return _Span(tuple(entry), _unique(exits), branching)

    def _condition(self, entry: Iterable[str], condition: tuple[Condition, str], at: _At) -> None:
        """A branch's condition (parsed, and as written) on each entry node of its first block,
        joined with the one the node holds (an If or a Together inside the branch)."""
        parsed, text = condition
        for node_id in entry:
            made = self.made[node_id]
            own = made.node.get("when")
            when = text
            if isinstance(own, str):
                joined = conjoin(parsed, parse_condition(own, scenario=True))
                if joined is None:
                    message = (
                        f"joined with a condition inside its branch, it passes {MAX_TERMS} terms"
                    )
                    self._refuse((*at.key, "if"), message)
                    continue
                when = condition_text(joined)
            made.node["when"] = when
            made.when = made.when or (*at.key, "if")

    def _id(self, explicit: str | None, at: _At) -> str:
        """The block's node id, given or derived; an id another block has is refused where it
        is written (two derived ids meet only when two stage slugs do, refused there)."""
        node_id = explicit or at.derived_id()
        address, key, was_explicit = self.ids.setdefault(
            node_id, (at.address, at.key, explicit is not None)
        )
        if address != at.address and (explicit is not None or was_explicit):
            where, other = (at.key, address) if explicit is not None else (key, at.address)
            self._refuse((*where, "id"), f"the id {echo(node_id)} is also block {other}'s")
        return node_id

    def _make(self, node: _NodeSpec, kind: StepKind, at: _At) -> None:
        node_id = str(node["id"])
        group = at.within.group
        recorded = node_id if group is None else f"{group}{SEPARATOR}{node_id}"
        self.made[node_id] = _Made(node, kind, at.key, recorded)
        self.order.append(recorded)
        at.within.sink.append(node)
        if len(self.order) == MAX_TREE_NODES + 1:
            self._refuse(at.key, f"the translated scenario passes {MAX_TREE_NODES} nodes")

    def _document(self) -> WorkflowDocument:
        tree = self.tree
        content: dict[str, object] = {
            "version": 1,
            "kind": "scenario",
            "name": tree.name,
            "revision": tree.revision,
            "inputs": dict(tree.inputs),
            "nodes": self.top,
        }
        if tree.description is not None:
            content["description"] = tree.description
        origins = {node_id: NodeOrigin(m.kind, m.key, m.when) for node_id, m in self.made.items()}
        locator = TreeLocator(MappingProxyType(origins))
        try:
            document = WorkflowDocument.model_validate(content)
        except ValidationError as error:
            ids = [(str(node["id"]), self._raw_body(node)) for node in self.top]
            # A body is never empty here: pydantic's length error on one only echoes a body
            # node's own error.
            found = [p for p in load_error(error, content).problems if p.loc[2:] != ("nodes",)]
            located = _unique_problems(locator.locate_in(ids, p) for p in found)
            raise WorkflowLoadError(located) from None
        document = with_locator(document, locator)
        if problems := list(kind_problems(document)):
            raise WorkflowLoadError(document.located(problems))
        return document

    def _raw_body(self, node: _NodeSpec) -> list[str]:
        return [str(child["id"]) for child in self.bodies.get(str(node["id"]), [])]


def _node_keys(step: _Leaf) -> _NodeSpec:
    """A leaf's node keys but its id and graph keys: the ones it was given, as its node spells
    them, and its node's type."""
    given = step.model_dump(by_alias=True, exclude_unset=True, exclude={"id"})
    if isinstance(step, WaitStep):
        spec = given.pop("wait")
        given |= spec
    renamed = _NODE_KEYS.get(step.kind, {})
    return {"type": _NODE_TYPES[step.kind]} | {
        renamed.get(key, key): value for key, value in given.items()
    }


def _unique_problems(problems: Iterable[WorkflowProblem]) -> list[WorkflowProblem]:
    return list(dict.fromkeys(problems))
