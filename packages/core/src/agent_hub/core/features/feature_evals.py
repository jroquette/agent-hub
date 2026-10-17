"""Evals per delivery and what they cover (AGH-136 S6, S7): pure, no I/O.

Each evaluation is its own file, ``brain/features/<slug>/evals/<delivery>.md``, whose frontmatter
holds its scope: ``type: eval``, ``delivery``, ``verdict``, ``tickets``, ``acs`` (ids or ``all``),
``prs``, ``commit`` and ``evaluated_at``. A legacy ``eval.md`` is one delivery, ``legacy``, whose
verdict is its ``Final verdict`` line (an addendum that reverses the first verdict says so at the
top), else its first ``Verdict`` line, and whose scope is its frontmatter, when it has one.

For each AC the latest eval whose scope names it decides (S7): it is covered when that verdict is
SHIP or SHIP-WITH-OWNER-STEPS. "Latest" is a partial order. Two evals that both have a usable
``evaluated_at`` compare as instants in UTC (``+02:00`` and ``Z`` order correctly; a time without
an offset, or a date alone, is read as UTC). When either has no usable date, or both name the same
instant, a re-run of the same delivery is newer than what it re-runs (``dem-1-r2`` over ``dem-1``,
a higher ``-rN`` over a lower), and any ``evals/`` file is newer than the legacy ``eval.md``.
Otherwise the two have no order, and the latest evals naming an AC are all those no other one is
newer than: when they disagree the conservative verdict decides (NO-SHIP over
SHIP-WITH-OWNER-STEPS over SHIP), so an undated eval never lets an older SHIP cover an AC that a
NO-SHIP may have reopened. An eval naming only ``tickets`` covers the ACs whose
``ticket`` is one of them (a plan key and its tracker id are the same ticket). A legacy eval
without scope covers every AC only when every AC passes in ``features.json``; otherwise it covers
none and the coverage is ``unscoped``. Withdrawn ACs are left out of every count.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, Literal, cast, get_args

from agent_hub.core.brain.brain_note import FrontmatterValue
from agent_hub.core.brain.frontmatter import split_frontmatter
from agent_hub.core.features.feature_record import KEY_PATTERN, PlannedTicket, RecordAc
from agent_hub.core.features.feature_view import EvalRecord, Verdict
from agent_hub.core.features.scope_rules import (
    AC_ID_PATTERN,
    ALL_ACS,
    COMMIT_PATTERN,
    RERUN_PATTERN,
    named_scope,
    ticket_aliases,
)
from agent_hub.core.hub_config.problems import one_line

if TYPE_CHECKING:
    from agent_hub.core.features.feature_status import RecordHead

EVALS_FOLDER: Final = "evals"
# At most this many ``evals/*.md`` files are read, by name; their first bytes only.
MAX_EVAL_FILES: Final = 200
EVAL_HEAD_BYTES: Final = 16_384
LEGACY_DELIVERY: Final = "legacy"
NOTE_SUFFIX: Final = ".md"
# A delivery: a lower-case ticket id, ``pr-<repo>-<n>``, ``feature``; a re-run adds ``-r2``...
DELIVERY_PATTERN: Final = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
# The first ``Verdict`` line of a legacy ``eval.md`` (``**Verdict:** SHIP`` too).
VERDICT_LINE: Final = re.compile(r"Verdict\W{0,4}(SHIP-WITH-OWNER-STEPS|NO-SHIP|SHIP)\b")
# A ``Final verdict`` line of a legacy ``eval.md`` wins over its first ``Verdict`` line.
FINAL_VERDICT_LINE: Final = re.compile(
    r"Final\s+verdict\W{0,4}(SHIP-WITH-OWNER-STEPS|NO-SHIP|SHIP)\b", re.IGNORECASE
)
# An ISO date, optionally with a time and an offset.
ISO_TIME: Final = re.compile(
    r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?(?:Z|[+-]\d{2}:?\d{2})?)?"
)
_TICKET: Final = re.compile(KEY_PATTERN)
_PR: Final = re.compile(r"[A-Za-z0-9._/#:-]{1,200}")
_SHIPPED: Final = ("SHIP", "SHIP-WITH-OWNER-STEPS")
# When the latest evals of an AC disagree, the first of these among them decides.
_CONSERVATIVE: Final[tuple[Verdict, ...]] = ("NO-SHIP", "SHIP-WITH-OWNER-STEPS", "SHIP")
_VERDICTS: Final[tuple[str, ...]] = get_args(Verdict.__value__)


class RecordFieldError(ValueError):
    """A record file's frontmatter does not hold what it must; ``str()`` says what."""


