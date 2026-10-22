"""A ticket's own flow (two-level-flows AC-1.8, AC-1.9): a pure fold over the feature's records.

Steps, in order: Context, Preflight, Implement, Review, Eval, PR and Merged. Each is judged by its
evidence alone: Context is done when ``tickets/<ticket>/brief.md`` exists; Preflight by the latest
run of ``tickets/<ticket>/preflight.json`` and the plan change requests (AC-2.5, AC-2.8: done with
no drift or local drift, ``waiting`` while the ticket's own request is open, ``stale`` when a newer
plan version was approved than its latest run checked, or when a blocker's outcome was recorded
after it, AC-3.3, ``blocked`` on plan drift otherwise);
Implement is done when a review round of the ticket exists
(``reviews/<ticket>/<reviewer>-r<N>.json``), current once its ticket ``plan.md`` exists; Review
when a review record of it is ``approved`` (``current`` while its records only request changes),
Eval by the latest eval naming it (NO-SHIP is ``blocked``), PR when its review record or an eval
naming it names a pull request, and Merged when Linear has it ``completed`` or its
``tickets/<ticket>/outcome.md`` exists ("Outcome recorded", D-5; ``unknown`` when Linear was not
read and no outcome is recorded, or when the outcome cannot be read). The flow's one ``signal``:
waiting for the owner, then held by another ticket's open request, then a re-run needed, then
local drift. A record that cannot be read turns
only the step it feeds ``unknown``, with its problem.

A step with no evidence reads ``unrecorded`` ("Not recorded") when a later step has some, else
``pending`` ("Not reached"), so no step looks further along than an earlier one for the wrong
reason. A ticket is named by its plan key and its tracker id, in any case; a malformed record
counts for nothing. Same records, same flow, whatever their order: an eval's "latest" is the
partial order of ``feature_evals``, and every other step asks whether any record says so.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, get_args

from agent_hub.core.features.feature_evals import latest_verdict
from agent_hub.core.features.feature_reviews import (
    ReviewRecord,
    approved_tickets,
    names_pull_request,
)
from agent_hub.core.features.feature_view import EvalRecord, StepState, Verdict
from agent_hub.core.features.output_models import PreflightRecord, PreflightRun
from agent_hub.core.features.ticket_planning import DONE_TYPES
from agent_hub.core.features.ticket_records import (
    FIX_IT,
    MAX_TICKET_FOLDERS,
    NO_REQUESTS,
    TICKETS_FOLDER,
    ChangeRequests,
    OutcomeFile,
    TicketFiles,
    TicketOutcome,
    preflight_record,
    recorded_outcomes,
)
from agent_hub.core.features.ticket_view import TicketFlow, TicketRow, TicketStep, TicketStepName

_STEPS: Final[tuple[TicketStepName, ...]] = get_args(TicketStepName.__value__)
# A step the ticket is past: done, or left without a record before later evidence.
_PASSED: Final = ("done", "unrecorded")
OUTCOME_RECORDED: Final = "Outcome recorded"
TICKETS_UNREAD: Final = (
    f"not every folder in {TICKETS_FOLDER}/ was read (more than {MAX_TICKET_FOLDERS}, or over the "
    f"read budget). {FIX_IT}"
)

type _Found = tuple[StepState, str | None]


@dataclass(frozen=True, kw_only=True, slots=True)
class TicketEvidence:
    """What the feature's records say about its tickets (built by ``ticket_evidence``).

    ``rounds`` names (upper case) the tickets with a review round; ``reviews`` are the feature's
    review records; ``evals`` its readable evals by each ticket name they list (upper case);
    ``unread`` is Build's meta when Linear was not read (Merged is then unknown), None when it
    was. ``files`` and ``preflights`` hold each ticket folder read and its parsed preflight record
    (or its problem), by name (upper case); ``tickets_unread`` says not every ticket folder was
    read; ``requests`` are the plan change requests and ``approved`` the newest approved plan
    version (the plan's own, or an approved request's). ``outcomes`` holds each ticket folder's
    outcome (or its problem) by name (upper case), and ``aliases`` each row's names (upper case) by
    its ``ref``, so a blocker's outcome is found under its key or id. ``_verdicts`` caches the
    latest verdict of
    each set of evals already folded (no part of its value: never compared or shown).
    """

    rounds: frozenset[str]
    reviews: Sequence[ReviewRecord]
    evals: Mapping[str, tuple[EvalRecord, ...]]
    unread: str | None
    files: Mapping[str, TicketFiles]
    preflights: Mapping[str, PreflightRecord | str]
    tickets_unread: str | None
    requests: ChangeRequests
    approved: int | None
    outcomes: Mapping[str, TicketOutcome | str] = field(default_factory=dict)
    aliases: Mapping[str, frozenset[str]] = field(default_factory=dict)
    _verdicts: dict[tuple[EvalRecord, ...], Verdict | None] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )


def ticket_evidence(
    *,
    rounds: frozenset[str],
    reviews: Sequence[ReviewRecord],
    evals: Iterable[EvalRecord],
    unread: str | None,
    tickets: Iterable[TicketFiles] = (),
    tickets_skipped: int = 0,
    requests: ChangeRequests = NO_REQUESTS,
    plan_version: int | None = None,
    outcomes: Iterable[OutcomeFile] = (),
    rows: Iterable[TicketRow] = (),
) -> TicketEvidence:
    """The evidence of a feature's tickets, its evals indexed once by the ticket names they list
    and each ticket folder's preflight and outcome parsed once; ``plan_version`` is the plan's
    version, ``rows`` the feature's tickets (their names find a blocker's outcome)."""
    by_ticket: dict[str, list[EvalRecord]] = {}
    for record in evals:
        if record.problem is None:
            for name in dict.fromkeys(ticket.upper() for ticket in record.tickets):
                by_ticket.setdefault(name, []).append(record)
    files: dict[str, TicketFiles] = {}
    for found in sorted(tickets, key=lambda found: found.name):
        files.setdefault(found.name.upper(), found)
    preflights = {
        name: parsed
        for name, found in files.items()
        if (parsed := preflight_record(found.preflight, folder=found.name)) is not None
    }
    versions = [v for v in (plan_version, requests.approved_version) if v is not None]
    return TicketEvidence(
        rounds=rounds,
        reviews=reviews,
        evals={name: tuple(named) for name, named in by_ticket.items()},
        unread=unread,
        files=files,
        preflights=preflights,
        tickets_unread=TICKETS_UNREAD if tickets_skipped else None,
        requests=requests,
        approved=max(versions, default=None),
        outcomes=recorded_outcomes(outcomes),
        aliases={
            row.ref.upper(): frozenset(name.upper() for name in (row.ref, row.key, row.id) if name)
            for row in rows
        },
    )


def ticket_flow(row: TicketRow, evidence: TicketEvidence) -> TicketFlow | None:
    """The ticket's seven steps and its current one; None for an epic, which only tracks."""
    if row.children:
        return None
    names = {name.upper() for name in (row.key, row.id) if name}
    outcome = _outcome(names, evidence)
    completed = row.state is not None and row.state.type in DONE_TYPES
    merged = completed or isinstance(outcome, TicketOutcome)
    found, signal = _picked_up(names, evidence, merged=merged, row=row)
    found |= _delivered(names, evidence, merged=completed, outcome=outcome)
    last = max(
        (_STEPS.index(name) for name, (state, _) in found.items() if state != "unknown"),
        default=-1,
    )
    steps = tuple(
        TicketStep(name=name, state=found[name][0], meta=found[name][1])
        if name in found
        else TicketStep(name=name, state="unrecorded" if index < last else "pending", meta=None)
        for index, name in enumerate(_STEPS)
    )
    current: TicketStepName = next(
        (step.name for step in steps if step.state not in _PASSED), "merged"
    )
    return TicketFlow(steps=steps, current=current, signal=signal)


