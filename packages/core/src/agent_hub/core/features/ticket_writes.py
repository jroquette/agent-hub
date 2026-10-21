"""The ticket records an ``implement`` run writes (two-level-flows S2, P7): their bytes, pure.

``hub step`` writes them into the hub's feature folder and never commits. Each text is checked
the way its reader will read it, so a record this module returns is never a record problem:

- ``tickets/<ticket>/brief.md``, the context brief: one ``## Brief v<n> (<time>)`` section per
  run, appended, every earlier byte kept (NFR Idempotency). A section opens with its fields as a
  JSON block (``plan_version``, ``blockers`` ``{id, outcome_path, recorded_at}``, ``adrs``), then
  the ticket's ACs, its plan section (quoted), its blockers, main's commits since the plan on
  the files the section names, and the ADRs it cites.
- ``tickets/<ticket>/preflight.json``: one run appended to the ``PreflightRecord``; earlier runs
  are copied as parsed JSON, never through the model, so each stays equal in canonical form.
- ``change-requests/<n>.md`` and ``change-requests/<n>.decision.md``: what ``ticket_records``
  reads; a decision needs a person (A5) and a decline a note (AC-2.12).
- ``plan.md``: one ``A<k> (<date>, <who>): …`` entry appended at the end, under an
  ``## Amendments`` heading (added when the last section is another), only while the plan is
  still the version the approved request was opened against.
"""

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final, cast

from pydantic import ValidationError

from agent_hub.core.approvals.decide_gate import NO_PERSON
from agent_hub.core.brain.frontmatter import scalar, split_frontmatter
from agent_hub.core.errors import AgentHubError
from agent_hub.core.features.feature_evals import RecordFieldError, record_fields, text_field
from agent_hub.core.features.feature_record import KEY_PATTERN, RecordAc
from agent_hub.core.features.feature_status import RecordHead
from agent_hub.core.features.output_models import (
    OutputProblem,
    PreflightRecord,
    PreflightRun,
)
from agent_hub.core.features.output_shape import parse_document, shape_problems
from agent_hub.core.features.plan_version import last_section, opens_amendments, plan_version
from agent_hub.core.features.ticket_records import (
    CHANGE_REQUEST_HEAD_BYTES,
    MAX_PREFLIGHT_BYTES,
    change_requests,
    preflight_record,
)
from agent_hub.core.hub_config.problems import one_line

BRIEF_TYPE: Final = "ticket-brief"
PREFLIGHT_SCHEMA: Final = "agent-hub/preflight/1"
# A decision's note on its frontmatter line; the whole note is the file's body.
NOTE_LINE_CHARS: Final = 1000
MAX_NAMED_PATHS: Final = 50

_TICKET: Final = re.compile(KEY_PATTERN)
_RUN_ID: Final = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
_BRIEF_HEADING: Final = re.compile(r"^## Brief v[1-9][0-9]* \(", re.MULTILINE)
_HEADING: Final = re.compile(r" {0,3}(#{1,6})[ \t]+(.*)")
_CODE_SPAN: Final = re.compile(r"`([^`\s]+)`")
_PATH: Final = re.compile(r"[A-Za-z0-9_.@-]+(?:/[A-Za-z0-9_.@-]+)+/?")
_LINE_SUFFIX: Final = re.compile(r":[0-9]+(?:[-,][0-9]+)*$")
_ADR: Final = re.compile(r"\bADR[ -]?([0-9]{4})\b|docs/adr/([0-9]{4})-")
_REQUEST_NAME: Final = re.compile(r"([1-9][0-9]{0,5})(?:\.decision)?\.md")
_AMENDMENT_ID: Final = re.compile(r"A([1-9][0-9]*)")


class TicketRecordError(AgentHubError):
    """A record refused, nothing written; the message says why in one line."""


