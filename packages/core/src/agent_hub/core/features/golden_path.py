"""A feature's golden path (AGH-136 D3-D5, S8): each step done only when the whole feature is.

Steps, in order: Spec, Research and Plan (their record file is written; one left out while a
later record exists is ``skipped``), Tickets (every planned ticket has a tracker id), Implement
(every ticket Done in Linear and every AC passing), Review (every ticket reviewed: Done in Linear
or an approved review record), Evaluate (the latest eval of every AC is a SHIP, none waiting on
owner steps) and Shipped (every ticket Done in Linear). Canceled tickets and withdrawn ACs are
left out of every count.

The fold: steps hold in turn until the first that does not, the gate; it is ``current`` (or
``unknown`` when its evidence cannot be read) and the ``phase``. No step after the gate is
``done``: one whose own condition holds is ``blocked`` naming the gate, one with recorded
evidence for part of the feature (passing ACs, created tickets, review records, a SHIP over
some ACs) is ``partial``, one that cannot be read is ``unknown``, the rest ``pending``. Without
Linear (the plan fallback), ticket states are unknown: Implement's tickets, Review without a
record for every ticket and Shipped are ``unknown``, never done.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from agent_hub.core.features.feature_record import RecordAc
from agent_hub.core.features.feature_view import (
    FeaturePhase,
    GoldenPath,
    GoldenStep,
    StepProgress,
    StepState,
    TicketsSource,
)
from agent_hub.core.features.ticket_view import TicketRow

SPEC_FILE: Final = "spec.md"
RESEARCH_FILE: Final = "research.md"
PLAN_FILE: Final = "plan.md"
ISSUES_FILE: Final = "issues.md"
RECORD_FILE: Final = "features.json"
MAX_EVALS: Final = 200
MAX_REVIEWS: Final = 500
LINEAR_NOT_CONNECTED: Final = "Linear not connected"
LINEAR_NOT_LOADED: Final = "Linear not loaded yet"
LINEAR_NOT_LOADED_REASON: Final = "Ticket status from Linear not loaded yet; open the Tickets tab."
STEP_TITLES: Final[dict[FeaturePhase, str]] = {
    "spec": "Spec",
    "research": "Research",
    "plan": "Plan",
    "tickets": "Tickets",
    "implement": "Implement",
    "review": "Review",
    "evaluate": "Evaluate",
    "shipped": "Shipped",
}
_DOC_STEPS: Final[tuple[tuple[FeaturePhase, str], ...]] = (
    ("spec", SPEC_FILE),
    ("research", RESEARCH_FILE),
    ("plan", PLAN_FILE),
)
_CANCELED: Final = frozenset({"canceled", "duplicate"})
_NOT_YET: Final = {"tickets": "tickets not Done", "ACs": "ACs not passing"}


@dataclass(frozen=True, kw_only=True, slots=True)
class EvalGate:
    """What the feature's evals say about its ACs (the caller folds the eval records).

    ``evals`` counts the eval records read (the legacy ``eval.md`` included); ``covered`` the
    non-withdrawn ACs whose latest eval is SHIP or SHIP-WITH-OWNER-STEPS; ``owner_steps`` those
    of them whose latest is SHIP-WITH-OWNER-STEPS. ``scope_recorded`` is False for a legacy
    ``eval.md`` with no scope that does not cover every AC; ``skipped`` counts the eval files
    over the cap, left unread.
    """

    evals: int
    covered: int
    owner_steps: int
    scope_recorded: bool = True
    skipped: int = 0


NO_EVALS: Final = EvalGate(evals=0, covered=0, owner_steps=0)


@dataclass(frozen=True, kw_only=True, slots=True)
class GoldenInputs:
    """Everything the golden path reads of one feature.

    ``files`` names the record files present; ``rows`` the ticket rows (Linear's states when
    ``source`` is ``linear``, None in the plan fallback; ``reviewed`` per D4); ``acs`` the
    record's ACs; ``approved_reviews`` the approved review records of the feature's tickets and
    ``reviews_skipped`` the review files over the cap. ``not_loaded`` says the plan fallback is
    a cold cache with a key present (E5), not a missing connection.
    """

    files: tuple[str, ...]
    rows: tuple[TicketRow, ...]
    acs: tuple[RecordAc, ...]
    coverage: EvalGate = NO_EVALS
    approved_reviews: int = 0
    reviews_skipped: int = 0
    source: TicketsSource
    not_loaded: bool = False


@dataclass(frozen=True, kw_only=True, slots=True)
class _Own:
    """A step judged alone: whether its own condition ``holds`` (None: cannot tell, ``reason``
    says why), its texts, and whether part of it is recorded (``started``)."""

    holds: bool | None
    meta: str | None = None
    reason: str | None = None
    progress: StepProgress | None = None
    started: bool = False
    skippable: bool = False


@dataclass(frozen=True, kw_only=True, slots=True)
class _Facts:
    inputs: GoldenInputs
    active: tuple[TicketRow, ...]
    acs: tuple[RecordAc, ...]
    done: int

    @property
    def linear(self) -> bool:
        return self.inputs.source == "linear"

    @property
    def unread(self) -> tuple[str, str]:
        """The (meta, reason) of a count Linear would give and was not read."""
        if self.inputs.not_loaded:
            return LINEAR_NOT_LOADED, LINEAR_NOT_LOADED_REASON
        return LINEAR_NOT_CONNECTED, LINEAR_NOT_CONNECTED


def golden_path(inputs: GoldenInputs) -> GoldenPath:
    """The feature's steps with their state, meta, reason and progress, and its phase."""
    owns = _owns(inputs)
    steps: list[GoldenStep] = []
    gate: GoldenStep | None = None
    for name, own in owns.items():
        state, reason = _before_gate(own) if gate is None else _after_gate(own, gate)
        step = GoldenStep(
            name=name, state=state, meta=own.meta, reason=reason, progress=own.progress
        )
        if gate is None and state not in ("done", "skipped"):
            gate = step
        steps.append(step)
    return GoldenPath(steps=tuple(steps), phase="shipped" if gate is None else gate.name)


