"""Feature views (D23): a feature folder's phase, golden path, acceptance criteria and evals."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from agent_hub.core.readmodels.view_types import DerivedView, ViewModel

type FeaturePhase = Literal[
    "spec", "ux_design", "research", "plan", "tickets", "build", "acceptance", "shipped"
]
type Verdict = Literal["SHIP", "SHIP-WITH-OWNER-STEPS", "NO-SHIP"]
# A golden-path step's state (AGH-136 S8): ``partial`` is a later step with some progress,
# ``blocked`` a step whose own condition holds while an earlier gate does not, ``unknown`` a
# step whose evidence cannot be read (``reason`` says why), ``unrecorded`` the gate step whose
# record was never written (Acceptance with no whole-feature eval, two-level-flows AC-1.6),
# ``waiting`` a step paused until the owner decides, ``stale`` a step whose record must be made
# again (a preflight that checked an older plan version than the one approved, AC-2.8).
type StepState = Literal[
    "done",
    "partial",
    "current",
    "pending",
    "skipped",
    "unknown",
    "blocked",
    "unrecorded",
    "waiting",
    "stale",
]
# Where a feature's ticket data came from: Linear (a snapshot) or the plan (``features.json``).
type TicketsSource = Literal["linear", "plan"]


class StepProgress(ViewModel):
    """How much of a step is done: ``done`` of ``total`` (tickets, ACs, reviews)."""

    done: int = Field(ge=0)
    total: int = Field(ge=0)


class GoldenStep(ViewModel):
    """One step of the golden path: its state, a short ``meta`` text and the ``reason`` it is
    not done (naming the failing gate), its ``progress`` when it counts something, and the one
    ``signal`` that needs attention (Plan: "v3 waits for you" while a change request is open)."""

    name: FeaturePhase
    state: StepState
    meta: str | None
    reason: str | None
    progress: StepProgress | None
    signal: str | None = None


class GoldenPath(ViewModel):
    """The feature's steps in their fixed order; ``phase`` is the first step neither done nor
    skipped (``shipped`` when all are)."""

    steps: tuple[GoldenStep, ...]
    phase: FeaturePhase


class EvalRecord(ViewModel):
    """One evaluation of a delivery: ``evals/<delivery>.md``, or the legacy ``eval.md``.

    ``path`` is relative to the hub's ``brain/``. ``acs`` is the AC ids evaluated or ``"all"``;
    ``evaluated_at`` is the frontmatter's text (an ISO date or time). ``provenance`` says who ran
    it (e.g. ``agent``, ``agent-evaluator``, ``owner``), None when the note does not say.
    ``problem`` says why the file could not be read or parsed; its other fields are then empty.
    """

    delivery: str
    path: str
    verdict: Verdict | None
    tickets: tuple[str, ...]
    acs: tuple[str, ...] | Literal["all"]
    prs: tuple[str, ...]
    commit: str | None
    evaluated_at: str | None
    legacy: bool
    problem: str | None
    provenance: str | None = None


class AcCounts(ViewModel):
    """Passing and total acceptance criteria, and how many are owner steps."""

    passing: int = Field(ge=0)
    total: int = Field(ge=0)
    owner_steps: int = Field(ge=0)


class AcRow(ViewModel):
    """One acceptance criterion of ``features.json``."""

    id: str
    description: str
    repo: str | None
    passes: bool
    manual: bool = False
    evidence: str | None = None
    command: str | None = None


class FeatureView(DerivedView):
    """A feature as the Features list shows it; ``problem`` when a file of it is malformed.

    ``phase`` equals ``golden_path.phase``; ``tickets_source`` says whether the ticket counts
    behind the golden path came from Linear or from the plan.
    """

    project: str
    slug: str
    issues: tuple[str, ...]
    size: Literal["spike", "bounded", "architectural"] | None
    phase: FeaturePhase
    files: tuple[str, ...]
    acs: AcCounts | None
    verdict: Verdict | None
    verdict_line: str | None
    repos: tuple[str, ...]
    golden_path: GoldenPath
    tickets_source: TicketsSource
    problem: str | None = None


type FeatureRecordName = Literal["spec", "research", "plan", "eval", "issues"]


class FeatureRecord(ViewModel):
    """One record file of a feature folder; ``path`` is relative to the hub's ``brain/``, so the
    brain note route reads it."""

    name: FeatureRecordName
    path: str
    present: bool


class AmendmentView(ViewModel):
    """One ``A<n> (<date>, <who>): <title>`` entry of the plan's ``## Amendments``; ``anchor`` is
    the text of that ``## Amendments…`` heading, which the Plan record view links to."""

    id: str
    date: str
    who: str
    title: str
    anchor: str


class PlanView(ViewModel):
    """The plan's version (AC-1.4): ``v<amendments + 1>``. ``version`` is None and ``problem``
    says why when ``plan.md`` could not be read (larger than its cap)."""

    version: int | None = Field(ge=1)
    amendments: tuple[AmendmentView, ...] = ()
    problem: str | None = None


type OwnerWaitState = Literal["sign_off", "reopened", "undated", "future", "no_acs"]


class OwnerWaitView(ViewModel):
    """What the acceptance eval waits on from the owner (A9-A11, A15), the state the Eval tab's
    prompt shows: ``sign_off`` (the one state a sign-off can be recorded in), ``reopened`` (a
    later eval says NO-SHIP for ``reopened``: only "more work" can be recorded), ``undated`` and
    ``future`` (no sign-off can rank newer than an eval with no ``evaluated_at``, or one dated
    after the read), ``no_acs`` (no live AC to sign off, A10). ``acs`` are the ACs it waits on;
    ``signable_after`` (``future`` only) the whole minute after which a sign-off can follow it."""

    state: OwnerWaitState
    acs: tuple[str, ...] = ()
    reopened: tuple[str, ...] = ()
    signable_after: datetime | None = None


class AcceptanceEval(ViewModel):
    """The feature's acceptance eval (AC-1.6): the latest whole-feature eval (``acs: all``, or a
    legacy ``eval.md`` with no scope), by its ``delivery`` (``legacy`` for ``eval.md``);
    ``owner_wait`` is None when it waits on no owner decision the app can take."""

    delivery: str
    verdict: Verdict
    owner_wait: OwnerWaitView | None = None


class FeatureDetail(FeatureView):
    """A feature with its acceptance criteria rows, its records (D3) and every eval; ``plan``
    (None without ``plan.md``) and ``acceptance_eval`` (None before one exists), whose verdict is
    the header's ``verdict``."""

    ac_rows: tuple[AcRow, ...] = ()
    records: tuple[FeatureRecord, ...] = ()
    evals: tuple[EvalRecord, ...] = ()
    plan: PlanView | None = None
    acceptance_eval: AcceptanceEval | None = None
