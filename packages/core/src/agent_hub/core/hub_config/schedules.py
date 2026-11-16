"""``hub.json``'s ``schedules`` and ``events``: workflows that ``hub web`` starts by itself.

The value shapes; ``model.py`` puts them in ``HubConfig`` and checks across them (a declared
environment, a known repo, one schedule per workflow, one event per workflow, kind and repo, no
event input set by hand). The cron is 5 numeric fields read in UTC (ADR 0048).
"""

from datetime import UTC, datetime
from typing import Annotated, Final, Literal

from pydantic import (
    AfterValidator,
    BeforeValidator,
    Discriminator,
    Field,
    StrictBool,
    StrictInt,
    Tag,
    WithJsonSchema,
)
from pydantic_core import PydanticCustomError

from agent_hub.core.hub_config.config_object import ConfigObject, absent_by_default
from agent_hub.core.hub_config.doctor_rules import drop_map_comment_keys
from agent_hub.core.hub_config.environments import EnvironmentName, NoSecret, comment_keyed_map
from agent_hub.core.hub_config.text_shapes import SAFE_SEGMENT
from agent_hub.core.schedules.cron import MAX_CRON_CHARS, CronError, parse_cron

MAX_STARTS: Final = 32
MAX_START_INPUTS: Final = 64
MAX_START_INPUT_CHARS: Final = 1_000
MAX_START_WORKFLOW_CHARS: Final = 128
# The inputs an event offers its run, each passed only when the workflow declares it.
EVENT_INPUTS: Final = {"merge": ("sha",), "ci_red": ("sha", "ci_run"), "pr_opened": ("pr", "sha")}
EVENT_INPUT_NAMES: Final = frozenset(name for names in EVENT_INPUTS.values() for name in names)
# A cron that fires never after this moment is refused: it would never start a run.
_CRON_PROBE: Final = datetime(2000, 1, 1, tzinfo=UTC)

type EventKind = Literal["merge", "ci_red", "pr_opened"]


def _firing_cron(value: str) -> str:
    try:
        schedule = parse_cron(value)
    except CronError as error:
        raise PydanticCustomError("cron", "{reason}", {"reason": str(error)}) from None
    if schedule.next_after(_CRON_PROBE) is None:
        raise PydanticCustomError("cron", "the cron never fires")
    return value


def _value_kind(value: object) -> str | None:
    # One branch per JSON type, so a bad value reports one error, not one per type.
    for kind, types in (("bool", bool), ("int", int), ("float", float), ("str", str)):
        if isinstance(value, types):
            return kind
    return None


# Plain aliases, not ``type`` statements: pydantic inlines them (as in model.py).
CronText = Annotated[
    str, Field(min_length=1, max_length=MAX_CRON_CHARS), AfterValidator(_firing_cron)
]
StartWorkflowName = Annotated[
    str, Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=MAX_START_WORKFLOW_CHARS)
]
StartInputName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
StartInputText = Annotated[
    str, Field(max_length=MAX_START_INPUT_CHARS, pattern=r"^[^\x00]*$"), NoSecret
]
StartInputValue = Annotated[
    Annotated[StrictBool, Tag("bool")]
    | Annotated[StrictInt, Tag("int")]
    | Annotated[float, Field(allow_inf_nan=False), Tag("float")]
    | Annotated[StartInputText, Tag("str")],
    Discriminator(_value_kind),
    # ``anyOf``, not the ``oneOf`` pydantic exports: an integer is also a JSON Schema number.
    WithJsonSchema(
        {
            "anyOf": [
                {"type": "boolean"},
                {"type": "number"},
                {
                    "type": "string",
                    "maxLength": MAX_START_INPUT_CHARS,
                    "pattern": "^[^\\x00]*$",
                },
            ]
        }
    ),
]
StartInputs = Annotated[
    dict[StartInputName, StartInputValue],
    Field(max_length=MAX_START_INPUTS),
    BeforeValidator(drop_map_comment_keys),
    Field(json_schema_extra=comment_keyed_map),
]
StartRepoDir = Annotated[str, Field(pattern=rf"^{SAFE_SEGMENT}$")]


class Schedule(ConfigObject):
    """A workflow ``hub web`` starts at each slot of a cron (UTC)."""

    workflow: StartWorkflowName
    cron: CronText = Field(
        description="5 numeric fields (minute hour day month weekday), read in UTC."
    )
    inputs: StartInputs = Field(default_factory=dict, description="The run's inputs.")
    environment: EnvironmentName | None = absent_by_default(
        description="A declared environment the run gets (--env). Absent: none."
    )


class EventStart(ConfigObject):
    """A workflow ``hub web`` starts when a repo's event happens (GitHub, through gh)."""

    workflow: StartWorkflowName
    on: EventKind = Field(
        description="merge: a new commit on the default branch; ci_red: a failed Actions run on"
        " it; pr_opened: a newly opened pull request."
    )
    repo: StartRepoDir = Field(description="A repos[].dir.")
    inputs: StartInputs = Field(
        default_factory=dict,
        description="The run's inputs; sha, pr and ci_run come from the event.",
    )
