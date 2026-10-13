"""The JSON documents agents hand to ``/feature`` (AGH-139 D6, S3): models and bounds, pure.

A review output is what one reviewer reports for one round of one task. The models are the
single source of truth: the validator checks a document against them and the shipped JSON
Schemas are exported from them, so a class docstring here becomes a schema ``description`` and
names no project.
"""

from typing import Annotated, Final, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from agent_hub.core.features.feature_record import TicketKey
from agent_hub.core.features.scope_rules import AC_ID_PATTERN, COMMIT_PATTERN

REVIEW_SCHEMA_ID: Final = "agent-hub/review/1"
# An output over this size is refused before it is parsed.
MAX_OUTPUT_BYTES: Final = 524_288
# Text an agent writes on one line: no control character, line breaks included.
_ONE_LINE: Final = r"^[^\x00-\x1f\x7f-\x9f]*$"


class OutputProblem(NamedTuple):
    """One problem in an agent output: its JSON path, and what is wrong."""

    path: str
    message: str


type AcId = Annotated[StrictStr, Field(pattern=f"^{AC_ID_PATTERN.pattern}$")]
type Commit = Annotated[StrictStr, Field(pattern=f"^{COMMIT_PATTERN.pattern}$")]
type FindingId = Annotated[StrictStr, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")]
type TaskId = Annotated[StrictStr, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")]
type OneLine1000 = Annotated[StrictStr, Field(min_length=1, max_length=1000, pattern=_ONE_LINE)]
type PathText = Annotated[StrictStr, Field(min_length=1, max_length=512, pattern=_ONE_LINE)]
type ReviewRound = Annotated[StrictInt, Field(ge=1, le=9999)]
type LineNumber = Annotated[StrictInt, Field(ge=1, le=10_000_000)]
type FindingKind = Literal[
    "missing",
    "extra",
    "test",
    "assertion",
    "contract",
    "invariant",
    "security",
    "idempotency",
    "quality",
]


class ReviewFinding(BaseModel):
    """One finding of a review: where it is, how serious, what is wrong and what is expected."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: FindingId
    kind: FindingKind
    severity: Literal["blocking", "minor"]
    path: PathText
    line: LineNumber | None
    acs: Annotated[tuple[AcId, ...], Field(max_length=50)]
    what: OneLine1000
    expected: OneLine1000


class ReviewOutput(BaseModel):
    """A reviewer's report for one review round of one task: PASS iff no blocking finding."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["agent-hub/review/1"] = Field(alias="schema")
    reviewer: Literal["spec", "quality"]
    ticket: TicketKey
    task: TaskId
    round: ReviewRound
    commit: Commit
    verdict: Literal["PASS", "FAIL"]
    findings: Annotated[tuple[ReviewFinding, ...], Field(max_length=100)]