@dataclass(frozen=True, kw_only=True, slots=True)
class EvalCoverage:
    """The non-withdrawn ACs of a feature, by what the latest eval naming each one says.

    ``covered`` (SHIP or SHIP-WITH-OWNER-STEPS), ``owner_steps`` (the covered ones whose deciding
    verdict is SHIP-WITH-OWNER-STEPS) and ``uncovered`` (NO-SHIP, or no eval names it) hold AC ids
    in ``features.json`` order; ``total`` counts them. ``unscoped`` is True when a legacy
    ``eval.md`` without scope could not count ("partial: scope not recorded").
    """

    covered: tuple[str, ...]
    owner_steps: tuple[str, ...]
    uncovered: tuple[str, ...]
    total: int
    unscoped: bool


def eval_records(
    heads: Sequence[RecordHead], legacy_head: bytes | None, *, slug: str
) -> tuple[EvalRecord, ...]:
    """Each eval of the feature ``slug``: the heads of ``evals/*.md`` and the legacy ``eval.md``
    (``legacy_head``, None when absent). Listed oldest first as far as the order is known: the
    legacy eval, then the dated evals by instant, then the undated ones by delivery and re-run
    (the listing only; ``eval_coverage`` uses the partial order of the module docstring).

    A file that cannot be read or whose frontmatter is malformed is listed with its ``problem``
    and empty fields; it covers nothing.
    """
    records = [_eval(head, slug=slug) for head in heads]
    if legacy_head is not None:
        records.append(_legacy(legacy_head, slug=slug))
    return tuple(sorted(records, key=_listing_key))


def eval_coverage(
    records: Iterable[EvalRecord],
    acs: Iterable[RecordAc],
    *,
    tickets: Iterable[PlannedTicket] = (),
) -> EvalCoverage:
    """What ``records`` cover of ``acs`` (S7); ``tickets`` tie a plan key to its tracker id."""
    live = tuple(ac for ac in acs if not ac.withdrawn)
    aliases = ticket_aliases(tickets)
    naming: dict[str, list[int]] = {}
    scoped: list[EvalRecord] = []
    unscoped = False
    for record in records:
        if record.problem is not None or record.verdict is None:
            continue
        named = _scope(record, live, aliases)
        if named is None:
            unscoped = True
            continue
        for ac_id in dict.fromkeys(named):
            naming.setdefault(ac_id, []).append(len(scoped))
        scoped.append(record)
    keys = [_order_key(record) for record in scoped]
    decided: dict[tuple[int, ...], Verdict] = {}
    verdicts: dict[str, Verdict] = {}
    for ac_id, indexes in naming.items():
        group = tuple(indexes)
        if group not in decided:
            decided[group] = _latest_verdict(group, scoped, keys)
        verdicts[ac_id] = decided[group]
    covered = tuple(ac.id for ac in live if verdicts.get(ac.id) in _SHIPPED)
    return EvalCoverage(
        covered=covered,
        owner_steps=tuple(ac.id for ac in live if verdicts.get(ac.id) == "SHIP-WITH-OWNER-STEPS"),
        uncovered=tuple(ac.id for ac in live if ac.id not in covered),
        total=len(live),
        unscoped=unscoped,
    )


def record_fields(head: bytes) -> dict[str, FrontmatterValue]:
    """The frontmatter fields of a record file's ``head``; ``RecordFieldError`` when it has none or
    it is malformed (a cut multi-byte character at the end of the head is replaced)."""
    front = split_frontmatter(head.decode("utf-8", "replace"))
    if front.problem is not None:
        raise RecordFieldError(f"frontmatter: {front.problem}")
    if not front.fields:
        raise RecordFieldError("no frontmatter")
    return front.fields


