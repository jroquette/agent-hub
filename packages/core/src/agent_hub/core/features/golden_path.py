"""A feature's golden path (AGH-136 D3-D5, S8; two-level-flows AC-1.1-1.7): the feature steps.

Steps, in order: Spec (``spec.md`` written; with only ``brief.md`` it is current, "Brief only"),
UX design (every top-level ``ux-*.md`` says ``status: approved``; none while a later record
exists is ``skipped``, "No screen change recorded"), Research and Plan (their record file is
written; one left out while a later record exists is ``skipped``; Plan's meta is the plan's
version, and its signal says the next version waits for the owner while a plan change request is
open, AC-2.8), Tickets (every planned ticket has a tracker id), Build (every ticket merged: Done in
Linear or its outcome recorded, D-5; its meta counts the tickets an open change request pauses),
Acceptance (the latest
whole-feature eval is SHIP, or SHIP-WITH-OWNER-STEPS whose owner steps the owner signed off;
ticket evals never make it done) and Shipped (Build and Acceptance done). Canceled tickets and
withdrawn ACs are left out of every count; an epic (a ticket with children) counts only under
Tickets, as it tracks the others. Each ticket's own steps are its row's, not the golden path's.

The fold: steps hold in turn until the first that does not, the gate; it is ``current`` (or
``unknown`` when its evidence cannot be read, ``unrecorded`` when its record was never written)
and the ``phase``. No step after the gate is ``done``: one whose own condition holds is
``blocked`` naming the gate, one with recorded evidence for part of the feature (created or
merged tickets, ticket evals covering some ACs, a design written) is ``partial``, one that cannot
be read is ``unknown``, the rest ``pending``. Without Linear (the plan fallback), ticket states
are unknown: Build and Shipped are ``unknown``, done only when every ticket's outcome is recorded.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Final

from agent_hub.core.features.feature_record import RecordAc
from agent_hub.core.features.feature_view import (
    FeaturePhase,
    GoldenPath,
    GoldenStep,
    OwnerWaitState,
    PlanView,
    StepProgress,
    StepState,
    TicketsSource,
    Verdict,
)
from agent_hub.core.features.ticket_records import NO_REQUESTS, ChangeRequests
from agent_hub.core.features.ticket_view import TicketRow

BRIEF_FILE: Final = "brief.md"
SPEC_FILE: Final = "spec.md"
RESEARCH_FILE: Final = "research.md"
PLAN_FILE: Final = "plan.md"
ISSUES_FILE: Final = "issues.md"
RECORD_FILE: Final = "features.json"
MAX_EVALS: Final = 200
LINEAR_NOT_CONNECTED: Final = "Linear not connected"
LINEAR_NOT_LOADED: Final = "Linear not loaded yet"
LINEAR_NOT_LOADED_REASON: Final = "Ticket status from Linear not loaded yet; open the Tickets tab."
STEP_TITLES: Final[dict[FeaturePhase, str]] = {
    "spec": "Spec",
    "ux_design": "UX design",
    "research": "Research",
    "plan": "Plan",
    "tickets": "Tickets",
    "build": "Build",
    "acceptance": "Acceptance",
    "shipped": "Shipped",
}
_CANCELED: Final = frozenset({"canceled", "duplicate"})


@dataclass(frozen=True, kw_only=True, slots=True)
class EvalGate:
    """What the feature's evals say (the caller folds the eval records).

    ``evals`` counts the eval records read (the legacy ``eval.md`` included); ``covered`` the
    non-withdrawn ACs whose latest eval is SHIP or SHIP-WITH-OWNER-STEPS; ``acceptance`` the
    verdict of the acceptance eval (the latest whole-feature one), None without one; ``wait``
    the state of what a SHIP-WITH-OWNER-STEPS acceptance eval waits on from the owner
    (``OwnerWaitState``, A9-A11, A15), None when the owner signed its steps off; ``owner_steps``
    the ACs it leaves as owner steps not signed off yet (``feature_evals.owner_wait``),
    ``reopened`` those of them whose latest eval is NO-SHIP, ``signable_after`` (``future``) when
    a sign-off becomes possible; ``skipped`` the eval files over the cap, left unread.
    """

    evals: int
    covered: int
    wait: OwnerWaitState | None = None
    owner_steps: int = 0
    reopened: int = 0
    signable_after: str | None = None
    skipped: int = 0
    acceptance: Verdict | None = None


NO_EVALS: Final = EvalGate(evals=0, covered=0)


@dataclass(frozen=True, kw_only=True, slots=True)
class GoldenInputs:
    """Everything the golden path reads of one feature.

    ``files`` names the record files present; ``rows`` the ticket rows (Linear's states when
    ``source`` is ``linear``, None in the plan fallback); ``acs`` the record's ACs;
    ``ux_designs`` whether each ``ux-*.md`` is approved, and ``ux_problem`` why they could not
    all be read; ``plan`` the plan's version (None without ``plan.md``); ``requests`` the plan
    change requests; ``merged`` the names (upper case) of the ticket folders whose outcome is
    recorded (a ticket merged whatever Linear says, D-5). ``not_loaded`` says the plan fallback is
    a cold cache with a key present (E5), not a missing connection.
    """

    files: tuple[str, ...]
    rows: tuple[TicketRow, ...]
    acs: tuple[RecordAc, ...]
    coverage: EvalGate = NO_EVALS
    ux_designs: tuple[bool, ...] = ()
    ux_problem: str | None = None
    plan: PlanView | None = None
    requests: ChangeRequests = NO_REQUESTS
    merged: frozenset[str] = frozenset()
    source: TicketsSource
    not_loaded: bool = False

    def is_merged(self, row: TicketRow) -> bool:
        """Whether ``row`` is merged: Done in Linear, or its outcome recorded (D-5)."""
        if row.state is not None and row.state.type == "completed":
            return True
        return any(name and name.upper() in self.merged for name in (row.key, row.id))


@dataclass(frozen=True, kw_only=True, slots=True)
class _Own:
    """A step judged alone: whether its own condition ``holds`` (None: cannot tell, ``reason``
    says why), its texts, whether part of it is recorded (``started``) and whether, as the gate,
    its record was never written (``unrecorded``) or it waits on the owner's decision
    (``waiting``)."""

    holds: bool | None
    meta: str | None = None
    signal: str | None = None
    reason: str | None = None
    progress: StepProgress | None = None
    started: bool = False
    skippable: bool = False
    unrecorded: bool = False
    waiting: bool = False


@dataclass(frozen=True, kw_only=True, slots=True)
class _Facts:
    inputs: GoldenInputs
    # Every ticket not canceled; ``active`` leaves out the epics, which only track the others.
    planned: tuple[TicketRow, ...]
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
            name=name,
            state=state,
            meta=own.meta,
            reason=reason,
            progress=own.progress,
            signal=own.signal,
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
    if own.holds is None:
        return "unknown", own.reason
    if own.waiting:
        return "waiting", own.reason
    return ("unrecorded" if own.unrecorded else "current"), own.reason


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
    planned = tuple(
        row for row in inputs.rows if row.state is None or row.state.type not in _CANCELED
    )
    active = tuple(row for row in planned if not row.children)
    facts = _Facts(
        inputs=inputs,
        planned=planned,
        active=active,
        acs=tuple(ac for ac in inputs.acs if not ac.withdrawn),
        done=sum(inputs.is_merged(row) for row in active),
    )
    judges: tuple[tuple[FeaturePhase, Callable[[_Facts], _Own]], ...] = (
        ("spec", _spec),
        ("ux_design", _ux_design),
        ("research", lambda facts: _document(facts, file=RESEARCH_FILE, later=(PLAN_FILE,))),
        ("plan", _plan),
        ("tickets", _tickets),
        ("build", _build),
        ("acceptance", _acceptance),
    )
    owns = {name: judge(facts) for name, judge in judges}
    owns["shipped"] = _shipped(owns["build"], owns["acceptance"])
    return owns


def _later_record(facts: _Facts, later: tuple[str, ...]) -> bool:
    """Whether a record of a later step exists: one of the ``later`` files, the ticket plan, a
    ticket, an AC or an eval."""
    files = facts.inputs.files
    return any(name in files for name in (*later, ISSUES_FILE, RECORD_FILE)) or bool(
        facts.inputs.rows or facts.acs or facts.inputs.coverage.evals
    )


def _document(facts: _Facts, *, file: str, later: tuple[str, ...]) -> _Own:
    if file in facts.inputs.files:
        return _Own(holds=True)
    return _Own(holds=False, reason=f"{file} not written", skippable=_later_record(facts, later))


def _spec(facts: _Facts) -> _Own:
    own = _document(facts, file=SPEC_FILE, later=(RESEARCH_FILE, PLAN_FILE))
    if own.holds or own.skippable or BRIEF_FILE not in facts.inputs.files:
        return own
    return replace(own, meta="Brief only · spec not written")


def _ux_design(facts: _Facts) -> _Own:
    designs = facts.inputs.ux_designs
    if facts.inputs.ux_problem is not None:
        return _Own(holds=None, reason=facts.inputs.ux_problem)
    if not designs:
        later = _later_record(facts, (RESEARCH_FILE, PLAN_FILE))
        meta = "No screen change recorded" if later else None
        return _Own(holds=False, meta=meta, reason="no ux-*.md written", skippable=later)
    total, drafts = len(designs), designs.count(False)
    count = f"{total} design{'' if total == 1 else 's'}"
    if not drafts:
        return _Own(holds=True, meta=f"{count} approved")
    return _Own(
        holds=False,
        meta=f"{count} · {drafts} draft",
        reason=f"{drafts} of {total} UX designs not approved",
        started=True,
    )


def _plan(facts: _Facts) -> _Own:
    own = replace(_document(facts, file=PLAN_FILE, later=()), signal=_plan_signal(facts))
    plan = facts.inputs.plan
    if not own.holds or plan is None:
        return own
    if plan.version is None:
        return _Own(holds=None, reason=plan.problem, signal=own.signal)
    amended = len(plan.amendments)
    meta = f"v{plan.version}"
    if amended:
        meta += f" · {amended} amendment{'' if amended == 1 else 's'}"
    return _Own(holds=True, meta=meta, signal=own.signal)


def _plan_signal(facts: _Facts) -> str | None:
    """The first open change request's version waiting for the owner, else why the change
    requests could not all be read."""
    requests = facts.inputs.requests
    if requests.open:
        return f"v{requests.open[0].plan_to} waits for you"
    return requests.problem or next(
        (request.problem for request in requests.requests if request.problem), None
    )


def _tickets(facts: _Facts) -> _Own:
    total = len(facts.planned)
    if total == 0:
        if ISSUES_FILE in facts.inputs.files:
            return _Own(holds=True)
        return _Own(holds=False, reason="no tickets planned in features.json")
    created = sum(row.id is not None for row in facts.planned)
    return _Own(
        holds=created == total,
        meta=f"{created} of {total} created",
        reason=f"{total - created} of {total} tickets have no tracker id yet",
        progress=StepProgress(done=created, total=total),
        started=created > 0,
    )


def _build(facts: _Facts) -> _Own:
    """Build is every ticket merged (Done in Linear, or its outcome recorded); its meta also
    counts those in progress. With no ticket to build (Tickets done by ``issues.md`` alone, or
    only epics) it is never done: "No tickets planned". Without Linear it is unknown unless every
    ticket's outcome is recorded."""
    total = len(facts.active)
    if total == 0:
        return _Own(holds=False, meta="No tickets planned", reason="no tickets planned")
    if not facts.linear and facts.done < total:
        meta, reason = facts.unread
        return _Own(holds=None, meta=meta, reason=reason)
    working = sum(
        row.state is not None and row.state.type == "started" and not facts.inputs.is_merged(row)
        for row in facts.active
    )
    meta = f"{facts.done} of {total} merged"
    if working:
        meta += f" · {working} in progress"
    meta += _paused(facts)
    return _Own(
        holds=facts.done == total,
        meta=meta,
        reason=f"{total - facts.done} of {total} tickets not merged",
        progress=StepProgress(done=facts.done, total=total),
        started=facts.done > 0,
    )


