"""A feature's ticket records and plan change requests (two-level-flows S2): read, pure.

``tickets/<ticket>/`` holds a ticket's context ``brief.md``, its ``preflight.json``
(``PreflightRecord``, runs appended) and its ticket ``plan.md``; only the preflight is read, the
other two are only seen present. ``change-requests/<n>.md`` is a plan change request, written
``status: open`` and never edited; ``change-requests/<n>.decision.md``, created once, records the
owner's decision, and the request's status is folded from it (D-11). A file that cannot be read
or parsed is kept with its problem ("<file> could not be read (…). Fix it in a hub PR."), so only
the step it feeds turns unknown.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, cast

from pydantic import ValidationError

from agent_hub.core.brain.brain_note import FrontmatterValue
from agent_hub.core.features.feature_evals import (
    ISO_TIME,
    RecordFieldError,
    record_fields,
    record_type,
    text_field,
)
from agent_hub.core.features.feature_record import KEY_PATTERN
from agent_hub.core.features.output_models import OutputProblem, PreflightRecord
from agent_hub.core.features.output_shape import parse_document, shape_problems
from agent_hub.core.hub_config.problems import one_line

if TYPE_CHECKING:
    from agent_hub.core.features.feature_status import RecordHead

TICKETS_FOLDER: Final = "tickets"
TICKET_BRIEF: Final = "brief.md"
TICKET_PLAN: Final = "plan.md"
PREFLIGHT_FILE: Final = "preflight.json"
# At most this many ticket folders are read, by name; each ``preflight.json`` up to its cap.
MAX_TICKET_FOLDERS: Final = 500
MAX_PREFLIGHT_BYTES: Final = 65_536
CHANGE_REQUESTS_FOLDER: Final = "change-requests"
# 200 requests and their decisions, by name; each file's head only.
MAX_CHANGE_REQUEST_FILES: Final = 400
CHANGE_REQUEST_HEAD_BYTES: Final = 16_384
FIX_IT: Final = "Fix it in a hub PR."

type ChangeStatus = Literal["open", "approved", "declined"]

_REQUEST: Final = re.compile(r"([1-9][0-9]{0,5})\.md")
_DECISION: Final = re.compile(r"([1-9][0-9]{0,5})\.decision\.md")
_VERSION: Final = re.compile(r"[1-9][0-9]{0,5}")
_TICKET: Final = re.compile(KEY_PATTERN)


@dataclass(frozen=True, kw_only=True, slots=True)
class TicketFiles:
    """What was read of ``tickets/<name>/``: whether ``brief.md`` and ``plan.md`` are regular
    files, and ``preflight.json``'s bytes (a one-line problem when not read, None when absent)."""

    name: str
    brief: bool = False
    plan: bool = False
    preflight: bytes | str | None = None


@dataclass(frozen=True, kw_only=True, slots=True)
class ChangeRequest:
    """One plan change request: its origin ``ticket``, its status folded from its decision, the
    plan version it asks for and the tickets it affects. ``problem`` says why it could not be
    read (status None; ``ticket`` kept when it could be), or why its decision could not be: the
    request then stays ``open``, not known to be decided. A decision needs a person
    (``decided_by`` neither empty nor ``unknown``, A5)."""

    n: int
    ticket: str | None
    status: ChangeStatus | None
    plan_to: int | None
    affected: tuple[str, ...]
    problem: str | None


@dataclass(frozen=True, kw_only=True, slots=True)
class ChangeRequests:
    """A feature's change requests by number; ``problem`` says not all were read."""

    requests: tuple[ChangeRequest, ...] = ()
    problem: str | None = None

    @property
    def open(self) -> tuple[ChangeRequest, ...]:
        return tuple(request for request in self.requests if request.status == "open")

    @property
    def paused(self) -> frozenset[str]:
        """The tickets (upper case) an open request pauses: its origin and the affected ones."""
        return frozenset(
            name.upper()
            for request in self.open
            for name in (request.ticket or "", *request.affected)
            if name
        )

    @property
    def approved_version(self) -> int | None:
        """The highest plan version an approved request asks for; None when none is approved."""
        return max(
            (r.plan_to for r in self.requests if r.status == "approved" and r.plan_to),
            default=None,
        )


NO_REQUESTS: Final = ChangeRequests()


