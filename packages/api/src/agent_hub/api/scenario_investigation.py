"""The investigation session of a paused scenario run (P-7, AM-2, AM-9, AM-13, E-13;
docs/design/scenarios.md § Investigation, answers and workarounds).

``ScenarioInvestigations.open`` serves ``POST /scenario-runs/{run_id}/investigation``. It finds
the run's folder, ``<hub>/.agent-runs/workflows/<run>/``, in a registered hub (never through a
link), reads its ``records.jsonl`` (at most ``MAX_RECORD_BYTES``, a torn last line dropped) and
folds it with core's ``fold_records``: the run must be a scenario run paused at an open,
unanswered investigation, which only its record says (E-10), else 409 ``not_paused``. It then
starts one driven session in the hub, mode ``default``, with the investigation's system prompt,
its tool policy (P-17, E-13: reads only under the real path of the hub and of each declared
repo, ``actions/`` and every declared env file's real path; refused, 409 ``workspace_root``,
when a root is ``/``, the home folder or an ancestor of it) and, like every driven session,
without the hub's declared credentials. Chat goes through ``POST /agent-sessions/{id}/messages``
(AM-9).

One session per investigation: the link file ``investigation-<n>.session`` in the run folder
is created ``O_CREAT|O_EXCL`` (owner-only, never through a link) before the session starts and
gets its id after, all under one lock, so a second call answers the same session. A start that
fails removes the file; a link that cannot be written stops the session it would have named.
A link that is empty (a server stopped mid-start), names a session the store does not know, or
names one that ended and cannot be resumed is taken over by the next call. When
``hub.local.json`` cannot be read, the env files it may declare are unknown, so no session
starts (409 ``hub_local_invalid``). No env file is opened here: the session's own
``hub action run --run`` loads it in the action's process (P-24).

``InvestigationRestrictions.restriction_of`` is the control's port for a reopen (E-13): it finds
the link naming the session in its project's runs and rebuilds the tool policy and the prompt
from that run's record and a fresh read of the hub's config; a session a link names whose
restriction cannot be rebuilt is not reopened (``SessionRestrictionError``).
"""

import asyncio
import contextlib
import errno
import os
import re
from pathlib import Path
from typing import Final

from agent_hub.api.agent_session_runtime import HubCredentials
from agent_hub.core.agent_sessions.agent_session import (
    UUID_PATTERN,
    AgentSession,
    AgentSessionStatus,
    CreateAgentSession,
    EndReason,
)
from agent_hub.core.agent_sessions.control import AgentSessionCommands, SessionRestriction
from agent_hub.core.agent_sessions.errors import (
    HubLocalInvalidError,
    RestrictionUnreadableError,
    SessionRestrictionError,
)
from agent_hub.core.errors import AgentHubError
from agent_hub.core.json_form import JsonValue
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.readmodels.view_types import ViewModel
from agent_hub.core.scenarios.investigation import (
    ToolPolicy,
    WorkspaceRootError,
    investigation_prompt,
)
from agent_hub.core.scenarios.run_record import (
    InvestigationView,
    RecordTooLargeError,
    fold_records,
    record_lines,
)
from agent_hub.core.workflows.launch import RUN_ID_PATTERN, RunConflictError

RUN_FOLDERS: Final = Path(".agent-runs", "workflows")
RECORDS: Final = "records.jsonl"
# The API's bound on a scenario run's record (docs/design/scenarios.md § Events and bounds).
MAX_RECORD_BYTES: Final = 8 << 20
SCENARIO_KIND: Final = "scenario"
LINK_PATTERN: Final = re.compile(r"investigation-([1-9][0-9]{0,5})\.session")
_LINK_BYTES: Final = 128
_OPEN_NEW: Final = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_OPEN_READ: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
_OPEN_WRITE: Final = os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW | os.O_CLOEXEC
_SESSION_ID = re.compile(UUID_PATTERN)
_ENDED: Final = frozenset({AgentSessionStatus.ENDED, AgentSessionStatus.FAILED})
NOT_PAUSED: Final = "the scenario run is not paused at an open investigation"


class InvestigationSession(ViewModel):
    """The session of a scenario run's open investigation: ``started`` when this call
    started it."""

    run_id: str
    project: str
    investigation: int
    step: str
    agent_session_id: str
    started: bool


