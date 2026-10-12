"""Feature views (D23): a feature folder's phase, acceptance criteria and verdict."""

from typing import Literal

from pydantic import Field

from agent_hub.core.readmodels.view_types import DerivedView, ViewModel

type FeaturePhase = Literal[
    "spec", "research", "plan", "tickets", "implement", "review", "evaluate", "shipped"
]
type Verdict = Literal["SHIP", "SHIP-WITH-OWNER-STEPS", "NO-SHIP"]


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
    """A feature as the Features list shows it; ``problem`` when a file of it is malformed."""

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
    problem: str | None = None


class FeatureDetail(FeatureView):
    """A feature with its acceptance criteria rows."""

    ac_rows: tuple[AcRow, ...] = ()
