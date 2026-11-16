"""Review records, ``brain/features/<slug>/reviews/<ticket>.md`` (AGH-136 S5, D4): pure, no I/O.

``/feature`` step 7 writes one per ticket once both reviewers pass: frontmatter ``type: review``,
``ticket``, ``outcome`` (``approved`` or ``changes-requested``), ``pr`` and ``reviewed_at``. A
ticket with an ``approved`` record counts as reviewed; a malformed record carries its ``problem``
and counts for nothing. ``pr`` names the ticket's pull request as ``<repo>#<number>`` (the
repo's ``dir`` or its GitHub name) or as its GitHub URL; ``#pending`` names none yet. A ticket
that owns several repos names one per repo instead, ``prs: [...]``, in the order they merge
(AGH-592); a record with both is malformed.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, NamedTuple, cast

from agent_hub.core.brain.brain_note import FrontmatterValue
from agent_hub.core.features.feature_evals import (
    ISO_TIME,
    NOTE_SUFFIX,
    RecordFieldError,
    record_fields,
    record_type,
    text_field,
    text_items,
)
from agent_hub.core.features.feature_record import KEY_PATTERN
from agent_hub.core.hub_config.problems import one_line

if TYPE_CHECKING:
    from agent_hub.core.features.feature_status import RecordHead

REVIEWS_FOLDER: Final = "reviews"
# At most this many ``reviews/*.md`` files are read, by name; their first bytes only.
MAX_REVIEW_FILES: Final = 500
REVIEW_HEAD_BYTES: Final = 8_192
# The tickets with a review round, ``reviews/<ticket>/<reviewer>-r<N>.json`` (P3): at most this
# many ticket folders looked at, at most this many entries read in all of them.
MAX_ROUND_TICKETS: Final = 500
MAX_ROUND_ENTRIES: Final = 20_000

type ReviewOutcome = Literal["approved", "changes-requested"]
_OUTCOMES: Final = ("approved", "changes-requested")
_TICKET: Final = re.compile(KEY_PATTERN)
_PR: Final = re.compile(r"[A-Za-z0-9._/#:-]{1,200}")
_PR_REF: Final = re.compile(r"(?P<repo>[A-Za-z0-9._-]{1,100})#(?P<number>[1-9][0-9]{0,8})")
_PR_URL: Final = re.compile(
    r"https://github\.com/[A-Za-z0-9._-]{1,100}/[A-Za-z0-9._-]{1,100}/pull/[1-9][0-9]{0,8}"
)


@dataclass(frozen=True, kw_only=True, slots=True)
class ReviewRecord:
    """One review record. ``ticket`` is the frontmatter's, else the file name's; ``path`` is
    relative to the hub's ``brain/``. With a ``problem``, ``outcome`` and the rest are None.
    ``prs`` are the pull requests it names in merge order (``prs``, else ``pr``); ``pr`` is the
    first."""

    ticket: str
    path: str
    outcome: ReviewOutcome | None
    pr: str | None
    reviewed_at: str | None
    problem: str | None
    prs: tuple[str, ...] = ()


class ReviewPullRequest(NamedTuple):
    """A reviewed ticket's pull request: the hub repo it is in (its ``dir``; None outside the
    hub's repos) and its GitHub URL."""

    repo: str | None
    url: str


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


def review_pull_requests(
    records: Iterable[ReviewRecord], repos: Mapping[str, str]
) -> dict[str, tuple[ReviewPullRequest, ...]]:
    """Each reviewed ticket's pull requests, in merge order, by ticket (upper case, as named).

    ``repos`` maps each hub repo's ``dir`` to its GitHub ``owner/name``. A ``<repo>#<number>``
    whose repo is no hub repo (by dir or name, any case), a placeholder such as ``#pending`` and a
    malformed record give no URL; a later record of the same ticket wins.
    """
    github = {name.lower(): full for dir_name, full in repos.items() for name in (dir_name, full)}
    github.update({full.rpartition("/")[2].lower(): full for full in repos.values()})
    dirs = {full.lower(): dir_name for dir_name, full in repos.items()}
    found: dict[str, tuple[ReviewPullRequest, ...]] = {}
    for record in records:
        urls = () if record.problem is not None else record.prs
        linked = tuple(
            ReviewPullRequest(dirs.get(_github_name(url)), url)
            for pr in urls
            if (url := _pull_request_url(pr, github)) is not None
        )
        if linked:
            found[record.ticket.upper()] = linked
    return found


def names_pull_request(pr: str | None) -> bool:
    """Whether ``pr`` names a pull request: ``<repo>#<number>`` or a GitHub pull request URL
    (``#pending`` names none)."""
    return pr is not None and (
        _PR_URL.fullmatch(pr) is not None or _PR_REF.fullmatch(pr) is not None
    )


def _github_name(url: str) -> str:
    """The ``owner/name`` of a GitHub pull request URL, lower case."""
    return "/".join(url.split("/")[3:5]).lower()


def _pull_request_url(pr: str | None, github: Mapping[str, str]) -> str | None:
    if pr is None:
        return None
    if _PR_URL.fullmatch(pr) is not None:
        return pr
    match = _PR_REF.fullmatch(pr)
    if match is None:
        return None
    full = github.get(match["repo"].lower())
    return None if full is None else f"https://github.com/{full}/pull/{match['number']}"


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
    pr = text_field(fields, "pr", _PR)
    prs = text_items(fields, "prs", _PR)
    if pr is not None and prs:
        raise RecordFieldError("give pr or prs, not both")
    return ReviewRecord(
        ticket=ticket or stem,
        path=path,
        outcome=cast("ReviewOutcome", outcome),
        pr=prs[0] if prs else pr,
        reviewed_at=text_field(fields, "reviewed_at", ISO_TIME),
        problem=None,
        prs=prs or (() if pr is None else (pr,)),
    )


def _broken(stem: str, path: str, problem: str) -> ReviewRecord:
    return ReviewRecord(
        ticket=stem, path=path, outcome=None, pr=None, reviewed_at=None, problem=one_line(problem)
    )
