"""``/agent-sessions``: start, read and drive the Claude Code sessions ``hub web`` runs (S3, P5).

Every route is one call to ``AgentSessionCommands`` (ADR 0031). The static paths come before
the id paths, and ids are UUIDs (``uuid`` convertor), so ``/cloud`` or ``/workdirs`` never
reach ``/{agent_session_id}``. Access (cookie, Origin) is checked before routing.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query, Response

from agent_hub.api.dependencies import AgentSessionControlDep
from agent_hub.api.openapi_paths import AGENT_SESSIONS
from agent_hub.api.schemas import PROBLEM_RESPONSES, ProjectParam
from agent_hub.core.agent_sessions.agent_session import (
    MAX_PROJECT_CHARS,
    WORKDIR_ID_PATTERN,
    AgentSession,
    AgentSessionList,
    AgentSessionStatus,
    CreateAgentSession,
    MessageAccepted,
    PermissionDecision,
    ResumableList,
    SendMessage,
    SessionSettings,
    WorkdirList,
)
from agent_hub.core.agent_sessions.driver import DriverCapabilities
from agent_hub.core.agent_sessions.records import LogRecordPage
from agent_hub.core.agent_sessions.repo_changes import (
    COMMIT_SHA_PATTERN,
    RepoCommitDiff,
    RepoFileText,
    SessionRepoChanges,
)

router = APIRouter(prefix="/agent-sessions", tags=["agent-sessions"], responses=PROBLEM_RESPONSES)

MAX_EVENTS_LIMIT = 500
DEFAULT_EVENTS_LIMIT = 200

SessionIdPath = Annotated[UUID, Path()]
RequestIdPath = Annotated[str, Path(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]
TaskIdPath = Annotated[str, Path(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]
RequiredProject = Annotated[str, Query(min_length=1, max_length=MAX_PROJECT_CHARS)]
WorkdirParam = Annotated[str, Query(pattern=WORKDIR_ID_PATTERN)]
MAX_WROTE_CHARS = 1024
WroteParam = Annotated[str | None, Query(min_length=1, max_length=MAX_WROTE_CHARS)]


@router.get("/workdirs")
async def list_workdirs(project: RequiredProject, control: AgentSessionControlDep) -> WorkdirList:
    """The folders a session may start in: the hub, its repos and their worktrees (D6)."""
    return await control.workdirs(project)


@router.get("/capabilities")
async def get_capabilities(control: AgentSessionControlDep) -> DriverCapabilities:
    """Whether sessions can start on this machine (and why not), the models, the cloud."""
    return await control.capabilities()


@router.get("/resumable")
async def list_resumable(
    project: RequiredProject, workdir_id: WorkdirParam, control: AgentSessionControlDep
) -> ResumableList:
    """Past Claude sessions of a workdir that can be resumed or forked."""
    return await control.resumable(project, workdir_id)


@router.get("")
async def list_agent_sessions(
    control: AgentSessionControlDep,
    *,
    project: ProjectParam = None,
    status: AgentSessionStatus | None = None,
    wrote: WroteParam = None,
) -> AgentSessionList:
    """Agent sessions, newest first; with ``wrote``, the ones that changed that file (a path
    relative to any workdir, such as ``brain/features/<slug>/spec.md``)."""
    return await control.list_sessions(project=project, status=status, wrote=wrote)


@router.post("", status_code=201)
async def create_agent_session(
    body: CreateAgentSession, control: AgentSessionControlDep, response: Response
) -> AgentSession:
    """Start a session in a listed workdir, optionally with a first prompt or a resume."""
    session = await control.create(body)
    response.headers["Location"] = f"{AGENT_SESSIONS}/{session.id}"
    return session


@router.get("/{agent_session_id:uuid}")
async def get_agent_session(
    agent_session_id: SessionIdPath, control: AgentSessionControlDep
) -> AgentSession:
    """One session, with the permission request it waits on while live."""
    return await control.snapshot(str(agent_session_id))


@router.get("/{agent_session_id:uuid}/repo-changes")
async def get_agent_session_repo_changes(
    agent_session_id: SessionIdPath, control: AgentSessionControlDep
) -> SessionRepoChanges:
    """What the repositories the session worked in change against their base branch, as git
    reads them: the pull request's files, whoever changed them."""
    return await control.repo_changes(str(agent_session_id))


