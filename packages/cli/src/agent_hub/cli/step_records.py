"""The ticket records an ``implement`` run writes into the hub (two-level-flows S2, P7), and a
merged ticket's outcome (S3).

``hub step ticket-brief|preflight|change-request|decide|amend-plan|outcome`` call these with the
hub's main checkout (``pending-decision`` and ``preflight-due`` too, which only read). They
write under ``brain/features/<slug>/`` only and never commit: the run's report names the changed
files for the owner's hub PR (D-1). The texts and their checks are
``agent_hub.core.features.ticket_writes``'; here are the reads and writes. No link is followed:
the feature folder, ``tickets/``, ``change-requests/`` and every file read or replaced must not
be one. A file that is appended to (``brief.md``, ``preflight.json``, ``plan.md``) is replaced
whole through a temp file and a rename; a change request and its decision are created
exclusively, never over another file, so a request is decided once; so is an outcome, written
once (a second ``outcome`` writes nothing). ``brief.md``,
``preflight.json`` and ``plan.md`` are read and replaced under a per-feature lock
(``.agent-runs/locks/<slug>.lock``, never committed), so two runs never drop or interleave
entries. A ticket must be planned in ``features.json``; its records go to one folder whatever
name it is given: the existing ``tickets/`` folder named (any case) by its key or id, else its id
(its key before it has one). ``ticket-brief`` also reads git, without changing anything: the hub's
last commit of ``plan.md``, and the log of the ticket's repo checkout on ``origin/<default
branch>`` as last fetched.
"""

import contextlib
import fcntl
import os
import re
import secrets
from collections.abc import Iterator, Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Final

from agent_hub.cli.errors import PrStepError
from agent_hub.cli.exclusive_write import TEMP_INFIX, sync_folder, write_exclusive
from agent_hub.cli.pr_steps import git_output
from agent_hub.cli.ship_steps import ship_child, step_timeouts
from agent_hub.core.features.feature_evals import RecordFieldError, record_fields, text_field
from agent_hub.core.features.feature_record import (
    MAX_RECORD_BYTES,
    RECORD_FILE,
    FeatureRecordFile,
    PlannedTicket,
    record_from_bytes,
)
from agent_hub.core.features.feature_reviews import names_pull_request
from agent_hub.core.features.feature_status import MAX_PLAN_BYTES
from agent_hub.core.features.output_models import PreflightRecord
from agent_hub.core.features.plan_version import plan_version
from agent_hub.core.features.ticket_records import (
    CHANGE_REQUESTS_FOLDER,
    MAX_OUTCOME_BYTES,
    MAX_PREFLIGHT_BYTES,
    OUTCOME_FILE,
    PREFLIGHT_FILE,
    TICKET_BRIEF,
    TICKETS_FOLDER,
    TicketOutcome,
    already_read,
    aware_time,
    outcome_record,
    preflight_record,
    ticket_folder,
)
from agent_hub.core.features.ticket_writes import (
    MAX_REQUEST_BYTES,
    NO_PENDING,
    Blocker,
    PlanMovedError,
    PreflightFacts,
    TicketBrief,
    TicketOutcomeText,
    TicketRecordError,
    amended_plan,
    appended_brief,
    appended_preflight,
    change_request_text,
    cited_adrs,
    decision_text,
    named_paths,
    next_request,
    outcome_text,
    pending_decision,
    pending_request,
    plan_ids,
    plan_section,
    preflight_run,
    ticket_acs,
    with_blocker_read,
)
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import one_line
from agent_hub.core.json_form import JsonValue

FEATURES: Final = ("brain", "features")
PLAN: Final = "plan.md"
OUTCOME: Final = OUTCOME_FILE
LOCKS: Final = (".agent-runs", "locks")
MAX_BRIEF_BYTES: Final = 1_048_576
MAX_COMMITS: Final = 50
# A new number is tried this many times when another run took the one picked.
MAX_REQUEST_TRIES: Final = 100
_SLUG: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_TEMP_FLAGS: Final = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC


def ticket_brief(
    hub: Path, config: HubConfig, *, feature: str, ticket: str, now: datetime
) -> dict[str, JsonValue]:
    """Append the next version of ``tickets/<ticket>/brief.md``."""
    folder = _feature(hub, feature)
    record = _record(folder)
    planned = _planned_or_refuse(record.tickets, ticket)
    # Main as last fetched, read once: the preflight reads this commit and its run records it.
    main = _main_commit(hub, config, planned)
    plan = _required(folder / PLAN, MAX_PLAN_BYTES)
    names = (*plan_ids(planned.key), *_names(planned)[1:])
    section = plan_section(plan.decode("utf-8", "replace"), names)
    commits, note = _commits(
        hub, config, planned=planned, folder=folder, paths=named_paths(section)
    )
    target = _ticket_folder(folder, planned)
    brief = TicketBrief(
        ticket=target.name,
        at=now,
        plan_version=_version(plan),
        acs=ticket_acs(record.acs, names, section),
        plan_section=section,
        blockers=tuple(
            _blocker(folder, _planned(record.tickets, key), key) for key in planned.blocked_by
        ),
        adrs=cited_adrs(section),
        commits=commits,
        commits_note=note,
    )
    with _feature_lock(hub, feature):
        written, version = appended_brief(_read(target / TICKET_BRIEF, MAX_BRIEF_BYTES), brief)
        _replace(target, TICKET_BRIEF, written)
    # The hub, the ticket's repo (the plan's, not a caller's) and main's commit the preflight reads.
    return {
        "path": _relative(hub, target / TICKET_BRIEF),
        "version": version,
        "hub": str(hub),
        "repo": planned.repo,
        "commit": main,
    }


def preflight(
    hub: Path,
    *,
    feature: str,
    ticket: str,
    findings: bytes,
    facts: PreflightFacts,
    read: str = "",
) -> dict[str, JsonValue]:
    """Append the run built from the agent's ``findings`` to ``tickets/<ticket>/preflight.json``;
    ``facts`` gives the time, the run's id, main's commit the preflight read (``ticket-brief``'s)
    and the input, and this fills the plan's version."""
    folder = _feature(hub, feature)
    tickets = _record(folder).tickets
    planned = _planned_or_refuse(tickets, ticket)
    target = _ticket_folder(folder, planned)
    plan = _required(folder / PLAN, MAX_PLAN_BYTES)
    facts = replace(facts, plan_version=_version(plan))
    if read:
        # The blocker an automatic preflight was started for is read, whatever the agent listed.
        blocking = _planned(tickets, read)
        names = _names(blocking) if blocking is not None else (read,)
        if not {name.upper() for name in names} & {name.upper() for name in planned.blocked_by}:
            shown = planned.id or planned.key
            raise TicketRecordError(
                f"{shown} is not blocked by {one_line(read)[:64]} in {RECORD_FILE}"
            )
        findings = with_blocker_read(findings, read, names=names)
    if facts.input == "approve" and facts.request is not None:
        # An approval the plan moved past is re-checked as a plain check that says so (A23).
        moved = _superseded(folder, facts.request, plan)
        if moved:
            # It opened no request: the superseded one is not named (A24).
            facts = replace(facts, input="none", input_text=moved, request=None)
    with _feature_lock(hub, feature):
        existing = _read(target / PREFLIGHT_FILE, MAX_PREFLIGHT_BYTES)
        run = preflight_run(findings, facts)
        written, count = appended_preflight(existing, run, folder=target.name)
        _replace(target, PREFLIGHT_FILE, written)
    return {"path": _relative(hub, target / PREFLIGHT_FILE), "runs": count}