class InvestigationRestrictions:
    """The tool policy and prompt of an investigation session, built from its run's record and
    the hub's config as read now (``credentials``, which also lists the projects' hubs)."""

    def __init__(self, credentials: HubCredentials) -> None:
        self._credentials = credentials

    def run_folder(self, run_id: str) -> tuple[str, str, Path]:
        """The project, hub and folder of scenario run ``run_id`` (``EntityNotFoundError``)."""
        if RUN_ID_PATTERN.fullmatch(run_id):
            for project, hub in self._credentials.project_hubs():
                folder = Path(hub) / RUN_FOLDERS / run_id
                if folder.is_dir() and not folder.is_symlink():
                    return project, hub, folder
        raise EntityNotFoundError(entity="scenario run", entity_id=run_id)

    def for_run(
        self, *, project: str, hub: str, records: list[dict[str, JsonValue]], step: str
    ) -> SessionRestriction:
        """The restriction of an investigation of the run ``records`` describe, after ``step``;
        ``HubLocalInvalidError`` when the hub's declared env files cannot all be read."""
        declared = self._credentials.of_hub(hub)
        if not declared.complete:
            raise HubLocalInvalidError(project, before="starting a session")
        header = records[0]
        run_id = str(header.get("run"))
        try:
            policy = ToolPolicy.of(
                hub=hub, repos=declared.repos, env_files=declared.env_files, run_id=run_id
            )
        except WorkspaceRootError as error:
            raise RunConflictError(
                code="workspace_root", reason=str(error), run_id=run_id
            ) from None
        return SessionRestriction(
            tool_policy=policy,
            system_prompt=investigation_prompt(
                run_id=run_id,
                scenario=str(header.get("scenario")),
                environment=str(header.get("environment")),
                step=step,
            ),
        )

    def restriction_of(self, session: AgentSession) -> SessionRestriction | None:
        """The restriction ``session`` is held to when a link names it, else None;
        ``SessionRestrictionError`` when a link names it and it cannot be rebuilt."""
        try:
            found = self._linked(session)
        except OSError as error:
            reason = (
                "the hub's scenario runs cannot be read to tell whether this session is held"
                " to a scenario run's tool policy"
            )
            raise RestrictionUnreadableError(session.id, reason, refuses_reopen=True) from error
        if found is None:
            return None
        hub, folder, number = found
        try:
            records = read_records(folder)
            investigation = next(
                item for item in fold_records(records).investigations if item.number == number
            )
            if records[0].get("kind") != SCENARIO_KIND:
                raise SessionRestrictionError(session.id, "the run is not a scenario run")
            return self.for_run(
                project=session.project, hub=hub, records=records, step=investigation.step
            )
        except (AgentHubError, OSError, StopIteration, IndexError) as error:
            reason = "the investigation session's restriction cannot be rebuilt"
            raise SessionRestrictionError(session.id, reason) from error

    def _linked(self, session: AgentSession) -> tuple[str, Path, int] | None:
        """The hub, run folder and investigation number of the link naming ``session``, None once
        its project's runs are scanned (``RestrictionUnreadableError`` when no registered hub
        names the project). Only
        folders holding an ``investigation-<n>.session`` are read; a folder or a link that
        vanishes while read is skipped; any other read error (an unreadable link included) raises
        ``OSError``, so the caller refuses rather than reopen unrestricted."""
        hubs = self._credentials.project_hubs()
        if all(project != session.project for project, _hub in hubs):
            # The registry cannot be read, or names no hub of the project: unknown, not "none".
            reason = "no registered hub names the session's project"
            raise RestrictionUnreadableError(session.id, reason, refuses_reopen=False)
        for project, hub in hubs:
            runs = Path(hub) / RUN_FOLDERS
            if project != session.project or not runs.is_dir() or runs.is_symlink():
                continue
            for folder in _entries(runs):
                if not folder.is_dir() or folder.is_symlink():
                    continue
                number = _link_in(folder, session.id)
                if number is not None:
                    return hub, folder, number
        return None


class ScenarioInvestigations:
    """``POST /scenario-runs/{run_id}/investigation``; see the module docstring. ``control``
    starts (and answers about) the session; ``restrictions`` finds the run and builds its
    session's restriction."""

    def __init__(
        self, *, control: AgentSessionCommands, restrictions: InvestigationRestrictions
    ) -> None:
        self._control = control
        self._restrictions = restrictions
        self._lock = asyncio.Lock()

    async def open(self, run_id: str) -> InvestigationSession:
        """The investigation session of ``run_id``, started on the first call."""
        project, hub, folder = await asyncio.to_thread(self._restrictions.run_folder, run_id)
        async with self._lock:
            records = await asyncio.to_thread(read_records, folder)
            pending = open_investigation(records, run_id)
            link = folder / f"investigation-{pending.number}.session"
            existing = await asyncio.to_thread(_claim, link, run_id)
            if existing is not None and await self._usable(existing):
                return _view(
                    run_id=run_id,
                    project=project,
                    pending=pending,
                    session_id=existing,
                    started=False,
                )
            try:
                session_id = await self._start(
                    project=project, hub=hub, run_id=run_id, records=records, pending=pending
                )
            except BaseException:
                with contextlib.suppress(OSError):
                    link.unlink()
                raise
            try:
                await asyncio.to_thread(_write_link, link, session_id)
            except BaseException:
                # The session exists but nothing names it: stop it, keep the link to take over.
                with contextlib.suppress(Exception):
                    await self._control.close(session_id)
                raise
        return _view(
            run_id=run_id, project=project, pending=pending, session_id=session_id, started=True
        )

    async def _usable(self, session_id: str) -> bool:
        """Whether the linked session is known and live, or ended and still resumable; an
        error reading what can be resumed is raised, never taken as "not resumable"."""
        try:
            session = await self._control.snapshot(session_id)
        except EntityNotFoundError:
            return False
        if session.status not in _ENDED:
            return True
        claude = session.claude_session_id
        if claude is None or session.end_reason == EndReason.LOG_FULL:
            return False
        listed = await self._control.resumable(session.project, session.workdir_id)
        return any(past.session_id == claude for past in listed.items)

    async def _start(
        self,
        *,
        project: str,
        hub: str,
        run_id: str,
        records: list[dict[str, JsonValue]],
        pending: InvestigationView,
    ) -> str:
        restriction = await asyncio.to_thread(
            lambda: self._restrictions.for_run(
                project=project, hub=hub, records=records, step=pending.step
            )
        )
        listed = await self._control.workdirs(project)
        workdir = next((item for item in listed.items if item.kind == "hub"), None)
        if workdir is None:
            raise EntityNotFoundError(entity="workdir", entity_id=project)
        failure = f" ({pending.failure_kind})" if pending.failure_kind else ""
        request = CreateAgentSession(
            project=project,
            workdir_id=workdir.workdir_id,
            mode="default",
            prompt=f"Investigate why step {pending.step} diverged{failure} in scenario run"
            f" {run_id}, then record your proposal.",
        )
        session = await self._control.create(request, restriction=restriction)
        return session.id


