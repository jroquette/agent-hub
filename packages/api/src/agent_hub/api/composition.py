"""``build_app``: the API as ``hub web`` serves it, wired to the real adapters.

The event store at ``settings.db_path`` (opened and upgraded here), the hook mapper and live
transcript tail of the collector, the hub registry at ``settings.registry_path`` and the hubs'
files read as ``hub doctor`` reads them, the read models folded on request, the change feed
the streams wait on, the learning reads and decisions, which open hub pull requests through
``hub_git`` (ADR 0024), and the hubs' workflows (the generator's discovery). Git config stays
with the caller (the CLI): ``read_git`` makes the git config reader of one hub folder, so the
branch prefix and author match ``hub doctor``.

The feature tickets read Linear through ``CachedTicketSnapshots`` (ADR 0025): ``TicketReaders``
gives its reader per request, None (not connected) when ``LINEAR_API_KEY`` is unset in
``environ`` or the hub's ``tracker.transport`` is ``mcp``; the key is read at call time and never
logged or shown.

The agent sessions (AGH-165, ADR 0031) run over the Claude driver and cloud launcher of
``agent_hub.claude_sessions``, imported in ``claude_adapters`` alone: without the ``sessions``
extra the driver is ``UnavailableSessionDriver`` (P2). Their store is the same database's
agent-session tables; ``SessionRuntime`` sweeps and shuts them down with the app. Inside the
container (``settings.sessions_off``, L2) none of it is built.
"""

import ipaddress
import os
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from fastapi import FastAPI

from agent_hub.api.agent_session_runtime import (
    SessionRuntime,
    UnavailableCloudLauncher,
    UnavailableSessionDriver,
)
from agent_hub.api.app import create_app
from agent_hub.api.change_feed import ChangeFeed, SystemTimer
from agent_hub.api.dependencies import ApiPorts
from agent_hub.api.rfc9457 import (
    ProblemFactory,
    busy_problem,
    hub_conflict_problem,
    hub_invalid_problem,
    hub_registry_problem,
    invalid_cursor_problem,
)
from agent_hub.api.settings import ApiSettings, utc_now
from agent_hub.api.static_files import WEB_DIST
from agent_hub.api.ticket_snapshots import (
    READ_BUDGET_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    CachedTicketSnapshots,
)
from agent_hub.api.workdir_listing import RegisteredWorkdirs
from agent_hub.collector.claude_hooks import ClaudeHookMapper
from agent_hub.collector.transcript_tail import TranscriptTail
from agent_hub.core.agent_sessions.cloud import CloudLauncher, CloudSessions
from agent_hub.core.agent_sessions.control import AgentSessionControl, WorkdirSource
from agent_hub.core.agent_sessions.driver import SessionDriver
from agent_hub.core.agent_sessions.links import AgentSessionLinks
from agent_hub.core.agent_sessions.store import AgentSessionStore
from agent_hub.core.features.ticket_snapshots import (
    SnapshotRequest,
    TicketSnapshots,
    TrackerTransport,
)
from agent_hub.core.hub_config.effective_identity import (
    GitReader,
    IdentityKey,
    IdentityValues,
    resolve_identity,
)
from agent_hub.core.hub_config.local_config import LocalConfig
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hubs.hub_document import read_hub_document
from agent_hub.core.hubs.hub_read_models import HubFilesReadModels, ProjectActivitySource
from agent_hub.core.hubs.hub_registry import (
    HubConflictError,
    HubFileReader,
    HubInvalidError,
    HubRegistry,
    HubRegistryError,
)
from agent_hub.core.ingestion.ingest_events import IngestEvents
from agent_hub.core.ingestion.ingest_hook import IngestHook
from agent_hub.core.ingestion.ingestion_status import IngestionCounters
from agent_hub.core.learnings.brain_change_requests import BrainChangeRequests, CommitAuthor
from agent_hub.core.learnings.decide_learning import DecideLearning
from agent_hub.core.learnings.learning_ports import LearningHub
from agent_hub.core.learnings.read_learnings import (
    HUB_NOT_REGISTERED,
    ReadLearnings,
    UnavailableHub,
)
from agent_hub.core.readmodels.cursor import InvalidCursorError
from agent_hub.core.readmodels.event_read_models import FoldedEventReadModels
from agent_hub.core.readmodels.read_ports import EntityNotFoundError, HubReadModels
from agent_hub.core.readmodels.settings_view import SettingsView
from agent_hub.core.redaction.redact import KINDS as REDACTION_KINDS
from agent_hub.core.sessions.pricing import PRICES, PRICES_AS_OF
from agent_hub.core.sessions.session_label import LabelRules
from agent_hub.core.skills.skill_reads import SkillUsageSource
from agent_hub.core.tracker.tracker_reader import TrackerReader
from agent_hub.core.workflows.workflow_reads import ListedWorkflowSource, ReadWorkflows
from agent_hub.generator.registered_hub_files import GitReaderFactory, HubFileSystem
from agent_hub.generator.workflow_source import DiscoveredWorkflowSource
from agent_hub.hub_git.brain_change_requests import GitBrainChangeRequests
from agent_hub.hub_git.git_runner import GitRunner
from agent_hub.storage.agent_session_store import open_agent_session_store
from agent_hub.storage.event_store import DatabaseBusyError, SqliteEventStore, open_event_store
from agent_hub.storage.hub_registry import JsonHubRegistry
from agent_hub.tracker_linear.graphql_reader import LinearGraphqlTrackerReader
from agent_hub.tracker_linear.graphql_transport import LINEAR_API_KEY_VARIABLE, Post

