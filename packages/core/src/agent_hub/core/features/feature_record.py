"""The ``features.json`` record of a feature folder, as the app parses it (AGH-136 S3).

``tickets`` (optional) is the planner's ticket plan: a draft ``key`` (``T1``...), the tracker ``id``
once the issue is created, ``blocked_by`` (keys or ids), a plan ``order`` and its ``parent`` (the
key or id of the epic it belongs to: a tracking ticket that is never worked on itself). Each AC may
name its ``ticket`` (a key or id) and be ``withdrawn`` by a spec amendment. Older records, with
neither, parse unchanged; unknown keys are ignored. Bounds keep one record from flooding a view.
``record_from_bytes`` parses the file's bytes, read whole up to ``MAX_RECORD_BYTES``.
"""

from typing import Annotated, Final

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
)

from agent_hub.core.hub_config.problems import one_line
from agent_hub.core.json_form import InvalidJsonError, load_json_bytes
from agent_hub.core.tracker.tracker_client import ISSUE_ID_PATTERN

RECORD_FILE: Final = "features.json"
# A ``features.json`` larger than this is not read.
MAX_RECORD_BYTES: Final = 1_048_576
MAX_TICKETS: Final = 200
MAX_BLOCKED_BY: Final = 50
MAX_TITLE_CHARS: Final = 200
# A draft key or a tracker id (``T1``, ``DEMO-1520``).
KEY_PATTERN: Final = r"^[A-Za-z][A-Za-z0-9_-]{0,31}$"

type TicketKey = Annotated[StrictStr, Field(pattern=KEY_PATTERN)]
type IssueId = Annotated[StrictStr, Field(pattern=f"^{ISSUE_ID_PATTERN.pattern}$")]


class PlannedTicket(BaseModel):
    """One ticket of the plan; ``id`` is None until the issue is created."""

    model_config = ConfigDict(frozen=True)

    key: TicketKey
    id: IssueId | None = None
    title: Annotated[StrictStr, Field(max_length=MAX_TITLE_CHARS)] | None = None
    repo: StrictStr | None = None
    blocked_by: Annotated[tuple[TicketKey, ...], Field(max_length=MAX_BLOCKED_BY)] = ()
    order: Annotated[StrictInt, Field(ge=0)] | None = None
    parent: TicketKey | None = None


class RecordAc(BaseModel):
    """One acceptance criterion; ``ticket`` names the ticket that delivers it."""

    model_config = ConfigDict(frozen=True)

    id: StrictStr
    description: StrictStr
    repo: StrictStr | None = None
    verification: StrictStr | None = None
    passes: StrictBool
    evidence: StrictStr | None = None
    ticket: StrictStr | None = None
    withdrawn: StrictBool = False


class FeatureRecordFile(BaseModel):
    """``features.json``: the Linear ids, the ticket plan and the acceptance criteria."""

    model_config = ConfigDict(frozen=True)

    linear: tuple[StrictStr, ...] = ()
    tickets: Annotated[tuple[PlannedTicket, ...], Field(max_length=MAX_TICKETS)] = ()
    acs: tuple[RecordAc, ...]


def record_from_bytes(content: bytes) -> FeatureRecordFile | str:
    """``content`` parsed as ``features.json``, or a one-line problem naming the file."""
    try:
        return FeatureRecordFile.model_validate(load_json_bytes(content))
    except InvalidJsonError as error:
        return one_line(f"{RECORD_FILE} could not be parsed ({error.message})")
    except ValidationError as error:
        first = error.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        return one_line(f"{RECORD_FILE} could not be parsed ({where}: {first['msg']})")
