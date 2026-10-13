"""Review records, ``brain/features/<slug>/reviews/<ticket>.md`` (AGH-136 S5, D4): pure, no I/O.

``/feature`` step 7 writes one per ticket once both reviewers pass: frontmatter ``type: review``,
``ticket``, ``outcome`` (``approved`` or ``changes-requested``), ``pr`` and ``reviewed_at``. A
ticket with an ``approved`` record counts as reviewed; a malformed record carries its ``problem``
and counts for nothing.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, cast

from agent_hub.core.brain.brain_note import FrontmatterValue
from agent_hub.core.features.feature_evals import (
    ISO_TIME,
    NOTE_SUFFIX,
    RecordFieldError,
    record_fields,
    record_type,
    text_field,
)
from agent_hub.core.features.feature_record import KEY_PATTERN
from agent_hub.core.hub_config.problems import one_line

if TYPE_CHECKING:
    from agent_hub.core.features.feature_status import RecordHead

REVIEWS_FOLDER: Final = "reviews"
# At most this many ``reviews/*.md`` files are read, by name; their first bytes only.
MAX_REVIEW_FILES: Final = 500
REVIEW_HEAD_BYTES: Final = 8_192

type ReviewOutcome = Literal["approved", "changes-requested"]
_OUTCOMES: Final = ("approved", "changes-requested")
_TICKET: Final = re.compile(KEY_PATTERN)
_PR: Final = re.compile(r"[A-Za-z0-9._/#:-]{1,200}")


@dataclass(frozen=True, kw_only=True, slots=True)
class ReviewRecord:
    """One review record. ``ticket`` is the frontmatter's, else the file name's; ``path`` is
    relative to the hub's ``brain/``. With a ``problem``, ``outcome`` and the rest are None."""

    ticket: str
    path: str
    outcome: ReviewOutcome | None
    pr: str | None
    reviewed_at: str | None
    problem: str | None


def review_records(heads: Sequence[RecordHead], *, slug: str) -> tuple[ReviewRecord, ...]:
    """Each review record of the feature ``slug``, from the heads of ``reviews/*.md``, in order."""
    return tuple(_review(head, slug=slug) for head in heads)


def approved_tickets(records: Iterable[ReviewRecord]) -> frozenset[str]:
    """The tickets (upper case, as named: a plan key or a tracker id) with an approved record."""
    return frozenset(
        record.ticket.upper()
        for record in records
        if record.problem is None and record.outcome == "approved"
    )


def _review(head: RecordHead, *, slug: str) -> ReviewRecord:
    stem = head.name.removesuffix(NOTE_SUFFIX)
    path = f"features/{slug}/{REVIEWS_FOLDER}/{head.name}"
    if head.head is None:
        return _broken(stem, path, head.problem or "could not be read")
    try:
        return _parsed(stem, path, record_fields(head.head))
    except RecordFieldError as problem:
        return _broken(stem, path, str(problem))


def _parsed(stem: str, path: str, fields: dict[str, FrontmatterValue]) -> ReviewRecord:
    record_type(fields, "review")
    ticket = text_field(fields, "ticket", _TICKET)
    if ticket is None and _TICKET.fullmatch(stem) is None:
        raise RecordFieldError("the file name is not a ticket and no ticket is named")
    outcome = text_field(fields, "outcome")
    if outcome not in _OUTCOMES:
        raise RecordFieldError(f"outcome must be one of {', '.join(_OUTCOMES)}")
    return ReviewRecord(
        ticket=ticket or stem,
        path=path,
        outcome=cast("ReviewOutcome", outcome),
        pr=text_field(fields, "pr", _PR),
        reviewed_at=text_field(fields, "reviewed_at", ISO_TIME),
        problem=None,
    )


def _broken(stem: str, path: str, problem: str) -> ReviewRecord:
    return ReviewRecord(
        ticket=stem, path=path, outcome=None, pr=None, reviewed_at=None, problem=one_line(problem)
    )
