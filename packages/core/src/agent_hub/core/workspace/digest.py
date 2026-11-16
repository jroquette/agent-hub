"""The owner digest: what waits on the owner, built from one input file and the local claims.

Pure: no I/O. ``hub digest`` reads the session's ``DigestInput`` file and the hub's claim files,
calls ``build_digest`` and prints ``digest_lines``; ``hub brief`` shows the cached ``Digest``.

The input (``DigestInput``, written by the session from the tracker and GitHub) is bounded:
``version`` 1, at most ``MAX_ITEMS`` tickets and ``MAX_ITEMS`` pull requests, no unknown field.
Every text field is external data, so a validator replaces its control characters with a space
and cuts it at ``MAX_FIELD`` characters.

The three rules:

- waiting: every input ticket claim with a ``question``, and every local claim with a
  ``question`` whose ticket is among the input's tickets (an unreleased claim on a ticket that
  left In Progress and In Review is not listed), a local claim winning over the input's for the
  same ticket, oldest ``asked_at`` first. So waiting holds at most one item per input ticket,
  at most ``MAX_ITEMS``, whatever the number of claim files. The title is the
  claim's ``title``, else ``session <id>``; the link is the input's, else ``local, <hub>`` plus
  ``, pid <pid>``.
- idle: input tickets not listed as waiting, whose claim is null or not live, that no local claim
  holds as live, and that no pull request updated in the ``RECENT`` before ``now`` names (the
  ticket id in its title or branch, any case), by team then number. The process table cannot be
  read here, so a local claim counts as live only while its ``last_activity`` is within
  ``STALE_AFTER`` (the claims' 24-hour rule), pid or not.
- ready: pull requests not draft, ``mergeable_state`` ``clean``, no check counted under a
  conclusion other than ``success``, ``neutral`` or ``skipped``, and no unresolved review thread,
  by repo then number.

The lines: nothing waiting gives one line, ``Owner digest <YYYY-MM-DD>: nothing waits on you.``
Else ``Owner digest <YYYY-MM-DD>``, then each non-empty section, a ``<name>:`` line and one ``- ``
line per item (at most ``limit``, then ``- …and <n> more``):

- ``Sessions waiting on you``: ``- <title> (<ticket>): <question> <link>``
- ``Tickets no one is on``: ``- <ticket> <title> (<state>) <url>``
- ``Ready to merge``: ``- <repo>#<number> <title> <url>``

Every item line fits in ``ITEM_CAP`` characters. The ticket and the link or url at its end stay
whole: the question then the title shrink first on a waiting line, the title then the state on
an idle one, the title then the repo on a ready one, each ending in "…"; only when that is not
enough is the line's end cut.
"""

import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Final, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    model_validator,
)

from agent_hub.core.claims.claim import STALE_AFTER, TICKET_PATTERN, Claim

# Bounds on the input file.
MAX_ITEMS: Final = 200
MAX_FIELD: Final = 512
MAX_CHECK_KINDS: Final = 32
# The largest ``Digest`` as JSON, in bytes, so its reader's limit never refuses what is written:
# at most 4 * MAX_ITEMS items (waiting has twice MAX_ITEMS), each with at most 4 text fields (the
# ticket id counted as one) of MAX_FIELD characters, each character at most 4 bytes (control
# characters are stripped, so none is escaped as \uXXXX), plus 256 bytes of keys, a time and a
# number per item and for the whole document.
_UTF8_MAX: Final = 4
_ITEM_TEXT_FIELDS: Final = 4
_OVERHEAD: Final = 256
MAX_DIGEST_BYTES: Final = _OVERHEAD + 4 * MAX_ITEMS * (
    _ITEM_TEXT_FIELDS * _UTF8_MAX * MAX_FIELD + _OVERHEAD
)
# Each item line of the digest is cut at this many characters.
ITEM_CAP: Final = 200
# A pull request updated this recently shows someone is on its ticket.
RECENT: Final = timedelta(hours=24)
# Check conclusions that do not stop a merge.
PASSING_CHECKS: Final = frozenset({"success", "neutral", "skipped"})

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]+")
_TICKET_PARTS = re.compile(r"^([A-Z][A-Z0-9]*)-([0-9]+)$")


def _clean(value: object) -> object:
    """Control characters become one space; the text is cut at ``MAX_FIELD``."""
    if not isinstance(value, str):
        return value
    return _CONTROL.sub(" ", value).strip()[:MAX_FIELD]


