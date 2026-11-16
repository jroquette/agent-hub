"""``EnvironmentDiscoveries``: start, list, read and discard a project's discoveries (ADR 0046).

``start`` checks the picked repos and environments against the project's effective config (an
unknown one is refused, 422, before anything starts), starts a ``read_only`` session in the
project's hub with the server's prompt and the picked repos attached, then records the
discovery. A read answers the session's state and, once there is one, the proposal of its last
reply, checked (``proposal``) and compared with the config of now.

The state follows the session: a turn at work or a request open is ``running``; a proposal in
the last reply is ``finished`` (whatever the session did after); a turn the person interrupted,
or a session they closed, without one is ``stopped``; any other end without one is ``failed``,
with the reason in plain words.
"""

import asyncio
import contextlib
import secrets
from collections.abc import Callable
from datetime import datetime
from pathlib import PurePosixPath
from typing import Final, Protocol

from agent_hub.core.agent_sessions.agent_session import (
    AgentSession,
    AgentSessionStatus,
    CreateAgentSession,
    EndReason,
    FinalReply,
    WorkdirList,
)
from agent_hub.core.agent_sessions.driver import ToolAccess
from agent_hub.core.agent_sessions.errors import AgentSessionNotFoundError
from agent_hub.core.environment_discovery.discovery import (
    DiscoveryNotFoundError,
    DiscoveryRecord,
    DiscoveryRecords,
    DiscoveryState,
    EnvironmentDiscovery,
    StartEnvironmentDiscovery,
)
from agent_hub.core.environment_discovery.prompt import discovery_prompt
from agent_hub.core.environment_discovery.proposal import (
    Asked,
    ProposalError,
    read_proposal,
    with_statuses,
)
from agent_hub.core.hub_config.config_view import HubConfigView
from agent_hub.core.hubs.hub_registry import HubInvalidError
from agent_hub.core.hubs.registered_hub import ValidationProblem
from agent_hub.core.readmodels.page import Page

NOT_STARTED: Final = "This discovery was not started"
SESSION_GONE: Final = "The Claude session of this discovery was removed"
SESSION_FAILED: Final = "The Claude session failed before it proposed anything"
SERVER_STOPPED: Final = "hub web stopped before Claude finished"
MAX_LISTED: Final = 50
_RUNNING: Final = frozenset({AgentSessionStatus.RUNNING, AgentSessionStatus.WAITING_PERMISSION})
_STOPPED_BY_PERSON: Final = frozenset({EndReason.CLOSED})


class DiscoverySessions(Protocol):
    """What a discovery needs of the agent sessions (``AgentSessionControl``)."""

    async def workdirs(self, project: str) -> WorkdirList:
        """The folders a session of ``project`` may start in."""
        ...

    async def create(
        self,
        request: CreateAgentSession,
        *,
        tool_access: ToolAccess = "all",
        add_dirs: tuple[str, ...] = (),
    ) -> AgentSession:
        """Start a session."""
        ...

    async def snapshot(self, agent_session_id: str) -> AgentSession:
        """One session."""
        ...

    async def final_reply(self, agent_session_id: str) -> FinalReply:
        """What the session answered its last message."""
        ...

    async def close(self, agent_session_id: str) -> AgentSession:
        """End the session."""
        ...


class ProjectConfigs(Protocol):
    """A project's effective hub config (``HubReadModels.hub_config``)."""

    def hub_config(self, project: str) -> HubConfigView:
        """The project's config; ``EntityNotFoundError`` when unknown."""
        ...


def _new_id() -> str:
    return secrets.token_hex(6)


