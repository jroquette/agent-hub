"""The ``features.tracker`` checks of a feature's ticket plan and evals (AGH-136 S3, S6, Q9).

``tickets`` (optional, at most ``MAX_TICKETS``) holds objects with a unique draft ``key``
(``KEY_PATTERN``), an ``id`` (null or a tracker id), a ``title`` (null or at most
``MAX_TITLE_CHARS``), a ``repo`` (null or a repo name), ``blocked_by`` (at most ``MAX_BLOCKED_BY``
keys or ids of ``tickets``, never the ticket itself) and an ``order`` (null or a whole number, 0 or
more) and a ``parent`` (null, or the key or id of the epic of ``tickets`` it belongs to, never the
ticket itself). A cycle of ``blocked_by`` is a warning: the plan still reads, its tickets wait. An
AC's ``ticket`` names a key or id of ``tickets`` or a ``linear`` id; its ``withdrawn`` is true or
false.

Each ``evals/<delivery>.md`` starts with a frontmatter block holding a ``verdict`` (one of
``VERDICTS``), a scope (``acs``: AC ids of ``features.json`` or ``all``; and/or ``tickets``) and a
``delivery`` equal to its file name, itself a delivery name (``DELIVERY_PATTERN``).
"""

import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import Final, NamedTuple

from agent_hub.core.brain.frontmatter import FENCE, split_frontmatter
from agent_hub.core.features.feature_record import (
    KEY_PATTERN,
    MAX_BLOCKED_BY,
    MAX_TICKETS,
    MAX_TITLE_CHARS,
)
from agent_hub.core.hub_config.versions import cut_echo
from agent_hub.core.hub_files.tree_snapshot import FileEntry, TreeEntry
from agent_hub.core.json_form import JsonValue
from agent_hub.core.tracker.tracker_client import ISSUE_ID_PATTERN

RECORD_FIX: Final = "fix the record in features.json"
LINK_FIX: Final = "replace it with the file itself"
NOT_READ: Final = "not read as a regular file (links are never followed)"
UNREAD: Final = "could not be read"
UNREAD_FIX: Final = "run hub doctor again"
TICKET_FIX: Final = "name a key or id of `tickets` (or add that ticket)"
SELF_FIX: Final = "remove it from blocked_by"
PARENT_FIX: Final = "name the key or id of the epic in `tickets`, or set parent to null"
CYCLE_FIX: Final = "remove one blocked_by edge of the cycle"
AC_TICKET_FIX: Final = (
    "name the ticket that delivers the AC: a key or id of `tickets`, or a `linear` id"
)
EVAL_FIX: Final = "write the eval's frontmatter: type: eval, delivery, verdict, and acs or tickets"
EVAL_ACS_FIX: Final = "name only AC ids of features.json in the eval's acs"
DELIVERY_FIX: Final = "make `delivery` the file name; a re-run is a new file <delivery>-r2.md"
RENAME_FIX: Final = "rename the eval to <delivery>.md: lower-case letters, digits and -"

VERDICTS: Final = ("SHIP", "SHIP-WITH-OWNER-STEPS", "NO-SHIP")
DELIVERY_PATTERN: Final = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
ALL_ACS: Final = "all"

_KEY: Final = re.compile(KEY_PATTERN)


class Problem(NamedTuple):
    """A finding's message and fix, before it is placed on a file; ``warning`` lowers its level."""

    message: str
    fix: str
    warning: bool = False


def file_content(entry: TreeEntry | None) -> bytes | Problem:
    """A listed file's bytes, or why there are none: not a regular file, or its read failed."""
    if not isinstance(entry, FileEntry):
        return Problem(NOT_READ, LINK_FIX)
    if entry.content is None:
        return Problem(UNREAD, UNREAD_FIX)
    return entry.content


class _Ticket(NamedTuple):
    key: str
    id: str | None
    blocked_by: tuple[str, ...]
    parent: str | None = None


