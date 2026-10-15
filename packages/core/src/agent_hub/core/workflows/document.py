"""The workflow document's top level, and its load errors (docs/design/workflow-schema.md).

``parse_workflow`` takes the value a loader read (YAML or JSON, already parsed) and returns the
frozen model, or raises ``WorkflowLoadError`` with every problem pydantic found. A problem is
located by its key path (``loc``), never by a line: the loader that read the file knows the
lines, and the catalog maps a key path to one (``catalog.WorkflowFile.line_of``).
"""

import math
from collections.abc import Mapping, Sequence
from typing import Annotated, Literal, NamedTuple, Self

from pydantic import (
    AfterValidator,
    Field,
    JsonValue,
    StrictBool,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)

from agent_hub.core.errors import AgentHubError
from agent_hub.core.features.output_shape import output_path
from agent_hub.core.hub_config.problems import one_line
from agent_hub.core.workflows.nodes import (
    READ_ONLY,
    FieldName,
    KebabId,
    Node,
    NodeId,
    Text,
    VariableName,
    WorkflowObject,
    empty,
)

type Loc = tuple[str | int, ...]

_INPUT_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
}
_NODE_TYPES = "agent, shell, script, loop, loop_group, approval, wait, halt, include"
_MESSAGES = {
    "extra_forbidden": "unknown key",
    "model_type": "must be a mapping",
    "model_attributes_type": "must be a mapping",
    "union_tag_invalid": f"must be one of {_NODE_TYPES}",
    "union_tag_not_found": "Field required",
}
# Errors pydantic reports at a node's index, about its ``type`` key.
_TYPE_ERRORS = frozenset({"union_tag_invalid", "union_tag_not_found"})
# What pydantic puts after a mapping key it refuses.
_KEY_LABEL = "[key]"


def _not_empty[Item](items: tuple[Item, ...]) -> tuple[Item, ...]:
    if not items:
        msg = "must hold at least one node"
        raise ValueError(msg)
    return items


class WorkflowProblem(NamedTuple):
    """One load error: the key path it is at, and what is wrong."""

    loc: Loc
    message: str

    @property
    def key(self) -> str:
        """The key path as people read it: ``nodes[0].command``, ``$`` for the document."""
        return output_path(self.loc)


class WorkflowLoadError(AgentHubError):
    """A document that does not load; ``problems`` holds every problem found, in order."""

    def __init__(self, problems: Sequence[WorkflowProblem]) -> None:
        self.problems = tuple(problems)
        super().__init__("; ".join(f"{problem.key}: {problem.message}" for problem in problems))


class WorkflowInput(WorkflowObject):
    type: Literal["string", "integer", "number", "boolean"] = "string"
    required: StrictBool = False
    # Any JSON value, checked against ``type`` below: one message whatever the mismatch.
    default: JsonValue = None
    description: Text | None = None

    @model_validator(mode="after")
    def _default_fits(self) -> Self:
        if self.default is None:
            return self
        if self.required:
            msg = "a required input takes no 'default'"
            raise ValueError(msg)
        if isinstance(self.default, float) and not math.isfinite(self.default):
            msg = "'default' must be a finite number"
            raise ValueError(msg)
        # ``bool`` is an ``int``: it fits only a boolean input.
        if isinstance(self.default, bool) != (self.type == "boolean") or not isinstance(
            self.default, _INPUT_TYPES[self.type]
        ):
            msg = f"'default' must be of type {self.type}"
            raise ValueError(msg)
        return self


class WorkflowDocument(WorkflowObject):
    """A workflow file's content: a graph of typed nodes."""

    version: Literal[1]
    name: KebabId
    description: Text | None = None
    revision: Annotated[StrictInt, Field(ge=1)]
    inputs: Annotated[Mapping[VariableName, WorkflowInput], *READ_ONLY] = Field(
        default_factory=empty
    )
    returns: NodeId | None = None
    outcome_field: FieldName | None = None
    # Checked after the items, not as a length constraint: pydantic reports a length error
    # whenever an item fails, which would hide the real problems behind a false one.
    nodes: Annotated[tuple[Node, ...], AfterValidator(_not_empty)]

    @field_validator("version", mode="before")
    @classmethod
    def _version_is_an_integer(cls, value: object) -> object:
        # ``Literal[1]`` takes ``true`` too, as ``True == 1``.
        if isinstance(value, bool):
            msg = "must be the integer 1"
            raise ValueError(msg)
        return value


def parse_workflow(content: object) -> WorkflowDocument:
    """The document ``content`` holds; raises ``WorkflowLoadError`` naming every problem."""
    try:
        return WorkflowDocument.model_validate(content)
    except ValidationError as error:
        problems = []
        for detail in error.errors(include_url=False, include_input=False):
            loc = _document_loc(detail["loc"], content)
            if detail["type"] in _TYPE_ERRORS:
                loc = (*loc, "type")
            problems.append(WorkflowProblem(loc, _message(detail["type"], detail["msg"])))
        raise WorkflowLoadError(problems) from None


def _document_loc(loc: Sequence[str | int], content: object) -> Loc:
    """``loc`` without pydantic's own labels: a node's type tag, a union member, ``[key]``.

    A segment is kept when the content has it, or when it is the last one and names a key
    missing from a mapping; any other segment is a label, not a key of the document.
    """
    loc = _without_node_tag(loc, content)
    kept: list[str | int] = []
    current = content
    for position, segment in enumerate(loc):
        found, child = _child(current, segment)
        if found:
            current = child
        elif position < len(loc) - 1 or not isinstance(current, dict) or segment == _KEY_LABEL:
            continue
        kept.append(segment)
    return tuple(kept)


def _without_node_tag(loc: Sequence[str | int], content: object) -> Sequence[str | int]:
    # pydantic puts a node's ``type`` value after its index; a rule of the whole node ends
    # there, where it would otherwise read as a missing key.
    if len(loc) > 2 and loc[0] == "nodes" and isinstance(loc[1], int):
        _, nodes = _child(content, "nodes")
        _, node = _child(nodes, loc[1])
        if isinstance(node, dict) and node.get("type") == loc[2]:
            return (*loc[:2], *loc[3:])
    return loc


def _child(value: object, segment: str | int) -> tuple[bool, object]:
    if isinstance(value, dict) and segment in value:
        return True, value[segment]
    if isinstance(value, list) and isinstance(segment, int) and segment < len(value):
        return True, value[segment]
    return False, None


def _message(kind: str, message: str) -> str:
    return _MESSAGES.get(kind) or one_line(message.removeprefix("Value error, "))