@dataclass(frozen=True, kw_only=True, slots=True)
class Blocker:
    """A blocker of the ticket and its outcome: the path under the feature folder and its
    ``merged_at``, both None when no outcome is recorded."""

    id: str
    outcome_path: str | None
    recorded_at: str | None


@dataclass(frozen=True, kw_only=True, slots=True)
class TicketBrief:
    """What one context run read: ``commits`` as lines, or ``commits_note`` saying why none were
    read."""

    ticket: str
    at: datetime
    plan_version: int
    acs: tuple[RecordAc, ...]
    plan_section: str
    blockers: tuple[Blocker, ...]
    adrs: tuple[str, ...]
    commits: tuple[str, ...]
    commits_note: str | None


def appended_brief(existing: bytes | None, brief: TicketBrief) -> tuple[bytes, int]:
    """``brief.md`` with ``brief`` appended as its next version, and that version."""
    if existing is None:
        front = f"---\ntype: {BRIEF_TYPE}\nticket: {brief.ticket}\n---\n"
        start = f"{front}\n# Context brief: {brief.ticket}\n".encode()
    else:
        fields = split_frontmatter(existing.decode("utf-8", "replace")).fields
        if fields.get("type") != BRIEF_TYPE or str(fields.get("ticket", "")).upper() != (
            brief.ticket.upper()
        ):
            raise TicketRecordError(f"brief.md is not a ticket brief of {brief.ticket}")
        start = existing if existing.endswith(b"\n") else existing + b"\n"
    version = len(_BRIEF_HEADING.findall(start.decode("utf-8", "replace"))) + 1
    return start + _brief_section(brief, version).encode(), version


def _brief_section(brief: TicketBrief, version: int) -> str:
    fields = {
        "plan_version": brief.plan_version,
        "blockers": [
            {"id": b.id, "outcome_path": b.outcome_path, "recorded_at": b.recorded_at}
            for b in brief.blockers
        ],
        "adrs": list(brief.adrs),
    }
    acs = [f"- **{ac.id}** {one_line(ac.description)}" for ac in brief.acs]
    quoted = [f"> {line}".rstrip() for line in brief.plan_section.splitlines()]
    blockers = [
        f"- {b.id}: `{b.outcome_path}`, recorded {b.recorded_at or 'at an unknown time'}"
        if b.outcome_path
        else f"- {b.id}: none recorded"
        for b in brief.blockers
    ]
    commits = list(brief.commits) or [f"None read: {brief.commits_note or 'none found'}."]
    parts = [
        f"## Brief v{version} ({brief.at.isoformat()})",
        f"```json\n{json.dumps(fields, ensure_ascii=False)}\n```",
        "### Acceptance criteria\n\n" + ("\n".join(acs) or "None listed in features.json."),
        "### Plan section\n\n"
        + ("\n".join(quoted) or f"No heading of plan.md names {brief.ticket}."),
        "### Blockers\n\n" + ("\n".join(blockers) or "None."),
        "### Main commits since the plan\n\n" + "\n".join(f"- {line}" for line in commits),
        "### ADRs cited\n\n" + ("\n".join(f"- {adr}" for adr in brief.adrs) or "None."),
    ]
    return "\n" + "\n\n".join(parts) + "\n"


def plan_section(plan: str, names: Iterable[str]) -> str:
    """Every section of ``plan`` whose heading names one of ``names`` (a whole word, any case),
    each up to the next heading of its level or higher; empty when none does."""
    wanted = [re.compile(rf"(?<![\w-]){re.escape(name)}(?![\w-])", re.IGNORECASE) for name in names]
    taken: list[str] = []
    level: int | None = None
    for line in plan.splitlines():
        heading = _HEADING.fullmatch(line)
        if heading is not None:
            depth = len(heading.group(1))
            if level is not None and depth <= level:
                level = None
            if level is None and any(name.search(heading.group(2)) for name in wanted):
                level = depth
        if level is not None:
            taken.append(line)
    return "\n".join(taken) + "\n" if taken else ""