def _outcome(names: set[str], evidence: TicketEvidence) -> TicketOutcome | str | None:
    """The outcome recorded under one of ``names`` (the first in sorted order), or its problem."""
    return next((evidence.outcomes[n] for n in sorted(names) if n in evidence.outcomes), None)


def _picked_up(
    names: set[str], evidence: TicketEvidence, *, merged: bool, row: TicketRow
) -> tuple[dict[TicketStepName, _Found], str | None]:
    """Context, Preflight and the ticket plan's Implement from ``tickets/<ticket>/``, and the
    flow's signal; Context and Preflight unknown when its folder was left unread over the cap. A
    ticket whose own request is open waits for the owner whatever its Preflight reads; only the
    other tickets a request names are held."""
    found: dict[TicketStepName, _Found] = {}
    files = next((evidence.files[name] for name in sorted(names) if name in evidence.files), None)
    signal = None
    if files is None and evidence.tickets_unread is not None:
        found["context"] = found["preflight"] = ("unknown", evidence.tickets_unread)
    else:
        if files is not None and files.brief:
            found["context"] = ("done", None)
        preflight, signal = _preflight(names, evidence, merged=merged, row=row)
        if preflight is not None:
            found["preflight"] = preflight
    asking = any(
        request.status == "open" and request.ticket and request.ticket.upper() in names
        for request in evidence.requests.requests
    )
    if asking:
        signal = "Waiting for you: plan change"
    elif not merged and names & evidence.requests.paused:
        signal = "Held: plan change pending"
    if files is not None and files.plan:
        found["implement"] = ("current", "Ticket plan written")
    return found, signal