def own_conditions(inputs: GoldenInputs) -> dict[FeaturePhase, bool | None]:
    """Whether each step's own condition holds, earlier gates aside (None: cannot tell)."""
    return {name: own.holds for name, own in _owns(inputs).items()}


def _before_gate(own: _Own) -> tuple[StepState, str | None]:
    if own.holds is True:
        return "done", None
    if own.skippable:
        return "skipped", None
    return ("unknown" if own.holds is None else "current"), own.reason


def _after_gate(own: _Own, gate: GoldenStep) -> tuple[StepState, str | None]:
    title = STEP_TITLES[gate.name]
    waiting = f"{title} is unknown" if gate.state == "unknown" else f"{title} is not done"
    if own.holds is True:
        return "blocked", waiting
    if own.skippable:
        return "skipped", None
    if own.holds is None:
        return "unknown", own.reason
    return ("partial" if own.started else "pending"), waiting


def _owns(inputs: GoldenInputs) -> dict[FeaturePhase, _Own]:
    active = tuple(
        row for row in inputs.rows if row.state is None or row.state.type not in _CANCELED
    )
    facts = _Facts(
        inputs=inputs,
        active=active,
        acs=tuple(ac for ac in inputs.acs if not ac.withdrawn),
        done=sum(row.state is not None and row.state.type == "completed" for row in active),
    )
    owns: dict[FeaturePhase, _Own] = {
        name: _document(facts, file=file, later=_DOC_STEPS[index + 1 :])
        for index, (name, file) in enumerate(_DOC_STEPS)
    }
    judges: tuple[tuple[FeaturePhase, Callable[[_Facts], _Own]], ...] = (
        ("tickets", _tickets),
        ("implement", _implement),
        ("review", _review),
        ("evaluate", _evaluate),
        ("shipped", _shipped),
    )
    for name, judge in judges:
        owns[name] = judge(facts)
    return owns


def _document(facts: _Facts, *, file: str, later: tuple[tuple[FeaturePhase, str], ...]) -> _Own:
    files = facts.inputs.files
    if file in files:
        return _Own(holds=True)
    later_evidence = (
        any(name in files for _, name in later)
        or any(name in files for name in (ISSUES_FILE, RECORD_FILE))
        or bool(facts.inputs.rows or facts.acs or facts.inputs.coverage.evals)
    )
    return _Own(holds=False, reason=f"{file} not written", skippable=later_evidence)


