"""A scenario in the tree format, version 2 (docs/design/scenarios.md § Tree format, ADR 0049).

A ``kind: scenario`` document with ``version: 2`` holds named ``stages`` in place of ``nodes``,
each an ordered list of steps. A step holds exactly one kind key: a leaf (``do``,
``wait_until``, ``you``, ``wait``, ``include``) becomes one node; a container (``repeat``,
``if`` with ``then`` and ``else``, ``together``) holds step lists of its own. Position is order,
so ``nodes``, ``depends_on`` and ``trigger_rule`` are refused with a reason.

``parse_tree`` returns the frozen model, or raises ``WorkflowLoadError`` naming each problem at
the tree's key path (``stages[2].steps[1].until``). The rules across blocks (slugs, ids, where an
If without else may stand, nesting) and the rules a node's own model holds (a wait's one
condition, unique decisions) are ``tree_translate``'s, which reports them on the same paths.
"""

from abc import abstractmethod
from collections.abc import Mapping
from typing import Annotated, ClassVar, Final, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    Discriminator,
    Field,
    JsonValue,
    StrictBool,
    StrictInt,
    Tag,
    ValidationError,
)

from agent_hub.core.workflows.conditions import ConditionParseError, parse_condition
from agent_hub.core.workflows.document import (
    UNKNOWN_KEY,
    Loc,
    WorkflowInput,
    WorkflowLoadError,
    WorkflowProblem,
    is_tree,
    load_error,
)
from agent_hub.core.workflows.nodes import (
    READ_ONLY,
    ActionRef,
    ActionTimeout,
    Decision,
    Duration,
    ExpectEvery,
    ExpectTimeout,
    KebabId,
    NodeId,
    Retry,
    Text,
    VariableName,
    WholeRef,
    WorkflowObject,
    empty,
)

type StepKind = Literal["do", "wait_until", "you", "wait", "include", "repeat", "if", "together"]

STEP_KINDS: Final[tuple[StepKind, ...]] = (
    "do",
    "wait_until",
    "you",
    "wait",
    "include",
    "repeat",
    "if",
    "together",
)
MAX_STAGES: Final = 64
# At the same time: two paths at least.
MIN_PATHS: Final = 2
# An If's condition: its else is its complement, expanded to the grammar's or-of-ands form,
# and translation writes both on every entry node of a branch, so both its atoms and its
# characters are bounded.
MAX_CONDITION_ATOMS: Final = 8
MAX_CONDITION_CHARS: Final = 1024
_STEP_KIND_MESSAGE: Final = "a step holds exactly one of " + ", ".join(STEP_KINDS)
# Why a graph key has no place in a tree, by the key a document gave.
_GRAPH_KEYS: Final = {
    "nodes": "a version-2 scenario holds stages, not nodes (version 1 is the graph format)",
    "depends_on": "a version-2 scenario has no depends_on: a block runs after the one before it",
    "trigger_rule": (
        "a version-2 scenario has no trigger_rule: the block after an If or a Together joins"
        " by its place"
    ),
}
# The keys whose items are stages or steps.
_BLOCK_LISTS: Final = frozenset({"stages", "steps", "then", "else"})
_NOT_A_TREE: Final = "must be 2, a scenario's tree format"
_NOT_A_SCENARIO: Final = (
    "version 2 is a scenario's tree format: set kind: scenario, or write version 1"
)


def _steps_not_empty[Item](items: tuple[Item, ...]) -> tuple[Item, ...]:
    if not items:
        msg = "must hold at least one step"
        raise ValueError(msg)
    return items


def _two_paths[Item](items: tuple[Item, ...]) -> tuple[Item, ...]:
    if len(items) < MIN_PATHS:
        msg = f"must hold at least {MIN_PATHS} paths"
        raise ValueError(msg)
    return items


def _stage_count[Item](items: tuple[Item, ...]) -> tuple[Item, ...]:
    if not items:
        msg = "must hold at least one stage"
        raise ValueError(msg)
    if len(items) > MAX_STAGES:
        msg = f"must hold at most {MAX_STAGES} stages"
        raise ValueError(msg)
    return items