def _superseded(folder: Path, n: int, plan: bytes) -> str:
    """What the run says of approved request ``n`` when the plan moved past it, else ``""``."""
    requests = folder / CHANGE_REQUESTS_FOLDER
    request = _read(requests / f"{n}.md", MAX_REQUEST_BYTES)
    decision = _read(requests / f"{n}.decision.md", MAX_REQUEST_BYTES)
    if request is None or decision is None:
        return ""
    return pending_decision(n, request=request, decision=decision, plan=plan).superseded


def _main_commit(hub: Path, config: HubConfig, planned: PlannedTicket) -> str:
    """``origin/<default branch>``'s commit in the ticket's repo checkout: main as last fetched,
    read without a checkout."""
    entry = next((repo for repo in config.repos if repo.dir == planned.repo), None)
    if entry is None:
        raise TicketRecordError(
            f"the ticket's repo {one_line(planned.repo or 'none')} is not in hub.json"
        )
    base = f"origin/{config.default_branch_for(entry.dir)}"
    try:
        found = git_output(
            ship_child(hub.parent / entry.dir),
            *("rev-parse", "--verify", "--quiet", f"{base}^{{commit}}"),
            environ=os.environ,
            timeout=step_timeouts().git,
        ).strip()
    except PrStepError as error:
        raise TicketRecordError(
            f"{base} could not be read: {one_line(error.reason.strip())}"
        ) from None
    return found


def change_request(
    hub: Path,
    *,
    feature: str,
    ticket: str,
    affected: Sequence[str],
    run_id: str,
    evidence: str,
    proposal: str,
    now: datetime,
    findings: bytes = b"",
    facts: PreflightFacts | None = None,
) -> dict[str, JsonValue]:
    """Create ``change-requests/<n>.md`` (``n`` the next free number) against the plan's
    current version. With the preflight's ``findings`` and the run's ``facts``, the run
    that will name the request is checked first: a run the writer would refuse opens no request
    that no preflight run names."""
    folder = _feature(hub, feature)
    planned = _planned_or_refuse(_record(folder).tickets, ticket)
    plan_from = _version(_required(folder / PLAN, MAX_PLAN_BYTES))
    requests = _folder(folder, CHANGE_REQUESTS_FOLDER)
    first = next_request(os.listdir(requests))
    if facts is not None:
        facts = replace(facts, plan_version=plan_from, request=first)
        run = preflight_run(findings, facts)
        appended_preflight(None, run, folder=planned.id or planned.key)
    for n in range(first, first + MAX_REQUEST_TRIES):
        text = change_request_text(
            n=n,
            ticket=planned.id or planned.key,
            plan_from=plan_from,
            affected=affected,
            opened_at=now,
            run_id=run_id,
            evidence=evidence,
            proposal=proposal,
        )
        if write_exclusive(requests, f"{n}.md", text):
            return {
                "path": _relative(hub, requests / f"{n}.md"),
                "n": n,
                "plan_from": plan_from,
                "plan_to": plan_from + 1,
            }
    raise TicketRecordError(f"no free change request number after {MAX_REQUEST_TRIES} tries")


def decide(
    hub: Path,
    *,
    feature: str,
    request: int,
    decision: str,
    decided_by: str,
    note: str,
    now: datetime,
) -> dict[str, JsonValue]:
    """Create ``change-requests/<n>.decision.md``; refused when the request is decided."""
    requests = _folder(_feature(hub, feature), CHANGE_REQUESTS_FOLDER, create=False)
    text = decision_text(
        n=request,
        request=_required(requests / f"{request}.md", MAX_REQUEST_BYTES),
        decision=decision,
        decided_by=decided_by,
        decided_at=now,
        note=note,
    )
    name = f"{request}.decision.md"
    if not write_exclusive(requests, name, text):
        raise TicketRecordError(f"change request {request} is already decided")
    return {"path": _relative(hub, requests / name), "decision": decision}