def text_field(
    fields: dict[str, FrontmatterValue], name: str, pattern: re.Pattern[str] | None = None
) -> str | None:
    """The one-line value of ``name`` (None when absent or empty), matching ``pattern`` when one
    is given; ``RecordFieldError`` otherwise."""
    value = fields.get(name)
    if value is None or value == "":
        return None
    if isinstance(value, list):
        raise RecordFieldError(f"{name} must be one value, not a list")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise RecordFieldError(f"{name} is not valid: {value[:64]}")
    return value


def record_type(fields: dict[str, FrontmatterValue], expected: str) -> None:
    """``RecordFieldError`` when the file says it is another ``type`` of record."""
    found = text_field(fields, "type")
    if found is not None and found != expected:
        raise RecordFieldError(f"type is {found[:64]}, not {expected}")


def _eval(head: RecordHead, *, slug: str) -> EvalRecord:
    stem = head.name.removesuffix(NOTE_SUFFIX)
    path = f"features/{slug}/{EVALS_FOLDER}/{head.name}"
    if head.head is None:
        return _broken(stem, path, head.problem or "could not be read")
    try:
        return _parsed(stem, path, record_fields(head.head))
    except RecordFieldError as problem:
        return _broken(stem, path, str(problem))


def _parsed(stem: str, path: str, fields: dict[str, FrontmatterValue]) -> EvalRecord:
    record_type(fields, "eval")
    if DELIVERY_PATTERN.fullmatch(stem) is None:
        raise RecordFieldError(f"the file name is not a delivery ({DELIVERY_PATTERN.pattern})")
    delivery = text_field(fields, "delivery") or stem
    if delivery != stem:
        raise RecordFieldError(f"delivery {delivery[:64]} does not match the file name")
    verdict = _verdict(fields)
    tickets = _items(fields, "tickets", _TICKET)
    acs = _acs(fields)
    if not tickets and not acs:
        raise RecordFieldError("no scope: neither acs nor tickets")
    return EvalRecord(
        delivery=delivery,
        path=path,
        verdict=verdict,
        tickets=tickets,
        acs=acs,
        prs=_items(fields, "prs", _PR),
        commit=text_field(fields, "commit", COMMIT_PATTERN),
        evaluated_at=text_field(fields, "evaluated_at", ISO_TIME),
        legacy=False,
        problem=None,
    )


def _legacy(head: bytes, *, slug: str) -> EvalRecord:
    """``eval.md``: its verdict line, and its frontmatter's scope when it has a valid one."""
    tickets: tuple[str, ...] = ()
    acs: tuple[str, ...] | Literal["all"] = ()
    prs: tuple[str, ...] = ()
    commit = evaluated_at = None
    try:
        fields = record_fields(head)
        tickets, acs = _items(fields, "tickets", _TICKET), _acs(fields)
        prs, commit = _items(fields, "prs", _PR), text_field(fields, "commit", COMMIT_PATTERN)
        evaluated_at = text_field(fields, "evaluated_at", ISO_TIME)
    except RecordFieldError:
        tickets, acs, prs, commit, evaluated_at = (), (), (), None, None
    return EvalRecord(
        delivery=LEGACY_DELIVERY,
        path=f"features/{slug}/eval.md",
        verdict=legacy_verdict(head),
        tickets=tickets,
        acs=acs,
        prs=prs,
        commit=commit,
        evaluated_at=evaluated_at,
        legacy=True,
        problem=None,
    )


def legacy_verdict(head: bytes) -> Verdict | None:
    """The verdict of ``eval.md``: its ``Final verdict`` line, else its first ``Verdict`` line;
    None without one."""
    found = legacy_verdict_line(head)
    return None if found is None else found[0]


