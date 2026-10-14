"""``HubReadModels`` over the hub registry and the registered hubs' files (D18, D22, D23).

Each read lists the registry and reads the hubs it needs now, so a file edited in a hub shows on
the next request; only the doctor is cached (``DoctorCache``). A project is a registered hub
whose ``hub.json`` is valid (any pin, Q4), named by ``project.name``; when two hubs name the same
project the first registered wins. A project's event-derived numbers come from ``activity``
(``EventReadModels.project_activity``). An unknown project or feature raises
``EntityNotFoundError``; a list scoped to an unknown project is empty.

A project's Skills tab (AGH-164) is read through ``SkillReads``, with usage from ``usage``
(``EventReadModels.skill_usage``; zero without it).

A feature's tickets come from ``ticket_snapshots`` (AGH-136): only ``feature_tickets`` fetches
(the one read that may call the tracker); the Features list and the detail use what the cache
holds (Q6), so the list, the detail and the Tickets view fold the same snapshot. Without
``ticket_snapshots`` every feature is served from the plan, not connected.
"""

from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Final, Protocol

from agent_hub.core.brain.brain_note import (
    BrainEntry,
    BrainNote,
    BrainNoteNotFoundError,
    BrainNoteTooLargeError,
    BrainTree,
)
from agent_hub.core.brain.brain_path import (
    MAX_NOTE_BYTES,
    NOTE_SUFFIX,
    BrainPathError,
    brain_relative,
    is_personal_folder,
)
from agent_hub.core.brain.frontmatter import split_frontmatter
from agent_hub.core.doctor.finding import Finding
from agent_hub.core.doctor.lock_rules import NOT_ADOPTED
from agent_hub.core.events.event import EventSource
from agent_hub.core.features.feature_status import (
    FeatureFolder,
    feature_detail,
    feature_view,
    ticket_ids,
)
from agent_hub.core.features.feature_tickets import NOT_CONNECTED_READ, feature_tickets
from agent_hub.core.features.feature_view import FeatureDetail, FeatureView
from agent_hub.core.features.ticket_snapshots import (
    SnapshotRead,
    SnapshotRequest,
    TicketSnapshots,
)
from agent_hub.core.features.ticket_view import FeatureTickets
from agent_hub.core.hub_config.doctor_rules import LOCK_DRIFT_RULE, Severity
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hubs.doctor_cache import DoctorCache
from agent_hub.core.hubs.finding_view import FindingView
from agent_hub.core.hubs.hub_document import HubDocument
from agent_hub.core.hubs.hub_registry import HubFileReader, HubRegistry, UnreadHubFile
from agent_hub.core.hubs.list_hubs import HubRead, ListHubs, module_ids
from agent_hub.core.hubs.now_note import now_sections
from agent_hub.core.hubs.register_hub import RegisterHub
from agent_hub.core.hubs.registered_hub import HubView
from agent_hub.core.hubs.remove_hub import RemoveHub
from agent_hub.core.projects.project_views import (
    HubHealth,
    ProjectActivity,
    ProjectDetail,
    ProjectNow,
    ProjectSummary,
    RepoView,
    TrackerView,
)
from agent_hub.core.readmodels.filters import Scope
from agent_hub.core.readmodels.page import Page
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.readmodels.settings_view import SettingsView
from agent_hub.core.skills.skill_reads import SkillReads, SkillUsageSource
from agent_hub.core.skills.skill_view import (
    BundledFileText,
    ItemKind,
    SkillCatalog,
    SkillDetail,
)

NOW_PATH: Final = "brain/now.md"
# Portfolio cards and repos need sources not connected in Phase 2.
_CARD_SOURCES_MISSING: Final = (EventSource.GITHUB, EventSource.LINEAR)


class ProjectActivitySource(Protocol):
    """Where a project's event-derived numbers come from (``EventReadModels``)."""

    def project_activity(self, project: str) -> ProjectActivity:
        """The event-derived numbers of one project."""
        ...


class _Project:
    """A valid registered hub: its read and its config."""

    def __init__(self, read: HubRead, config: HubConfig) -> None:
        self.read = read
        self.config = config

    @property
    def name(self) -> str:
        return self.config.project.name

    @property
    def path(self) -> str:
        return self.read.entry.path