def ticket_plan(
    data: Mapping[str, JsonValue], *, names: Sequence[str]
) -> tuple[tuple[Problem, ...], frozenset[str] | None]:
    """The plan's problems, and the refs an AC's ``ticket`` may name (``None``: not checked).

    ``names`` are the repo names a ticket's ``repo`` may take.
    """
    raw = data.get("tickets", [])
    if not isinstance(raw, list) or len(raw) > MAX_TICKETS:
        return (
            Problem(f"`tickets` must be a list of at most {MAX_TICKETS} tickets", RECORD_FIX),
        ), None
    problems: list[Problem] = []
    tickets: dict[str, _Ticket] = {}
    for index, item in enumerate(raw):
        problems.extend(_ticket_problems(index, item, names=names, tickets=tickets))
    to_key = {ref: ticket.key for ticket in tickets.values() for ref in _refs(ticket)}
    edges = {key: tuple(_edges(ticket, to_key, problems)) for key, ticket in tickets.items()}
    problems.extend(_parent_problems(tickets.values(), to_key))
    problems.extend(
        Problem(f"{', '.join(cycle)}: a cycle of blocked_by", CYCLE_FIX, warning=True)
        for cycle in _cycles(edges)
    )
    linear = data.get("linear", [])
    linear_ids = (
        {item for item in linear if isinstance(item, str)} if isinstance(linear, list) else set()
    )
    return tuple(problems), frozenset({*to_key, *linear_ids})


def _refs(ticket: _Ticket) -> tuple[str, ...]:
    return (ticket.key,) if ticket.id is None else (ticket.key, ticket.id)


def _ticket_problems(
    index: int, item: JsonValue, *, names: Sequence[str], tickets: dict[str, _Ticket]
) -> list[Problem]:
    where = f"tickets[{index}]"
    if not isinstance(item, dict):
        return [Problem(f"{where}: must be an object", RECORD_FIX)]
    key = item.get("key")
    if not isinstance(key, str) or not _KEY.fullmatch(key):
        message = (
            "`key` must be a draft key such as T1 (a letter, then up to 31 letters, digits, - or _)"
        )
        return [Problem(f"{where}: {message}", RECORD_FIX)]
    if key in tickets:
        return [Problem(f"{key}: duplicate key", RECORD_FIX)]
    problems = [
        Problem(f"{key}: {message}", RECORD_FIX) for message in _field_messages(item, names)
    ]
    issue_id = item.get("id")
    blocked_by = item.get("blocked_by", [])
    parent = item.get("parent")
    tickets[key] = _Ticket(
        key=key,
        id=issue_id if isinstance(issue_id, str) else None,
        blocked_by=_blockers(blocked_by),
        parent=parent if isinstance(parent, str) else None,
    )
    return problems


def _field_messages(item: Mapping[str, JsonValue], names: Sequence[str]) -> Iterator[str]:
    issue_id = item.get("id")
    if issue_id is not None and not (
        isinstance(issue_id, str) and ISSUE_ID_PATTERN.fullmatch(issue_id)
    ):
        yield "`id` must be null or a tracker id such as TST-12"
    title = item.get("title")
    if title is not None and not (isinstance(title, str) and len(title) <= MAX_TITLE_CHARS):
        yield f"`title` must be null or at most {MAX_TITLE_CHARS} characters"
    repo = item.get("repo")
    if repo is not None and repo not in names:
        yield f"repo must be one of {', '.join(names)}"
    blocked_by = item.get("blocked_by", [])
    if (
        not isinstance(blocked_by, list)
        or len(blocked_by) > MAX_BLOCKED_BY
        or not all(isinstance(ref, str) for ref in blocked_by)
    ):
        yield f"`blocked_by` must be a list of at most {MAX_BLOCKED_BY} keys or ids"
    parent = item.get("parent")
    if parent is not None and not (isinstance(parent, str) and _KEY.fullmatch(parent)):
        yield "`parent` must be null or the key or id of a ticket"
    order = item.get("order")
    if order is not None and (isinstance(order, bool) or not isinstance(order, int) or order < 0):
        yield "`order` must be null or a whole number, 0 or more"


def _blockers(blocked_by: JsonValue) -> tuple[str, ...]:
    """The refs of a well-formed ``blocked_by``; a malformed one is reported and read as none."""
    if not isinstance(blocked_by, list) or len(blocked_by) > MAX_BLOCKED_BY:
        return ()
    refs = tuple(ref for ref in blocked_by if isinstance(ref, str))
    return refs if len(refs) == len(blocked_by) else ()


def _edges(ticket: _Ticket, to_key: Mapping[str, str], problems: list[Problem]) -> Iterator[str]:
    """The keys ``ticket`` waits on; an unknown or self reference is added to ``problems``."""
    for ref in ticket.blocked_by:
        blocker = to_key.get(ref)
        if blocker is None:
            message = f"{ticket.key}: blocked_by {cut_echo(ref)} is not a key or id of `tickets`"
            problems.append(Problem(message, TICKET_FIX))
        elif blocker == ticket.key:
            problems.append(Problem(f"{ticket.key}: blocked by itself", SELF_FIX))
        else:
            yield blocker