def _condition(value: str) -> str:
    if len(value) > MAX_CONDITION_CHARS:
        msg = (
            f"holds {len(value):,} characters: an If's condition holds at most"
            f" {MAX_CONDITION_CHARS:,} characters, as translation writes it on each branch's"
            " entry nodes"
        )
        raise ValueError(msg)
    try:
        condition = parse_condition(value, scenario=True)
    except ConditionParseError as error:
        raise ValueError(str(error)) from None
    atoms = sum(len(clause) for clause in condition.clauses)
    if atoms > MAX_CONDITION_ATOMS:
        msg = (
            f"holds {atoms} atoms: an If's condition holds at most {MAX_CONDITION_ATOMS} atoms,"
            " so its else stays small"
        )
        raise ValueError(msg)
    return value


# An If's condition as written; checked here, parsed again by translation.
IfCondition = Annotated[Text, AfterValidator(_condition)]
Values = Annotated[Mapping[VariableName, JsonValue], *READ_ONLY]
Captures = Annotated[Mapping[VariableName, WholeRef], *READ_ONLY]


class _Block(WorkflowObject):
    """A step of a list; ``kind`` is its kind key."""

    kind: ClassVar[StepKind]
    description: Text | None = None

    @property
    def label(self) -> str:
        """What a person reads for the block: its description, else its kind's main value."""
        return self.description or self._value()

    @abstractmethod
    def _value(self) -> str: ...


class _NodeBlock(_Block):
    """A block that becomes one node; without ``id`` it gets one from its address."""

    id: NodeId | None = None


class DoStep(_NodeBlock):
    """``do: <action>``: an ``action`` node."""

    kind: ClassVar[StepKind] = "do"
    do: ActionRef
    with_: Values = Field(default_factory=empty, alias="with")
    capture: Captures = Field(default_factory=empty)
    retry: Retry | None = None
    timeout: ActionTimeout | None = None

    def _value(self) -> str:
        return self.do


class WaitUntilStep(_NodeBlock):
    """``wait_until: <read action>``, polled every ``every`` until ``until``: an ``expect``."""

    kind: ClassVar[StepKind] = "wait_until"
    wait_until: ActionRef
    with_: Values = Field(default_factory=empty, alias="with")
    until: Text
    every: ExpectEvery
    timeout: ExpectTimeout
    capture: Captures = Field(default_factory=empty)
    retry: Retry | None = None

    def _value(self) -> str:
        return self.wait_until


class YouStep(_NodeBlock):
    """``you: <message>``: an ``approval`` a person answers."""

    kind: ClassVar[StepKind] = "you"
    you: Text
    decisions: Annotated[tuple[Decision, ...], Field(min_length=1)] | None = None
    capture_response: StrictBool = False

    def _value(self) -> str:
        return self.you


class WaitSpec(WorkflowObject):
    """A ``wait``'s condition; the ``wait`` node's model holds its rules."""

    duration: Duration | None = None
    until: Text | None = None
    attention: Text | None = None
    options: Annotated[tuple[Decision, ...], Field(min_length=1)] | None = None


class WaitStep(_NodeBlock):
    """``wait: {duration | until | attention}``: a ``wait`` node."""

    kind: ClassVar[StepKind] = "wait"
    wait: WaitSpec

    def _value(self) -> str:
        spec = self.wait
        return spec.duration or spec.until or spec.attention or "wait"


class IncludeStep(_NodeBlock):
    """``include: <scenario>`` with ``with``: an ``include`` node, one block."""

    kind: ClassVar[StepKind] = "include"
    include: KebabId
    with_: Values = Field(default_factory=empty, alias="with")

    def _value(self) -> str:
        return self.include


class RepeatSpec(WorkflowObject):
    """A Repeat's body, run until ``until`` holds, at most ``max`` times."""

    max: Annotated[StrictInt, Field(ge=1, le=50)]
    until: Text
    steps: Annotated[tuple[Step, ...], AfterValidator(_steps_not_empty)]


class RepeatStep(_NodeBlock):
    """``repeat: {max, until, steps}``: a ``loop_group`` whose body is its steps."""

    kind: ClassVar[StepKind] = "repeat"
    repeat: RepeatSpec

    def _value(self) -> str:
        return self.repeat.until


class IfStep(_Block):
    """``if: <condition>`` with ``then`` and an optional ``else``: no node of its own."""

    kind: ClassVar[StepKind] = "if"
    if_: IfCondition = Field(alias="if")
    then: Annotated[tuple[Step, ...], AfterValidator(_steps_not_empty)]
    else_: Annotated[tuple[Step, ...], AfterValidator(_steps_not_empty)] | None = Field(
        default=None, alias="else"
    )

    def _value(self) -> str:
        return self.if_