class HubFilesReadModels:
    """The hub reads of the control plane (``HubReadModels``)."""

    def __init__(
        self,
        *,
        registry: HubRegistry,
        reader: HubFileReader,
        activity: ProjectActivitySource,
        running_version: str,
        settings: SettingsView,
        clock: Callable[[], datetime],
        ticket_snapshots: TicketSnapshots | None = None,
        usage: SkillUsageSource | None = None,
    ) -> None:
        self._reader = reader
        self._skills = SkillReads(reader, usage)
        self._snapshots = ticket_snapshots
        self._activity = activity
        self._settings = settings
        self._doctor = DoctorCache(reader, running_version=running_version, clock=clock)
        self._hubs = ListHubs(
            registry, reader, running_version=running_version, has_drift=self._has_drift
        )
        self._register = RegisterHub(
            registry, reader, running_version=running_version, has_drift=self._has_drift
        )
        self._remove = RemoveHub(registry)

    def list_hubs(self) -> Page[HubView]:
        """Every registered hub, valid or not."""
        return _page(tuple(read.view for read in self._hubs()))

    def register_hub(self, path: str) -> HubView:
        """Register the hub at ``path``."""
        return self._register(path)

    def remove_hub(self, hub_id: str) -> None:
        """Forget a hub; its events stay in the store."""
        self._remove(hub_id)

    def list_projects(self) -> Page[ProjectSummary]:
        """A Portfolio card per project."""
        return _page(tuple(self._card(project) for project in self._projects()))

    def get_project(self, project: str) -> ProjectDetail:
        """The Project overview header."""
        found = self._project(project)
        config, view = found.config, found.read.view
        return ProjectDetail(
            name=found.name,
            hub_id=view.id,
            hub_path=found.path,
            hub_repo=config.project.hub_repo,
            tracker=TrackerView(
                kind=config.tracker.kind,
                teams=config.tracker.team_keys,
                ready_label=config.tracker.ready_label,
                failed_label=config.tracker.failed_label,
            ),
            default_branch=config.project.default_branch,
            branch_prefix=config.project.branch_prefix,
            platform_version=config.platform.version,
            lock_version=view.lock_version,
            lock_state=view.lock_state,
            modules=module_ids(config),
            warnings=view.warnings,
        )

    def project_now(self, project: str) -> ProjectNow:
        """The project's ``brain/now.md``."""
        found = self._project(project)
        read = self._reader.read_now(found.path)
        if isinstance(read, UnreadHubFile):
            problem = None if read.is_missing else read.message
            return ProjectNow(
                project=project, focus=(), next=(), watch=(), source_path=None, problem=problem
            )
        focus, next_items, watch = now_sections(read)
        return ProjectNow(
            project=project, focus=focus, next=next_items, watch=watch, source_path=NOW_PATH
        )

    def project_repos(self, project: str) -> Page[RepoView]:
        """The project's repos and their checkouts' ``AGENTS.md``."""
        found = self._project(project)
        return _page(tuple(self._repo(found, index) for index in range(len(found.config.repos))))

    def list_features(self, scope: Scope) -> Page[FeatureView]:
        """Feature folders of every scoped project."""
        return _page(
            tuple(
                feature_view(folder, project=found.name, read=self._cached(found, folder))
                for found in self._scoped(scope)
                for folder in self._reader.feature_folders(found.path)
            )
        )

    def get_feature(self, project: str, slug: str) -> FeatureDetail:
        """One feature with its acceptance criteria; an unknown project is an unknown feature."""
        found, folder = self._feature(project, slug)
        return feature_detail(folder, project=found.name, read=self._cached(found, folder))

    def feature_tickets(self, project: str, slug: str) -> FeatureTickets:
        """One feature's tickets, planning and golden path: the only read that may call the
        tracker (through ``ticket_snapshots.fetch``, cached)."""
        found, folder = self._feature(project, slug)
        tracker = found.config.tracker
        read = NOT_CONNECTED_READ
        if self._snapshots is not None:
            read = self._snapshots.fetch(_ticket_request(found, folder))
        return feature_tickets(folder, read, project=found.name, tracker=tracker)

    def doctor_findings(self, scope: Scope) -> Page[FindingView]:
        """Doctor findings of every scoped hub that names its project, in ``hub doctor`` order.

        A scope whose project no readable hub names (its ``hub.json`` became unreadable, or no
        hub has it) is ``EntityNotFoundError``: an empty list would read as a clean doctor run.
        """
        hubs = tuple(self._doctor_hubs(scope))
        if scope.project is not None and not hubs:
            raise EntityNotFoundError(entity="project", entity_id=scope.project)
        return _page(
            tuple(
                _finding_view(project, finding)
                for project, hub_path in hubs
                for finding in self._doctor.findings(hub_path)
            )
        )

    def settings(self) -> SettingsView:
        """The running server's settings."""
        return self._settings

    def brain_tree(self, project: str) -> BrainTree:
        """The ``.md`` notes of the project's hub brain, sorted by path.

        ``auto/`` and hidden names are dropped here too, whatever the reader listed (L7).
        """
        found = self._project(project)
        listing = self._reader.brain_tree(found.path)
        entries = sorted(
            (entry for entry in listing.entries if _listable(entry)), key=lambda e: e.path
        )
        return BrainTree(
            project=found.name,
            entries=tuple(entries),
            truncated=listing.truncated,
            skipped=listing.skipped,
        )

    def brain_note(self, project: str, path: str) -> BrainNote:
        """One note of the project's hub brain, its frontmatter split from its body.

        The path is checked before any read (``BrainPathError``); a path under ``auto/`` is
        ``BrainNoteNotFoundError`` like a missing note, a link or a non-regular file, so a
        response never tells whether it exists (L7); a note over ``MAX_NOTE_BYTES`` is
        ``BrainNoteTooLargeError``. Bytes are decoded as UTF-8, invalid ones replaced.
        """
        missing = BrainNoteNotFoundError(project=project, path=path)
        try:
            relative = str(brain_relative(path))
        except BrainPathError:
            if is_personal_folder(path.split("/", 1)[0]):
                raise missing from None
            raise
        found = self._project(project)
        read = self._reader.read_brain_file(found.path, relative, max_bytes=MAX_NOTE_BYTES)
        if isinstance(read, UnreadHubFile):
            if read.kind == "too_large":
                size = self._reader.brain_file_size(found.path, relative)
                raise BrainNoteTooLargeError(
                    project=project,
                    path=path,
                    size=MAX_NOTE_BYTES + 1 if size is None else size,
                    limit=MAX_NOTE_BYTES,
                )
            raise missing
        split = split_frontmatter(read.decode("utf-8", "replace"))
        return BrainNote(
            project=found.name,
            path=relative,
            frontmatter=split.fields,
            frontmatter_problem=split.problem,
            markdown=split.body,
            size=len(read),
        )

    def skill_catalog(self, project: str) -> SkillCatalog:
        """The project's skills, agents and hooks with their usage (``SkillReads``)."""
        found = self._project(project)
        return self._skills.catalog(project=found.name, hub_path=found.path)

    def skill_detail(self, project: str, *, kind: ItemKind, source: str, name: str) -> SkillDetail:
        """One item of the catalog by its id; ``EntityNotFoundError`` (``skill``) when unknown."""
        found = self._project(project)
        return self._skills.detail(
            project=found.name, hub_path=found.path, kind=kind, source=source, name=name
        )

    def skill_file(
        self, project: str, *, kind: ItemKind, source: str, name: str, file_id: str
    ) -> BundledFileText:
        """One bundled file of a skill by its issued id (``skill file`` when unknown, 413 over
        the cap)."""
        found = self._project(project)
        return self._skills.file(
            project=found.name,
            hub_path=found.path,
            kind=kind,
            source=source,
            name=name,
            file_id=file_id,
        )

    def _feature(self, project: str, slug: str) -> tuple[_Project, FeatureFolder]:
        missing = EntityNotFoundError(entity="feature", entity_id=f"{project}/{slug}")
        try:
            found = self._project(project)
        except EntityNotFoundError:
            raise missing from None
        folder = self._reader.feature_folder(found.path, slug)
        if folder is None:
            raise missing
        return found, folder

    def _cached(self, found: _Project, folder: FeatureFolder) -> SnapshotRead | None:
        """What the snapshot cache holds for the feature's tickets; never reads the tracker."""
        if self._snapshots is None:
            return None
        return self._snapshots.cached(_ticket_request(found, folder))

    def _has_drift(self, hub_path: str, document: HubDocument) -> bool:
        del document
        return any(
            finding.rule == LOCK_DRIFT_RULE and finding.message != NOT_ADOPTED
            for finding in self._doctor.findings(hub_path)
        )

    def _projects(self) -> Iterator[_Project]:
        seen: set[str] = set()
        for read in self._hubs():
            config = read.document.config
            if config is not None and config.project.name not in seen:
                seen.add(config.project.name)
                yield _Project(read, config)

    def _project(self, name: str) -> _Project:
        for found in self._projects():
            if found.name == name:
                return found
        raise EntityNotFoundError(entity="project", entity_id=name)

    def _scoped(self, scope: Scope) -> Iterator[_Project]:
        return (found for found in self._projects() if scope.project in {None, found.name})

    def _doctor_hubs(self, scope: Scope) -> Iterator[tuple[str, str]]:
        seen: set[str] = set()
        for read in self._hubs():
            project = read.document.project
            if project is None or project in seen or scope.project not in {None, project}:
                continue
            seen.add(project)
            yield project, read.entry.path

    def _card(self, found: _Project) -> ProjectSummary:
        activity = self._activity.project_activity(found.name)
        view = found.read.view
        return ProjectSummary(
            name=found.name,
            hub_id=view.id,
            hub_repo=found.config.project.hub_repo,
            tracker_teams=found.config.tracker.team_keys,
            platform_version=found.config.platform.version,
            lock_version=view.lock_version,
            lock_state=view.lock_state,
            repos=view.repos,
            hub_health=_health(self._doctor.findings(found.path)),
            live_sessions=activity.live_sessions,
            runs_in_flight_by_stage=activity.runs_in_flight_by_stage,
            failed_runs_7d=activity.failed_runs_7d,
            cost_period=activity.cost_period,
            cost_previous_period=activity.cost_previous_period,
            cost_daily=activity.cost_daily,
            sources_missing=tuple(
                dict.fromkeys((*activity.sources_missing, *_CARD_SOURCES_MISSING))
            ),
        )

    def _repo(self, found: _Project, index: int) -> RepoView:
        repo = found.config.repos[index]
        lines = self._reader.agents_md_lines(found.path, repo.dir)
        return RepoView(
            name=repo.dir,
            dir=repo.dir,
            github=repo.github,
            role=repo.role,
            default_branch=found.config.default_branch_for(repo.dir),
            check_fast=repo.check_fast or "",
            check=repo.check,
            agents_md_present=lines is not None,
            agents_md_lines=lines,
            sources_missing=(EventSource.GITHUB,),
        )