# The errors of the wired adapters, each answered by its problem (API.md "Error mapping").
COMPOSED_PROBLEMS: Mapping[type[Exception], ProblemFactory] = {
    DatabaseBusyError: busy_problem,
    InvalidCursorError: invalid_cursor_problem,
    HubInvalidError: hub_invalid_problem,
    HubConflictError: hub_conflict_problem,
    HubRegistryError: hub_registry_problem,
}


# How long a hub's facts (hub.json, hub.local.json, git config) and a hub's action availability
# (up to three child processes) are reused before they are read again.
HUB_FACTS_SECONDS: Final = 5.0
AVAILABILITY_SECONDS: Final = 10.0
NO_AUTHOR: Final = "No commit author for this hub (set author_name and author_email)"
HUB_CONFIG_INVALID: Final = "Hub config is invalid"
HUB_LOCAL_INVALID: Final = "hub.local.json is invalid"
_IDENTITY_KEYS: Final = tuple(IdentityKey)


def default_projects_root() -> Path:
    """Where Claude Code keeps its transcripts: ``~/.claude/projects``."""
    return Path.home() / ".claude" / "projects"


class _HubPaths:
    """A project's hub path for "How to decide"; None when no valid registered hub names it.

    Bound after the hub read models exist, which themselves read the event read models.
    """

    def __init__(self) -> None:
        self.hubs: HubReadModels | None = None

    def __call__(self, project: str) -> str | None:
        if self.hubs is None:
            return None
        try:
            return self.hubs.get_project(project).hub_path
        except EntityNotFoundError, HubRegistryError:
            return None


def _no_git(_keys: frozenset[str]) -> Mapping[str, str]:
    return {}


def _files_only(_hub_path: str) -> GitReader:
    return _no_git


@dataclass(frozen=True, slots=True)
class _HubFacts:
    """What the learning actions and the session labels need of one project's hub."""

    hub: LearningHub | UnavailableHub
    label_rules: LabelRules | None
    transport: TrackerTransport | None = None


_UNREGISTERED: Final = _HubFacts(hub=UnavailableHub(reason=HUB_NOT_REGISTERED), label_rules=None)