class EnvironmentDiscoveries:
    """The discoveries use case; see the module docstring."""

    def __init__(
        self,
        sessions: DiscoverySessions,
        configs: ProjectConfigs,
        records: DiscoveryRecords,
        *,
        clock: Callable[[], datetime],
        new_id: Callable[[], str] = _new_id,
    ) -> None:
        self._sessions = sessions
        self._configs = configs
        self._records = records
        self._clock = clock
        self._new_id = new_id

    async def start(self, project: str, request: StartEnvironmentDiscovery) -> EnvironmentDiscovery:
        """Start a read-only session on the picked repos and record the discovery."""
        config = await asyncio.to_thread(self._configs.hub_config, project)
        repos, environments = _checked(config, request)
        workspace = str(PurePosixPath(config.hub_path).parent)
        workdirs = await self._sessions.workdirs(project)
        hub = next((item for item in workdirs.items if item.kind == "hub"), None)
        if hub is None:
            problem = ValidationProblem(pointer="", message="the hub folder cannot be read")
            raise HubInvalidError(NOT_STARTED, problems=(problem,))
        prompt = discovery_prompt(
            workspace=workspace,
            repos=repos,
            environments=environments,
            suggest_environments=request.suggest_environments,
        )
        session = await self._sessions.create(
            CreateAgentSession(project=project, workdir_id=hub.workdir_id, prompt=prompt),
            tool_access="read_only",
            add_dirs=tuple(str(PurePosixPath(workspace, repo)) for repo in repos),
        )
        record = DiscoveryRecord(
            id=self._new_id(),
            project=project,
            agent_session_id=session.id,
            repos=repos,
            environments=environments,
            suggest_environments=request.suggest_environments,
            created_at=self._clock(),
        )
        await asyncio.to_thread(self._records.create, config.hub_path, record)
        return await self._view(record, config)

    async def list(self, project: str) -> Page[EnvironmentDiscovery]:
        """The project's discoveries not discarded, newest first, at most ``MAX_LISTED``."""
        config = await asyncio.to_thread(self._configs.hub_config, project)
        stored = await asyncio.to_thread(self._records.list, config.hub_path)
        kept = sorted(
            (record for record in stored if not record.discarded and record.project == project),
            key=lambda record: record.created_at,
            reverse=True,
        )[:MAX_LISTED]
        views = [await self._view(record, config) for record in kept]
        return Page(items=tuple(views), total_estimate=len(views))

    async def get(self, project: str, discovery_id: str) -> EnvironmentDiscovery:
        """One discovery; ``DiscoveryNotFoundError`` when unknown or discarded."""
        config = await asyncio.to_thread(self._configs.hub_config, project)
        record = await self._record(config, project, discovery_id)
        return await self._view(record, config)

    async def discard(self, project: str, discovery_id: str) -> None:
        """Mark a discovery discarded, and end its session when it still works."""
        config = await asyncio.to_thread(self._configs.hub_config, project)
        record = await self._record(config, project, discovery_id)
        discarded = record.model_copy(update={"discarded": True})
        await asyncio.to_thread(self._records.replace, config.hub_path, discarded)
        with contextlib.suppress(AgentSessionNotFoundError):
            await self._sessions.close(record.agent_session_id)

    async def _record(
        self, config: HubConfigView, project: str, discovery_id: str
    ) -> DiscoveryRecord:
        record = await asyncio.to_thread(self._records.get, config.hub_path, discovery_id)
        if record is None or record.discarded or record.project != project:
            raise DiscoveryNotFoundError(discovery_id)
        return record

    async def _view(self, record: DiscoveryRecord, config: HubConfigView) -> EnvironmentDiscovery:
        fields = record.model_dump(exclude={"discarded"})
        try:
            session = await self._sessions.snapshot(record.agent_session_id)
        except AgentSessionNotFoundError:
            return EnvironmentDiscovery(**fields, state="failed", problem=SESSION_GONE)
        if session.status in _RUNNING:
            return EnvironmentDiscovery(**fields, state="running")
        reply = await self._sessions.final_reply(record.agent_session_id)
        asked = Asked(
            repos=record.repos,
            environments=record.environments,
            suggest_environments=record.suggest_environments,
            declared=tuple(item.name for item in config.environments.environments),
            workspace=str(PurePosixPath(config.hub_path).parent),
        )
        try:
            proposal = read_proposal(reply.text, asked)
        except ProposalError as error:
            state, problem = _without_proposal(session, reply, str(error))
            return EnvironmentDiscovery(**fields, state=state, problem=problem)
        checked = with_statuses(proposal, config.environments)
        return EnvironmentDiscovery(**fields, state="finished", proposal=checked)


def _without_proposal(
    session: AgentSession, reply: FinalReply, problem: str
) -> tuple[DiscoveryState, str | None]:
    """The state of a session that holds no proposal now, and the reason when it failed."""
    if reply.interrupted or session.end_reason in _STOPPED_BY_PERSON:
        return "stopped", None
    if session.end_reason == EndReason.SERVER_STOPPED and reply.text is None:
        return "failed", SERVER_STOPPED
    if session.status == AgentSessionStatus.FAILED and reply.text is None:
        return "failed", SESSION_FAILED
    return "failed", problem


def _checked(
    config: HubConfigView, request: StartEnvironmentDiscovery
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The picked repos and environments (as declared, without repeats); 422 naming each one
    the config does not hold."""
    repo_dirs = {repo.dir for repo in config.repos}
    declared = {item.name.casefold(): item.name for item in config.environments.environments}
    problems: list[ValidationProblem] = []
    repos: list[str] = []
    for index, repo in enumerate(request.repos):
        if repo not in repo_dirs:
            problems.append(
                ValidationProblem(pointer=f"/repos/{index}", message="not a repo of hub.json")
            )
        elif repo not in repos:
            repos.append(repo)
    environments: list[str] = []
    for index, name in enumerate(request.environments):
        found = declared.get(name.casefold())
        if found is None:
            problems.append(
                ValidationProblem(
                    pointer=f"/environments/{index}", message="not a declared environment"
                )
            )
        elif found not in environments:
            environments.append(found)
    if problems:
        raise HubInvalidError(NOT_STARTED, problems=tuple(problems))
    return tuple(repos), tuple(environments)