def legacy_verdict_line(head: bytes) -> tuple[Verdict, str] | None:
    """The verdict of ``eval.md`` and the line that holds it: the first ``Final verdict`` line,
    else the first ``Verdict`` line; None without one."""
    lines = head.decode("utf-8", "replace").splitlines()
    for pattern in (FINAL_VERDICT_LINE, VERDICT_LINE):
        for line in lines:
            found = pattern.search(line)
            if found is not None:
                return cast("Verdict", found.group(1).upper()), line
    return None


def _broken(stem: str, path: str, problem: str) -> EvalRecord:
    return EvalRecord(
        delivery=stem,
        path=path,
        verdict=None,
        tickets=(),
        acs=(),
        prs=(),
        commit=None,
        evaluated_at=None,
        legacy=False,
        problem=one_line(problem),
    )


def _verdict(fields: dict[str, FrontmatterValue]) -> Verdict:
    verdict = text_field(fields, "verdict")
    if verdict not in _VERDICTS:
        raise RecordFieldError(f"verdict must be one of {', '.join(_VERDICTS)}")
    return cast("Verdict", verdict)


def _items(
    fields: dict[str, FrontmatterValue], name: str, pattern: re.Pattern[str]
) -> tuple[str, ...]:
    value = fields.get(name)
    if value is None or value == "":
        return ()
    items = value if isinstance(value, list) else [value]
    for item in items:
        if pattern.fullmatch(item) is None:
            raise RecordFieldError(f"{name} has an invalid item: {item[:64]}")
    return tuple(dict.fromkeys(items))


def _acs(fields: dict[str, FrontmatterValue]) -> tuple[str, ...] | Literal["all"]:
    return "all" if fields.get("acs") == ALL_ACS else _items(fields, "acs", AC_ID_PATTERN)


@dataclass(frozen=True, slots=True)
class _OrderKey:
    instant: datetime | None
    legacy: bool
    stem: str
    rerun: int


def _order_key(record: EvalRecord) -> _OrderKey:
    found = RERUN_PATTERN.search(record.delivery)
    stem = record.delivery[: found.start()] if found else record.delivery
    return _OrderKey(
        instant=_instant(record.evaluated_at),
        legacy=record.legacy,
        stem=stem,
        rerun=int(found.group(1)) if found else 1,
    )


def _instant(text: str | None) -> datetime | None:
    """``evaluated_at`` as an instant in UTC (no offset: UTC); None when absent or unusable."""
    if text is None:
        return None
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def _newer(first: _OrderKey, second: _OrderKey) -> bool:
    """True when ``first`` is known to be newer than ``second`` (the module's partial order)."""
    left, right = first.instant, second.instant
    if left is not None and right is not None and left != right:
        return left > right
    if first.legacy != second.legacy:
        return second.legacy
    return first.stem == second.stem and first.rerun > second.rerun


def _latest_verdict(
    group: tuple[int, ...], records: Sequence[EvalRecord], keys: Sequence[_OrderKey]
) -> Verdict:
    """The verdict of the latest evals in ``group``: those no other is newer than (all of them
    if the order loops), the conservative one when they disagree."""
    latest = [
        index
        for index in group
        if not any(_newer(keys[other], keys[index]) for other in group if other != index)
    ] or list(group)
    verdicts = {records[index].verdict for index in latest}
    return next(verdict for verdict in _CONSERVATIVE if verdict in verdicts)


def _listing_key(record: EvalRecord) -> tuple[bool, bool, datetime, str, int, str]:
    key = _order_key(record)
    instant = key.instant or datetime.min.replace(tzinfo=UTC)
    return (not key.legacy, key.instant is None, instant, key.stem, key.rerun, record.path)


def _scope(
    record: EvalRecord, live: tuple[RecordAc, ...], aliases: dict[str, frozenset[str]]
) -> tuple[str, ...] | None:
    """The AC ids ``record`` names; None for a legacy eval without scope that cannot count."""
    named = named_scope(acs=record.acs, tickets=record.tickets, live=live, aliases=aliases)
    if named is not None:
        return named
    if record.legacy and all(ac.passes for ac in live):
        return tuple(ac.id for ac in live)
    return None