def _delivered(
    names: set[str],
    evidence: TicketEvidence,
    *,
    merged: bool,
    outcome: TicketOutcome | str | None,
) -> dict[TicketStepName, _Found]:
    """Implement (a review round), Review, Eval, PR and Merged from the feature's records; Merged
    from the ticket's outcome first (its problem makes it unknown), then Linear (``merged``)."""
    reviews = [r for r in evidence.reviews if r.problem is None and r.ticket.upper() in names]
    evals = tuple(
        dict.fromkeys(record for name in sorted(names) for record in evidence.evals.get(name, ()))
    )
    found: dict[TicketStepName, _Found] = {}
    if names & evidence.rounds:
        found["implement"] = ("done", None)
    if reviews:
        found["review"] = (
            ("done", None) if approved_tickets(reviews) else ("current", "Changes requested")
        )
    verdict = _verdict(evals, evidence._verdicts)
    if verdict is not None:
        found["eval"] = ("blocked" if verdict == "NO-SHIP" else "done", verdict)
    prs = (*(review.pr for review in reviews), *(pr for record in evals for pr in record.prs))
    if any(names_pull_request(pr) for pr in prs):
        found["pr"] = ("done", None)
    step = _merged(outcome, merged=merged, unread=evidence.unread)
    if step is not None:
        found["merged"] = step
    return found


def _merged(
    outcome: TicketOutcome | str | None, *, merged: bool, unread: str | None
) -> _Found | None:
    """Merged: the ticket's outcome first (its problem makes it unknown), then Linear's
    ``completed`` (``merged``), else unknown when Linear was not read (``unread``)."""
    if isinstance(outcome, str):
        return "unknown", outcome
    if outcome is not None:
        return "done", OUTCOME_RECORDED
    if merged:
        return "done", None
    return None if unread is None else ("unknown", unread)


def _preflight(
    names: set[str], evidence: TicketEvidence, *, merged: bool, row: TicketRow
) -> tuple[_Found | None, str | None]:
    """The Preflight step and the signal it gives, from the ticket's own change requests and the
    latest run of its preflight record; (None, None) when neither says anything."""
    record = next((evidence.preflights[n] for n in sorted(names) if n in evidence.preflights), None)
    if isinstance(record, str):
        return ("unknown", record), None
    asked = [r for r in evidence.requests.requests if r.ticket and r.ticket.upper() in names]
    broken = next((request.problem for request in asked if request.problem), None)
    if broken is not None:
        return ("unknown", broken), None
    if any(request.status == "open" for request in asked):
        return ("waiting", "Waiting for you"), None
    if record is None or not record.runs:
        return None, None
    latest = record.runs[-1]
    stale = None if merged else _stale(latest, row, evidence)
    if stale is not None:
        return ("stale", stale), stale
    if latest.drift == "plan":
        return ("blocked", "Plan drift"), None
    if latest.drift == "local":
        count = len(latest.local_notes)
        local = f"Local drift · {count} note{'' if count == 1 else 's'}"
        return ("done", local), local
    return ("done", None), None


def _stale(latest: PreflightRun, row: TicketRow, evidence: TicketEvidence) -> str | None:
    """Why a ticket's latest preflight needs a re-run: a newer plan version approved than it
    checked (AC-2.8), else a blocker merged after it ran (AC-3.3); None when neither."""
    approved = evidence.approved
    if approved is not None and latest.plan_version < approved:
        return f"Plan v{approved} approved: re-run preflight"
    blocker = _merged_since(row, evidence, latest.ran_at)
    return None if blocker is None else f"{blocker} merged: re-run preflight"


def _merged_since(row: TicketRow, evidence: TicketEvidence, ran_at: datetime) -> str | None:
    """The first blocker of ``row`` (in its plan's order) whose outcome was recorded after the
    ticket's latest preflight ran at ``ran_at``; None when none was (AC-3.3)."""
    for edge in row.blocked_by:
        names = evidence.aliases.get(edge.ref.upper(), frozenset({edge.ref.upper()}))
        outcome = _outcome(set(names), evidence)
        if isinstance(outcome, TicketOutcome) and outcome.merged_at > ran_at:
            return edge.ref
    return None


def _verdict(
    evals: tuple[EvalRecord, ...], folded: dict[tuple[EvalRecord, ...], Verdict | None]
) -> Verdict | None:
    """The latest verdict of ``evals``, folded once per set of evals."""
    if evals not in folded:
        folded[evals] = latest_verdict(evals)
    return folded[evals]
