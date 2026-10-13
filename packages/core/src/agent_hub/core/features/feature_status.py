"""A feature folder's state (D23, AGH-136), from the files the generator read: pure, no I/O.

``features.json`` (``feature_record.py``) gives the acceptance criteria and the ticket plan:
passing ACs, owner steps (a criterion whose verification starts with ``manual`` and does not pass
yet), the planned tickets and the Linear ids. ``spec.md``'s frontmatter gives the size
(``process_size``), ``repos`` and ``linear`` issues; ``eval.md``'s first ``Verdict`` line the
verdict. ``evals/*.md`` and ``reviews/*.md`` are the evals per delivery and the review records.
The golden path (``golden_path.py``) folds all of it with the ticket board (``ticket_planning.py``)
over a tracker snapshot when one is given (the warm cache), else the plan; ``phase`` is its
phase. The detail's ``records`` name each record file (brain-relative, so the brain note route
reads it) and whether it is present. A malformed or unreadable record degrades this feature
only: its ``problem`` says why and its criteria are unknown.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Literal, cast

from pydantic import ValidationError

from agent_hub.core.events.event import EventSource
from agent_hub.core.features.feature_evals import eval_coverage, eval_records
from agent_hub.core.features.feature_record import FeatureRecordFile, RecordAc
from agent_hub.core.features.feature_reviews import approved_tickets, review_records
from agent_hub.core.features.feature_view import (
    AcCounts,
    AcRow,
    EvalRecord,
    FeatureDetail,
    FeatureRecord,
    FeatureRecordName,
    FeatureView,
    GoldenPath,
    TicketsSource,
    Verdict,
)
from agent_hub.core.features.golden_path import EvalGate, GoldenInputs, golden_path
from agent_hub.core.features.ticket_planning import TicketBoard, ticket_board
from agent_hub.core.features.ticket_snapshots import SnapshotRead
from agent_hub.core.hub_config.problems import one_line
from agent_hub.core.json_form import InvalidJsonError, load_json_bytes
from agent_hub.core.tracker.tracker_client import ISSUE_ID_PATTERN

SPEC: Final = "spec.md"
RESEARCH: Final = "research.md"
PLAN: Final = "plan.md"
ISSUES: Final = "issues.md"
RECORD: Final = "features.json"
EVAL: Final = "eval.md"
# The record files of a feature folder, in the order a feature is built.
RECORD_FILES: Final = (SPEC, RESEARCH, PLAN, ISSUES, RECORD, EVAL)
# How much of ``spec.md`` and ``eval.md`` is read for the frontmatter and the verdict.
HEAD_BYTES: Final = 65_536
_VERDICT_LINE_CHARS: Final = 200
_SIZES: Final = ("spike", "bounded", "architectural")

type FeatureSize = Literal["spike", "bounded", "architectural"]
_VERDICT: Final = re.compile(r"Verdict\W{0,4}(SHIP-WITH-OWNER-STEPS|NO-SHIP|SHIP)\b")
_MANUAL: Final = re.compile(r"\s*manual\b", re.IGNORECASE)
# The records a feature detail lists, each with its file (AC-201.32), in the order shown.
_RECORDS: Final[tuple[tuple[FeatureRecordName, str], ...]] = (
    ("spec", SPEC),
    ("research", RESEARCH),
    ("plan", PLAN),
    ("eval", EVAL),
    ("issues", ISSUES),
)
FEATURES_FOLDER: Final = "features"


@dataclass(frozen=True, kw_only=True, slots=True)
class RecordHead:
    """The start of one file of ``evals/`` or ``reviews/``: its ``name`` and ``head`` bytes, or
    the one-line ``problem`` that kept it from being read (a link, not a regular file)."""

    name: str
    head: bytes | None
    problem: str | None


@dataclass(frozen=True, kw_only=True, slots=True)
class FeatureFolder:
    """What was read of ``brain/features/<slug>/``.

    ``files`` names the record files present as regular files. ``features_json`` holds the
    record's bytes, a one-line problem when it could not be read, or None when absent;
    ``spec_head`` and ``eval_head`` are the first ``HEAD_BYTES`` of ``spec.md`` and ``eval.md``.
    ``evals`` and ``reviews`` hold the heads of ``evals/*.md`` and ``reviews/*.md`` sorted by
    name; ``evals_skipped`` and ``reviews_skipped`` count the files left unread over the cap.
    """

    slug: str
    files: tuple[str, ...]
    features_json: bytes | str | None = None
    spec_head: bytes | None = None
    eval_head: bytes | None = None
    evals: tuple[RecordHead, ...] = ()
    reviews: tuple[RecordHead, ...] = ()
    evals_skipped: int = 0
    reviews_skipped: int = 0


@dataclass(frozen=True, kw_only=True, slots=True)
class FeatureParts:
    """What the feature views share: the parsed ``record`` (its one-line problem, or None when
    absent), every eval, the ticket ``board``, the ``golden_path`` and the tickets' ``source``."""

    record: FeatureRecordFile | str | None
    evals: tuple[EvalRecord, ...]
    board: TicketBoard
    golden_path: GoldenPath
    source: TicketsSource


def ticket_ids(folder: FeatureFolder) -> tuple[str, ...]:
    """The tracker ids of the feature's tickets (planned ones created, and ``linear``), sorted
    and unique: what a snapshot of it reads. None for a record that is absent or malformed."""
    record = _record(folder.features_json)
    if not isinstance(record, FeatureRecordFile):
        return ()
    ids = (
        *(ticket.id for ticket in record.tickets if ticket.id is not None),
        *(issue for issue in record.linear if ISSUE_ID_PATTERN.fullmatch(issue) is not None),
    )
    return tuple(sorted(set(ids)))


def feature_parts(folder: FeatureFolder, read: SnapshotRead | None = None) -> FeatureParts:
    """The feature's evals, ticket board and golden path, over ``read``'s snapshot when it holds
    one (else the plan; ``read`` None is a hub web with no tracker reader: not connected)."""
    record = _record(folder.features_json)
    parsed = record if isinstance(record, FeatureRecordFile) else None
    acs = () if parsed is None else parsed.acs
    tickets = () if parsed is None else parsed.tickets
    evals = eval_records(folder.evals, folder.eval_head, slug=folder.slug)
    coverage = eval_coverage(evals, acs, tickets=tickets)
    approved = approved_tickets(review_records(folder.reviews, slug=folder.slug))
    snapshot = None if read is None else read.snapshot
    board = ticket_board(
        tickets,
        acs,
        snapshot,
        linear=() if parsed is None else parsed.linear,
        approved=approved,
    )
    source: TicketsSource = "plan" if snapshot is None else "linear"
    gate = EvalGate(
        evals=len(evals),
        covered=len(coverage.covered),
        owner_steps=len(coverage.owner_steps),
        scope_recorded=not coverage.unscoped or len(coverage.covered) == coverage.total > 0,
        skipped=folder.evals_skipped,
    )
    path = golden_path(
        GoldenInputs(
            files=folder.files,
            rows=board.rows,
            acs=acs,
            coverage=gate,
            approved_reviews=sum(_approved(row.key, row.id, approved) for row in board.rows),
            reviews_skipped=folder.reviews_skipped,
            source=source,
            not_loaded=read is not None and snapshot is None and read.failure is None,
        )
    )
    return FeatureParts(record=record, evals=evals, board=board, golden_path=path, source=source)


def feature_view(
    folder: FeatureFolder, *, project: str, read: SnapshotRead | None = None
) -> FeatureView:
    """The feature as the Features list shows it (``read``: the warm snapshot, as the detail)."""
    detail = feature_detail(folder, project=project, read=read)
    return FeatureView.model_validate(detail.model_dump(include=set(FeatureView.model_fields)))


def feature_detail(
    folder: FeatureFolder, *, project: str, read: SnapshotRead | None = None
) -> FeatureDetail:
    """The feature with its acceptance criteria rows and every eval; ``read`` is what the
    snapshot cache holds for its tickets (never a tracker read), None when hub web has none."""
    front = _frontmatter(folder.spec_head)
    parts = feature_parts(folder, read)
    record = parts.record
    rows = () if not isinstance(record, FeatureRecordFile) else tuple(_row(ac) for ac in record.acs)
    verdict, verdict_line = _verdict(folder.eval_head)
    spec_repos = _listed(front.get("repos"))
    return FeatureDetail(
        project=project,
        slug=folder.slug,
        issues=_unique(
            (
                *_listed(front.get("linear")),
                *(record.linear if isinstance(record, FeatureRecordFile) else ()),
            )
        ),
        size=_size(front.get("process_size")),
        phase=parts.golden_path.phase,
        files=tuple(name for name in RECORD_FILES if name in folder.files),
        acs=None if not isinstance(record, FeatureRecordFile) else _counts(rows),
        verdict=verdict,
        verdict_line=verdict_line,
        repos=spec_repos or _unique(row.repo for row in rows if row.repo),
        golden_path=parts.golden_path,
        tickets_source=parts.source,
        problem=record if isinstance(record, str) else None,
        sources_missing=(EventSource.GITHUB,),
        ac_rows=rows,
        records=_records(folder),
        evals=parts.evals,
    )


def _approved(key: str | None, issue_id: str | None, approved: frozenset[str]) -> bool:
    return any(name is not None and name.upper() in approved for name in (key, issue_id))


def _records(folder: FeatureFolder) -> tuple[FeatureRecord, ...]:
    """Each record file with its brain-relative path and whether the folder listing had it."""
    return tuple(
        FeatureRecord(
            name=name,
            path=f"{FEATURES_FOLDER}/{folder.slug}/{file}",
            present=file in folder.files,
        )
        for name, file in _RECORDS
    )


def _record(read: bytes | str | None) -> FeatureRecordFile | str | None:
    if read is None:
        return None
    if isinstance(read, str):
        return one_line(f"{RECORD} could not be read ({read})")
    try:
        return FeatureRecordFile.model_validate(load_json_bytes(read))
    except InvalidJsonError as error:
        return one_line(f"{RECORD} could not be parsed ({error.message})")
    except ValidationError as error:
        first = error.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        return one_line(f"{RECORD} could not be parsed ({where}: {first['msg']})")


def _row(ac: RecordAc) -> AcRow:
    return AcRow(
        id=ac.id,
        description=ac.description,
        repo=ac.repo,
        passes=ac.passes,
        manual=ac.verification is not None and _MANUAL.match(ac.verification) is not None,
        evidence=ac.evidence,
        command=ac.verification,
    )


def _counts(rows: tuple[AcRow, ...]) -> AcCounts:
    return AcCounts(
        passing=sum(row.passes for row in rows),
        total=len(rows),
        owner_steps=sum(row.manual and not row.passes for row in rows),
    )


def _verdict(head: bytes | None) -> tuple[Verdict | None, str | None]:
    if head is None:
        return None, None
    for line in head.decode("utf-8", "replace").splitlines():
        found = _VERDICT.search(line)
        if found is not None:
            shown = one_line(line.strip())[:_VERDICT_LINE_CHARS]
            return cast("Verdict", found.group(1)), shown
    return None, None


def _frontmatter(head: bytes | None) -> dict[str, str]:
    """The ``key: value`` lines between the leading ``---`` lines; nothing without them."""
    if head is None:
        return {}
    lines = head.decode("utf-8", "replace").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    found: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return found
        key, colon, value = line.partition(":")
        if colon and key and not key.startswith((" ", "\t")):
            found[key.strip()] = value.strip()
    return {}


def _listed(value: str | None) -> tuple[str, ...]:
    """``[a, b]`` or a single ``a`` as a tuple; quotes around items are dropped."""
    if not value:
        return ()
    inner = value[1:-1] if value.startswith("[") and value.endswith("]") else value
    return _unique(item.strip().strip("'\"") for item in inner.split(","))


def _size(value: str | None) -> FeatureSize | None:
    return cast("FeatureSize", value) if value in _SIZES else None


def _unique(items: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item for item in items if item))
