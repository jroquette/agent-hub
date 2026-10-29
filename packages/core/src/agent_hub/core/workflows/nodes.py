"""The workflow nodes: one frozen model per ``type`` (docs/design/workflow-schema.md § Nodes).

Every model forbids unknown keys. An ``include`` is replaced at load by the nodes of the workflow
it names (``includes.py``), so the engine never sees one. A ``loop_group`` holds a body of nodes
repeated per iteration (no include or group inside). Checks that need more than one node
(``depends_on`` targets, references, ``context.resume``) are planning's (``plan.py``).
"""

import math
from collections.abc import Mapping
from datetime import datetime
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Annotated, Final, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Discriminator,
    Field,
    JsonValue,
    PlainSerializer,
    StrictBool,
    StrictInt,
    StrictStr,
    Tag,
    field_validator,
    model_validator,
)

from agent_hub.core.hub_config.model_tiers import Tier
from agent_hub.core.scenarios.access_policy import Effect
from agent_hub.core.workflows.substitution import NodeRef, SubstitutionError, parse_ref

TriggerRule = Literal["all_success", "one_success", "none_failed_min_one_success", "all_done"]
# A hub step node runs the engine's own hub executable (ADR 0032): ``command[0:2]``.
HUB_STEP: Final = ("hub", "step")
DEFAULT_DECISIONS: Final = (("approve", "Approve"), ("reject", "Reject"))


def _not_blank(value: str) -> str:
    if not value.strip():
        msg = "must not be empty or blank"
        raise ValueError(msg)
    return value


# The engine's own gate ids: a policy ask before a step, an investigation after a divergence.
RESERVED_SUFFIXES: Final = ("__ask", "__investigation")
# ``$self.output`` reads the node's own output: no scenario node may be named ``self``.
SELF_ID: Final = "self"


def _node_id(value: str) -> str:
    if value.endswith(RESERVED_SUFFIXES):
        msg = "an id ending __ask or __investigation is reserved for the engine's gates"
        raise ValueError(msg)
    if "__" in value:
        msg = "an id never contains '__' (kept for include namespacing)"
        raise ValueError(msg)
    return value


def _pack_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        msg = "must be a relative path inside the pack, without '..'"
        raise ValueError(msg)
    return value


def _unique[Item](items: tuple[Item, ...]) -> tuple[Item, ...]:
    if len(set(items)) != len(items):
        msg = "must not repeat an item"
        raise ValueError(msg)
    return items


def _json_number(value: object) -> object:
    # A float field would take ``"3"`` and ``true``; a document's number is an int or a float.
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = "must be a number"
        raise ValueError(msg)
    return value


def _positive_finite(value: float) -> float:
    if not math.isfinite(value) or value <= 0:
        msg = "must be a finite number greater than 0"
        raise ValueError(msg)
    return value


MAX_DURATION_SECONDS: Final = 7 * 24 * 3600
MAX_DURATION_DIGITS: Final = 6
_UNIT_SECONDS: Final = {"s": 1, "m": 60, "h": 3600, "d": 24 * 3600}


def duration_seconds(duration: str) -> int:
    """The seconds a ``Duration`` (``30s``, ``5m``, ``2h``, ``7d``) stands for."""
    return int(duration[:-1]) * _UNIT_SECONDS[duration[-1]]


def _within_a_week(value: str) -> str:
    # The digit count first: a long number is never converted.
    if len(value) > MAX_DURATION_DIGITS + 1 or duration_seconds(value) > MAX_DURATION_SECONDS:
        msg = f"must be at most 7 days, in at most {MAX_DURATION_DIGITS} digits"
        raise ValueError(msg)
    return value


# Scenario bounds (docs/design/scenarios.md § Events and bounds).
MIN_EXPECT_EVERY_SECONDS: Final = 5
MAX_EXPECT_TIMEOUT_SECONDS: Final = 24 * 3600
MAX_ACTION_TIMEOUT_SECONDS: Final = 3600


def _at_least_five_seconds(value: str) -> str:
    if duration_seconds(value) < MIN_EXPECT_EVERY_SECONDS:
        msg = f"must be at least {MIN_EXPECT_EVERY_SECONDS}s"
        raise ValueError(msg)
    return value


def _within_a_day(value: str) -> str:
    if duration_seconds(value) > MAX_EXPECT_TIMEOUT_SECONDS:
        msg = "must be at most 24h"
        raise ValueError(msg)
    return value


def _within_an_hour(value: str) -> str:
    if duration_seconds(value) > MAX_ACTION_TIMEOUT_SECONDS:
        msg = "must be at most 1h"
        raise ValueError(msg)
    return value


