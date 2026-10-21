"""The investigation session of a paused scenario run (P-7, AM-2, AM-9, AM-13; docs/design/
scenarios.md § Investigation, answers and workarounds).

``ScenarioInvestigations.open`` serves ``POST /scenario-runs/{run_id}/investigation``. It finds
the run's folder, ``<hub>/.agent-runs/workflows/<run>/``, in a registered hub (never through a
link), reads its ``records.jsonl`` (at most ``MAX_RECORD_BYTES``, a torn last line dropped) and
folds it with core's ``fold_records``: the run must be a scenario run paused at an open,
unanswered investigation, which only its record says (E-10), else 409 ``not_paused``. It then
starts one driven session in the hub, mode ``default``, with the investigation's system prompt,
its tool policy (P-17: the hub, ``actions/`` and every declared env file's real path) and,
like every driven session, without the hub's declared credentials. Chat goes through
``POST /agent-sessions/{id}/messages`` (AM-9).

One session per investigation: the link file ``investigation-<n>.session`` in the run folder
is created ``O_CREAT|O_EXCL`` (owner-only, never through a link) before the session starts and
gets its id after, all under one lock, so a second call answers the same session. A start that
fails removes the file; an empty one (a server stopped mid-start) is taken over by the next
call. When ``hub.local.json`` cannot be read, the env files it may declare are unknown, so no
session starts (409 ``hub_local_invalid``). No env file is opened here: the session's own
``hub action run --run`` loads it in the action's process (P-24).
"""

import asyncio
import contextlib
import errno
import os
import re
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Final

from agent_hub.api.agent_session_runtime import HubCredentials
from agent_hub.core.agent_sessions.agent_session import UUID_PATTERN, CreateAgentSession
from agent_hub.core.agent_sessions.control import AgentSessionCommands, SessionRestriction
from agent_hub.core.json_form import JsonValue
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.readmodels.view_types import ViewModel
from agent_hub.core.scenarios.investigation import ToolPolicy, investigation_prompt
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
_LINK_BYTES: Final = 128
_OPEN_NEW: Final = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_OPEN_READ: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
_OPEN_WRITE: Final = os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW | os.O_CLOEXEC
_SESSION_ID = re.compile(UUID_PATTERN)
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


type HubPaths = Callable[[], Iterable[tuple[str, str]]]


class ScenarioInvestigations:
    """``POST /scenario-runs/{run_id}/investigation``; see the module docstring. ``hubs``
    lists each project's hub folder; ``control`` starts the session; ``credentials`` reads what
    each hub declares."""

    def __init__(
        self, *, hubs: HubPaths, control: AgentSessionCommands, credentials: HubCredentials
    ) -> None:
        self._hubs = hubs
        self._control = control
        self._credentials = credentials
        self._lock = asyncio.Lock()

    async def open(self, run_id: str) -> InvestigationSession:
        """The investigation session of ``run_id``, started on the first call."""
        project, hub, folder = await asyncio.to_thread(self._run_folder, run_id)
        async with self._lock:
            records = await asyncio.to_thread(_read_records, folder)
            pending = _open_investigation(records, run_id)
            link = folder / f"investigation-{pending.number}.session"
            existing = await asyncio.to_thread(_claim, link, run_id)
            if existing is not None:
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
            await asyncio.to_thread(_write_link, link, session_id)
        return _view(
            run_id=run_id, project=project, pending=pending, session_id=session_id, started=True
        )

    def _run_folder(self, run_id: str) -> tuple[str, str, Path]:
        if RUN_ID_PATTERN.fullmatch(run_id):
            for project, hub in self._hubs():
                folder = Path(hub) / RUN_FOLDERS / run_id
                if folder.is_dir() and not folder.is_symlink():
                    return project, hub, folder
        raise EntityNotFoundError(entity="scenario run", entity_id=run_id)

    async def _start(
        self,
        *,
        project: str,
        hub: str,
        run_id: str,
        records: list[dict[str, JsonValue]],
        pending: InvestigationView,
    ) -> str:
        declared = await asyncio.to_thread(self._credentials.of_hub, hub)
        if not declared.complete:
            reason = "hub.local.json cannot be read, so its env files are unknown; fix it first"
            raise RunConflictError(code="hub_local_invalid", reason=reason, run_id=run_id)
        header = records[0]
        policy = ToolPolicy.of(hub=hub, env_files=declared.env_files, run_id=run_id)
        prompt = investigation_prompt(
            run_id=run_id,
            scenario=str(header.get("scenario")),
            environment=str(header.get("environment")),
            step=pending.step,
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
        restriction = SessionRestriction(tool_policy=policy, system_prompt=prompt)
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


def _read_records(folder: Path) -> list[dict[str, JsonValue]]:
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


def _open_investigation(records: list[dict[str, JsonValue]], run_id: str) -> InvestigationView:
    """The open, unanswered investigation of a scenario run, which its record names."""
    pending = fold_records(records).open_investigation
    is_scenario = bool(records) and records[0].get("kind") == SCENARIO_KIND
    if not is_scenario or pending is None or pending.choice is not None:
        raise RunConflictError(code="not_paused", reason=NOT_PAUSED, run_id=run_id)
    return pending


def _claim(link: Path, run_id: str) -> str | None:
    """The session id ``link`` holds; None when this call made it (or found it empty)."""
    try:
        os.close(os.open(link, _OPEN_NEW, 0o600))
    except FileExistsError:
        pass
    else:
        return None
    try:
        descriptor = os.open(link, _OPEN_READ)
    except OSError as error:
        if error.errno != errno.ELOOP:
            raise
        reason = "the investigation's session file is a link"
        raise RunConflictError(code="link_in_path", reason=reason, run_id=run_id) from None
    with os.fdopen(descriptor, "rb") as file:
        text = file.read(_LINK_BYTES).decode("ascii", errors="replace").strip()
    return text if _SESSION_ID.fullmatch(text) else None


def _write_link(link: Path, session_id: str) -> None:
    descriptor = os.open(link, _OPEN_WRITE)
    with os.fdopen(descriptor, "wb") as file:
        file.write(f"{session_id}\n".encode("ascii"))
        file.flush()
        os.fsync(file.fileno())
