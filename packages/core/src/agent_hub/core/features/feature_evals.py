"""Evals per delivery and what they cover (AGH-136 S6, S7): pure, no I/O.

Each evaluation is its own file, ``brain/features/<slug>/evals/<delivery>.md``, whose frontmatter
holds its scope: ``type: eval``, ``delivery``, ``verdict``, ``tickets``, ``acs`` (ids or ``all``),
``prs``, ``commit`` and ``evaluated_at``. A legacy ``eval.md`` is one delivery, ``legacy``, whose
verdict is its first ``Verdict`` line and whose scope is its frontmatter, when it has one.

For each AC the latest eval whose scope names it decides (S7): it is covered when that verdict is
SHIP or SHIP-WITH-OWNER-STEPS. "Latest" is ``evaluated_at`` (ISO text, compared as text), then the
re-run suffix ``-rN``, then the file name. An eval naming only ``tickets`` covers the ACs whose
``ticket`` is one of them (a plan key and its tracker id are the same ticket). A legacy eval
without scope covers every AC only when every AC passes in ``features.json``; otherwise it covers
none and the coverage is ``unscoped``. Withdrawn ACs are left out of every count.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, cast, get_args

from agent_hub.core.brain.brain_note import FrontmatterValue
from agent_hub.core.brain.frontmatter import split_frontmatter
from agent_hub.core.features.feature_record import KEY_PATTERN, PlannedTicket, RecordAc
from agent_hub.core.features.feature_view import EvalRecord, Verdict
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
# An ISO date, optionally with a time and an offset.
ISO_TIME: Final = re.compile(
    r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?(?:Z|[+-]\d{2}:?\d{2})?)?"
)
_AC_ID: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_TICKET: Final = re.compile(KEY_PATTERN)
_PR: Final = re.compile(r"[A-Za-z0-9._/#:-]{1,200}")
_COMMIT: Final = re.compile(r"[0-9a-f]{7,40}")
_RERUN: Final = re.compile(r"-r([1-9][0-9]{0,3})$")
_SHIPPED: Final = ("SHIP", "SHIP-WITH-OWNER-STEPS")
_ALL: Final = "all"
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
    (``legacy_head``, None when absent), oldest first (the order "latest" uses).

    A file that cannot be read or whose frontmatter is malformed is listed with its ``problem``
    and empty fields; it covers nothing.
    """
    records = [_eval(head, slug=slug) for head in heads]
    if legacy_head is not None:
        records.append(_legacy(legacy_head, slug=slug))
    return tuple(sorted(records, key=_recency))


def eval_coverage(
    records: Iterable[EvalRecord],
    acs: Iterable[RecordAc],
    *,
    tickets: Iterable[PlannedTicket] = (),
) -> EvalCoverage:
    """What ``records`` cover of ``acs`` (S7); ``tickets`` tie a plan key to its tracker id."""
    live = tuple(ac for ac in acs if not ac.withdrawn)
    aliases = _aliases(tickets)
    deciding: dict[str, tuple[tuple[str, int, str], Verdict]] = {}
    unscoped = False
    for record in records:
        if record.problem is not None or record.verdict is None:
            continue
        named = _scope(record, live, aliases)
        if named is None:
            unscoped = True
            continue
        rank = _recency(record)
        for ac_id in named:
            if ac_id not in deciding or deciding[ac_id][0] <= rank:
                deciding[ac_id] = (rank, record.verdict)
    verdicts = {ac_id: verdict for ac_id, (_, verdict) in deciding.items()}
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
        commit=text_field(fields, "commit", _COMMIT),
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
        prs, commit = _items(fields, "prs", _PR), text_field(fields, "commit", _COMMIT)
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
    """The verdict of ``eval.md``'s first ``Verdict`` line; None without one."""
    for line in head.decode("utf-8", "replace").splitlines():
        found = VERDICT_LINE.search(line)
        if found is not None:
            return cast("Verdict", found.group(1))
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
    return "all" if fields.get("acs") == _ALL else _items(fields, "acs", _AC_ID)


def _recency(record: EvalRecord) -> tuple[str, int, str]:
    found = _RERUN.search(record.delivery)
    return (record.evaluated_at or "", int(found.group(1)) if found else 1, record.path)


def _aliases(tickets: Iterable[PlannedTicket]) -> dict[str, frozenset[str]]:
    """Each ticket ref (upper case) with every ref of the same ticket (its key and its id)."""
    aliases: dict[str, frozenset[str]] = {}
    for ticket in tickets:
        refs = frozenset(ref.upper() for ref in (ticket.key, ticket.id) if ref is not None)
        for ref in refs:
            aliases[ref] = aliases.get(ref, frozenset()) | refs
    return aliases


def _scope(
    record: EvalRecord, live: tuple[RecordAc, ...], aliases: dict[str, frozenset[str]]
) -> tuple[str, ...] | None:
    """The AC ids ``record`` names; None for a legacy eval without scope that cannot count."""
    if record.acs == _ALL:
        return tuple(ac.id for ac in live)
    if record.acs:
        return record.acs
    if record.tickets:
        named: set[str] = set()
        for ref in record.tickets:
            named |= aliases.get(ref.upper(), frozenset({ref.upper()}))
        return tuple(ac.id for ac in live if ac.ticket is not None and ac.ticket.upper() in named)
    if record.legacy and all(ac.passes for ac in live):
        return tuple(ac.id for ac in live)
    return None
