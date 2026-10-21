"""The ticket records an ``implement`` run writes into the hub (two-level-flows S2, P7).

``hub step ticket-brief|preflight|change-request|decide|amend-plan`` call these with the hub's
main checkout. They write under ``brain/features/<slug>/`` only and never commit: the run's
report names the changed files for the owner's hub PR (D-1). The texts and their checks are
``agent_hub.core.features.ticket_writes``'; here are the reads and writes. No link is followed:
the feature folder, ``tickets/``, ``change-requests/`` and every file read or replaced must not
be one. A file that is appended to (``brief.md``, ``preflight.json``, ``plan.md``) is replaced
whole through a temp file and a rename; a change request and its decision are created
exclusively, never over another file, so a request is decided once. ``plan.md`` is amended under
a per-feature lock (``.agent-runs/locks/<slug>.plan.lock``, never committed), so two runs never
interleave their entries. ``ticket-brief`` also reads git, without changing anything: the hub's
last commit of ``plan.md``, and the log of the ticket's repo checkout on ``origin/<default
branch>`` as last fetched.
"""

import contextlib
import fcntl
import os
import re
import secrets
from collections.abc import Iterator, Sequence
from datetime import datetime
from pathlib import Path
from typing import Final

from agent_hub.cli.errors import PrStepError
from agent_hub.cli.exclusive_write import TEMP_INFIX, sync_folder, write_exclusive
from agent_hub.cli.pr_steps import git_output
from agent_hub.cli.ship_steps import ship_child, step_timeouts
from agent_hub.core.features.feature_evals import RecordFieldError, record_fields, text_field
from agent_hub.core.features.feature_record import (
    KEY_PATTERN,
    MAX_RECORD_BYTES,
    RECORD_FILE,
    PlannedTicket,
    record_from_bytes,
)
from agent_hub.core.features.feature_status import MAX_PLAN_BYTES
from agent_hub.core.features.plan_version import plan_version
from agent_hub.core.features.ticket_records import (
    CHANGE_REQUESTS_FOLDER,
    MAX_PREFLIGHT_BYTES,
    PREFLIGHT_FILE,
    TICKET_BRIEF,
    TICKETS_FOLDER,
)
from agent_hub.core.features.ticket_writes import (
    Blocker,
    TicketBrief,
    TicketRecordError,
    amended_plan,
    appended_brief,
    appended_preflight,
    change_request_text,
    cited_adrs,
    decision_text,
    named_paths,
    next_request,
    plan_section,
)
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import one_line
from agent_hub.core.json_form import JsonValue

FEATURES: Final = ("brain", "features")
PLAN: Final = "plan.md"
OUTCOME: Final = "outcome.md"
LOCKS: Final = (".agent-runs", "locks")
MAX_BRIEF_BYTES: Final = 1_048_576
MAX_REQUEST_BYTES: Final = 262_144
MAX_COMMITS: Final = 50
# A new number is tried this many times when another run took the one picked.
MAX_REQUEST_TRIES: Final = 100
_SLUG: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_TICKET: Final = re.compile(KEY_PATTERN)
_TEMP_FLAGS: Final = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC


def ticket_brief(
    hub: Path, config: HubConfig, *, feature: str, ticket: str, now: datetime
) -> dict[str, JsonValue]:
    """Append the next version of ``tickets/<ticket>/brief.md``."""
    folder = _feature(hub, feature)
    record = record_from_bytes(_required(folder / RECORD_FILE, MAX_RECORD_BYTES))
    if isinstance(record, str):
        raise TicketRecordError(record)
    planned = _planned(record.tickets, ticket)
    if planned is None:
        raise TicketRecordError(f"{one_line(ticket)} is not a ticket of {RECORD_FILE}")
    plan = _required(folder / PLAN, MAX_PLAN_BYTES)
    names = _names(planned)
    section = plan_section(plan.decode("utf-8", "replace"), names)
    commits, note = _commits(
        hub, config, planned=planned, folder=folder, paths=named_paths(section)
    )
    brief = TicketBrief(
        ticket=ticket,
        at=now,
        plan_version=_version(plan),
        acs=tuple(
            ac
            for ac in record.acs
            if not ac.withdrawn and (ac.ticket or "").upper() in {n.upper() for n in names}
        ),
        plan_section=section,
        blockers=tuple(
            _blocker(folder, _planned(record.tickets, key), key) for key in planned.blocked_by
        ),
        adrs=cited_adrs(section),
        commits=commits,
        commits_note=note,
    )
    target = _ticket_folder(folder, ticket)
    written, version = appended_brief(_read(target / TICKET_BRIEF, MAX_BRIEF_BYTES), brief)
    _replace(target, TICKET_BRIEF, written)
    return {"path": _relative(hub, target / TICKET_BRIEF), "version": version}


def preflight(hub: Path, *, feature: str, ticket: str, run: bytes) -> dict[str, JsonValue]:
    """Append ``run`` to ``tickets/<ticket>/preflight.json``."""
    target = _ticket_folder(_feature(hub, feature), ticket)
    existing = _read(target / PREFLIGHT_FILE, MAX_PREFLIGHT_BYTES)
    written, count = appended_preflight(existing, run, folder=ticket)
    _replace(target, PREFLIGHT_FILE, written)
    return {"path": _relative(hub, target / PREFLIGHT_FILE), "runs": count}


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
) -> dict[str, JsonValue]:
    """Create ``change-requests/<n>.md`` (``n`` the next free number) against the plan's
    current version."""
    folder = _feature(hub, feature)
    plan_from = _version(_required(folder / PLAN, MAX_PLAN_BYTES))
    requests = _folder(folder, CHANGE_REQUESTS_FOLDER)
    first = next_request(os.listdir(requests))
    for n in range(first, first + MAX_REQUEST_TRIES):
        text = change_request_text(
            n=n,
            ticket=ticket,
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
    with _plan_lock(hub, feature):
        written, ident = amended_plan(
            _required(folder / PLAN, MAX_PLAN_BYTES),
            n=request,
            request=_required(requests / f"{request}.md", MAX_REQUEST_BYTES),
            decision=_required(requests / f"{request}.decision.md", MAX_REQUEST_BYTES),
            summary=summary,
        )
        _replace(folder, PLAN, written)
    return {"path": _relative(hub, folder / PLAN), "amendment": ident}


def _version(plan: bytes) -> int:
    # ``plan_version`` always counts a plan it is given; its None is for a plan left unread.
    return plan_version(plan).version or 1


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


def _ticket_folder(feature: Path, ticket: str) -> Path:
    if _TICKET.fullmatch(ticket) is None:
        raise TicketRecordError(f"not a ticket key or id: {one_line(ticket)[:64]}")
    return _folder(_folder(feature, TICKETS_FOLDER), ticket)


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
def _plan_lock(hub: Path, slug: str) -> Iterator[None]:
    """Hold the feature's plan lock (an exclusive ``flock``); refused while a run holds it."""
    folder = hub.joinpath(*LOCKS)
    folder.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open(folder / f"{slug}.plan.lock", flags, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            reason = f"{PLAN} of {slug} is being amended by another run; run again"
            raise TicketRecordError(reason) from None
        yield
    finally:
        os.close(descriptor)


def _relative(hub: Path, path: Path) -> str:
    return path.relative_to(hub).as_posix()