def _paused(facts: _Facts) -> str:
    """ " · n paused for a plan change": the tickets not merged an open change request pauses."""
    paused = facts.inputs.requests.paused
    count = sum(
        not facts.inputs.is_merged(row)
        and any(name and name.upper() in paused for name in (row.key, row.id))
        for row in facts.active
    )
    return f" · {count} paused for a plan change" if count else ""


def _acceptance(facts: _Facts) -> _Own:
    gate = facts.inputs.coverage
    if gate.skipped:
        return _Own(holds=None, reason=f"more than {MAX_EVALS} evals; not all were read")
    if gate.acceptance == "SHIP":
        return _Own(holds=True)
    if gate.acceptance == "NO-SHIP":
        return _Own(holds=False, meta="NO-SHIP", reason="the whole-feature eval says NO-SHIP")
    if gate.acceptance == "SHIP-WITH-OWNER-STEPS":
        return _owner_steps(gate)
    total = len(facts.acs)
    covered = min(gate.covered, total)
    return _Own(
        holds=False,
        meta=f"Ticket evals cover {covered} of {total} ACs" if total else None,
        reason="no whole-feature eval yet",
        progress=StepProgress(done=covered, total=total) if total else None,
        started=covered > 0,
        unrecorded=True,
    )


def _owner_steps(gate: EvalGate) -> _Own:
    """Acceptance over a SHIP-WITH-OWNER-STEPS acceptance eval, by the state of its wait (A9-A11,
    A15, A18, A19): signed off, no AC listed (``waiting`` for a sign-off the owner writes by hand),
    no sign-off able to follow it, reopened, or waiting for the owner's sign-off (``waiting``)."""
    one = gate.owner_steps == 1
    acs = f"{gate.owner_steps} AC{'' if one else 's'}"
    match gate.wait:
        case None:
            return _Own(holds=True, meta="Owner steps signed off")
        case "no_acs":
            return _Own(
                holds=False,
                meta="Sign off by hand · no ACs listed",
                reason="the whole-feature eval leaves owner steps and lists no AC to sign off",
                started=True,
                waiting=True,
            )
        case "undated":
            return _Own(
                holds=False,
                meta="Acceptance eval undated · evaluate again",
                reason="the whole-feature eval has no evaluated_at: no sign-off can follow it",
                started=True,
            )
        case "future":
            return _Own(
                holds=False,
                meta=f"Sign-off possible after {gate.signable_after}",
                reason="the whole-feature eval is dated after now: no sign-off can follow it yet",
                started=True,
            )
        case "reopened":
            reopened = f"{gate.reopened} AC{'' if gate.reopened == 1 else 's'}"
            return _Own(
                holds=False,
                meta=f"{reopened} reopened · evaluate again",
                reason=f"the latest eval of {reopened} waiting on owner steps is NO-SHIP",
                started=True,
            )
        case "sign_off":
            return _Own(
                holds=False,
                meta=f"Sign off {acs}",
                reason=f"{acs} wait{'s' if one else ''} on owner steps (SHIP-WITH-OWNER-STEPS)",
                started=True,
                waiting=True,
            )


def _shipped(build: _Own, acceptance: _Own) -> _Own:
    """Shipped is Build and Acceptance both done; unknown while either cannot be told."""
    holds = (build.holds, acceptance.holds)
    if False in holds:
        return _Own(holds=False, reason="Build and Acceptance are not both done")
    if None in holds:
        unread = build if build.holds is None else acceptance
        return _Own(holds=None, reason=unread.reason)
    return _Own(holds=True)
