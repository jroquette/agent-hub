"""The JSON documents agents hand to ``/feature`` (AGH-139 D6, S3): models and bounds, pure.

A review output is what one reviewer reports for one round of one task; an eval output is what
the evaluator found for one delivery, beside its ``evals/<delivery>.md``. The models are the
single source of truth: the validator checks a document against them and the shipped JSON
Schemas are exported from them, so a class docstring here becomes a schema ``description`` and
names no project.
"""

from typing import Annotated, Final, Literal, NamedTuple

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    Tag,
)

from agent_hub.core.features.feature_evals import DELIVERY_PATTERN
from agent_hub.core.features.feature_record import TicketKey
from agent_hub.core.features.feature_view import Verdict
from agent_hub.core.features.scope_rules import AC_ID_PATTERN, COMMIT_PATTERN

REVIEW_SCHEMA_ID: Final = "agent-hub/review/1"
EVAL_SCHEMA_ID: Final = "agent-hub/eval/1"
# An output over this size is refused before it is parsed.
MAX_OUTPUT_BYTES: Final = 524_288
MAX_FINDINGS: Final = 100
MAX_FINDING_ACS: Final = 50
MAX_EVAL_TICKETS: Final = 100
MAX_EVAL_ACS: Final = 300
MAX_RESULTS: Final = 300
MAX_GATES: Final = 50
MAX_RED_ON_PARENT: Final = 300
MAX_OWNER_STEPS: Final = 50
# The tags of an eval's ``acs`` union; pydantic puts the chosen one in an error's ``loc``.
ACS_ALL_TAG: Final = "all"
ACS_LIST_TAG: Final = "ids"
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
type CommandText = Annotated[StrictStr, Field(min_length=1, max_length=2000, pattern=_ONE_LINE)]
type GateText = Annotated[StrictStr, Field(min_length=1, max_length=64, pattern=_ONE_LINE)]
type Delivery = Annotated[StrictStr, Field(pattern=f"^{DELIVERY_PATTERN.pattern}$")]
type ExitCode = Annotated[StrictInt, Field(ge=-255, le=255)]
type RunStatus = Literal["pass", "fail", "not-run"]
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
    acs: Annotated[tuple[AcId, ...], Field(max_length=MAX_FINDING_ACS)]
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
    findings: Annotated[tuple[ReviewFinding, ...], Field(max_length=MAX_FINDINGS)]


def _acs_arm(value: object) -> str:
    """The ``acs`` arm a value is validated against, by its JSON type: a string, or a list."""
    return ACS_ALL_TAG if isinstance(value, str) else ACS_LIST_TAG


type EvalAcs = Annotated[
    Annotated[Literal["all"], Tag(ACS_ALL_TAG)]
    | Annotated[tuple[AcId, ...], Field(max_length=MAX_EVAL_ACS), Tag(ACS_LIST_TAG)],
    Discriminator(_acs_arm),
]


class AcResult(BaseModel):
    """The run of one acceptance criterion's check: its command, exit code, status and summary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ac: AcId
    command: CommandText
    exit_code: ExitCode | None
    status: RunStatus
    summary: OneLine1000


class GateResult(BaseModel):
    """The run of one repo gate: the repo, the gate's name, its exit code and status."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo: GateText
    name: GateText
    exit_code: ExitCode | None
    status: RunStatus


class RedOnParent(BaseModel):
    """A new test, and whether it failed on the base commit (null when not checked)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    test: PathText
    failed_on_base: StrictBool | None


class EvalOutput(BaseModel):
    """The evaluator's report for one delivery: its verdict, scope, results and gates.

    ``acs`` is ``"all"`` or a list of AC ids; an empty list scopes the eval by ``tickets``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["agent-hub/eval/1"] = Field(alias="schema")
    delivery: Delivery
    verdict: Verdict
    commit: Commit
    tickets: Annotated[tuple[TicketKey, ...], Field(max_length=MAX_EVAL_TICKETS)]
    acs: EvalAcs
    results: Annotated[tuple[AcResult, ...], Field(max_length=MAX_RESULTS)]
    gates: Annotated[tuple[GateResult, ...], Field(max_length=MAX_GATES)]
    red_on_parent: Annotated[tuple[RedOnParent, ...], Field(max_length=MAX_RED_ON_PARENT)]
    owner_steps: Annotated[tuple[OneLine1000, ...], Field(max_length=MAX_OWNER_STEPS)]
