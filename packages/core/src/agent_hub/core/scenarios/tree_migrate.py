"""A graph scenario (version 1) written as a tree (version 2), for ``hub scenario migrate``
(docs/design/scenarios.md § Tree format, ADR 0049).

``migrate_graph`` takes a version-1 scenario, its document or the mapping a loader read, and
returns the version-2 mapping whose translation (``tree_translate``) is the same graph: the same
nodes, edges and conditions. The header is kept (revision included); the steps are one stage
named after the scenario (``scenario <name>`` when the name starts with a digit: a stage slug
starts with a letter), and each node keeps its id as ``id:`` where it differs from the one its
block's address derives. It is pure: the canonical text is the generator's writer's.

The graph is read by the translation's rules run the other way, one step list at a time (the
stage's steps, then each branch, path and Repeat body):

- The next block of a list starts at its entry nodes, those that depend on none of the list's
  nodes still to read; its nodes are the ones not every entry reaches. One entry is a Do, Wait
  until, You, Wait or Include (a ``loop_group`` a Repeat, its body read as a list of its own),
  or, with a ``when``, an If with no else whose branch is what only that node leads to. Several
  entries each with a ``when``, two texts, one the exact complement of the other, are an If
  with an else; otherwise they start a Together, one path per group of entries whose nodes meet
  before the block after it.
- Each node depends on exactly the exit nodes of the block before it in its list (a list's
  first block on what its container depends on), and takes ``none_failed_min_one_success``
  when that block is an If, or a Together a path of which ends with one, else ``all_success``.

What a tree cannot hold is refused (``MigrationError``), naming each node and why: another
``trigger_rule``, a ``loop_group`` with ``until_bash`` or ``fresh_context``, ``returns`` or
``outcome_field`` (a tree has neither: an include reads an included tree's output from its
single last node), a node that breaks those dependency rules (the graph is not
series-parallel), and a ``when`` no If gives: on a node that opens a list, two that are no
condition and its complement, and the conditions of nested Ifs joined on one node, which are
not split. A node's own keys are all checked. A graph past ``MAX_TREE_NODES`` (a Repeat's steps
included) is not read; else reading stops at the first block whose shape breaks (a node whose
edges or rule are not its place's included), and at the first If, Together or Repeat that would
nest past ``MAX_DEPTH``, reading nothing inside it. A block refuses its first ``MAX_NAMED``
entries in full and the rest in one problem, and a problem names ``MAX_NAMED`` nodes at most,
so the work and the problems stay bounded whatever the graph holds. The mapping found is
translated back and compared, node for node and key for key of the header, so a tree that would
not load (past another cap), or would give another graph, is refused too; so is one whose
written text (``read_back``) would read back as another graph.
"""

import contextlib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, NamedTuple

from agent_hub.core.errors import AgentHubError
from agent_hub.core.json_form import JsonValue
from agent_hub.core.scenarios.tree_document import MAX_CONDITION_ATOMS, MAX_CONDITION_CHARS
from agent_hub.core.scenarios.tree_translate import (
    JOIN_RULE,
    MAX_DEPTH,
    MAX_TREE_NODES,
    complement,
    condition_text,
    stage_slug,
    translate_tree,
)
from agent_hub.core.workflows.conditions import ConditionParseError, parse_condition
from agent_hub.core.workflows.document import (
    Loc,
    WorkflowDocument,
    WorkflowLoadError,
    WorkflowProblem,
    is_tree,
    kind_problems,
    parse_workflow,
)
from agent_hub.core.workflows.nodes import (
    ActionNode,
    ApprovalNode,
    ExpectNode,
    IncludeNode,
    LoopGroupNode,
    Node,
    WaitNode,
)
from agent_hub.core.workflows.substitution import echo

