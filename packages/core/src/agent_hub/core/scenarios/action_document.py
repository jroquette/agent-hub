"""An action document: ``actions/<pack>/<name>.yaml`` (docs/design/scenarios.md § Actions).

``parse_action`` takes the value a loader read and returns the frozen model, or raises the
workflows' ``WorkflowLoadError`` with every problem at its key path, as ``parse_workflow`` does.
What needs the file system (the script's real path, the name against the file's stem) and the
JSON Schema check of ``output_format`` are the loader's (``generator.action_discovery``).
"""

import math
from collections.abc import Mapping
from typing import Annotated, Final, Literal, Self

from pydantic import AfterValidator, Field, JsonValue, StrictBool, ValidationError, model_validator

from agent_hub.core.scenarios.access_policy import Effect
from agent_hub.core.workflows.document import load_error
from agent_hub.core.workflows.nodes import (
    READ_ONLY,
    Duration,
    JsonObject,
    KebabId,
    PackPath,
    Text,
    VariableName,
    WorkflowObject,
    duration_seconds,
    empty,
)

MAX_ACTION_TIMEOUT_SECONDS: Final = 3600
DEFAULT_ACTION_TIMEOUT: Final = "5m"
SCRIPTS_FOLDER: Final = "scripts"

ActionInputType = Literal["string", "integer", "number", "boolean", "service"]
# A ``service`` value names a service of ``repos[].services``.
_INPUT_TYPES: Final[Mapping[ActionInputType, tuple[type, ...]]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "service": (str,),
}


def _within_an_hour(value: str) -> str:
    if duration_seconds(value) > MAX_ACTION_TIMEOUT_SECONDS:
        msg = "must be at most 1h"
        raise ValueError(msg)
    return value


def _in_scripts_folder(value: str) -> str:
    if not value.startswith(f"{SCRIPTS_FOLDER}/"):
        msg = f"must be a file under the pack's {SCRIPTS_FOLDER}/ folder"
        raise ValueError(msg)
    return value


ActionTimeout = Annotated[Duration, AfterValidator(_within_an_hour)]
ScriptPath = Annotated[PackPath, AfterValidator(_in_scripts_folder)]


class ActionInput(WorkflowObject):
    """A typed input; a value that does not fit its type is refused before the script runs."""

    type: ActionInputType = "string"
    required: StrictBool = False
    default: JsonValue = None
    description: Text | None = None

    @model_validator(mode="after")
    def _default_fits(self) -> Self:
        if self.default is None:
            return self
        if self.required:
            msg = "a required input takes no 'default'"
            raise ValueError(msg)
        if not self.fits(self.default):
            msg = f"'default' must be of type {self.type}"
            raise ValueError(msg)
        return self

    def fits(self, value: JsonValue) -> bool:
        """Whether ``value`` is of this input's type (a boolean fits only a boolean input)."""
        if isinstance(value, float) and not math.isfinite(value):
            return False
        is_bool = isinstance(value, bool)
        return is_bool == (self.type == "boolean") and isinstance(value, _INPUT_TYPES[self.type])


class ActionDocument(WorkflowObject):
    """A project script with a declared effect, typed inputs and an output schema."""

    version: Literal[1]
    name: KebabId
    description: Text
    effect: Effect
    runtime: Literal["sh", "python"]
    script: ScriptPath
    timeout: ActionTimeout = DEFAULT_ACTION_TIMEOUT
    inputs: Annotated[Mapping[VariableName, ActionInput], *READ_ONLY] = Field(default_factory=empty)
    output_format: JsonObject


def parse_action(content: object) -> ActionDocument:
    """The action ``content`` holds; raises ``WorkflowLoadError`` naming every problem."""
    try:
        return ActionDocument.model_validate(content)
    except ValidationError as error:
        raise load_error(error, content) from None