class RegisteredHubFacts:
    """Each project's hub as the registry and its files name it, reread every ``ttl`` seconds.

    ``hub_of`` is the hub a learning decision acts on (``hub.json`` with ``hub.local.json``,
    else git config, for the author and branch prefix: ADR 0016), or why it cannot act;
    ``label_rules_of`` the tracker teams and branch prefix a session's issue is read with;
    ``tracker_transport_of`` the hub's ``tracker.transport`` (ADR 0025). When
    two hubs name a project, the first valid one registered wins, as in the hub read models.
    """

    def __init__(
        self,
        *,
        registry: HubRegistry,
        reader: HubFileReader,
        running_version: str,
        read_git: Callable[[str], GitReader] = _files_only,
        ttl: float = HUB_FACTS_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._registry = registry
        self._reader = reader
        self._running = running_version
        self._read_git = read_git
        self._ttl = ttl
        self._clock = clock
        self._guard = threading.Lock()
        self._read_at: float | None = None
        self._facts: Mapping[str, _HubFacts] = {}

    def hub_of(self, project: str) -> LearningHub | UnavailableHub:
        """The project's hub for a learning decision, or why there is none."""
        return self._current().get(project, _UNREGISTERED).hub

    def label_rules_of(self, project: str) -> LabelRules | None:
        """The project's tracker teams and branch prefix; None when no valid hub names it."""
        return self._current().get(project, _UNREGISTERED).label_rules

    def tracker_transport_of(self, project: str) -> TrackerTransport | None:
        """The project's ``tracker.transport``; None when no valid hub names it."""
        return self._current().get(project, _UNREGISTERED).transport

    def _current(self) -> Mapping[str, _HubFacts]:
        with self._guard:
            now = self._clock()
            if self._read_at is None or now - self._read_at >= self._ttl:
                self._facts = self._read()
                self._read_at = now
            return self._facts

    def _read(self) -> dict[str, _HubFacts]:
        try:
            entries = self._registry.entries()
        except HubRegistryError:
            return {}
        valid: dict[str, _HubFacts] = {}
        invalid: dict[str, _HubFacts] = {}
        for entry in entries:
            document = read_hub_document(
                self._reader.read_hub_json(entry.path), running_version=self._running
            )
            config = document.config
            if config is None:
                if document.project is not None and document.project not in invalid:
                    hub = UnavailableHub(reason=HUB_CONFIG_INVALID, path=entry.path)
                    invalid[document.project] = _HubFacts(hub=hub, label_rules=None)
            elif config.project.name not in valid:
                valid[config.project.name] = self._facts_of(entry.path, config)
        return invalid | valid

    def _facts_of(self, hub_path: str, config: HubConfig) -> _HubFacts:
        transport = config.tracker.transport
        local = self._reader.read_local(hub_path)
        if not isinstance(local, LocalConfig):
            rules = LabelRules(
                teams=config.tracker.team_keys, branch_prefix=config.project.branch_prefix or ""
            )
            return _HubFacts(
                hub=UnavailableHub(reason=HUB_LOCAL_INVALID, path=hub_path),
                label_rules=rules,
                transport=transport,
            )
        values = resolve_identity(
            local=IdentityValues.of(local.project),
            hub=IdentityValues.of(config.project),
            keys=_IDENTITY_KEYS,
            read_git=self._read_git(hub_path),
        ).values
        prefix = values[IdentityKey.BRANCH_PREFIX]
        branch_prefix = "" if prefix is None else prefix.value
        rules = LabelRules(teams=config.tracker.team_keys, branch_prefix=branch_prefix)
        name, email = values[IdentityKey.AUTHOR_NAME], values[IdentityKey.AUTHOR_EMAIL]
        if name is None or email is None:
            return _HubFacts(
                hub=UnavailableHub(reason=NO_AUTHOR, path=hub_path),
                label_rules=rules,
                transport=transport,
            )
        hub = LearningHub(
            project=config.project.name,
            path=hub_path,
            hub_repo=config.project.hub_repo,
            default_branch=config.project.default_branch,
            branch_prefix=branch_prefix,
            author=CommitAuthor(name=name.value, email=email.value),
        )
        return _HubFacts(hub=hub, label_rules=rules, transport=transport)


class CachedAvailability:
    """``BrainChangeRequests.availability`` per hub, reused for ``ttl`` seconds.

    A check spawns up to three processes; a learnings list asks it once per project. The
    decision itself checks again, uncached, before it acts.
    """

    def __init__(
        self,
        check: Callable[[str], str | None],
        *,
        ttl: float = AVAILABILITY_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._check = check
        self._ttl = ttl
        self._clock = clock
        self._guard = threading.Lock()
        self._seen: dict[str, tuple[float, str | None]] = {}

    def __call__(self, hub_path: str) -> str | None:
        now = self._clock()
        with self._guard:
            seen = self._seen.get(hub_path)
        if seen is not None and now - seen[0] < self._ttl:
            return seen[1]
        reason = self._check(hub_path)
        with self._guard:
            self._seen[hub_path] = (now, reason)
        return reason


class TicketReaders:
    """The ``reader_of`` of ``CachedTicketSnapshots``: ``reader``, or None when not connected.

    Not connected (Not-connected rule, ADR 0025): the request's or the registered hub's
    ``tracker.transport`` is ``mcp`` (never read through MCP), or ``LINEAR_API_KEY`` is unset or
    empty in ``environ``. Both are read on every call, so a key set while ``hub web`` runs takes
    effect at once; no network here, and the key is only tested for presence.
    """

    def __init__(
        self, facts: RegisteredHubFacts, *, environ: Mapping[str, str], reader: TrackerReader
    ) -> None:
        self._facts = facts
        self._environ = environ
        self._reader = reader

    def __call__(self, request: SnapshotRequest) -> TrackerReader | None:
        if request.transport == "mcp" or self._facts.tracker_transport_of(request.project) == "mcp":
            return None
        if not self._environ.get(LINEAR_API_KEY_VARIABLE):
            return None
        return self._reader


def ticket_snapshots(
    facts: RegisteredHubFacts,
    *,
    environ: Mapping[str, str] | None = None,
    linear_post: Post | None = None,
    tracker_reader: TrackerReader | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> CachedTicketSnapshots:
    """The feature tickets' cache over Linear's GraphQL reader (``tracker_reader`` in tests).

    ``environ`` defaults to this process's environment, read at call time; ``linear_post`` is
    the reader's HTTP transport (default ``urllib``); ``clock`` times the cache (the app's).
    """
    env: Mapping[str, str] = os.environ if environ is None else environ
    reader = (
        LinearGraphqlTrackerReader(
            environ=env,
            post=linear_post,
            timeout_s=REQUEST_TIMEOUT_SECONDS,
            deadline_s=READ_BUDGET_SECONDS,
        )
        if tracker_reader is None
        else tracker_reader
    )
    return CachedTicketSnapshots(TicketReaders(facts, environ=env, reader=reader), clock=clock)


def workflow_source_of(hub_path: str) -> ListedWorkflowSource:
    """The workflows of the hub at ``hub_path``: its ``workflows/``, then the built-ins."""
    return DiscoveredWorkflowSource(Path(hub_path))


def default_brain_changes() -> BrainChangeRequests:
    """The ``hub_git`` adapter with this process's environment (``AGENT_HUB_IN_CONTAINER=1``
    makes every hub read-only)."""
    return GitBrainChangeRequests(GitRunner())


def claude_adapters(environ: Mapping[str, str]) -> tuple[SessionDriver, CloudLauncher]:
    """The Claude driver and cloud launcher over ``environ`` (the children's environment), or
    their unavailable stand-ins when the ``sessions`` extra is not installed (P2)."""
    try:
        from agent_hub.claude_sessions.cloud_launcher import ClaudeCloudLauncher  # noqa: PLC0415
        from agent_hub.claude_sessions.sdk_driver import ClaudeSdkSessionDriver  # noqa: PLC0415
    except ImportError:
        return UnavailableSessionDriver(), UnavailableCloudLauncher()
    return ClaudeSdkSessionDriver(environ=environ), ClaudeCloudLauncher(environ=environ)


def web_url(settings: ApiSettings) -> str:
    """The URL the children reach ``hub web`` at (``AGENT_HUB_WEB_URL``): the bound address
    and port, an IPv6 one in brackets; a bind on every address (the container's) is reached at
    127.0.0.1."""
    host = settings.bound_host
    if ipaddress.ip_address(host).is_unspecified:
        host = "127.0.0.1"
    shown = f"[{host}]" if ":" in host else host
    return f"http://{shown}:{settings.port}"


@dataclass(frozen=True)
class AgentSessionWiring:
    """The agent-session use cases of one app, the links into the session views, and the
    runtime that sweeps and stops them with the app."""

    control: AgentSessionControl
    cloud: CloudSessions
    links: AgentSessionLinks
    runtime: SessionRuntime


def wire_agent_sessions(  # noqa: PLR0913 -- the use cases' ports, all injected
    settings: ApiSettings,
    *,
    store: AgentSessionStore,
    workdirs: WorkdirSource,
    driver: SessionDriver,
    launcher: CloudLauncher,
    url: str,
) -> AgentSessionWiring:
    """``AgentSessionControl``, ``CloudSessions`` and ``AgentSessionLinks`` over ``driver``,
    ``launcher`` and ``store``; the children get ``AGENT_HUB_WEB_URL=url`` (never the token)."""
    control = AgentSessionControl(
        driver,
        store,
        workdirs=workdirs,
        clock=settings.clock,
        limits=settings.limits,
        environment_extra={"AGENT_HUB_WEB_URL": url},
    )
    cloud = CloudSessions(
        launcher=launcher,
        store=store,
        capabilities=driver.capabilities,
        clock=settings.clock,
        limits=settings.limits,
    )
    return AgentSessionWiring(
        control=control,
        cloud=cloud,
        links=AgentSessionLinks(control.live_link, store),
        runtime=SessionRuntime(control, store, clock=settings.clock),
    )


def _event_read_models(
    store: SqliteEventStore,
    settings: ApiSettings,
    *,
    hub_paths: _HubPaths,
    label_rules_of: Callable[[str], LabelRules | None],
    sessions: AgentSessionWiring | None,
) -> FoldedEventReadModels:
    return FoldedEventReadModels(
        store,
        now=settings.clock,
        hub_path_of=hub_paths,
        prices=PRICES,
        label_rules_of=label_rules_of,
        agent_session_link_of=None if sessions is None else sessions.links.link_of,
    )


def hub_read_models(  # noqa: PLR0913 - the hub reads' ports, all keyword-only
    settings: ApiSettings,
    *,
    registry: HubRegistry,
    reader: HubFileReader,
    activity: ProjectActivitySource,
    usage: SkillUsageSource,
    ticket_snapshots: TicketSnapshots | None,
) -> HubFilesReadModels:
    """The hub read models of ``hub web``: ``activity`` and ``usage`` are the event read models
    (the project cards' numbers, the Skills tab's 30-day counts)."""
    return HubFilesReadModels(
        registry=registry,
        reader=reader,
        activity=activity,
        running_version=settings.running_version,
        settings=SettingsView(
            db_path=str(settings.db_path),
            registry_path=str(settings.registry_path),
            port=settings.port,
            running_version=settings.running_version,
            redaction_kinds=REDACTION_KINDS,
            prices_as_of=PRICES_AS_OF if PRICES else None,
        ),
        clock=settings.clock,
        ticket_snapshots=ticket_snapshots,
        usage=usage,
    )


def build_app(
    settings: ApiSettings,
    *,
    projects_root: Path | None = None,
    read_git: GitReaderFactory | None = None,
    web_dist: Path = WEB_DIST,
    brain_changes: BrainChangeRequests | None = None,
    environ: Mapping[str, str] | None = None,
    linear_post: Post | None = None,
    tracker_reader: TrackerReader | None = None,
    session_driver: SessionDriver | None = None,
    cloud_launcher: CloudLauncher | None = None,
) -> FastAPI:
    """The app of ``hub web``: every route wired to the real adapters.

    ``projects_root`` is Claude Code's transcripts folder (default ``~/.claude/projects``):
    the live tail reads only under it. ``brain_changes`` opens the learning decisions' hub pull
    requests (default: ``git`` and ``gh`` through ``hub_git``). The tickets route reads Linear
    with ``LINEAR_API_KEY`` from ``environ`` (default this process's environment, read at call
    time) through ``linear_post`` (default ``urllib``), or ``tracker_reader`` when given (tests).
    The agent sessions run on ``session_driver`` and ``cloud_launcher`` (default
    ``claude_adapters`` over ``environ``); none is built when ``settings.sessions_off``.
    ``DatabaseAccessError`` when the store cannot be opened.
    """
    store = open_event_store(settings.db_path)
    counters = IngestionCounters(clock=settings.clock)
    tail = TranscriptTail(projects_root or default_projects_root())
    ingest = IngestHook(store, ClaudeHookMapper(), tail, status=counters)
    hub_paths = _HubPaths()
    reader = HubFileSystem() if read_git is None else HubFileSystem(read_git=read_git)
    registry = JsonHubRegistry(settings.registry_path)
    facts = RegisteredHubFacts(
        registry=registry,
        reader=reader,
        running_version=settings.running_version,
        read_git=_files_only if read_git is None else read_git,
    )
    sessions = _agent_sessions(
        settings,
        registry=registry,
        reader=reader,
        environ=environ,
        session_driver=session_driver,
        cloud_launcher=cloud_launcher,
    )
    events = _event_read_models(
        store,
        settings,
        hub_paths=hub_paths,
        label_rules_of=facts.label_rules_of,
        sessions=sessions,
    )
    snapshots = ticket_snapshots(
        facts,
        environ=environ,
        linear_post=linear_post,
        tracker_reader=tracker_reader,
        clock=settings.clock,
    )
    hubs = hub_read_models(
        settings,
        registry=registry,
        reader=reader,
        activity=events,
        usage=events,
        ticket_snapshots=snapshots,
    )
    hub_paths.hubs = hubs
    changes = default_brain_changes() if brain_changes is None else brain_changes
    learning_reads = ReadLearnings(
        events, reader, hub_of=facts.hub_of, availability=CachedAvailability(changes.availability)
    )
    ports = ApiPorts(
        event_read_models=events,
        hub_read_models=hubs,
        ingest_hook=ingest,
        event_reader=store,
        change_feed=ChangeFeed(store, timer=SystemTimer(settings.clock)),
        counters=counters,
        learning_reads=learning_reads,
        learning_decisions=DecideLearning(
            learning_reads,
            IngestEvents(store),
            changes,
            hub_of=facts.hub_of,
            today=settings.clock,
        ),
        agent_sessions=None if sessions is None else sessions.control,
        cloud_sessions=None if sessions is None else sessions.cloud,
        agent_session_links=None if sessions is None else sessions.links,
        workflow_reads=ReadWorkflows(hubs, workflow_source_of),
    )
    return create_app(
        settings,
        ports=ports,
        problems=COMPOSED_PROBLEMS,
        web_dist=web_dist,
        lifecycle=None if sessions is None else sessions.runtime,
    )


def _agent_sessions(  # noqa: PLR0913 -- build_app's session options, passed on
    settings: ApiSettings,
    *,
    registry: HubRegistry,
    reader: HubFileReader,
    environ: Mapping[str, str] | None,
    session_driver: SessionDriver | None,
    cloud_launcher: CloudLauncher | None,
) -> AgentSessionWiring | None:
    if settings.sessions_off:
        return None
    env: Mapping[str, str] = os.environ if environ is None else environ
    if session_driver is None or cloud_launcher is None:
        driver, launcher = claude_adapters(env)
        session_driver = session_driver or driver
        cloud_launcher = cloud_launcher or launcher
    return wire_agent_sessions(
        settings,
        store=open_agent_session_store(settings.db_path),
        workdirs=RegisteredWorkdirs(
            registry=registry, reader=reader, running_version=settings.running_version
        ),
        driver=session_driver,
        launcher=cloud_launcher,
        url=web_url(settings),
    )