ALL_SUCCESS: Final = "all_success"
# The nodes one problem names, and the entries of a block refused one problem each, at most.
MAX_NAMED: Final = 10
ALREADY_A_TREE: Final = "version: it is already written as blocks (version 2)"
_NOT_A_SCENARIO: Final = "kind: only a scenario has a tree format"
_RETURNS: Final = (
    "returns: the tree format has no returns (an include reads an included tree's output from"
    " its single last node)"
)
_OUTCOME_FIELD: Final = "outcome_field: the tree format has no outcome_field"
_UNTIL_BASH: Final = "has until_bash: a Repeat ends only on its until condition"
_FRESH_CONTEXT: Final = "has fresh_context: a Repeat has no fresh_context"
_OPENS: Final = (
    "has a when, which a tree writes as an If with no else, and such an If cannot open a step"
    " list (the scenario's start, a branch, a path or a Repeat body)"
)
_STARTS_TOGETHER: Final = (
    "starts together with {others}, each with a when of its own: migrate reads nodes that start"
    " together with a when only as an If with an else (a condition, and its exact complement on"
    " the else's first block), and does not split the conditions of nested Ifs joined on one node"
)
_BRANCHES_MEET: Final = (
    "starts a branch that meets the other branch before the block after the If: the graph is"
    " not series-parallel"
)
_PATHS_MEET: Final = (
    "starts together with {others}, but their paths meet before the block after them: the graph"
    " is not series-parallel"
)
_JOIN_WITHOUT_IF: Final = (
    "has trigger_rule none_failed_min_one_success, which a tree gives only to the block after an"
    " If (or after a Together a path of which ends with one)"
)
_CYCLE: Final = "depends on a node that depends on it: the graph has a cycle"
_SAME: Final = "has the same problem as the node before it"
# The keys of a node a block writes by its place, not by itself.
_PLACED: Final = frozenset({"id", "type", "depends_on", "when", "trigger_rule", "nodes"})


class MigrationProblem(NamedTuple):
    """A node a tree cannot hold, and why; ``node`` is ``None`` for the document's own key,
    which ``message`` names."""

    node: str | None
    message: str

    def __str__(self) -> str:
        return self.message if self.node is None else f"node {echo(self.node)}: {self.message}"


class _Says(NamedTuple):
    """How a tree found is refused when it is not the graph: it does not load, a header key
    has another value, a node is another."""

    load: str
    value: str
    node: str


_TRANSLATED: Final = _Says(
    "as a block it would not load",
    "as blocks it would translate to another value",
    "as a block it would translate to another node",
)
_READ_BACK: Final = _Says(
    "as written it would not load",
    "as written it would read back as another value: the YAML text does not keep it as it is",
    "as written it would read back as another node: the YAML text does not keep one of its"
    " values as it is",
)


class MigrationError(AgentHubError):
    """A graph scenario that cannot be written as a tree; ``problems`` names each node."""

    def __init__(self, problems: Sequence[MigrationProblem]) -> None:
        self.problems = tuple(problems)
        super().__init__("; ".join(str(problem) for problem in self.problems))


def migrate_graph(
    scenario: WorkflowDocument | object,
    *,
    read_back: Callable[[dict[str, JsonValue]], object] | None = None,
) -> dict[str, JsonValue]:
    """The tree that translates to the graph of ``scenario`` (a document, or the mapping a
    loader read: a ``WorkflowLoadError`` when it does not load, as ``parse_workflow`` gives);
    raises ``MigrationError`` naming each node a tree cannot hold. ``read_back``, when given,
    is the mapping the tree's written text loads back to (an error it raises goes through);
    that mapping must translate to the same graph too."""
    if not isinstance(scenario, WorkflowDocument):
        if is_tree(scenario):
            raise MigrationError([MigrationProblem(None, ALREADY_A_TREE)])
        scenario = parse_workflow(scenario)
    elif problems := list(kind_problems(scenario)):
        raise WorkflowLoadError(problems)
    if scenario.kind != "scenario":
        raise MigrationError([MigrationProblem(None, _NOT_A_SCENARIO)])
    return _Migrator(scenario).migrate(read_back)


def stage_name(scenario: str) -> str:
    """The name of the one stage a migrated scenario gets: its own, or ``scenario <name>`` when
    that starts with a digit."""
    return scenario if scenario[:1].isalpha() else f"scenario {scenario}"