def _ticket_request(found: _Project, folder: FeatureFolder) -> SnapshotRequest:
    return SnapshotRequest.of(
        project=found.name, transport=found.config.tracker.transport, ids=ticket_ids(folder)
    )


def _listable(entry: BrainEntry) -> bool:
    segments = entry.path.split("/")
    return (
        entry.path.endswith(NOTE_SUFFIX)
        and not is_personal_folder(segments[0])
        and not any(segment.startswith(".") or not segment for segment in segments)
    )


def _health(findings: tuple[Finding, ...]) -> HubHealth:
    severities = {finding.severity for finding in findings}
    if Severity.ERROR in severities:
        return "error"
    return "warning" if Severity.WARNING in severities else "ok"


def _finding_view(project: str, finding: Finding) -> FindingView:
    return FindingView(
        project=project,
        rule=finding.rule,
        severity=finding.severity,
        path=None if finding.path is None else _encodable(finding.path),
        line=finding.line,
        message=_encodable(finding.message),
        fix=_encodable(finding.fix),
    )


def _encodable(text: str) -> str:
    """``text`` with each lone surrogate as its ``\\udcff`` escape, as ``hub doctor --json``."""
    return text.encode("utf-8", "backslashreplace").decode("utf-8")


def _page[T](items: tuple[T, ...]) -> Page[T]:
    return Page[T](items=items, next_cursor=None, total_estimate=len(items))
