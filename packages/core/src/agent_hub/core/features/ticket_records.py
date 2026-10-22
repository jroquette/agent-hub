"""A feature's ticket records and plan change requests (two-level-flows S2, S3): read, pure.

``tickets/<ticket>/`` holds a ticket's context ``brief.md``, its ``preflight.json``
(``PreflightRecord``, runs appended), its ticket ``plan.md`` and, once merged, its ``outcome.md``
(created once; its frontmatter says when it merged, by which pull request, and the tickets it
unblocks); the preflight and the outcome are read, the other two are only seen present.
``change-requests/<n>.md`` is a plan change request, written ``status: open`` and never edited;
``change-requests/<n>.decision.md``, created once, records the owner's decision, and the
request's status is folded from it (D-11). A file that cannot be read or parsed is kept with
its problem ("<file> could not be read (…). Fix it in a hub PR."), so only the step it feeds
turns unknown.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Final, Literal, cast

from pydantic import ValidationError

from agent_hub.core.brain.brain_note import FrontmatterValue
from agent_hub.core.brain.frontmatter import split_frontmatter
from agent_hub.core.features.feature_evals import (
    ISO_TIME,
    RecordFieldError,
    record_fields,
    record_type,
    text_field,
)
from agent_hub.core.features.feature_record import KEY_PATTERN
from agent_hub.core.features.feature_reviews import names_pull_request
from agent_hub.core.features.feature_view import ChangeDecisionView, ChangeRequestView
from agent_hub.core.features.output_models import OutputProblem, PreflightRecord, PreflightRun
from agent_hub.core.features.output_shape import parse_document, shape_problems
from agent_hub.core.hub_config.problems import one_line

if TYPE_CHECKING:
    from agent_hub.core.features.feature_status import RecordHead

TICKETS_FOLDER: Final = "tickets"
TICKET_BRIEF: Final = "brief.md"
TICKET_PLAN: Final = "plan.md"
PREFLIGHT_FILE: Final = "preflight.json"
OUTCOME_FILE: Final = "outcome.md"
OUTCOME_TYPE: Final = "ticket-outcome"
# ``outcome.md`` is read whole up to this size, by every read of a feature (Build counts it).
MAX_OUTCOME_BYTES: Final = 16_384
MAX_DEPENDENTS: Final = 50
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
class OutcomeFile:
    """``tickets/<name>/outcome.md`` as read: its bytes, or why it was not read (a one-line
    problem: a link, larger than ``MAX_OUTCOME_BYTES``)."""

    name: str
    read: bytes | str


@dataclass(frozen=True, kw_only=True, slots=True)
class TicketOutcome:
    """A merged ticket's outcome: when it merged, its pull request and the tickets it unblocks."""

    ticket: str
    merged_at: datetime
    pr: str
    dependents: tuple[str, ...]


@dataclass(frozen=True, kw_only=True, slots=True)
class ChangeRequest:
    """One plan change request: its origin ``ticket``, its status folded from its decision, the
    plan versions it goes from and to, the tickets it affects, when it was opened and by which
    workflow run, and its ``body`` (evidence and proposal, within the head read; ``body_cut``
    when the file is longer than that head). ``problem``
    says why it could not be read (status None; ``ticket`` kept when it could be), or why its
    decision could not be: the request then stays ``open``, not known to be decided. A decision
    needs a person (``decided_by`` neither empty nor ``unknown``, A5)."""

    n: int
    ticket: str | None
    status: ChangeStatus | None
    plan_to: int | None
    affected: tuple[str, ...]
    problem: str | None
    plan_from: int | None = None
    opened_at: str | None = None
    run_id: str | None = None
    decision: ChangeDecisionView | None = None
    body: str | None = None
    body_cut: bool = False


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


def ticket_folder(folders: Iterable[str], names: Iterable[str]) -> str | None:
    """The folder of ``tickets/`` the ticket flow reads for a ticket named ``names`` (its key and
    id): per name in any case the first folder by name, then the first of ``names`` upper-cased
    in sorted order (``ticket_flow.ticket_evidence`` and ``_picked_up``); None when none is."""
    by_name: dict[str, str] = {}
    for folder in sorted(folders):
        by_name.setdefault(folder.upper(), folder)
    return next(
        (by_name[name] for name in sorted(n.upper() for n in names) if name in by_name), None
    )