Text = Annotated[str, BeforeValidator(_clean), Field(max_length=MAX_FIELD)]
TicketId = Annotated[str, Field(pattern=TICKET_PATTERN)]
Count = Annotated[int, Field(ge=0)]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class InputClaim(_Frozen):
    """A ticket's newest claim comment, as the session read it, and whether its session lives."""

    session: Text
    link: Text
    live: bool
    question: Text | None = None
    asked_at: AwareDatetime | None = None
    title: Text | None = None

    @model_validator(mode="after")
    def _question_and_asked_at_together(self) -> Self:
        if (self.question is None) != (self.asked_at is None):
            raise ValueError("question and asked_at are both set or both null")
        return self


class InputTicket(_Frozen):
    id: TicketId
    title: Text
    state: Text
    url: Text
    claim: InputClaim | None


class InputPr(_Frozen):
    repo: Text
    number: Annotated[int, Field(gt=0)]
    title: Text
    url: Text
    branch: Text
    draft: bool
    updated_at: AwareDatetime
    mergeable_state: Text
    checks: Annotated[dict[Text, Count], Field(max_length=MAX_CHECK_KINDS)]
    unresolved_threads: Count


class DigestInput(_Frozen):
    """The session's file: the team's open tickets with their claims, and the repos' open PRs."""

    version: Literal[1]
    read_at: AwareDatetime
    tickets: Annotated[tuple[InputTicket, ...], Field(max_length=MAX_ITEMS)]
    prs: Annotated[tuple[InputPr, ...], Field(max_length=MAX_ITEMS)]


class WaitingItem(_Frozen):
    title: Text
    ticket: TicketId
    question: Text
    link: Text
    asked_at: AwareDatetime


class IdleItem(_Frozen):
    ticket: TicketId
    title: Text
    state: Text
    url: Text


class ReadyItem(_Frozen):
    repo: Text
    number: Annotated[int, Field(gt=0)]
    title: Text
    url: Text


class Digest(_Frozen):
    """What waits on the owner at ``built_at``: the cache ``hub brief`` shows."""

    built_at: AwareDatetime
    waiting: Annotated[tuple[WaitingItem, ...], Field(max_length=2 * MAX_ITEMS)]
    idle: Annotated[tuple[IdleItem, ...], Field(max_length=MAX_ITEMS)]
    ready: Annotated[tuple[ReadyItem, ...], Field(max_length=MAX_ITEMS)]


def _local_live(claim: Claim, now: datetime) -> bool:
    """The sandbox hides the process table, so a pid proves nothing here: only recent activity."""
    return now - claim.last_activity <= STALE_AFTER


def _local_link(claim: Claim) -> str:
    link = f"local, {claim.hub}"
    return link if claim.pid is None else f"{link}, pid {claim.pid}"


def _ticket_order(ticket_id: str) -> tuple[str, int]:
    match = _TICKET_PARTS.match(ticket_id)
    return (ticket_id, 0) if match is None else (match.group(1), int(match.group(2)))


def _names_ticket(pr: InputPr, ticket_id: str) -> bool:
    pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(ticket_id)}(?![0-9])", re.IGNORECASE)
    return bool(pattern.search(pr.title) or pattern.search(pr.branch))


def _waiting(source: DigestInput, claims: tuple[Claim, ...]) -> tuple[WaitingItem, ...]:
    items: dict[str, WaitingItem] = {}
    for ticket in source.tickets:
        claim = ticket.claim
        if claim is None or claim.question is None or claim.asked_at is None:
            continue
        items[ticket.id] = WaitingItem(
            title=claim.title or f"session {claim.session}",
            ticket=ticket.id,
            question=claim.question,
            link=claim.link,
            asked_at=claim.asked_at,
        )
    listed = {ticket.id for ticket in source.tickets}
    for local in claims:
        if local.question is None or local.asked_at is None or local.ticket not in listed:
            continue
        items[local.ticket] = WaitingItem(
            title=local.title or f"session {local.session}",
            ticket=local.ticket,
            question=local.question,
            link=_local_link(local),
            asked_at=local.asked_at,
        )
    return tuple(sorted(items.values(), key=lambda item: (item.asked_at, item.ticket)))


