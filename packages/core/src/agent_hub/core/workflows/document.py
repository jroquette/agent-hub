"""The workflow document's top level, and its load errors (docs/design/workflow-schema.md).

``parse_workflow`` takes the value a loader read (YAML or JSON, already parsed) and returns the
frozen model, or raises ``WorkflowLoadError`` with every problem pydantic found. A problem is
located by its key path (``loc``), never by a line: the loader that read the file knows the
lines, and the catalog maps a key path to one (``catalog.WorkflowFile.line_of``).
"""

from collections.abc import Sequence
from typing import Annotated, Literal, NamedTuple, Self

from pydantic import (
    AfterValidator,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)

from agent_hub.core.errors import AgentHubError
from agent_hub.core.features.output_shape import output_path
from agent_hub.core.hub_config.problems import one_line
from agent_hub.core.workflows.nodes import (
    FieldName,
    KebabId,
    Node,
    NodeId,
    Text,
    VariableName,
    WorkflowObject,
)

type Loc = tuple[str | int, ...]
type InputValue = StrictStr | StrictInt | StrictFloat | StrictBool

_INPUT_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
}
_MESSAGES = {
    "extra_forbidden": "unknown key",
    "model_type": "must be a mapping",
    "model_attributes_type": "must be a mapping",
}


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
    default: InputValue | None = None
    description: Text | None = None

    @model_validator(mode="after")
    def _default_fits(self) -> Self:
        if self.default is None:
            return self
        if self.required:
            msg = "a required input takes no 'default'"
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
    inputs: dict[VariableName, WorkflowInput] = Field(default_factory=dict)
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
        raise WorkflowLoadError(
            [
                WorkflowProblem(_untagged(detail["loc"]), _message(detail["type"], detail["msg"]))
                for detail in error.errors(include_url=False, include_input=False)
            ]
        ) from None


def _untagged(loc: Sequence[str | int]) -> Loc:
    # pydantic puts the node's ``type`` after its index (``nodes.0.shell.command``) and
    # ``[key]`` after a mapping key it refuses; neither is a key of the document.
    if len(loc) > 2 and loc[0] == "nodes" and isinstance(loc[1], int):
        loc = (*loc[:2], *loc[3:])
    return tuple(segment for segment in loc if segment != "[key]")


def _message(kind: str, message: str) -> str:
    return _MESSAGES.get(kind) or one_line(message.removeprefix("Value error, "))