def amend_plan(hub: Path, *, feature: str, request: int, summary: str) -> dict[str, JsonValue]:
    """Append the amendment of approved request ``request`` to ``plan.md``."""
    folder = _feature(hub, feature)
    requests = _folder(folder, CHANGE_REQUESTS_FOLDER, create=False)
    with _feature_lock(hub, feature):
        plan = _required(folder / PLAN, MAX_PLAN_BYTES)
        try:
            written, ident = amended_plan(
                plan,
                n=request,
                request=_required(requests / f"{request}.md", MAX_REQUEST_BYTES),
                decision=_required(requests / f"{request}.decision.md", MAX_REQUEST_BYTES),
                summary=summary,
            )
        except PlanMovedError as moved:
            # The run checks the ticket against the current plan instead (AGH-404 Q1).
            path = _relative(hub, folder / PLAN)
            return {"path": path, "amendment": None, "already": None, "moved": str(moved)}
        if written == plan:
            already: str | None = f"already amended as {ident}"
        else:
            already = None
            _replace(folder, PLAN, written)
    return {
        "path": _relative(hub, folder / PLAN),
        "amendment": ident,
        "already": already,
        "moved": None,
    }


def pending(hub: Path, *, feature: str, ticket: str) -> dict[str, JsonValue]:
    """The owner's decision on the change request the ticket's last preflight opened, when one
    was recorded with no run waiting for it (AC-2.14); empty values when there is none."""
    folder = _feature(hub, feature)
    planned = _planned_or_refuse(_record(folder).tickets, ticket)
    target = _ticket_folder(folder, planned)
    record = _preflight(target)
    requests = folder / CHANGE_REQUESTS_FOLDER
    found = pending_request(record)
    if found is None and requests.is_dir() and not requests.is_symlink():
        found = _unnamed_request(requests, planned, record)
    decided = NO_PENDING
    if found is not None and requests.is_dir() and not requests.is_symlink():
        request = _read(requests / f"{found}.md", MAX_REQUEST_BYTES)
        decision = _read(requests / f"{found}.decision.md", MAX_REQUEST_BYTES)
        if request is not None and decision is not None:
            plan = _required(folder / PLAN, MAX_PLAN_BYTES)
            decided = pending_decision(found, request=request, decision=decision, plan=plan)
    return {
        "request": decided.request,
        "decision": decided.decision,
        "input": decided.input,
        "note": decided.note,
        "summary": decided.summary,
        "superseded": decided.superseded,
    }


def outcome(
    hub: Path,
    *,
    feature: str,
    ticket: str,
    pr: str,
    merged_at: str,
    built: str,
    changes: str,
    interfaces: str,
) -> dict[str, JsonValue]:
    """Create ``tickets/<ticket>/outcome.md`` once (AC-3.1): a second run, or one for a ticket
    whose outcome an earlier merge recorded, writes nothing (``written`` false)."""
    folder = _feature(hub, feature)
    record = _record(folder)
    planned = _planned_or_refuse(record.tickets, ticket)
    dependents = _dependents(record.tickets, planned)
    existing = _existing_ticket_folder(folder, _names(planned))
    if existing is not None and (existing / OUTCOME).is_symlink():
        raise TicketRecordError(f"{OUTCOME} is a link; no link is followed")
    if existing is not None and (existing / OUTCOME).exists():
        return _kept(hub, existing, dependents)
    if not names_pull_request(pr.strip()):
        # The writer's own input, named as given (the record's reader would say the same).
        raise TicketRecordError(f"--pr: names no pull request: {one_line(pr)[:64]}")
    try:
        when = aware_time(merged_at, "merged_at")
    except RecordFieldError as error:
        raise TicketRecordError(str(error)) from None
    # Checked whole before any folder is made.
    text = outcome_text(
        TicketOutcomeText(
            ticket=(planned.id or planned.key) if existing is None else existing.name,
            merged_at=when,
            pr=pr.strip(),
            dependents=dependents,
            built=built,
            changes=changes,
            interfaces=interfaces,
        )
    )
    target = _ticket_folder(folder, planned)
    if not write_exclusive(target, OUTCOME, text):
        # Another run recorded it first: its outcome stands.
        return _kept(hub, target, dependents)
    done: dict[str, JsonValue] = {"written": True, "merged_at": when.isoformat()}
    return done | {"path": _relative(hub, target / OUTCOME), "dependents": list(dependents)}


