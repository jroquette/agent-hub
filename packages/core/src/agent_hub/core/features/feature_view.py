"""Feature views (D23): a feature folder's phase, golden path, acceptance criteria and evals."""

from typing import Literal

from pydantic import Field

from agent_hub.core.readmodels.view_types import DerivedView, ViewModel

type FeaturePhase = Literal[
    "spec", "research", "plan", "tickets", "implement", "review", "evaluate", "shipped"
]
type Verdict = Literal["SHIP", "SHIP-WITH-OWNER-STEPS", "NO-SHIP"]
# A golden-path step's state (AGH-136 S8): ``partial`` is a later step with some progress,
# ``blocked`` a step whose own condition holds while an earlier gate does not, ``unknown`` a
# step whose evidence cannot be read (``reason`` says why).
type StepState = Literal["done", "partial", "current", "pending", "skipped", "unknown", "blocked"]
# Where a feature's ticket data came from: Linear (a snapshot) or the plan (``features.json``).
type TicketsSource = Literal["linear", "plan"]


class StepProgress(ViewModel):
    """How much of a step is done: ``done`` of ``total`` (tickets, ACs, reviews)."""

    done: int = Field(ge=0)
    total: int = Field(ge=0)


class GoldenStep(ViewModel):
    """One step of the golden path: its state, a short ``meta`` text and the ``reason`` it is
    not done (naming the failing gate), and its ``progress`` when it counts something."""

    name: FeaturePhase
    state: StepState
    meta: str | None
    reason: str | None
    progress: StepProgress | None


class GoldenPath(ViewModel):
    """The feature's steps in their fixed order; ``phase`` is the first step neither done nor
    skipped (``shipped`` when all are)."""

    steps: tuple[GoldenStep, ...]
    phase: FeaturePhase


class EvalRecord(ViewModel):
    """One evaluation of a delivery: ``evals/<delivery>.md``, or the legacy ``eval.md``.

    ``path`` is relative to the hub's ``brain/``. ``acs`` is the AC ids evaluated or ``"all"``;
    ``evaluated_at`` is the frontmatter's text (an ISO date or time). ``problem`` says why the
    file could not be read or parsed; its other fields are then empty.
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


class FeatureDetail(FeatureView):
    """A feature with its acceptance criteria rows, its records (D3) and every eval."""

    ac_rows: tuple[AcRow, ...] = ()
    records: tuple[FeatureRecord, ...] = ()
    evals: tuple[EvalRecord, ...] = ()