class TogetherStep(_Block):
    """``together: [[...], [...]]``: paths that start together; the next block waits for all."""

    kind: ClassVar[StepKind] = "together"
    together: Annotated[
        tuple[Annotated[tuple[Step, ...], AfterValidator(_steps_not_empty)], ...],
        AfterValidator(_two_paths),
    ]

    def _value(self) -> str:
        return f"{len(self.together)} paths"


_STEP_CLASSES: Final[tuple[type[_Block], ...]] = (
    DoStep,
    WaitUntilStep,
    YouStep,
    WaitStep,
    IncludeStep,
    RepeatStep,
    IfStep,
    TogetherStep,
)


def _step_kind(value: object) -> str | None:
    """The tag of the step ``value`` holds: its one kind key's (a model's, once validated)."""
    if isinstance(value, _Block):
        return f"<{value.kind}>"
    if not isinstance(value, dict):
        return None
    found = [kind for kind in STEP_KINDS if kind in value]
    return f"<{found[0]}>" if len(found) == 1 else None


# Tagged by the kind key it holds: one error per wrong step, not one per kind. The tags are no
# keys of a document, so error paths drop them.
type Step = Annotated[
    Annotated[DoStep, Tag("<do>")]
    | Annotated[WaitUntilStep, Tag("<wait_until>")]
    | Annotated[YouStep, Tag("<you>")]
    | Annotated[WaitStep, Tag("<wait>")]
    | Annotated[IncludeStep, Tag("<include>")]
    | Annotated[RepeatStep, Tag("<repeat>")]
    | Annotated[IfStep, Tag("<if>")]
    | Annotated[TogetherStep, Tag("<together>")],
    Discriminator(
        _step_kind, custom_error_type="step_kind", custom_error_message=_STEP_KIND_MESSAGE
    ),
]


class Stage(WorkflowObject):
    """A named stage: its steps run in order, after the stage before it."""

    name: Text
    description: Text | None = None
    steps: Annotated[tuple[Step, ...], AfterValidator(_steps_not_empty)]


class TreeDocument(WorkflowObject):
    """A version-2 scenario: its header, as a version-1 document's, and its stages."""

    version: Literal[2]
    kind: Literal["scenario"]
    name: KebabId
    description: Text | None = None
    revision: Annotated[StrictInt, Field(ge=1)]
    inputs: Annotated[Mapping[VariableName, WorkflowInput], *READ_ONLY] = Field(
        default_factory=empty
    )
    stages: Annotated[tuple[Stage, ...], AfterValidator(_stage_count)]


def _rebuild(models: tuple[type[BaseModel], ...]) -> None:
    for model in models:
        model.model_rebuild()


_rebuild((*_STEP_CLASSES, RepeatSpec, Stage, TreeDocument))


def parse_tree(content: object) -> TreeDocument:
    """The tree ``content`` holds; raises ``WorkflowLoadError`` naming every problem."""
    if isinstance(content, dict) and not is_tree(content):
        raise WorkflowLoadError([WorkflowProblem(("version",), _NOT_A_TREE)])
    if isinstance(content, dict) and content.get("kind", "workflow") == "workflow":
        raise WorkflowLoadError([WorkflowProblem(("version",), _NOT_A_SCENARIO)])
    try:
        return TreeDocument.model_validate(content)
    except ValidationError as error:
        problems = load_error(error, content).problems
    raise WorkflowLoadError([_explained(problem) for problem in problems])


def _explained(problem: WorkflowProblem) -> WorkflowProblem:
    """``problem``, a graph key's refusal saying why: ``nodes`` on the document, ``depends_on``
    and ``trigger_rule`` on a stage or a step (anywhere else they are only unknown keys)."""
    loc = problem.loc
    if problem.message != UNKNOWN_KEY or not loc or not isinstance(loc[-1], str):
        return problem
    reason = _GRAPH_KEYS.get(loc[-1])
    where = len(loc) == 1 if loc[-1] == "nodes" else _of_a_block(loc[:-1])
    return problem if reason is None or not where else WorkflowProblem(loc, reason)


def _of_a_block(loc: Loc) -> bool:
    """Whether ``loc`` is a stage's or a step's: an item of ``stages``, of a step list
    (``steps``, ``then``, ``else``) or of a Together's path."""
    if len(loc) < 2 or not isinstance(loc[-1], int):
        return False
    owner = loc[-2]
    if isinstance(owner, int):
        return len(loc) > 2 and loc[-3] == "together"
    return owner in _BLOCK_LISTS