def _view(
    *, run_id: str, project: str, pending: InvestigationView, session_id: str, started: bool
) -> InvestigationSession:
    return InvestigationSession(
        run_id=run_id,
        project=project,
        investigation=pending.number,
        step=pending.step,
        agent_session_id=session_id,
        started=started,
    )


def read_records(folder: Path) -> list[dict[str, JsonValue]]:
    """The record's lines; ``EntityNotFoundError`` without one, ``RunRecordError`` when it is
    too large or a line before the last is not one JSON object."""
    try:
        descriptor = os.open(folder / RECORDS, _OPEN_READ)
    except OSError:
        raise EntityNotFoundError(entity="scenario run", entity_id=folder.name) from None
    with os.fdopen(descriptor, "rb") as file:
        data = file.read(MAX_RECORD_BYTES + 1)
    if len(data) > MAX_RECORD_BYTES:
        msg = f"the scenario run's record is larger than {MAX_RECORD_BYTES} bytes"
        raise RecordTooLargeError(msg)
    return record_lines(data)


def open_investigation(records: list[dict[str, JsonValue]], run_id: str) -> InvestigationView:
    """The open, unanswered investigation of a scenario run, which its record names."""
    pending = fold_records(records).open_investigation
    is_scenario = bool(records) and records[0].get("kind") == SCENARIO_KIND
    if not is_scenario or pending is None or pending.choice is not None:
        raise RunConflictError(code="not_paused", reason=NOT_PAUSED, run_id=run_id)
    return pending


def _claim(link: Path, run_id: str) -> str | None:
    """The session id ``link`` holds; None when this call made it (or found no id in it)."""
    try:
        os.close(os.open(link, _OPEN_NEW, 0o600))
    except FileExistsError:
        pass
    else:
        return None
    try:
        return _read_link(link)
    except OSError as error:
        if error.errno != errno.ELOOP:
            raise
        reason = "the investigation's session file is a link"
        raise RunConflictError(code="link_in_path", reason=reason, run_id=run_id) from None


def linked_session(folder: Path, number: int) -> str | None:
    """The session ``investigation-<number>.session`` in a run folder names, never through a
    link; None when there is none or it cannot be read (a read for hub web's screens)."""
    try:
        return _read_link(folder / f"investigation-{number}.session")
    except OSError:
        return None


def _read_link(link: Path) -> str | None:
    """The session id a link file holds, never through a link; None when it holds none."""
    descriptor = os.open(link, _OPEN_READ)
    with os.fdopen(descriptor, "rb") as file:
        text = file.read(_LINK_BYTES).decode("ascii", errors="replace").strip()
    return text if _SESSION_ID.fullmatch(text) else None


def _link_in(folder: Path, session_id: str) -> int | None:
    """The number of the ``investigation-<n>.session`` in ``folder`` naming ``session_id``; a
    folder or a link that vanishes while read is skipped, other read errors raise."""
    try:
        entries = _entries(folder)
    except FileNotFoundError:
        return None
    for link in entries:
        named = LINK_PATTERN.fullmatch(link.name)
        if named is None:
            continue
        try:
            linked = _read_link(link)
        except FileNotFoundError:
            continue
        if linked == session_id:
            return int(named.group(1))
    return None


def _entries(folder: Path) -> list[Path]:
    """The entries of ``folder``, sorted; ``OSError`` when it cannot be listed."""
    return sorted(folder.iterdir())


def _write_link(link: Path, session_id: str) -> None:
    descriptor = os.open(link, _OPEN_WRITE)
    with os.fdopen(descriptor, "wb") as file:
        file.write(f"{session_id}\n".encode("ascii"))
        file.flush()
        os.fsync(file.fileno())