def _parent_problems(tickets: Iterable[_Ticket], to_key: Mapping[str, str]) -> Iterator[Problem]:
    """A ``parent`` that names no ticket of the plan, or the ticket itself."""
    for ticket in tickets:
        if ticket.parent is None:
            continue
        parent = to_key.get(ticket.parent)
        if parent is None:
            message = (
                f"{ticket.key}: parent {cut_echo(ticket.parent)} is not a key or id of `tickets`"
            )
            yield Problem(message, PARENT_FIX)
        elif parent == ticket.key:
            yield Problem(f"{ticket.key}: its own parent", PARENT_FIX)


def _cycles(edges: Mapping[str, tuple[str, ...]]) -> Iterator[tuple[str, ...]]:
    """Each group of tickets that wait on each other, once, in plan order."""
    reach = {key: _reachable(key, edges) for key in edges}
    reported: set[str] = set()
    for key in edges:
        if key in reported or key not in reach[key]:
            continue
        cycle = tuple(other for other in edges if other in reach[key] and key in reach[other])
        reported.update(cycle)
        yield cycle


def _reachable(start: str, edges: Mapping[str, tuple[str, ...]]) -> frozenset[str]:
    seen: set[str] = set()
    stack = list(edges[start])
    while stack:
        key = stack.pop()
        if key not in seen:
            seen.add(key)
            stack.extend(edges[key])
    return frozenset(seen)


def ac_plan_problems(
    where: str, ac: Mapping[str, JsonValue], *, refs: frozenset[str] | None
) -> Iterator[Problem]:
    """An AC's ``ticket`` and ``withdrawn``; ``refs`` ``None`` leaves the ticket unchecked."""
    ticket = ac.get("ticket")
    if ticket is not None and not isinstance(ticket, str):
        yield Problem(f"{where}: `ticket` must be null or a string", RECORD_FIX)
    elif isinstance(ticket, str) and refs is not None and ticket not in refs:
        message = f"{where}: ticket {cut_echo(ticket)} is not a key or id of `tickets` or `linear`"
        yield Problem(message, AC_TICKET_FIX)
    if not isinstance(ac.get("withdrawn", False), bool):
        yield Problem(f"{where}: `withdrawn` must be true or false", RECORD_FIX)


def eval_problems(name: str, text: str, *, ac_ids: frozenset[str] | None) -> tuple[Problem, ...]:
    """The problems of the eval file ``name`` (``<delivery>.md``) holding ``text``.

    ``ac_ids`` are the record's AC ids, ``None`` when the record could not be read.
    """
    delivery = name.removesuffix(".md")
    if not DELIVERY_PATTERN.fullmatch(delivery):
        return (Problem("the file name is not a delivery name", RENAME_FIX),)
    front = split_frontmatter(text)
    if front.problem is not None:
        return (Problem(f"frontmatter: {front.problem}", EVAL_FIX),)
    if not text.startswith(FENCE):
        return (Problem("no frontmatter: an eval starts with a --- block", EVAL_FIX),)
    fields = front.fields
    problems: list[Problem] = []
    if fields.get("verdict") not in VERDICTS:
        problems.append(
            Problem(f"`verdict` must be {', '.join(VERDICTS[:-1])} or {VERDICTS[-1]}", EVAL_FIX)
        )
    problems.extend(_scope_problems(fields.get("acs"), fields.get("tickets"), ac_ids=ac_ids))
    if fields.get("delivery") != delivery:
        problems.append(Problem(f"`delivery` must be the file name, {delivery}", DELIVERY_FIX))
    return tuple(problems)


def _scope_problems(
    acs: str | list[str] | None, tickets: str | list[str] | None, *, ac_ids: frozenset[str] | None
) -> Iterator[Problem]:
    if acs is None and tickets is None:
        yield Problem("no scope: give `acs` (a list of AC ids, or all) or `tickets`", EVAL_FIX)
    if isinstance(acs, list):
        unknown = () if ac_ids is None else (ac_id for ac_id in acs if ac_id not in ac_ids)
        for ac_id in unknown:
            yield Problem(
                f"{cut_echo(ac_id)}: in the eval's acs but not in features.json", EVAL_ACS_FIX
            )
    elif acs is not None and acs != ALL_ACS:
        yield Problem("`acs` must be a list of AC ids, or all", EVAL_FIX)
    if tickets is not None and not isinstance(tickets, list):
        yield Problem("`tickets` must be a list of ticket keys or ids", EVAL_FIX)
