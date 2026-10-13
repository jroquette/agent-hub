"""A feature folder's state (D23), from the files the generator read: pure, no I/O.

``features.json`` gives the acceptance criteria: passing ones, and owner steps (a criterion whose
verification starts with ``manual`` and does not pass yet). ``spec.md``'s frontmatter gives the
size (``process_size``), ``repos`` and ``linear`` issues; ``eval.md``'s first ``Verdict`` line the
verdict. The detail's ``records`` name each record file (brain-relative, so the brain note route
reads it) and whether it is present. The golden path phase comes from the files alone: spec,
research, plan, tickets (``issues.md``), implement (an AC passes), evaluate (a verdict). Review
needs runs and Shipped needs GitHub, not connected in Phase 2. A malformed or unreadable record
degrades this feature only: its ``problem`` says why and its criteria are unknown.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Literal, cast

from pydantic import ValidationError

from agent_hub.core.events.event import EventSource
from agent_hub.core.features.feature_record import FeatureRecordFile, RecordAc
from agent_hub.core.features.feature_view import (
    AcCounts,
    AcRow,
    FeatureDetail,
    FeaturePhase,
    FeatureRecord,
    FeatureRecordName,
    FeatureView,
    GoldenPath,
    GoldenStep,
    StepState,
    Verdict,
)
from agent_hub.core.hub_config.problems import one_line
from agent_hub.core.json_form import InvalidJsonError, load_json_bytes

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
_FILE_PHASES: Final[tuple[tuple[str, FeaturePhase], ...]] = (
    (SPEC, "spec"),
    (RESEARCH, "research"),
    (PLAN, "plan"),
    (ISSUES, "tickets"),
)
# The golden path's steps in order, with the record file a step reads, if any.
_STEPS: Final[tuple[tuple[FeaturePhase, str | None], ...]] = (
    ("spec", SPEC),
    ("research", RESEARCH),
    ("plan", PLAN),
    ("tickets", ISSUES),
    ("implement", None),
    ("review", None),
    ("evaluate", EVAL),
    ("shipped", None),
)


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


def feature_view(folder: FeatureFolder, *, project: str) -> FeatureView:
    """The feature as the Features list shows it."""
    detail = feature_detail(folder, project=project)
    return FeatureView.model_validate(detail.model_dump(include=set(FeatureView.model_fields)))


def feature_detail(folder: FeatureFolder, *, project: str) -> FeatureDetail:
    """The feature with its acceptance criteria rows."""
    front = _frontmatter(folder.spec_head)
    record = _record(folder.features_json)
    rows = () if not isinstance(record, FeatureRecordFile) else tuple(_row(ac) for ac in record.acs)
    verdict, verdict_line = _verdict(folder.eval_head)
    spec_repos = _listed(front.get("repos"))
    phase = _phase(folder.files, rows=rows, verdict=verdict)
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
        phase=phase,
        files=tuple(name for name in RECORD_FILES if name in folder.files),
        acs=None if not isinstance(record, FeatureRecordFile) else _counts(rows),
        verdict=verdict,
        verdict_line=verdict_line,
        repos=spec_repos or _unique(row.repo for row in rows if row.repo),
        golden_path=_interim_path(phase, files=folder.files, verdict=verdict),
        tickets_source="plan",
        problem=record if isinstance(record, str) else None,
        sources_missing=(EventSource.GITHUB,),
        ac_rows=rows,
        records=_records(folder),
    )


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


def _phase(
    files: tuple[str, ...], *, rows: tuple[AcRow, ...], verdict: Verdict | None
) -> FeaturePhase:
    if verdict is not None:
        return "evaluate"
    if any(row.passes for row in rows):
        return "implement"
    reached = [phase for name, phase in _FILE_PHASES if name in files]
    return reached[-1] if reached else "spec"


def _interim_path(
    phase: FeaturePhase, *, files: tuple[str, ...], verdict: Verdict | None
) -> GoldenPath:
    """Today's step states, as the web drew them from ``phase`` (removed by AGH-136 C.1)."""
    current = [name for name, _ in _STEPS].index(phase)
    steps = tuple(
        GoldenStep(
            name=name,
            state=_interim_state(index, current, file=file, files=files, verdict=verdict),
            meta=None,
            reason="not tracked in this version" if name in ("review", "shipped") else None,
            progress=None,
        )
        for index, (name, file) in enumerate(_STEPS)
    )
    return GoldenPath(steps=steps, phase=phase)


def _interim_state(
    index: int, current: int, *, file: str | None, files: tuple[str, ...], verdict: Verdict | None
) -> StepState:
    name = _STEPS[index][0]
    if name in ("review", "shipped"):
        return "unknown"
    if index < current:
        return "skipped" if file is not None and file not in files else "done"
    if index == current:
        return "done" if name == "evaluate" and verdict is not None else "current"
    return "pending"


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