def _kept(hub: Path, target: Path, dependents: Sequence[str]) -> dict[str, JsonValue]:
    """What ``outcome`` prints for an outcome already recorded: its ``merged_at`` as recorded
    (``""`` when its reader refuses it), nothing written."""
    read = _outcome_of(target)
    merged_at = read.merged_at.isoformat() if isinstance(read, TicketOutcome) else ""
    kept: dict[str, JsonValue] = {"written": False, "merged_at": merged_at}
    return kept | {"path": _relative(hub, target / OUTCOME), "dependents": list(dependents)}


def preflight_due(hub: Path, *, feature: str, ticket: str, blocker: str) -> dict[str, JsonValue]:
    """Whether dependent ``ticket`` still has to read ``blocker``'s outcome (AC-3.2, AC-3.3): not
    when it is merged itself, nor when a preflight run since the merge lists the blocker in
    ``blockers_read``. Writes nothing; ``input`` is the automatic preflight's (always ``none``)."""
    folder = _feature(hub, feature)
    record = _record(folder)
    planned = _planned_or_refuse(record.tickets, ticket)
    blocking = _planned(record.tickets, blocker)
    names = _names(blocking) if blocking is not None else (blocker,)
    wanted = {name.upper() for name in names}
    shown = planned.id or planned.key
    if not any(name.upper() in wanted for name in planned.blocked_by):
        reason = f"{shown} is not blocked by {one_line(blocker)[:64]} in {RECORD_FILE}"
        raise TicketRecordError(reason)
    blocking_folder = _existing_ticket_folder(folder, names)
    found = None if blocking_folder is None else _outcome_of(blocking_folder)
    if found is None:
        raise TicketRecordError(f"{one_line(blocker)[:64]} has no {OUTCOME}")
    if isinstance(found, str):
        raise TicketRecordError(found)
    due: dict[str, JsonValue] = {"due": True, "reason": "", "input": "none"}
    target = _existing_ticket_folder(folder, _names(planned))
    if target is not None and isinstance(_outcome_of(target), TicketOutcome):
        return due | {"due": False, "reason": f"{shown} is merged"}
    run = already_read(
        None if target is None else _preflight(target), names=names, merged_at=found.merged_at
    )
    if run is not None:
        at = run.ran_at.isoformat()
        reason = f"{shown} already read {one_line(blocker)[:64]}'s outcome (preflight run at {at})"
        return due | {"due": False, "reason": reason}
    return due


def _dependents(tickets: Sequence[PlannedTicket], planned: PlannedTicket) -> tuple[str, ...]:
    """The tickets whose ``blocked_by`` names ``planned``, by id once they have one."""
    names = {name.upper() for name in _names(planned)}
    return tuple(
        other.id or other.key
        for other in tickets
        if other is not planned and names & {name.upper() for name in other.blocked_by}
    )


def _outcome_of(target: Path) -> TicketOutcome | str | None:
    """The outcome recorded in the ticket folder ``target``, its reader's problem, or None."""
    return outcome_record(_read(target / OUTCOME, MAX_OUTCOME_BYTES), folder=target.name)


def _existing_ticket_folder(feature: Path, names: Sequence[str]) -> Path | None:
    """The folder of the ticket named ``names`` as ``_ticket_folder`` finds it, None when there
    is none (nothing is created); refused through a link."""
    tickets = feature / TICKETS_FOLDER
    if tickets.is_symlink():
        raise TicketRecordError(f"{TICKETS_FOLDER} is a link; no link is followed")
    if not tickets.is_dir():
        return None
    found = ticket_folder(os.listdir(tickets), names)
    if found is None:
        return None
    if (tickets / found).is_symlink():
        raise TicketRecordError(f"{found} is a link; no link is followed")
    return tickets / found