def _idle(
    source: DigestInput, claims: tuple[Claim, ...], now: datetime, *, waiting: frozenset[str]
) -> tuple[IdleItem, ...]:
    """``waiting`` are the tickets already listed as waiting on the owner: never idle too."""
    held = waiting | {claim.ticket for claim in claims if _local_live(claim, now)}
    recent = [pr for pr in source.prs if now - pr.updated_at <= RECENT]
    items = [
        IdleItem(ticket=ticket.id, title=ticket.title, state=ticket.state, url=ticket.url)
        for ticket in source.tickets
        if (ticket.claim is None or not ticket.claim.live)
        and ticket.id not in held
        and not any(_names_ticket(pr, ticket.id) for pr in recent)
    ]
    return tuple(sorted(items, key=lambda item: _ticket_order(item.ticket)))


def _ready(source: DigestInput) -> tuple[ReadyItem, ...]:
    items = [
        ReadyItem(repo=pr.repo, number=pr.number, title=pr.title, url=pr.url)
        for pr in source.prs
        if not pr.draft
        and pr.mergeable_state == "clean"
        and all(count == 0 or kind in PASSING_CHECKS for kind, count in pr.checks.items())
        and pr.unresolved_threads == 0
    ]
    return tuple(sorted(items, key=lambda item: (item.repo, item.number)))


def build_digest(source: DigestInput, claims: tuple[Claim, ...], now: datetime) -> Digest:
    """What waits on the owner at ``now``; ``claims`` are the hub's local claim files."""
    waiting = _waiting(source, claims)
    return Digest(
        built_at=now,
        waiting=waiting,
        idle=_idle(source, claims, now, waiting=frozenset(item.ticket for item in waiting)),
        ready=_ready(source),
    )


def _cut(line: str) -> str:
    return line if len(line) <= ITEM_CAP else line[: ITEM_CAP - 1] + "…"


def _shorten(text: str, excess: int) -> tuple[str, int]:
    """``text`` shorter by up to ``excess`` characters, ending in "…", and what is still over."""
    if excess <= 0 or len(text) <= 1:
        return text, excess
    size = max(len(text) - excess, 1)
    return text[: size - 1] + "…", excess - (len(text) - size)


def _fit(template: str, fields: dict[str, str], cut_first: tuple[str, ...]) -> str:
    """``- <template>`` within ``ITEM_CAP``: the ``cut_first`` fields shrink in turn, the rest
    stays whole, and only when that is not enough is the line's end cut."""
    excess = len("- " + template.format(**fields)) - ITEM_CAP
    for name in cut_first:
        fields[name], excess = _shorten(fields[name], excess)
    return _cut("- " + template.format(**fields))


def _waiting_line(item: WaitingItem) -> str:
    return _fit(
        "{title} ({ticket}): {question} {link}",
        {"title": item.title, "ticket": item.ticket, "question": item.question, "link": item.link},
        ("question", "title"),
    )


def _idle_line(item: IdleItem) -> str:
    return _fit(
        "{ticket} {title} ({state}) {url}",
        {"ticket": item.ticket, "title": item.title, "state": item.state, "url": item.url},
        ("title", "state"),
    )


def _ready_line(item: ReadyItem) -> str:
    return _fit(
        "{repo}#{number} {title} {url}",
        {"repo": item.repo, "number": str(item.number), "title": item.title, "url": item.url},
        ("title", "repo"),
    )


def _section(name: str, item_lines: list[str], limit: int) -> list[str]:
    if not item_lines:
        return []
    shown = item_lines[:limit]
    rest = len(item_lines) - len(shown)
    return [f"{name}:", *shown, *([f"- …and {rest} more"] if rest > 0 else [])]


def digest_lines(digest: Digest, *, limit: int) -> tuple[str, ...]:
    """The digest as text: one line when nothing waits, else the sections, ``limit`` items each."""
    date = digest.built_at.astimezone(UTC).date().isoformat()
    if not (digest.waiting or digest.idle or digest.ready):
        return (f"Owner digest {date}: nothing waits on you.",)
    return (
        f"Owner digest {date}",
        *_section("Sessions waiting on you", [_waiting_line(w) for w in digest.waiting], limit),
        *_section("Tickets no one is on", [_idle_line(i) for i in digest.idle], limit),
        *_section("Ready to merge", [_ready_line(r) for r in digest.ready], limit),
    )