@dataclass
class _Level:
    """The nodes of one graph level (the document's, or a ``loop_group``'s body): by id, in
    declaration order, each node's dependents, and the entry nodes whose ``when`` an If took."""

    nodes: Mapping[str, Node]
    order: Mapping[str, int]
    dependents: Mapping[str, frozenset[str]]
    taken: set[str] = field(default_factory=set)
    rule_refused: set[str] = field(default_factory=set)

    @classmethod
    def of(cls, nodes: Sequence[Node]) -> _Level:
        dependents: dict[str, set[str]] = {node.id: set() for node in nodes}
        for node in nodes:
            for target in node.depends_on:
                if target in dependents:
                    dependents[target].add(node.id)
        return cls(
            {node.id: node for node in nodes},
            {node.id: index for index, node in enumerate(nodes)},
            {node_id: frozenset(found) for node_id, found in dependents.items()},
        )

    def ordered(self, ids: Iterable[str]) -> list[str]:
        return sorted(ids, key=self.order.__getitem__)

    def when(self, node_id: str) -> str | None:
        """The node's ``when``, unless an If around it took it."""
        return None if node_id in self.taken else self.nodes[node_id].when

    def reach(self, starts: Iterable[str], within: set[str]) -> set[str]:
        """``starts`` and every node that depends on one of them, transitively, in ``within``."""
        seen: set[str] = set()
        pending = [node_id for node_id in starts if node_id in within]
        while pending:
            node_id = pending.pop()
            if node_id not in seen:
                seen.add(node_id)
                pending.extend(self.dependents[node_id] & within)
        return seen


@dataclass(frozen=True)
class _Place:
    """Where a block stands: what its entry nodes depend on, whether they take the join rule,
    its address in the stage, its tree key path and the containers around it."""

    before: tuple[str, ...]
    join: bool
    address: str
    key: Loc
    depth: int

    def inner(self, head: str, key: Loc) -> _List:
        """A step list of the container at this place: ``head`` after its address, ``key``
        after its key path."""
        return _List(f"{self.address}.{head}", (*self.key, *key), self.depth + 1)


@dataclass(frozen=True)
class _List:
    """A step list: the addresses of its blocks (``<head><n>``), its key path and the
    containers around it."""

    head: str
    key: Loc
    depth: int = 0

    def at(self, index: int, before: tuple[str, ...], *, join: bool) -> _Place:
        """The place of block ``index`` (from 0), after ``before``."""
        return _Place(before, join, f"{self.head}{index + 1}", (*self.key, index), self.depth)


_STAGE_STEPS: Final = _List("", ("stages", 0, "steps"))


@dataclass(frozen=True)
class _Block:
    """A block read: its step, the nodes it holds, its exit nodes and whether a run may skip
    some of them."""

    step: dict[str, JsonValue]
    nodes: frozenset[str]
    exits: tuple[str, ...]
    branching: bool = False


@dataclass(frozen=True)
class _Group:
    """Entry nodes whose nodes meet before the block after theirs, and those nodes."""

    entries: tuple[str, ...]
    nodes: frozenset[str]


class _StopError(Exception):
    """A block whose shape breaks: its problems are recorded, the graph is read no further."""


class _StandingError(_StopError):
    """A stop whose problem stands though a Together tried around it is dropped: a node whose
    edges or rule are not its place's, or a container past ``MAX_DEPTH``."""