def request_view(request: ChangeRequest, *, slug: str, body: bool = False) -> ChangeRequestView:
    """``request`` as hub web reads it, with its ``body`` when asked (the ticket route); its
    run's gate and liveness are the API's to resolve (P8)."""
    return ChangeRequestView(
        n=request.n,
        ticket=request.ticket,
        status=request.status,
        plan_from=request.plan_from,
        plan_to=request.plan_to,
        affected=request.affected,
        opened_at=request.opened_at,
        run_id=request.run_id,
        decision=request.decision,
        path=f"features/{slug}/{CHANGE_REQUESTS_FOLDER}/{request.n}.md",
        problem=request.problem,
        body=request.body if body else None,
        body_cut=body and request.body_cut,
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


def outcome_record(read: bytes | str | None, *, folder: str) -> TicketOutcome | str | None:
    """The outcome of ``tickets/<folder>/``; its one-line problem when it cannot be read or its
    frontmatter does not hold a ``ticket-outcome`` of that ticket (ASCII case ignored) with
    ``merged_at`` (a time with an offset), ``pr`` (a pull request) and ``dependents`` (ticket keys
    or ids); None when absent."""
    if read is None:
        return None
    if isinstance(read, str):
        return _unreadable(OUTCOME_FILE, read)
    try:
        fields = record_fields(read)
        record_type(fields, OUTCOME_TYPE)
        ticket = text_field(fields, "ticket", _TICKET)
        if ticket is None:
            raise RecordFieldError("ticket is missing")
        if ticket.upper() != folder.upper():
            raise RecordFieldError(f"ticket: {ticket} is not the folder's ticket {folder}")
        merged_at = aware_time(text_field(fields, "merged_at"), "merged_at")
        pr = text_field(fields, "pr")
        if not names_pull_request(pr):
            raise RecordFieldError(f"pr names no pull request: {(pr or 'none')[:64]}")
        dependents = _names(fields.get("dependents"), "dependents")
        if len(dependents) > MAX_DEPENDENTS:
            raise RecordFieldError(f"dependents lists more than {MAX_DEPENDENTS} tickets")
    except RecordFieldError as problem:
        return _unreadable(OUTCOME_FILE, str(problem))
    return TicketOutcome(
        ticket=ticket, merged_at=merged_at, pr=cast("str", pr), dependents=dependents
    )


def recorded_outcomes(files: Iterable[OutcomeFile]) -> dict[str, TicketOutcome | str]:
    """Each ticket folder's outcome (or its problem) by its name upper-cased, the first folder by
    name when two differ only in case, as ``ticket_folder`` picks."""
    found: dict[str, TicketOutcome | str] = {}
    for file in sorted(files, key=lambda file: file.name):
        if file.name.upper() not in found:
            parsed = outcome_record(file.read, folder=file.name)
            if parsed is not None:
                found[file.name.upper()] = parsed
    return found


def already_read(
    record: PreflightRecord | None, *, names: Iterable[str], merged_at: datetime
) -> PreflightRun | None:
    """The latest preflight run that read a blocker's outcome: one that ran at or after the
    blocker's ``merged_at`` and lists the blocker (one of ``names``, any case) in
    ``blockers_read``; None when no run did (two-level-flows AC-3.3)."""
    wanted = {name.upper() for name in names}
    runs = () if record is None else record.runs
    return next(
        (
            run
            for run in reversed(runs)
            if run.ran_at >= merged_at and wanted & {name.upper() for name in run.blockers_read}
        ),
        None,
    )


def aware_time(value: str | None, name: str) -> datetime:
    """``value`` as an ISO 8601 date and time with an offset; ``RecordFieldError`` naming
    ``name`` otherwise."""
    if value is None:
        raise RecordFieldError(f"{name} is missing")
    try:
        found = datetime.fromisoformat(value)
    except ValueError:
        found = None
    if found is None or found.tzinfo is None or "T" not in value.upper():
        raise RecordFieldError(f"{name} needs a time with an offset")
    return found


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
        affected = _names(fields.get("affected"), "affected")
        plan_from = text_field(fields, "plan_from", _VERSION)
        opened_at = text_field(fields, "opened_at", ISO_TIME)
        run_id = text_field(fields, "run_id")
    except RecordFieldError as problem:
        return _broken(n, ticket, _unreadable(name, str(problem)))
    decided = None
    undecided = None
    if decision is not None:
        try:
            decided = _decision(decision)
        except RecordFieldError as error:
            # Not known to be decided: the request stays open, with the decision's problem.
            where = f"{CHANGE_REQUESTS_FOLDER}/{decision.name}"
            undecided = _unreadable(where, str(error))
    return ChangeRequest(
        n=n,
        ticket=ticket,
        status="open" if decided is None else decided.decision,
        plan_to=plan_to,
        affected=affected,
        problem=undecided,
        plan_from=None if plan_from is None else int(plan_from),
        opened_at=opened_at,
        run_id=run_id,
        decision=decided,
        body=_body(head),
        body_cut=_cut(head),
    )


def _body(head: RecordHead) -> str | None:
    """The request's text after its frontmatter (within the head read), None when empty. A
    full head may end inside a character: only then is its replacement mark dropped."""
    if head.head is None:
        return None
    text = split_frontmatter(head.head.decode("utf-8", "replace")).body.strip()
    if _cut(head):
        text = text.rstrip("\ufffd").rstrip()
    return f"{text}\n" if text else None


def _cut(head: RecordHead) -> bool:
    """Whether the head read fills its cap: the file may go on past it (a file of exactly the
    cap reads as cut too, which only sends the owner to read it whole)."""
    return head.head is not None and len(head.head) >= CHANGE_REQUEST_HEAD_BYTES


def _decision(head: RecordHead) -> ChangeDecisionView:
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
    decided_at = text_field(fields, "decided_at", ISO_TIME)
    if decided_at is None:
        raise RecordFieldError("decided_at is missing")
    return ChangeDecisionView(
        decision=cast("Literal['approved', 'declined']", decision),
        decided_by=decided_by.strip(),
        decided_at=decided_at,
        note=text_field(fields, "note"),
    )


def _fields(head: RecordHead) -> dict[str, FrontmatterValue]:
    if head.head is None:
        raise RecordFieldError(head.problem or "could not be read")
    return record_fields(head.head)


def _names(value: FrontmatterValue | None, name: str) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    items = value if isinstance(value, list) else [value]
    for item in items:
        if _TICKET.fullmatch(item) is None:
            raise RecordFieldError(f"{name} has an invalid item: {item[:64]}")
    return tuple(dict.fromkeys(items))


def _broken(n: int, ticket: str | None, problem: str) -> ChangeRequest:
    return ChangeRequest(
        n=n, ticket=ticket, status=None, plan_to=None, affected=(), problem=problem
    )


def _unreadable(name: str, why: str) -> str:
    return one_line(f"{name} could not be read ({why}). {FIX_IT}")
