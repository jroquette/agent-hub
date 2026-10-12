"""``build_app``: the API as ``hub web`` serves it, wired to the real adapters.

The event store at ``settings.db_path`` (opened and upgraded here), the hook mapper and live
transcript tail of the collector, the hub registry at ``settings.registry_path`` and the hubs'
files read as ``hub doctor`` reads them, the read models folded on request, and the change feed
the streams wait on. Git stays with the caller (the CLI): ``read_git`` makes the git config
reader of one hub folder, so the branch prefix the doctor reports matches ``hub doctor``.
"""

from collections.abc import Mapping
from pathlib import Path

from fastapi import FastAPI

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
from agent_hub.api.settings import ApiSettings
from agent_hub.api.static_files import WEB_DIST
from agent_hub.collector.claude_hooks import ClaudeHookMapper
from agent_hub.collector.transcript_tail import TranscriptTail
from agent_hub.core.hubs.hub_read_models import HubFilesReadModels
from agent_hub.core.hubs.hub_registry import HubConflictError, HubInvalidError, HubRegistryError
from agent_hub.core.ingestion.ingest_hook import IngestHook
from agent_hub.core.ingestion.ingestion_status import IngestionCounters
from agent_hub.core.readmodels.cursor import InvalidCursorError
from agent_hub.core.readmodels.event_read_models import FoldedEventReadModels
from agent_hub.core.readmodels.read_ports import EntityNotFoundError, HubReadModels
from agent_hub.core.readmodels.settings_view import SettingsView
from agent_hub.core.redaction.redact import KINDS as REDACTION_KINDS
from agent_hub.core.sessions.pricing import PRICES, PRICES_AS_OF
from agent_hub.generator.registered_hub_files import GitReaderFactory, HubFileSystem
from agent_hub.storage.event_store import DatabaseBusyError, open_event_store
from agent_hub.storage.hub_registry import JsonHubRegistry

# The errors of the wired adapters, each answered by its problem (API.md "Error mapping").
COMPOSED_PROBLEMS: Mapping[type[Exception], ProblemFactory] = {
    DatabaseBusyError: busy_problem,
    InvalidCursorError: invalid_cursor_problem,
    HubInvalidError: hub_invalid_problem,
    HubConflictError: hub_conflict_problem,
    HubRegistryError: hub_registry_problem,
}


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


def build_app(
    settings: ApiSettings,
    *,
    projects_root: Path | None = None,
    read_git: GitReaderFactory | None = None,
    web_dist: Path = WEB_DIST,
) -> FastAPI:
    """The app of ``hub web``: every Phase 2 route wired to the real adapters.

    ``projects_root`` is Claude Code's transcripts folder (default ``~/.claude/projects``):
    the live tail reads only under it. ``DatabaseAccessError`` when the store cannot be opened.
    """
    store = open_event_store(settings.db_path)
    counters = IngestionCounters(clock=settings.clock)
    tail = TranscriptTail(projects_root or default_projects_root())
    ingest = IngestHook(store, ClaudeHookMapper(), tail, status=counters)
    hub_paths = _HubPaths()
    events = FoldedEventReadModels(store, now=settings.clock, hub_path_of=hub_paths, prices=PRICES)
    reader = HubFileSystem() if read_git is None else HubFileSystem(read_git=read_git)
    hubs = HubFilesReadModels(
        registry=JsonHubRegistry(settings.registry_path),
        reader=reader,
        activity=events,
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
    )
    hub_paths.hubs = hubs
    ports = ApiPorts(
        event_read_models=events,
        hub_read_models=hubs,
        ingest_hook=ingest,
        event_reader=store,
        change_feed=ChangeFeed(store, timer=SystemTimer(settings.clock)),
        counters=counters,
    )
    return create_app(settings, ports=ports, problems=COMPOSED_PROBLEMS, web_dist=web_dist)