def _unnamed_request(
    requests: Path, planned: PlannedTicket, record: PreflightRecord | None
) -> int | None:
    """The ticket's newest decided request that no preflight run names, opened since its last
    run: the run that opened it failed before its preflight run was recorded."""
    runs = record.runs if record is not None else ()
    since = runs[-1].ran_at if runs else None
    named = {run.change_request for run in runs}
    names = {name.upper() for name in _names(planned)}
    found: list[int] = []
    for name in os.listdir(requests):
        if not name.endswith(".decision.md") or (n := name.split(".", 1)[0]).isdecimal() is False:
            continue
        head = _read(requests / f"{n}.md", MAX_REQUEST_BYTES)
        try:
            fields = record_fields(head or b"")
            ticket = text_field(fields, "ticket") or ""
            opened = datetime.fromisoformat(text_field(fields, "opened_at") or "")
        except RecordFieldError, ValueError:
            continue
        newer = since is None or opened > since
        if ticket.upper() in names and int(n) not in named and newer:
            found.append(int(n))
    return max(found, default=None)


def _preflight(target: Path) -> PreflightRecord | None:
    record = preflight_record(
        _read(target / PREFLIGHT_FILE, MAX_PREFLIGHT_BYTES), folder=target.name
    )
    if isinstance(record, str):
        raise TicketRecordError(record)
    return record


def _version(plan: bytes) -> int:
    # ``plan_version`` always counts a plan it is given; its None is for a plan left unread.
    return plan_version(plan).version or 1


def _record(folder: Path) -> FeatureRecordFile:
    record = record_from_bytes(_required(folder / RECORD_FILE, MAX_RECORD_BYTES))
    if isinstance(record, str):
        raise TicketRecordError(record)
    return record


def _planned_or_refuse(tickets: Sequence[PlannedTicket], name: str) -> PlannedTicket:
    planned = _planned(tickets, name)
    if planned is None:
        raise TicketRecordError(f"{one_line(name)} is not a ticket of {RECORD_FILE}")
    return planned


def _planned(tickets: Sequence[PlannedTicket], name: str) -> PlannedTicket | None:
    wanted = name.upper()
    return next((t for t in tickets if wanted in {n.upper() for n in _names(t)}), None)


def _names(ticket: PlannedTicket) -> tuple[str, ...]:
    return (ticket.key,) if ticket.id is None else (ticket.key, ticket.id)


def _blocker(folder: Path, planned: PlannedTicket | None, key: str) -> Blocker:
    """The blocker ``key`` and its ``tickets/<key or id>/outcome.md``, when one is recorded."""
    names = {n.upper() for n in _names(planned)} if planned is not None else {key.upper()}
    shown = key if planned is None else planned.id or planned.key
    tickets = folder / TICKETS_FOLDER
    if tickets.is_symlink() or not tickets.is_dir():
        return Blocker(id=shown, outcome_path=None, recorded_at=None)
    for entry in sorted(os.listdir(tickets)):
        outcome = tickets / entry / OUTCOME
        if entry.upper() not in names or (tickets / entry).is_symlink():
            continue
        content = _read(outcome, MAX_REQUEST_BYTES)
        if content is None:
            continue
        try:
            merged = text_field(record_fields(content), "merged_at")
        except RecordFieldError:
            merged = None
        path = f"{TICKETS_FOLDER}/{entry}/{OUTCOME}"
        return Blocker(id=shown, outcome_path=path, recorded_at=merged)
    return Blocker(id=shown, outcome_path=None, recorded_at=None)


