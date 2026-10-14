"""The workflow nodes: one frozen model per ``type`` (docs/design/workflow-schema.md § Nodes).

Every model forbids unknown keys. ``include``, ``loop_group`` and ``wait`` come later; until
then their ``type`` is refused like any other unknown one. Checks that need more than one node
(``depends_on`` targets, references, ``context.resume``) are planning's (``plan.py``).
"""

from pathlib import PurePosixPath
from typing import Annotated, Final, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from agent_hub.core.hub_config.model_tiers import Tier

TriggerRule = Literal["all_success", "one_success", "none_failed_min_one_success", "all_done"]
# A hub step node runs the engine's own hub executable (ADR 0032): ``command[0:2]``.
HUB_STEP: Final = ("hub", "step")
DEFAULT_DECISIONS: Final = (("approve", "Approve"), ("reject", "Reject"))


def _not_blank(value: str) -> str:
    if not value.strip():
        msg = "must not be empty or blank"
        raise ValueError(msg)
    return value


def _node_id(value: str) -> str:
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


def _positive(value: float) -> float:
    if value <= 0:
        msg = "must be greater than 0"
        raise ValueError(msg)
    return value


Text = Annotated[StrictStr, AfterValidator(_not_blank)]
NodeId = Annotated[StrictStr, Field(pattern=r"^[a-z][a-z0-9_-]*$"), AfterValidator(_node_id)]
FieldName = Annotated[StrictStr, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
VariableName = Annotated[StrictStr, Field(pattern=r"^[a-z][a-z0-9_]*$")]
KebabId = Annotated[StrictStr, Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]
EnvName = Annotated[StrictStr, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
Duration = Annotated[StrictStr, Field(pattern=r"^[1-9][0-9]*(s|m|h|d)$")]
PackPath = Annotated[Text, AfterValidator(_pack_path)]
Argv = Annotated[tuple[Text, ...], Field(min_length=1)]
OutputRef = Annotated[StrictStr, Field(pattern=r"^\$[a-z][a-z0-9_-]*\.output(\.[A-Za-z0-9_-]+)*$")]


class WorkflowObject(BaseModel):
    """A frozen object of a workflow document: an unknown key is a load error."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Retry(WorkflowObject):
    """``max_attempts`` retries after the first attempt, the delay doubling each time."""

    max_attempts: Annotated[StrictInt, Field(ge=0, le=5)] = 1
    delay: Duration = "2s"
    on_error: Literal["transient", "all"] = "transient"


class Limits(WorkflowObject):
    max_turns: Annotated[StrictInt, Field(ge=1)] = 40
    max_cost_usd: Annotated[StrictInt | StrictFloat, AfterValidator(_positive)] = 3.0


class ResumeContext(WorkflowObject):
    """Resume an upstream agent node's session instead of starting fresh."""

    resume: NodeId


class FromBinding(WorkflowObject):
    """A ``with`` value read from an upstream output, ``if_skipped`` when that node skipped."""

    from_: OutputRef = Field(alias="from")
    if_skipped: JsonValue = None


# Left to right: a mapping that is a well-formed binding never reads as a plain value.
Binding = Annotated[FromBinding | JsonValue, Field(union_mode="left_to_right")]


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
    output_format: dict[str, JsonValue] | None = None
    # ``false`` asks the engine to compare git status before and after: a change fails the node.
    mutates_checkout: StrictBool = True


class _AgentKeys(_Executable):
    prompt: Text | None = None
    prompt_file: PackPath | None = None
    with_: dict[VariableName, Binding] = Field(default_factory=dict, alias="with")
    model: Tier = "medium"
    limits: Limits = Field(default_factory=Limits)
    context: Literal["fresh"] | ResumeContext = "fresh"

    @field_validator("with_")
    @classmethod
    def _bindings_well_formed(
        cls, value: dict[str, FromBinding | JsonValue]
    ) -> dict[str, FromBinding | JsonValue]:
        # A mapping holding ``from`` is a binding: the plain-value branch must not swallow one
        # that has a typo or an extra key.
        for name, item in value.items():
            if isinstance(item, dict) and "from" in item:
                msg = (
                    f"the binding {name!r} takes only 'from' (an output reference) and 'if_skipped'"
                )
                raise ValueError(msg)
        return value

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
    env: dict[EnvName, StrictStr] = Field(default_factory=dict)

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
    env: dict[EnvName, StrictStr] = Field(default_factory=dict)


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


type ExecutableNode = AgentNode | ShellNode | ScriptNode | LoopNode
Node = Annotated[
    AgentNode | ShellNode | ScriptNode | LoopNode | ApprovalNode | HaltNode,
    Field(discriminator="type"),
]


def required_property(
    output_format: dict[str, JsonValue] | None, name: str
) -> dict[str, JsonValue] | None:
    """The schema of ``name`` when ``output_format`` is an object schema that requires it."""
    if output_format is None or output_format.get("type") != "object":
        return None
    properties = output_format.get("properties")
    required = output_format.get("required")
    if not isinstance(properties, dict) or not isinstance(required, list) or name not in required:
        return None
    schema = properties.get(name)
    return schema if isinstance(schema, dict) else None