def change_requests(heads: Sequence[RecordHead], *, skipped: int) -> ChangeRequests:
    """The requests among the heads of ``change-requests/*.md``, each with its decision folded
    in; ``skipped`` counts the files left unread over ``MAX_CHANGE_REQUEST_FILES``."""
    requests: dict[int, RecordHead] = {}
    decisions: dict[int, RecordHead] = {}
    for head in heads:
        if found := _REQUEST.fullmatch(head.name):
            requests[int(found[1])] = head
        elif found := _DECISION.fullmatch(head.name):
            decisions[int(found[1])] = head
    problem = None
    if skipped:
        problem = (
            f"more than {MAX_CHANGE_REQUEST_FILES} files in {CHANGE_REQUESTS_FOLDER}/; "
            f"not all were read. {FIX_IT}"
        )
    return ChangeRequests(
        requests=tuple(_request(n, requests[n], decisions.get(n)) for n in sorted(requests)),
        problem=problem,
    )


def preflight_record(read: bytes | str | None, *, folder: str) -> PreflightRecord | str | None:
    """The preflight record of ``tickets/<folder>/``; its one-line problem when it cannot be
    read, is malformed (the first problem, at its JSON path) or names another ticket (ASCII case
    ignored); None when absent."""
    if read is None:
        return None
    if isinstance(read, str):
        return _unreadable(PREFLIGHT_FILE, read)
    document = parse_document(read)
    if isinstance(document, OutputProblem):
        return _unreadable(PREFLIGHT_FILE, f"{document.path}: {document.message}")
    try:
        record = PreflightRecord.model_validate(document)
    except ValidationError as error:
        first = shape_problems(error)[0]
        return _unreadable(PREFLIGHT_FILE, f"{first.path}: {first.message}")
    if record.ticket.upper() != folder.upper():
        why = f"ticket: {record.ticket} is not the folder's ticket {folder}"
        return _unreadable(PREFLIGHT_FILE, why)
    return record


def _request(n: int, head: RecordHead, decision: RecordHead | None) -> ChangeRequest:
    name = f"{CHANGE_REQUESTS_FOLDER}/{head.name}"
    ticket: str | None = None
    try:
        fields = _fields(head)
        record_type(fields, "change-request")
        ticket = text_field(fields, "ticket", _TICKET)
        if ticket is None:
            raise RecordFieldError("ticket is missing")
        if text_field(fields, "status") != "open":
            raise RecordFieldError("status must be open: a decision is its own file")
        plan_to = int(text_field(fields, "plan_to", _VERSION) or 0)
        if not plan_to:
            raise RecordFieldError("plan_to is missing")
        affected = _names(fields.get("affected"))
    except RecordFieldError as problem:
        return _broken(n, ticket, _unreadable(name, str(problem)))
    status: ChangeStatus = "open"
    undecided = None
    if decision is not None:
        try:
            status = _decision(decision)
        except RecordFieldError as error:
            # Not known to be decided: the request stays open, with the decision's problem.
            where = f"{CHANGE_REQUESTS_FOLDER}/{decision.name}"
            undecided = _unreadable(where, str(error))
    return ChangeRequest(
        n=n, ticket=ticket, status=status, plan_to=plan_to, affected=affected, problem=undecided
    )


def _decision(head: RecordHead) -> ChangeStatus:
    fields = _fields(head)
    record_type(fields, "change-request-decision")
    decision = text_field(fields, "decision")
    if decision not in ("approved", "declined"):
        raise RecordFieldError("decision must be approved or declined")
    decided_by = text_field(fields, "decided_by")
    if decided_by is None:
        raise RecordFieldError("decided_by is missing")
    if decided_by.strip().lower() == "unknown":
        raise RecordFieldError(f"decided_by names no person: {decided_by.strip()}")
    if text_field(fields, "decided_at", ISO_TIME) is None:
        raise RecordFieldError("decided_at is missing")
    return cast("ChangeStatus", decision)


def _fields(head: RecordHead) -> dict[str, FrontmatterValue]:
    if head.head is None:
        raise RecordFieldError(head.problem or "could not be read")
    return record_fields(head.head)


def _names(value: FrontmatterValue | None) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    items = value if isinstance(value, list) else [value]
    for item in items:
        if _TICKET.fullmatch(item) is None:
            raise RecordFieldError(f"affected has an invalid item: {item[:64]}")
    return tuple(dict.fromkeys(items))


def _broken(n: int, ticket: str | None, problem: str) -> ChangeRequest:
    return ChangeRequest(
        n=n, ticket=ticket, status=None, plan_to=None, affected=(), problem=problem
    )


def _unreadable(name: str, why: str) -> str:
    return one_line(f"{name} could not be read ({why}). {FIX_IT}")