def _commits(
    hub: Path, config: HubConfig, *, planned: PlannedTicket, folder: Path, paths: Sequence[str]
) -> tuple[tuple[str, ...], str | None]:
    """Main's commits since the plan's last hub commit on ``paths``; else why none were read."""
    if not paths:
        return (), "the plan section names no file"
    entry = next((repo for repo in config.repos if repo.dir == planned.repo), None)
    if entry is None:
        return (), f"the ticket's repo {one_line(planned.repo or 'none')} is not in hub.json"
    timeout = step_timeouts().git
    try:
        since = git_output(
            ship_child(hub),
            *("log", "-1", "--format=%cI", "--", _relative(hub, folder / PLAN)),
            environ=os.environ,
            timeout=timeout,
        ).strip()
        if not since:
            return (), f"{PLAN} has no commit in the hub"
        log = git_output(
            ship_child(hub.parent / entry.dir),
            *("log", f"-n{MAX_COMMITS}", "--abbrev=12", "--format=%h %cs %s"),
            f"--since={since}",
            f"origin/{config.default_branch_for(entry.dir)}",
            "--",
            *(f":(glob)**/{path.rstrip('/')}" for path in paths),
            environ=os.environ,
            timeout=timeout,
        )
    except PrStepError as error:
        return (), one_line(error.reason.strip())
    lines = [line.split(" ", 1) for line in log.splitlines() if line]
    commits = tuple(f"`{parts[0]}` {one_line(parts[-1])}" for parts in lines)
    return commits, None if commits else f"no commit on those files since {since}"


def _feature(hub: Path, slug: str) -> Path:
    if _SLUG.fullmatch(slug) is None:
        raise TicketRecordError(f"not a feature folder name: {one_line(slug)[:64]}")
    path = hub
    for part in (*FEATURES, slug):
        path /= part
        if path.is_symlink() or not path.is_dir():
            raise TicketRecordError(f"no feature folder brain/features/{slug}")
    return path


def _ticket_folder(feature: Path, planned: PlannedTicket) -> Path:
    """The ticket's one folder: the existing one the ticket flow reads for its key or id
    (``ticket_folder``), else its id (its key before it has one)."""
    tickets = _folder(feature, TICKETS_FOLDER)
    found = ticket_folder(os.listdir(tickets), _names(planned))
    return _folder(tickets, found or planned.id or planned.key)


def _folder(parent: Path, name: str, *, create: bool = True) -> Path:
    path = parent / name
    if path.is_symlink():
        raise TicketRecordError(f"{name} is a link; no link is followed")
    if create:
        path.mkdir(exist_ok=True)
    if not path.is_dir():
        raise TicketRecordError(f"no folder {name}")
    return path


def _read(path: Path, cap: int) -> bytes | None:
    """The bytes of the regular file ``path``, None when absent; refused when it is a link or
    larger than ``cap``."""
    if path.is_symlink():
        raise TicketRecordError(f"{path.name} is a link; no link is followed")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor, "rb") as file:
        content = file.read(cap + 1)
    if len(content) > cap:
        raise TicketRecordError(f"{path.name} is larger than {cap} bytes")
    return content


def _required(path: Path, cap: int) -> bytes:
    content = _read(path, cap)
    if content is None:
        raise TicketRecordError(f"no {path.name} in the feature folder")
    return content


def _replace(folder: Path, name: str, content: bytes) -> None:
    """Replace ``folder/name`` whole: a temp file of this call, synced, then renamed over it."""
    temp = folder / f".{name}{TEMP_INFIX}{secrets.token_hex(4)}"
    descriptor = os.open(temp, _TEMP_FLAGS, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp, folder / name)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temp)
    sync_folder(folder)


@contextlib.contextmanager
def _feature_lock(hub: Path, slug: str) -> Iterator[None]:
    """Hold the feature's lock (an exclusive ``flock``); refused while a run holds it."""
    folder = hub.joinpath(*LOCKS)
    folder.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open(folder / f"{slug}.lock", flags, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            reason = f"the records of {slug} are being written by another run; run again"
            raise TicketRecordError(reason) from None
        yield
    finally:
        os.close(descriptor)


def _relative(hub: Path, path: Path) -> str:
    return path.relative_to(hub).as_posix()