@dataclass
class _Migrator:
    document: WorkflowDocument
    problems: list[MigrationProblem] = field(default_factory=list)
    # Each block's tree key path, and the node a problem there is named by.
    keys: dict[Loc, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.top = _Level.of(self.document.nodes)
        self.bodies = {
            node.id: _Level.of(node.nodes)
            for node in self.document.nodes
            if isinstance(node, LoopGroupNode)
        }
        self.slug = stage_slug(stage_name(self.document.name))

    def migrate(
        self, read_back: Callable[[dict[str, JsonValue]], object] | None
    ) -> dict[str, JsonValue]:
        self._own_keys()
        steps: list[JsonValue] = []
        if self._fits():
            with contextlib.suppress(_StopError):
                top = self.top
                read = self._read(top, set(top.nodes), within=_STAGE_STEPS, before=(), join=False)
                steps = read[0]
        if self.problems:
            raise MigrationError(self.problems)
        tree = self._tree(steps)
        self._check(tree, _TRANSLATED)
        if read_back is not None:
            self._check(read_back(tree), _READ_BACK)
        return tree

    def _refuse(self, node: str | None, message: str) -> None:
        self.problems.append(MigrationProblem(node, message))

    def _refuse_each(self, nodes: Sequence[str], message: Callable[[str], str]) -> None:
        """Refuses each of ``nodes`` for one reason (``message`` gives it for a node): the first
        ``MAX_NAMED`` in full, those after them in one problem, on the first of them."""
        for node_id in nodes[:MAX_NAMED]:
            self._refuse(node_id, message(node_id))
        rest = nodes[MAX_NAMED:]
        if rest:
            same, after = _SAME, len(rest) - 1
            if after == 1:
                same += ", as does 1 more node after it"
            elif after:
                same += f", as do {after:,} more nodes after it"
            self._refuse(rest[0], same)

    def _fits(self) -> bool:
        """Whether the graph's nodes, a Repeat's steps included, fit in a tree; else refuses
        the graph, which is not read."""
        count = len(self.top.nodes) + sum(len(body.nodes) for body in self.bodies.values())
        if count > MAX_TREE_NODES:
            message = (
                f"nodes: the graph holds {count:,} nodes, a Repeat's steps included, and a tree"
                f" holds at most {MAX_TREE_NODES}"
            )
            self._refuse(None, message)
        return count <= MAX_TREE_NODES

    def _own_keys(self) -> None:
        """Every key a tree has no place for, on the document and on each node."""
        if self.document.returns is not None:
            self._refuse(None, _RETURNS)
        if self.document.outcome_field is not None:
            self._refuse(None, _OUTCOME_FIELD)
        for level in (self.top, *self.bodies.values()):
            for node in level.nodes.values():
                self._node_keys(level, node)

    def _node_keys(self, level: _Level, node: Node) -> None:
        if node.trigger_rule not in (ALL_SUCCESS, JOIN_RULE):
            level.rule_refused.add(node.id)
            message = (
                f"has trigger_rule {node.trigger_rule}: a tree joins with all_success, or with"
                f" {JOIN_RULE} after an If; no block gives {node.trigger_rule}"
            )
            self._refuse(node.id, message)
        if isinstance(node, LoopGroupNode):
            if node.until_bash is not None:
                self._refuse(node.id, _UNTIL_BASH)
            if node.fresh_context:
                self._refuse(node.id, _FRESH_CONTEXT)

    def _read(
        self,
        level: _Level,
        members: set[str],
        *,
        within: _List,
        before: tuple[str, ...],
        join: bool,
    ) -> tuple[list[JsonValue], _Block]:
        """The steps of the list ``within``, read from ``members``, its first block after
        ``before`` (taking the join rule when ``join``); and its last block."""
        remaining = set(members)
        # Each node's dependencies still to read; those with none are the next block's entries.
        waiting = {n: len(remaining.intersection(level.nodes[n].depends_on)) for n in remaining}
        ready = {node_id for node_id, count in waiting.items() if not count}
        steps: list[JsonValue] = []
        last = _Block({}, frozenset(), before, branching=join)
        while remaining:
            if not ready:
                self._refuse_each(level.ordered(remaining), lambda _: _CYCLE)
                raise _StopError
            at = within.at(len(steps), last.exits, join=last.branching)
            entries = level.ordered(ready)
            last = self._block(level, remaining, entries=entries, at=at, opening=not steps)
            steps.append(last.step)
            remaining -= last.nodes
            ready -= last.nodes
            for node_id in last.nodes:
                for dependent in level.dependents[node_id] & remaining:
                    waiting[dependent] -= 1
                    if not waiting[dependent]:
                        ready.add(dependent)
        return steps, last

    def _block(
        self, level: _Level, remaining: set[str], *, entries: list[str], at: _Place, opening: bool
    ) -> _Block:
        whens = {entry: level.when(entry) for entry in entries}
        if len(entries) == 1:
            (entry,) = entries
            when = whens[entry]
            if when is None:
                return self._leaf(level, entry, at)
            return self._if_alone(
                level, remaining, entries=entries, when=when, at=at, opening=opening
            )
        reached = {entry: level.reach([entry], remaining) for entry in entries}
        common = set.intersection(*reached.values())
        held = remaining - common
        groups = _groups(entries, reached, held)
        if None in whens.values():
            return self._together(level, _paths(level, groups), at=at, held=held)
        texts = list(dict.fromkeys(level.when(entry) or "" for entry in entries))
        if len(texts) == 1:
            return self._if_alone(
                level, remaining, entries=entries, when=texts[0], at=at, opening=opening
            )
        return self._conditioned(level, groups, entries=entries, at=at, held=held)

    def _leaf(self, level: _Level, node_id: str, at: _Place) -> _Block:
        node = level.nodes[node_id]
        self._placed(level, node, at)
        self.keys[at.key] = node_id
        steps: list[JsonValue] = []
        if isinstance(node, LoopGroupNode):
            self._nest(at, "repeat")
            body = self.bodies[node.id]
            within = at.inner("", ("repeat", "steps"))
            steps = self._read(body, set(body.nodes), within=within, before=(), join=False)[0]
        step = _step(node, derived=self._derived(at.address), body=steps)
        return _Block(step, frozenset({node_id}), (node_id,))

    def _placed(self, level: _Level, node: Node, at: _Place) -> None:
        """Refuses ``node`` where its edges or its rule are not those its place gives, and
        stops the reading there."""
        mark = len(self.problems)
        if set(node.depends_on) != set(at.before):
            where = (
                f"a block there depends on the ends of the block before it, {_names(at.before)}"
                if at.before
                else "it opens its step list, so a block there depends on nothing"
            )
            message = (
                f"depends on {_names(node.depends_on)}, but {where}: the graph is not"
                " series-parallel"
            )
            self._refuse(node.id, message)
        rule = JOIN_RULE if at.join else ALL_SUCCESS
        if node.trigger_rule != rule and node.id not in level.rule_refused:
            if at.join:
                message = (
                    "follows an If (or a Together a path of which ends with one), so a tree gives"
                    f" it trigger_rule {JOIN_RULE}, not {node.trigger_rule}"
                )
                self._refuse(node.id, message)
            else:
                self._refuse(node.id, _JOIN_WITHOUT_IF)
        if len(self.problems) > mark:
            raise _StandingError

    def _if_alone(
        self,
        level: _Level,
        remaining: set[str],
        *,
        entries: list[str],
        when: str,
        at: _Place,
        opening: bool,
    ) -> _Block:
        """Entries that each hold ``when``: an If with no else, whose branch is what only the
        entries lead to, before the nodes that also follow the block before it."""
        problem = _OPENS if opening else _if_problem(when)
        if problem is not None:
            self._refuse_each(entries, lambda _: problem)
            raise _StopError
        before = set(at.before)
        others = [
            node_id
            for node_id in remaining
            if node_id not in entries and before.intersection(level.nodes[node_id].depends_on)
        ]
        branch = remaining - level.reach(others, remaining.difference(entries))
        level.taken.update(entries)
        self.keys[at.key] = entries[0]
        self._nest(at, "if")
        steps, end = self._read(
            level, branch, within=self._branch(at, "then"), before=at.before, join=at.join
        )
        exits = tuple(dict.fromkeys((*end.exits, *at.before)))
        return _Block({"if": when, "then": steps}, frozenset(branch), exits, branching=True)

    def _conditioned(
        self, level: _Level, groups: list[_Group], *, entries: list[str], at: _Place, held: set[str]
    ) -> _Block:
        """Entries that each hold a ``when``: an If with an else (a condition and its exact
        complement, each group of entries holding one of the two), else a Together whose paths
        each open with one."""
        texts = list(dict.fromkeys(level.when(entry) or "" for entry in entries))
        condition = _condition_of(texts)
        pure = all(_text_of(level, group) is not None for group in groups)
        if condition is not None and pure:
            return self._if_else(level, groups, condition=condition, at=at, held=held)
        paths = _paths(level, groups)
        if len(paths) > 1:
            # Read as a Together, which may not hold; then what it read is undone. A node out of
            # its place, or a container past the nesting cap, ends the reading all the same, so
            # that refusal stands.
            mark, taken, keys = len(self.problems), set(level.taken), dict(self.keys)
            try:
                return self._together(level, paths, at=at, held=held)
            except _StandingError:
                raise
            except _StopError:
                del self.problems[mark:]
                level.taken, self.keys = taken, keys
        self._refuse_start(level, groups, texts, branches=condition is not None)
        raise _StopError

    def _refuse_start(
        self, level: _Level, groups: list[_Group], texts: list[str], *, branches: bool
    ) -> None:
        """Refuses entries that each hold a ``when`` and are no If with an else."""
        entries = level.ordered(entry for group in groups for entry in group.entries)
        if branches:
            # The entries of a group holding both texts: there the two branches meet.
            meet = {n for group in groups if _text_of(level, group) is None for n in group.entries}
            meeting = [entry for entry in entries if entry in meet]
            self._refuse_each(meeting, lambda _: _BRANCHES_MEET)
        elif len(texts) == 2:  # noqa: PLR2004 -- a condition and another
            first, second = texts
            first_entry = next(entry for entry in entries if level.when(entry) == first)
            second_entry = next(entry for entry in entries if level.when(entry) == second)
            problem = _if_problem(first)
            if problem is not None:
                self._refuse(first_entry, problem)
            else:
                message = (
                    f"its when is not the exact complement of the when of {echo(first_entry)},"
                    f" so the two are no If with an else: the else of {first} is"
                    f" {_else_of(first)}"
                )
                self._refuse(second_entry, message)
        else:
            self._refuse_each(
                entries, lambda entry: _STARTS_TOGETHER.format(others=_others(entry, entries))
            )

    def _if_else(
        self, level: _Level, groups: list[_Group], *, condition: str, at: _Place, held: set[str]
    ) -> _Block:
        """An If on ``condition`` whose then is the groups holding it, its else the others."""
        then = {n for group in groups if _text_of(level, group) == condition for n in group.nodes}
        otherwise = held - then
        entries = level.ordered(entry for group in groups for entry in group.entries)
        level.taken.update(entries)
        self.keys[at.key] = entries[0]
        self._nest(at, "if")
        then_steps, then_end = self._read(
            level, then, within=self._branch(at, "then"), before=at.before, join=at.join
        )
        else_steps, else_end = self._read(
            level, otherwise, within=self._branch(at, "else"), before=at.before, join=at.join
        )
        step: dict[str, JsonValue] = {"if": condition, "then": then_steps, "else": else_steps}
        exits = tuple(dict.fromkeys((*then_end.exits, *else_end.exits)))
        return _Block(step, frozenset(held), exits, branching=True)

    def _together(
        self, level: _Level, groups: list[_Group], *, at: _Place, held: set[str]
    ) -> _Block:
        """A Together, one path per group; paths that all meet before the block after them are
        none."""
        if len(groups) < 2:  # noqa: PLR2004 -- a Together holds two paths at least
            entries = groups[0].entries
            self._refuse_each(
                entries, lambda entry: _PATHS_MEET.format(others=_others(entry, entries))
            )
            raise _StopError
        paths: list[JsonValue] = []
        exits: list[str] = []
        branching = False
        self.keys[at.key] = groups[0].entries[0]
        self._nest(at, "together")
        for number, group in enumerate(groups, start=1):
            path = at.inner(f"p{number}.", ("together", number - 1))
            steps, end = self._read(
                level, set(group.nodes), within=path, before=at.before, join=at.join
            )
            paths.append(steps)
            exits.extend(end.exits)
            branching = branching or end.branching
        return _Block({"together": paths}, frozenset(held), tuple(dict.fromkeys(exits)), branching)

    @staticmethod
    def _branch(at: _Place, branch: str) -> _List:
        return at.inner(f"{branch}.", (branch,))

    def _nest(self, at: _Place, kind: str) -> None:
        """Refuses the container ``kind`` at ``at`` when it would nest past ``MAX_DEPTH``, on the
        node ``keys`` holds there, as translating the tree would; nothing inside it is read."""
        if at.depth >= MAX_DEPTH:
            problem = WorkflowProblem((*at.key, kind), f"containers nest at most {MAX_DEPTH} deep")
            self.problems.append(self._located(problem, _TRANSLATED.load))
            raise _StandingError

    def _derived(self, address: str) -> str:
        return f"{self.slug}--{address.replace('.', '-')}"

    def _tree(self, steps: list[JsonValue]) -> dict[str, JsonValue]:
        document = self.document
        tree: dict[str, JsonValue] = {
            "version": 2,
            "kind": "scenario",
            "name": document.name,
            "revision": document.revision,
        }
        if document.description is not None:
            tree["description"] = document.description
        if document.inputs:
            tree["inputs"] = {
                name: spec.model_dump(mode="json", exclude_unset=True)
                for name, spec in document.inputs.items()
            }
        tree["stages"] = [{"name": stage_name(document.name), "steps": steps}]
        return tree

    def _check(self, tree: object, says: _Says) -> None:
        """Refuses ``tree`` when it does not load or translates to another graph: a header key
        with another value, or another node."""
        try:
            translated = translate_tree(tree).document
        except WorkflowLoadError as error:
            located = [self._located(problem, says.load) for problem in error.problems]
            raise MigrationError(located) from None
        header = {"nodes", "version"}
        given_header = self.document.model_dump(mode="json", exclude=header)
        found_header = translated.model_dump(mode="json", exclude=header)
        for key, value in given_header.items():
            if found_header.get(key) != value:
                self._refuse(None, f"{key}: {says.value}")
        given = {node.id: _shape(node) for node in self.document.nodes}
        found = {node.id: _shape(node) for node in translated.nodes}
        ids = [*given, *(node_id for node_id in found if node_id not in given)]
        changed = [node_id for node_id in ids if given.get(node_id) != found.get(node_id)]
        self._refuse_each(changed, lambda _: says.node)
        if self.problems:
            raise MigrationError(self.problems)

    def _located(self, problem: WorkflowProblem, says: str) -> MigrationProblem:
        """A load problem of the tree found, on the node of the block it is at."""
        message = f"{says}: {problem.key}: {problem.message}"
        held = [key for key in self.keys if problem.loc[: len(key)] == key]
        if not held:
            return MigrationProblem(None, message)
        return MigrationProblem(self.keys[max(held, key=len)], message)


def _groups(entries: list[str], reached: Mapping[str, set[str]], held: set[str]) -> list[_Group]:
    """The entries whose nodes in ``held`` meet, grouped (in entry order), with those nodes."""
    parent = {entry: entry for entry in entries}
    index = {entry: position for position, entry in enumerate(entries)}

    def root(entry: str) -> str:
        while parent[entry] != entry:
            parent[entry] = parent[parent[entry]]
            entry = parent[entry]
        return entry

    owner: dict[str, str] = {}
    for entry in entries:
        for node_id in reached[entry] & held:
            if node_id in owner:
                first, second = root(owner[node_id]), root(entry)
                if first != second:
                    parent[max(first, second, key=index.__getitem__)] = min(
                        first, second, key=index.__getitem__
                    )
            else:
                owner[node_id] = entry
    grouped: dict[str, list[str]] = {}
    for entry in entries:
        grouped.setdefault(root(entry), []).append(entry)
    return [
        _Group(tuple(members), frozenset(n for m in members for n in reached[m] & held))
        for members in grouped.values()
    ]


def _text_of(level: _Level, group: _Group) -> str | None:
    """The ``when`` every entry of ``group`` holds, or ``None`` (none, or several)."""
    texts = {level.when(entry) for entry in group.entries}
    return texts.pop() if len(texts) == 1 else None


def _condition_of(texts: Sequence[str]) -> str | None:
    """The If's condition when ``texts`` are a condition and its exact complement."""
    if len(texts) != 2:  # noqa: PLR2004 -- a condition and its complement
        return None
    first, second = texts
    if _else_of(first) == second:
        return first
    return second if _else_of(second) == first else None


def _paths(level: _Level, groups: list[_Group]) -> list[_Group]:
    """The paths of a Together whose entry groups are ``groups``: a group holding a condition
    and one holding its exact complement are one path (an If with an else), one pair per path
    so no Together is added inside the If, a group left over joining the last pair of its
    condition's; every other group is a path of its own."""
    texts = [_text_of(level, group) for group in groups]
    buckets: dict[str, list[int]] = {}
    for index, text in enumerate(texts):
        if text is not None:
            buckets.setdefault(text, []).append(index)
    elses = {text: _else_of(text) for text in buckets}
    path_of = list(range(len(groups)))
    used: set[str] = set()
    for text, mine in buckets.items():
        partner = next(
            (
                other
                for other in buckets
                if other not in used | {text} and (elses[text] == other or elses[other] == text)
            ),
            None,
        )
        if text in used or partner is None:
            continue
        used |= {text, partner}
        theirs = buckets[partner]
        pairs = min(len(mine), len(theirs))
        for first, second in zip(mine, theirs, strict=False):
            path_of[first] = path_of[second] = min(first, second)
        last = min(mine[pairs - 1], theirs[pairs - 1])
        for left in (*mine[pairs:], *theirs[pairs:]):
            path_of[left] = last
    merged: dict[int, list[_Group]] = {}
    for index, group in enumerate(groups):
        merged.setdefault(path_of[index], []).append(group)
    return [
        _Group(
            tuple(entry for group in path for entry in group.entries),
            frozenset(node_id for group in path for node_id in group.nodes),
        )
        for _, path in sorted(merged.items())
    ]


def _if_problem(text: str) -> str | None:
    """Why ``text`` cannot be an If's condition, or ``None``."""
    if len(text) > MAX_CONDITION_CHARS:
        return (
            f"its when holds {len(text):,} characters: an If's condition holds at most"
            f" {MAX_CONDITION_CHARS:,}"
        )
    try:
        condition = parse_condition(text, scenario=True)
    except ConditionParseError as error:
        return f"its when cannot be an If's condition: {error}"
    atoms = sum(len(clause) for clause in condition.clauses)
    if atoms > MAX_CONDITION_ATOMS:
        return (
            f"its when holds {atoms} atoms: an If's condition holds at most {MAX_CONDITION_ATOMS}"
        )
    return None


def _else_of(text: str) -> str | None:
    """The condition translation writes on the else of an If on ``text``, or ``None`` when
    ``text`` cannot be an If's condition."""
    if _if_problem(text) is not None:
        return None
    return condition_text(complement(parse_condition(text, scenario=True)))


def _names(ids: Iterable[str]) -> str:
    """``ids`` quoted, the first ``MAX_NAMED`` of them, then how many more."""
    listed = list(ids)
    shown = ", ".join(echo(node_id) for node_id in listed[:MAX_NAMED])
    if len(listed) > MAX_NAMED:
        return f"{shown} and {len(listed) - MAX_NAMED:,} more"
    return shown or "nothing"


def _others(entry: str, entries: Sequence[str]) -> str:
    """The entries but ``entry``, named."""
    return _names(other for other in entries if other != entry)


def _step(node: Node, *, derived: str, body: list[JsonValue]) -> dict[str, JsonValue]:
    """The step ``node`` is (a Repeat's steps ``body``): its kind key, its id when it is not
    ``derived``, and the keys it was given as its block spells them."""
    given: dict[str, JsonValue] = node.model_dump(
        mode="json", by_alias=True, exclude_unset=True, exclude=set(_PLACED)
    )
    step: dict[str, JsonValue]
    if isinstance(node, ActionNode):
        step = {"do": given.pop("action")}
    elif isinstance(node, ExpectNode):
        step = {"wait_until": given.pop("action")}
        given["until"] = given.pop("until_when")
    elif isinstance(node, ApprovalNode):
        step = {"you": given.pop("message")}
    elif isinstance(node, IncludeNode):
        step = {"include": given.pop("include")}
    elif isinstance(node, LoopGroupNode):
        spec = {"max": given.pop("max_iterations"), "until": given.pop("until_when", None)}
        step = {"repeat": spec | {"steps": body}}
        given = {key: value for key, value in given.items() if key == "description"}
    elif isinstance(node, WaitNode):
        spec = {key: value for key, value in given.items() if key != "description"}
        step = {"wait": spec}
        given = {key: value for key, value in given.items() if key == "description"}
    else:
        # A type no block is: ``kind_problems`` refused it, so this step is never written.
        step = {}
    if node.id != derived:
        step["id"] = node.id
    return step | given


def _shape(node: Node) -> dict[str, JsonValue]:
    """``node`` as a graph holds it: every key, ``depends_on`` as a set, a body by id."""
    data: dict[str, JsonValue] = node.model_dump(mode="json", by_alias=True)
    depends_on: list[JsonValue] = [*sorted(node.depends_on)]
    data["depends_on"] = depends_on
    if isinstance(node, LoopGroupNode):
        data["nodes"] = {child.id: _shape(child) for child in node.nodes}
    return data