def named_paths(text: str) -> tuple[str, ...]:
    """The file paths ``text`` names in code spans (a ``:<line>`` suffix dropped), in order."""
    found: dict[str, None] = {}
    for span in _CODE_SPAN.findall(text):
        path = _LINE_SUFFIX.sub("", span)
        if _PATH.fullmatch(path) and ".." not in path.split("/"):
            found[path] = None
    return tuple(found)[:MAX_NAMED_PATHS]


def cited_adrs(text: str) -> tuple[str, ...]:
    """The ADRs ``text`` cites (``ADR 0040``, ``ADR-0040``, ``docs/adr/0040-…``), sorted."""
    return tuple(sorted({f"ADR {a or b}" for a, b in _ADR.findall(text)}))


def appended_preflight(existing: bytes | None, run: bytes, *, folder: str) -> tuple[bytes, int]:
    """``preflight.json`` of ``tickets/<folder>/`` with ``run`` appended, and its run count.

    Refused when ``run`` is no ``PreflightRun``, when the record there is malformed or names
    another ticket, and when the result would be over ``MAX_PREFLIGHT_BYTES``.
    """
    entry = parse_document(run)
    if isinstance(entry, OutputProblem):
        raise TicketRecordError(f"the run is unusable: {entry.message}")
    _valid(PreflightRun, entry, "the run")
    runs: list[object] = []
    ticket: object = folder
    if existing is not None:
        record = preflight_record(existing, folder=folder)
        if isinstance(record, str):
            raise TicketRecordError(record)
        # Parsed as JSON, not dumped from the model: each earlier run is copied as it was.
        parsed = cast("dict[str, list[object]]", parse_document(existing))
        runs, ticket = parsed["runs"], parsed["ticket"]
    document = {"schema": PREFLIGHT_SCHEMA, "ticket": ticket, "runs": [*runs, entry]}
    _valid(PreflightRecord, document, "the record")
    written = (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    if len(written) > MAX_PREFLIGHT_BYTES:
        why = f"preflight.json would be larger than {MAX_PREFLIGHT_BYTES} bytes, its read cap"
        raise TicketRecordError(why)
    return written, len(runs) + 1


def _valid(model: type[PreflightRun] | type[PreflightRecord], value: object, what: str) -> None:
    try:
        model.model_validate(value)
    except ValidationError as error:
        first = shape_problems(error)[0]
        raise TicketRecordError(f"{what} is refused: {first.path}: {first.message}") from None


def next_request(names: Iterable[str]) -> int:
    """The number after the highest request or decision among the folder's ``names``."""
    numbers = [int(found[1]) for name in names if (found := _REQUEST_NAME.fullmatch(name))]
    return max(numbers, default=0) + 1


def change_request_text(
    *,
    n: int,
    ticket: str,
    plan_from: int,
    affected: Sequence[str],
    opened_at: datetime,
    run_id: str,
    evidence: str,
    proposal: str,
) -> bytes:
    """``change-requests/<n>.md``, opened against plan ``v<plan_from>`` for the next version."""
    if _TICKET.fullmatch(ticket) is None:
        raise TicketRecordError(f"the ticket is not a key or id: {one_line(ticket)[:64]}")
    if bad := [name for name in affected if _TICKET.fullmatch(name) is None]:
        raise TicketRecordError(f"affected has an invalid ticket: {one_line(bad[0])[:64]}")
    if _RUN_ID.fullmatch(run_id) is None:
        raise TicketRecordError(f"not a run id: {one_line(run_id)[:64]}")
    for name, value in (("evidence", evidence), ("proposal", proposal)):
        if not value.strip():
            raise TicketRecordError(f"the {name} is empty")
    text = (
        f"---\ntype: change-request\nticket: {ticket}\nstatus: open\n"
        f"plan_from: {plan_from}\nplan_to: {plan_from + 1}\naffected: [{', '.join(affected)}]\n"
        f"opened_at: {opened_at.isoformat()}\nrun_id: {run_id}\n---\n\n"
        f"# Change request {n}: plan v{plan_from} to v{plan_from + 1}, from {ticket}\n\n"
        f"## Evidence\n\n{evidence.strip()}\n\n## Proposal\n\n{proposal.strip()}\n"
    ).encode()
    _read_back(n, text)
    return text


def decision_text(
    *,
    n: int,
    request: bytes,
    decision: str,
    decided_by: str,
    decided_at: datetime,
    note: str | None,
) -> bytes:
    """``change-requests/<n>.decision.md`` for ``request`` (the bytes of ``<n>.md``)."""
    if decided_by.strip().lower() in NO_PERSON:
        raise TicketRecordError(f"the decision names no person (decided_by {decided_by!r})")
    note = (note or "").strip()
    if decision == "declined" and not note:
        raise TicketRecordError("a declined change needs a note")
    line = scalar(note[:NOTE_LINE_CHARS])
    text = (
        f"---\ntype: change-request-decision\ndecision: {decision}\n"
        f"decided_by: {scalar(decided_by.strip())}\ndecided_at: {decided_at.isoformat()}\n"
        f"note: {line}\n---\n\n# Change request {n}: {decision}\n" + (f"\n{note}\n" if note else "")
    ).encode()
    _read_back(n, request, text)
    return text


def amended_plan(
    plan: bytes, *, n: int, request: bytes, decision: bytes, summary: str
) -> tuple[bytes, str]:
    """``plan.md`` with the amendment of approved request ``n`` appended, and its id."""
    status = _read_back(n, request, decision)
    if status != "approved":
        raise TicketRecordError(f"change request {n} is {status}, not approved")
    plan_from = int(_field(request, "plan_from"))
    view = plan_version(plan)
    if view.version != plan_from:
        why = (
            f"plan.md is v{view.version}; change request {n} asks v{plan_from} to "
            f"v{plan_from + 1}: re-run preflight"
        )
        raise TicketRecordError(why)
    if not summary.strip():
        raise TicketRecordError("the amendment's summary is empty")
    numbers = [int(found[1]) for a in view.amendments if (found := _AMENDMENT_ID.fullmatch(a.id))]
    ident = f"A{max(numbers, default=0) + 1}"
    who, date = _field(decision, "decided_by"), _field(decision, "decided_at")[:10]
    entry = (
        f"- {ident} ({date}, {who}): {one_line(' '.join(summary.split()))} "
        f"([change request {n}](change-requests/{n}.md))\n"
    )
    start = plan if plan.endswith(b"\n") or not plan else plan + b"\n"
    section = last_section(plan)
    if section is None or not opens_amendments(section):
        start += b"\n## Amendments\n\n"
    written = start + entry.encode()
    if plan_version(written).version != plan_from + 1:
        raise TicketRecordError(f"the entry would not read as {ident}: {one_line(entry.strip())}")
    return written, ident


def _read_back(n: int, request: bytes, decision: bytes | None = None) -> str | None:
    """The status ``ticket_records`` reads for request ``n``; refused on any problem."""
    files = [RecordHead(name=f"{n}.md", head=request[:CHANGE_REQUEST_HEAD_BYTES], problem=None)]
    if decision is not None:
        head = decision[:CHANGE_REQUEST_HEAD_BYTES]
        files.append(RecordHead(name=f"{n}.decision.md", head=head, problem=None))
    [read] = change_requests(files, skipped=0).requests
    if read.problem is not None:
        raise TicketRecordError(read.problem)
    return read.status


def _field(record: bytes, name: str) -> str:
    try:
        value = text_field(record_fields(record[:CHANGE_REQUEST_HEAD_BYTES]), name)
    except RecordFieldError as error:
        raise TicketRecordError(str(error)) from None
    if value is None:
        raise TicketRecordError(f"{name} is missing")
    return value
