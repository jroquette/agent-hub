"""A ticket's own flow (two-level-flows AC-1.8, AC-1.9): a pure fold over the feature's records.

Steps, in order: Context, Preflight, Implement, Review, Eval, PR and Merged. Each is judged by its
evidence alone: Implement is done when a review round of the ticket exists
(``reviews/<ticket>/<reviewer>-r<N>.json``), Review when a review record of it is ``approved``
(``current`` while its records only request changes), Eval by the latest eval naming it
(NO-SHIP is ``blocked``), PR when its review record or an eval naming it names a pull request,
and Merged when Linear has it ``completed`` (``unknown`` when Linear was not read). Context and
Preflight have no record yet (they arrive with the ``implement`` workflow, S2).

A step with no evidence reads ``unrecorded`` ("Not recorded") when a later step has some, else
``pending`` ("Not reached"), so no step looks further along than an earlier one for the wrong
reason. A ticket is named by its plan key and its tracker id, in any case; a malformed record
counts for nothing. Same records, same flow, whatever their order: an eval's "latest" is the
partial order of ``feature_evals``, and every other step asks whether any record says so.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, get_args

from agent_hub.core.features.feature_evals import latest_verdict
from agent_hub.core.features.feature_reviews import (
    ReviewRecord,
    approved_tickets,
    names_pull_request,
)
from agent_hub.core.features.feature_view import EvalRecord, StepState, Verdict
from agent_hub.core.features.ticket_planning import DONE_TYPES
from agent_hub.core.features.ticket_view import TicketFlow, TicketRow, TicketStep, TicketStepName

_STEPS: Final[tuple[TicketStepName, ...]] = get_args(TicketStepName.__value__)
# A step the ticket is past: done, or left without a record before later evidence.
_PASSED: Final = ("done", "unrecorded")


@dataclass(frozen=True, kw_only=True, slots=True)
class TicketEvidence:
    """What the feature's records say about its tickets (built by ``ticket_evidence``).

    ``rounds`` names (upper case) the tickets with a review round; ``reviews`` are the feature's
    review records; ``evals`` its readable evals by each ticket name they list (upper case);
    ``unread`` is Build's meta when Linear was not read (Merged is then unknown), None when it
    was. ``verdicts`` holds the latest verdict of each set of evals already folded.
    """

    rounds: frozenset[str]
    reviews: Sequence[ReviewRecord]
    evals: Mapping[str, tuple[EvalRecord, ...]]
    unread: str | None
    verdicts: dict[tuple[EvalRecord, ...], Verdict | None] = field(default_factory=dict)


def ticket_evidence(
    *,
    rounds: frozenset[str],
    reviews: Sequence[ReviewRecord],
    evals: Iterable[EvalRecord],
    unread: str | None,
) -> TicketEvidence:
    """The evidence of a feature's tickets, its evals indexed once by the ticket names they list."""
    by_ticket: dict[str, list[EvalRecord]] = {}
    for record in evals:
        if record.problem is None:
            for name in dict.fromkeys(ticket.upper() for ticket in record.tickets):
                by_ticket.setdefault(name, []).append(record)
    return TicketEvidence(
        rounds=rounds,
        reviews=reviews,
        evals={name: tuple(named) for name, named in by_ticket.items()},
        unread=unread,
    )


def ticket_flow(row: TicketRow, evidence: TicketEvidence) -> TicketFlow | None:
    """The ticket's seven steps and its current one; None for an epic, which only tracks."""
    if row.children:
        return None
    names = {name.upper() for name in (row.key, row.id) if name}
    reviews = [r for r in evidence.reviews if r.problem is None and r.ticket.upper() in names]
    evals = tuple(
        dict.fromkeys(record for name in sorted(names) for record in evidence.evals.get(name, ()))
    )
    found: dict[TicketStepName, tuple[StepState, str | None]] = {}
    if names & evidence.rounds:
        found["implement"] = ("done", None)
    if reviews:
        found["review"] = (
            ("done", None) if approved_tickets(reviews) else ("current", "Changes requested")
        )
    verdict = _verdict(evals, evidence.verdicts)
    if verdict is not None:
        found["eval"] = ("blocked" if verdict == "NO-SHIP" else "done", verdict)
    prs = (*(review.pr for review in reviews), *(pr for record in evals for pr in record.prs))
    if any(names_pull_request(pr) for pr in prs):
        found["pr"] = ("done", None)
    if row.state is not None and row.state.type in DONE_TYPES:
        found["merged"] = ("done", None)
    elif evidence.unread is not None:
        found["merged"] = ("unknown", evidence.unread)
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
    return TicketFlow(steps=steps, current=current)


def _verdict(
    evals: tuple[EvalRecord, ...], folded: dict[tuple[EvalRecord, ...], Verdict | None]
) -> Verdict | None:
    """The latest verdict of ``evals``, folded once per set of evals."""
    if evals not in folded:
        folded[evals] = latest_verdict(evals)
    return folded[evals]