def read_only[Key, Value](value: Mapping[Key, Value]) -> Mapping[Key, Value]:
    """A read-only copy of ``value``: a frozen document's mappings cannot be changed either."""
    return MappingProxyType(dict(value))


def _output_ref(value: str) -> str:
    try:
        ref = parse_ref(value)
    except SubstitutionError as error:
        raise ValueError(str(error)) from None
    if not isinstance(ref, NodeRef):
        msg = "must be a node output reference ($<node>.output[.path])"
        raise ValueError(msg)
    return value


def _plain_value(value: object) -> object:
    # A mapping holding ``from`` is a binding: the plain-value branch must not swallow one that
    # has a typo, an extra key or a bad reference.
    if isinstance(value, dict) and "from" in value:
        msg = "a binding takes only 'from' (a node output reference) and 'if_skipped'"
        raise ValueError(msg)
    return value


Text = Annotated[StrictStr, AfterValidator(_not_blank)]
NodeId = Annotated[StrictStr, Field(pattern=r"^[a-z][a-z0-9_-]*$"), AfterValidator(_node_id)]
FieldName = Annotated[StrictStr, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
VariableName = Annotated[StrictStr, Field(pattern=r"^[a-z][a-z0-9_]*$")]
KebabId = Annotated[StrictStr, Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]
EnvName = Annotated[StrictStr, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
# At most six digits and seven days (the contract's longest wait), so a run never overflows.
Duration = Annotated[
    StrictStr, Field(pattern=r"^[1-9][0-9]*(s|m|h|d)$"), AfterValidator(_within_a_week)
]
PackPath = Annotated[Text, AfterValidator(_pack_path)]
ActionTimeout = Annotated[Duration, AfterValidator(_within_an_hour)]
ExpectEvery = Annotated[Duration, AfterValidator(_at_least_five_seconds)]
ExpectTimeout = Annotated[Duration, AfterValidator(_within_a_day)]
Argv = Annotated[tuple[Text, ...], Field(min_length=1)]
OutputRef = Annotated[StrictStr, AfterValidator(_output_ref)]
PositiveNumber = Annotated[float, BeforeValidator(_json_number), AfterValidator(_positive_finite)]
# Validated as a dict, kept read-only, serialised as a dict again.
READ_ONLY = (AfterValidator(read_only), PlainSerializer(dict, return_type=dict))
JsonObject = Annotated[Mapping[str, JsonValue], *READ_ONLY]
EnvMap = Annotated[Mapping[EnvName, StrictStr], *READ_ONLY]


def empty[Key, Value]() -> Mapping[Key, Value]:
    """A new read-only empty mapping (a default: pydantic copies a default value it is given)."""
    return MappingProxyType({})


class WorkflowObject(BaseModel):
    """A frozen object of a workflow document: an unknown key is a load error."""

    # Built on first use, not at import: a command that loads no workflow skips it.
    model_config = ConfigDict(frozen=True, extra="forbid", defer_build=True)


class Retry(WorkflowObject):
    """``max_attempts`` retries after the first attempt, the delay doubling each time."""

    max_attempts: Annotated[StrictInt, Field(ge=0, le=5)] = 1
    delay: Duration = "2s"
    on_error: Literal["transient", "all"] = "transient"


class Limits(WorkflowObject):
    max_turns: Annotated[StrictInt, Field(ge=1)] = 40
    max_cost_usd: PositiveNumber = 3.0


class ResumeContext(WorkflowObject):
    """Resume an upstream agent node's session instead of starting fresh."""

    resume: NodeId


class FromBinding(WorkflowObject):
    """A ``with`` value read from an upstream output, ``if_skipped`` when that node skipped."""

    # Built at import: a read-only mapping dumps its values with their own serializer, which
    # must not be the placeholder a deferred model holds until its first use.
    model_config = ConfigDict(defer_build=False)

    from_: OutputRef = Field(alias="from")
    if_skipped: JsonValue = None


def _context_kind(value: object) -> str:
    return "<fresh>" if isinstance(value, str) else "<resume>"


# One member checked, chosen by the value's kind: a wrong value gets one error, not one per
# member. The tags are not keys a document can hold, so error paths drop them.
Context = Annotated[
    Annotated[Literal["fresh"], Tag("<fresh>")] | Annotated[ResumeContext, Tag("<resume>")],
    Discriminator(_context_kind),
]


# Left to right: a mapping that is a well-formed binding never reads as a plain value.
Binding = Annotated[
    FromBinding | JsonValue, Field(union_mode="left_to_right"), AfterValidator(_plain_value)
]


class Decision(WorkflowObject):
    id: KebabId
    label: Text


class _Node(WorkflowObject):
    id: NodeId
    description: Text | None = None
    depends_on: Annotated[tuple[NodeId, ...], AfterValidator(_unique)] = ()
    trigger_rule: TriggerRule = "all_success"
    when: Text | None = None


class _Executable(_Node):
    retry: Retry | None = None
    always_run: StrictBool = False
    timeout: Duration | None = None
    output_format: JsonObject | None = None
    # ``false`` asks the engine to compare git status before and after: a change fails the node.
    mutates_checkout: StrictBool = True


class _AgentKeys(_Executable):
    prompt: Text | None = None
    prompt_file: PackPath | None = None
    with_: Annotated[Mapping[VariableName, Binding], *READ_ONLY] = Field(
        default_factory=empty, alias="with"
    )
    model: Tier = "medium"
    limits: Limits = Field(default_factory=Limits)
    context: Context = "fresh"
    # The session's folder (the hub when absent), contained as a shell node's ``cwd``.
    cwd: Text | None = None

    @model_validator(mode="after")
    def _one_prompt(self) -> Self:
        if (self.prompt is None) == (self.prompt_file is None):
            msg = "give exactly one of 'prompt' or 'prompt_file'"
            raise ValueError(msg)
        return self


class AgentNode(_AgentKeys):
    type: Literal["agent"]


class ShellNode(_Executable):
    type: Literal["shell"]
    command: Argv
    cwd: Text | None = None
    env: EnvMap = Field(default_factory=empty)
    # Written to the child's stdin: a literal, or one whole reference's canonical text.
    stdin: Text | None = None
    # Under the workflow's ``environment``, the policy's input (``write`` when absent, P-18).
    effect: Effect | None = None

    @property
    def is_hub_step(self) -> bool:
        return self.command[: len(HUB_STEP)] == HUB_STEP

    @model_validator(mode="after")
    def _no_env_on_hub_step(self) -> Self:
        if self.is_hub_step and self.env:
            msg = "a hub step node takes no 'env': hub step scopes its own environment"
            raise ValueError(msg)
        return self


class ScriptNode(_Executable):
    type: Literal["script"]
    runtime: Literal["sh", "python"]
    script: PackPath
    args: tuple[StrictStr, ...] = ()
    cwd: Text | None = None
    env: EnvMap = Field(default_factory=empty)
    stdin: Text | None = None
    effect: Effect | None = None


class LoopNode(_AgentKeys):
    type: Literal["loop"]
    max_iterations: Annotated[StrictInt, Field(ge=1, le=50)]
    until: Text | None = None
    until_field: FieldName | None = None
    until_bash: Argv | None = None
    fresh_context: StrictBool = False

    @model_validator(mode="after")
    def _until_channel(self) -> Self:
        if self.until is None and self.until_field is None and self.until_bash is None:
            msg = "give at least one of 'until', 'until_field' or 'until_bash'"
            raise ValueError(msg)
        if self.until_field is not None:
            schema = required_property(self.output_format, self.until_field)
            if schema is None or schema.get("type") != "boolean":
                msg = "'until_field' must be a required boolean property of 'output_format'"
                raise ValueError(msg)
        return self


class ApprovalNode(_Node):
    type: Literal["approval"]
    message: Text
    decisions: Annotated[tuple[Decision, ...], Field(min_length=1)] = tuple(
        Decision(id=decision_id, label=label) for decision_id, label in DEFAULT_DECISIONS
    )
    capture_response: StrictBool = False

    @field_validator("decisions")
    @classmethod
    def _unique_decision_ids(cls, value: tuple[Decision, ...]) -> tuple[Decision, ...]:
        _unique(tuple(decision.id for decision in value))
        return value


class HaltNode(_Node):
    type: Literal["halt"]
    reason: Text


def _until(value: str) -> str:
    # A whole reference is read at run time; anything else is an instant with its offset. The
    # scenario grammar is accepted here: planning refuses ``$CTX`` outside a scenario.
    if value.startswith("$"):
        try:
            parse_ref(value, scenario=True)
        except SubstitutionError as error:
            raise ValueError(str(error)) from None
        return value
    try:
        instant = datetime.fromisoformat(value)
    except ValueError:
        instant = None
    if instant is None or instant.tzinfo is None:
        msg = "must be an ISO-8601 instant with an offset, or a whole reference"
        raise ValueError(msg)
    return value


class WaitNode(_Node):
    """Waits ``duration``, until an instant, or for a person's ``attention`` (text, or one of
    ``options``)."""

    type: Literal["wait"]
    duration: Duration | None = None
    until: Annotated[Text, AfterValidator(_until)] | None = None
    attention: Text | None = None
    options: Annotated[tuple[Decision, ...], Field(min_length=1)] | None = None

    @model_validator(mode="after")
    def _one_condition(self) -> Self:
        if [self.duration, self.until, self.attention].count(None) != 2:
            msg = "give exactly one of 'duration', 'until' or 'attention'"
            raise ValueError(msg)
        if self.options is not None:
            if self.attention is None:
                msg = "'options' needs 'attention'"
                raise ValueError(msg)
            _unique(tuple(option.id for option in self.options))
        return self


class IncludeNode(_Node):
    """Replaced at load by the workflow ``include`` names; ``with`` fills that one's ``inputs``.

    Its ``depends_on``, ``when`` and ``trigger_rule`` go to the block's roots; a root keeps its
    own ``trigger_rule`` when it sets one.
    """

    type: Literal["include"]
    include: KebabId
    with_: Annotated[Mapping[VariableName, JsonValue], *READ_ONLY] = Field(
        default_factory=empty, alias="with"
    )


# ``<name>``, an action of the scenario's pack, or ``<pack>/<name>``.
ActionRef = Annotated[
    StrictStr, Field(pattern=r"^(?:[a-z0-9]+(?:-[a-z0-9]+)*/)?[a-z0-9]+(?:-[a-z0-9]+)*$")
]


def _whole_ref(value: str) -> str:
    try:
        parse_ref(value, scenario=True)
    except SubstitutionError as error:
        raise ValueError(str(error)) from None
    return value


WholeRef = Annotated[StrictStr, AfterValidator(_whole_ref)]


class _ActionKeys(_Node):
    """An action call (docs/design/scenarios.md): ``with`` fills the action's inputs, ``capture``
    names values of its output for ``$CTX``. Its output format is the action's own."""

    action: ActionRef
    with_: Annotated[Mapping[VariableName, JsonValue], *READ_ONLY] = Field(
        default_factory=empty, alias="with"
    )
    capture: Annotated[Mapping[VariableName, WholeRef], *READ_ONLY] = Field(default_factory=empty)
    retry: Retry | None = None


class ActionNode(_ActionKeys):
    """Runs one action once, through the engine's runner."""

    type: Literal["action"]
    timeout: ActionTimeout | None = None


class ExpectNode(_ActionKeys):
    """Runs a read action every ``every`` until ``until_when`` holds over its output
    (``$self.output``), or fails ``timeout`` once ``timeout`` has passed."""

    type: Literal["expect"]
    every: ExpectEvery
    timeout: ExpectTimeout
    until_when: Text


type ExecutableNode = AgentNode | ShellNode | ScriptNode | LoopNode | ActionNode | ExpectNode
type GateNode = ApprovalNode | WaitNode
BodyNode = Annotated[
    AgentNode
    | ShellNode
    | ScriptNode
    | LoopNode
    | ApprovalNode
    | HaltNode
    | WaitNode
    | ActionNode
    | ExpectNode,
    Field(discriminator="type"),
]


class LoopGroupNode(_Node):
    """A body sub-graph run once per iteration until ``until_when`` holds or ``until_bash``
    exits 0, at most ``max_iterations`` times. Body ids are recorded as ``<group>__<id>``."""

    type: Literal["loop_group"]
    nodes: Annotated[tuple[BodyNode, ...], Field(min_length=1)]
    max_iterations: Annotated[StrictInt, Field(ge=1, le=50)]
    until_bash: Argv | None = None
    until_when: Text | None = None
    # ``false`` (default): a body agent resumes its own session of the previous iteration.
    fresh_context: StrictBool = False

    @model_validator(mode="after")
    def _until_channel(self) -> Self:
        if self.until_bash is None and self.until_when is None:
            msg = "give at least one of 'until_bash' or 'until_when'"
            raise ValueError(msg)
        return self


Node = Annotated[
    AgentNode
    | ShellNode
    | ScriptNode
    | LoopNode
    | ApprovalNode
    | HaltNode
    | WaitNode
    | IncludeNode
    | LoopGroupNode
    | ActionNode
    | ExpectNode,
    Field(discriminator="type"),
]


def required_property(
    output_format: Mapping[str, JsonValue] | None, name: str
) -> Mapping[str, JsonValue] | None:
    """The schema of ``name`` when ``output_format`` is an object schema that requires it."""
    if output_format is None or output_format.get("type") != "object":
        return None
    properties = output_format.get("properties")
    required = output_format.get("required")
    if not isinstance(properties, dict) or not isinstance(required, list) or name not in required:
        return None
    schema = properties.get(name)
    return schema if isinstance(schema, dict) else None