MAX_FILE_PATH_CHARS = 4096
FilePathParam = Annotated[str, Query(min_length=1, max_length=MAX_FILE_PATH_CHARS, pattern=r"^/")]
OldFilePathParam = Annotated[
    str | None, Query(min_length=1, max_length=MAX_FILE_PATH_CHARS, pattern=r"^/")
]
CommitShaParam = Annotated[str, Query(pattern=COMMIT_SHA_PATTERN)]


@router.get("/{agent_session_id:uuid}/repo-changes/commit")
async def get_agent_session_repo_commit_diff(
    agent_session_id: SessionIdPath,
    control: AgentSessionControlDep,
    *,
    path: FilePathParam,
    sha: CommitShaParam,
    old_path: OldFilePathParam = None,
) -> RepoCommitDiff:
    """What one commit changed in one file of the session's repositories (``path`` absolute,
    ``old_path`` its name before a rename)."""
    return await control.repo_commit_diff(
        str(agent_session_id), path=path, sha=sha, old_path=old_path
    )


@router.get("/{agent_session_id:uuid}/repo-changes/file")
async def get_agent_session_repo_file(
    agent_session_id: SessionIdPath,
    control: AgentSessionControlDep,
    *,
    path: FilePathParam,
    sha: CommitShaParam,
) -> RepoFileText:
    """One file of the session's repositories (``path`` absolute) as commit ``sha`` has it: the
    lines a review expands around a pull request's diff."""
    return await control.repo_file_text(str(agent_session_id), path=path, sha=sha)


@router.delete("/{agent_session_id:uuid}", status_code=204)
async def delete_agent_session(
    agent_session_id: SessionIdPath, control: AgentSessionControlDep
) -> None:
    """Remove an ended session and its stored conversation."""
    await control.delete(str(agent_session_id))


@router.get("/{agent_session_id:uuid}/events")
async def list_agent_session_events(
    agent_session_id: SessionIdPath,
    control: AgentSessionControlDep,
    *,
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_EVENTS_LIMIT)] = DEFAULT_EVENTS_LIMIT,
) -> LogRecordPage:
    """The stored log after ``after``, in ``seq`` order (redacted)."""
    return await control.events(str(agent_session_id), after=after, limit=limit)


@router.post("/{agent_session_id:uuid}/messages", status_code=202)
async def send_agent_session_message(
    agent_session_id: SessionIdPath, body: SendMessage, control: AgentSessionControlDep
) -> MessageAccepted:
    """Send a message; it plays after the running turn."""
    return await control.send(str(agent_session_id), body)


@router.post("/{agent_session_id:uuid}/interrupt", status_code=202)
async def interrupt_agent_session(
    agent_session_id: SessionIdPath, control: AgentSessionControlDep
) -> AgentSession:
    """Interrupt the running turn; its result follows on the stream."""
    return await control.interrupt(str(agent_session_id))


@router.post("/{agent_session_id:uuid}/tasks/{task_id}/stop", status_code=202)
async def stop_agent_session_task(
    agent_session_id: SessionIdPath, task_id: TaskIdPath, control: AgentSessionControlDep
) -> AgentSession:
    """Stop a background task (an agent or a command); its end follows on the stream."""
    return await control.stop_task(str(agent_session_id), task_id)


@router.post("/{agent_session_id:uuid}/permissions/{request_id}")
async def answer_agent_session_permission(
    agent_session_id: SessionIdPath,
    request_id: RequestIdPath,
    body: PermissionDecision,
    *,
    control: AgentSessionControlDep,
) -> AgentSession:
    """Answer a permission request: allow, deny (with a message) or always (a suggestion)."""
    return await control.answer(str(agent_session_id), request_id, body)


@router.post("/{agent_session_id:uuid}/settings")
async def change_agent_session_settings(
    agent_session_id: SessionIdPath, body: SessionSettings, control: AgentSessionControlDep
) -> AgentSession:
    """Change the permission mode or the model."""
    return await control.change_settings(str(agent_session_id), body)


@router.post("/{agent_session_id:uuid}/close")
async def close_agent_session(
    agent_session_id: SessionIdPath, control: AgentSessionControlDep
) -> AgentSession:
    """End the session; its log is kept and it can be resumed."""
    return await control.close(str(agent_session_id))