def _tickets(facts: _Facts) -> _Own:
    total = len(facts.active)
    if total == 0:
        if ISSUES_FILE in facts.inputs.files:
            return _Own(holds=True)
        return _Own(holds=False, reason="no tickets planned in features.json")
    created = sum(row.id is not None for row in facts.active)
    return _Own(
        holds=created == total,
        meta=f"{created} of {total} created",
        reason=f"{total - created} of {total} tickets have no tracker id yet",
        progress=StepProgress(done=created, total=total),
        started=created > 0,
    )


def _implement(facts: _Facts) -> _Own:
    total, acs = len(facts.active), len(facts.acs)
    passing = sum(ac.passes for ac in facts.acs)
    if total == 0 and acs == 0:
        return _Own(holds=False, reason="no tickets or acceptance criteria recorded")
    counts: list[tuple[int, int, str]] = []
    if total and facts.linear:
        counts.append((facts.done, total, "tickets"))
    if acs:
        counts.append((passing, acs, "ACs"))
    progress = StepProgress(done=counts[0][0], total=counts[0][1]) if counts else None
    meta = " · ".join(f"{done}/{of} {noun}" for done, of, noun in counts) or None
    started = passing > 0 or facts.done > 0
    missing = [f"{of - done} of {of} {_NOT_YET[noun]}" for done, of, noun in counts if done < of]
    if missing:
        reason = "; ".join(missing)
        return _Own(holds=False, meta=meta, reason=reason, progress=progress, started=started)
    if total and not facts.linear:
        _, reason = facts.unread
        return _Own(holds=None, meta=meta, reason=reason, progress=progress, started=started)
    return _Own(holds=True, meta=meta, progress=progress, started=started)


def _review(facts: _Facts) -> _Own:
    started = facts.inputs.approved_reviews > 0
    if facts.inputs.reviews_skipped:
        return _Own(
            holds=None,
            reason=f"more than {MAX_REVIEWS} review records; not all were read",
            started=started,
        )
    total = len(facts.active)
    if total == 0:
        return _Own(holds=None, reason="no tickets recorded")
    reviewed = sum(row.reviewed is True for row in facts.active)
    progress = StepProgress(done=reviewed, total=total)
    meta = f"{reviewed}/{total} reviewed"
    if reviewed == total:
        return _Own(holds=True, meta=meta, progress=progress, started=started)
    if any(row.reviewed is None for row in facts.active):
        unread_meta, reason = facts.unread
        return _Own(holds=None, meta=unread_meta, reason=reason, progress=progress, started=started)
    reason = f"{total - reviewed} of {total} tickets not reviewed"
    return _Own(holds=False, meta=meta, reason=reason, progress=progress, started=started)


def _evaluate(facts: _Facts) -> _Own:
    gate = facts.inputs.coverage
    total = len(facts.acs)
    if gate.skipped:
        return _Own(holds=None, reason=f"more than {MAX_EVALS} evals; not all were read")
    if gate.evals == 0:
        return _Own(holds=False, reason="no eval yet")
    if not gate.scope_recorded:
        return _Own(
            holds=False,
            meta="partial: scope not recorded",
            reason="eval.md records no scope and not every AC passes",
            started=True,
        )
    if total == 0:
        return _Own(holds=False, reason="no acceptance criteria in features.json")
    covered = min(gate.covered, total)
    progress = StepProgress(done=covered, total=total)
    if covered < total:
        meta = (
            f"partial: covers {covered} of {total} ACs" if covered else f"covers 0 of {total} ACs"
        )
        reason = f"{total - covered} of {total} ACs not covered by a SHIP"
        return _Own(holds=False, meta=meta, reason=reason, progress=progress, started=covered > 0)
    if gate.owner_steps:
        return _Own(
            holds=False,
            meta="waiting: owner steps",
            reason=f"{gate.owner_steps} ACs wait on owner steps (SHIP-WITH-OWNER-STEPS)",
            progress=progress,
            started=True,
        )
    return _Own(holds=True, meta=f"covers {total} of {total} ACs", progress=progress)


def _shipped(facts: _Facts) -> _Own:
    total = len(facts.active)
    if total == 0:
        return _Own(holds=None, reason="no tickets recorded")
    if not facts.linear:
        meta, reason = facts.unread
        return _Own(holds=None, meta=meta, reason=reason)
    return _Own(
        holds=facts.done == total,
        meta=f"{facts.done}/{total} Done",
        reason=f"{total - facts.done} of {total} tickets not Done in Linear",
        progress=StepProgress(done=facts.done, total=total),
    )
