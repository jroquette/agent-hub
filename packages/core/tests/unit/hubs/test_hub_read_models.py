import hashlib
import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from agent_hub.core.brain.brain_note import (
    BrainEntry,
    BrainNoteNotFoundError,
    BrainNoteTooLargeError,
)
from agent_hub.core.brain.brain_path import MAX_NOTE_BYTES, BrainPathError
from agent_hub.core.doctor.snapshot import DoctorSnapshot, LockAbsent, LockState
from agent_hub.core.events.event import EventSource
from agent_hub.core.features.feature_status import FeatureFolder, RecordHead
from agent_hub.core.features.feature_tickets import NOT_CONNECTED_NOTICE
from agent_hub.core.features.ticket_snapshots import SnapshotRequest, TicketSnapshots
from agent_hub.core.hub_config.doctor_rules import LOCK_DRIFT_RULE, Severity
from agent_hub.core.hub_files.hub_lock import HubLock, ManagedFileEntry
from agent_hub.core.hubs.hub_read_models import HubFilesReadModels
from agent_hub.core.hubs.hub_registry import (
    BrainListing,
    HubConflictError,
    HubInvalidError,
    UnreadHubFile,
)
from agent_hub.core.hubs.registered_hub import RegisteredHub
from agent_hub.core.item_versions.capture_item_versions import CaptureItemVersions
from agent_hub.core.projects.project_views import ProjectActivity
from agent_hub.core.readmodels.filters import Scope
from agent_hub.core.readmodels.read_ports import EntityNotFoundError, HubReadModels
from agent_hub.core.readmodels.settings_view import SettingsView
from agent_hub.core.runner.run_record import Stage
from agent_hub.core.skills.skill_view import ItemKind, SkillUsage, UsageWindows
from agent_hub.core.testing.hub_fakes import (
    FakeHub,
    FakeHubFileReader,
    InMemoryHubRegistry,
    hub_json_bytes,
)
from agent_hub.core.testing.item_version_fakes import InMemoryItemVersionStore
from agent_hub.core.testing.read_model_builders import a_skill_usage
from agent_hub.core.testing.skill_trees import a_skills_fixture_tree, fake_hub_of
from agent_hub.core.testing.tracker_reader_fakes import (
    CountingTrackerReader,
    InMemoryTicketSnapshots,
    InMemoryTrackerReader,
    a_seeded_issue_board,
)

RUNNING = "4.5.6"
DEMO = "/hubs/demo-hub"
OTHER = "/hubs/other-hub"
NOW = datetime(2026, 10, 9, 14, 0, tzinfo=UTC)
SETTINGS = SettingsView(
    db_path="/data/agent-hub.db",
    registry_path="/config/hubs.json",
    port=7420,
    running_version=RUNNING,
    redaction_kinds=("github token",),
    prices_as_of=date(2026, 10, 11),
)
SPEC = b"---\nprocess_size: bounded\nlinear: [DEM-7]\n---\n"
NOW_NOTE = b"---\nlast_verified: 2026-10-09\n---\n- **Focus:** Ship it.\n"
DECISIONS = b"---\ntype: decision-log\ntags: [a, b]\n---\n# Decisions\n"


class FakeActivity:
    def __init__(self) -> None:
        self.asked: list[str] = []

    def project_activity(self, project: str) -> ProjectActivity:
        self.asked.append(project)
        return ProjectActivity(
            project=project,
            live_sessions=2,
            runs_in_flight_by_stage={Stage.IMPLEMENTING: 1},
            failed_runs_7d=1,
            cost_period=Decimal("1.5"),
            cost_previous_period=None,
            last_activity_at=NOW,
            sources_missing=(EventSource.OTEL,),
        )


def a_lock(*, sha: str = "0" * 64) -> HubLock:
    return HubLock(
        lock_version=1,
        platform_version=RUNNING,
        schema_version=1,
        modules=("bench", "cloud"),
        files={"AGENTS.md": ManagedFileEntry(ownership="managed", sha256=sha, executable=False)},
    )


def a_demo_hub() -> FakeHub:
    return FakeHub(
        hub_json=hub_json_bytes(pin=RUNNING),
        lock=LockAbsent(),
        files={"AGENTS.md": b"# Demo\n"},
        now=NOW_NOTE,
        agents_md_lines={"demo-api": 42},
        features=(
            FeatureFolder(
                slug="demo-feature",
                files=("spec.md", "features.json"),
                features_json=b'{"acs": [{"id": "AC-7.1", "description": "d", "passes": true}]}',
                spec_head=SPEC,
            ),
            FeatureFolder(slug="broken", files=("features.json",), features_json=b"{"),
        ),
    )


def read_models(
    hubs: dict[str, FakeHub], *paths: str, ticket_snapshots: TicketSnapshots | None = None
) -> tuple[HubFilesReadModels, FakeHubFileReader, FakeActivity]:
    registry = InMemoryHubRegistry(clock=lambda: NOW)
    for path in paths:
        registry.add(path)
    reader = FakeHubFileReader(hubs)
    activity = FakeActivity()
    models = HubFilesReadModels(
        registry=registry,
        reader=reader,
        activity=activity,
        running_version=RUNNING,
        settings=SETTINGS,
        clock=lambda: NOW,
        ticket_snapshots=ticket_snapshots,
    )
    return models, reader, activity


def test_implements_hub_read_models_port_when_built() -> None:
    models, _, _ = read_models({})

    port: HubReadModels = models

    assert port.settings() == SETTINGS


def test_lists_hubs_valid_or_not_when_registered() -> None:
    models, _, _ = read_models({DEMO: a_demo_hub()}, DEMO, OTHER)

    page = models.list_hubs()

    assert page.total_estimate == 2
    assert page.next_cursor is None
    assert [(hub.path, hub.valid) for hub in page.items] == [(DEMO, True), (OTHER, False)]
    assert page.items[0].lock_state == "not_adopted"


def test_names_drift_when_doctor_finds_lock_drift() -> None:
    hub = a_demo_hub()
    hub.lock = a_lock()
    models, _, _ = read_models({DEMO: hub}, DEMO)
    models.refresh()

    [view] = models.list_hubs().items

    assert view.lock_state == "drift"
    rules = {finding.rule for finding in models.doctor_findings(Scope()).items}
    assert LOCK_DRIFT_RULE in rules


def test_registers_and_removes_hub_when_asked() -> None:
    models, _, _ = read_models({DEMO: a_demo_hub()})

    view = models.register_hub(DEMO)
    models.remove_hub(view.id)

    assert view.project == "demo"
    assert models.list_hubs().items == ()


def test_refuses_registration_when_invalid_or_conflicting() -> None:
    models, _, _ = read_models({DEMO: a_demo_hub(), OTHER: a_demo_hub()}, DEMO)

    with pytest.raises(HubInvalidError):
        models.register_hub("/hubs/empty")
    with pytest.raises(HubConflictError):
        models.register_hub(OTHER)


def test_cards_valid_projects_with_activity_when_listed() -> None:
    models, _, activity = read_models({DEMO: a_demo_hub()}, DEMO, OTHER)
    models.refresh()

    [card] = models.list_projects().items

    assert card.name == "demo"
    assert card.hub_repo == "acme/demo-hub"
    assert card.tracker_teams == ("DEM",)
    assert card.platform_version == RUNNING
    assert card.repos == ("demo-api",)
    assert card.hub_health == "warning"
    assert card.live_sessions == 2
    assert card.cost_period == Decimal("1.5")
    assert set(card.sources_missing) == {EventSource.OTEL, EventSource.GITHUB, EventSource.LINEAR}
    assert activity.asked == ["demo"]


def test_lists_project_hubs_when_valid_hubs_registered() -> None:
    models, _, _ = read_models({DEMO: a_demo_hub(), OTHER: a_demo_hub()}, DEMO, OTHER)

    assert list(models.project_hubs()) == [("demo", DEMO)]


def test_yields_each_project_config_once_when_scheduled_hubs_read() -> None:
    models, reader, _ = read_models({DEMO: a_demo_hub(), OTHER: a_demo_hub()}, DEMO, OTHER)

    [hub] = list(models.scheduled_hubs())

    assert (hub.project, hub.hub_path, hub.config.project.name) == ("demo", DEMO, "demo")
    assert reader.snapshots == {}


# AGH-429 (AC-429.5): hub paths never run the doctor.
def test_lists_project_hubs_without_running_doctor_when_lock_matches_pin() -> None:
    hub = a_demo_hub()
    hub.lock = a_lock()
    models, reader, _ = read_models({DEMO: hub}, DEMO)

    hubs = list(models.project_hubs())

    assert hubs == [("demo", DEMO)]
    assert reader.snapshots == {}
    models.refresh()
    assert models.get_project("demo").lock_state == "drift"
    assert reader.snapshots == {DEMO: 1}


def test_details_project_when_known() -> None:
    hub = a_demo_hub()
    hub.hub_json = hub_json_bytes(pin="0.1.0")
    models, _, _ = read_models({DEMO: hub}, DEMO)

    detail = models.get_project("demo")

    assert detail.hub_path == DEMO
    assert detail.tracker.teams == ("DEM",)
    assert detail.default_branch == "main"
    assert detail.platform_version == "0.1.0"
    assert detail.warnings == (f"pinned 0.1.0, running {RUNNING}",)


@pytest.mark.parametrize(
    "read",
    [
        lambda models: models.get_project("nope"),
        lambda models: models.project_now("nope"),
        lambda models: models.project_repos("nope"),
        lambda models: models.get_feature("nope", "demo-feature"),
        lambda models: models.get_feature("demo", "nope"),
        lambda models: models.ux_mockup("nope", "demo-feature", "ux-new-a.html"),
    ],
    ids=["project", "now", "repos", "feature-project", "feature-slug", "mockup-project"],
)
def test_raises_not_found_when_project_or_feature_unknown(read: object) -> None:
    models, _, _ = read_models({DEMO: a_demo_hub()}, DEMO)

    assert callable(read)
    with pytest.raises(EntityNotFoundError):
        read(models)


def test_names_feature_id_when_feature_project_unknown() -> None:
    models, _, _ = read_models({DEMO: a_demo_hub()}, DEMO)

    with pytest.raises(EntityNotFoundError) as raised:
        models.get_feature("nope", "demo-feature")

    assert (raised.value.entity, raised.value.entity_id) == ("feature", "nope/demo-feature")


MOCKUP = b"<style>p{color:red}</style><p>Sidebar \xc3\xa9</p>"


def test_serves_ux_mockup_when_html_beside_design() -> None:
    hub = a_demo_hub()
    hub.brain["features/demo-feature/ux-new-a.html"] = MOCKUP
    models, _, _ = read_models({DEMO: hub}, DEMO)

    mockup = models.ux_mockup("demo", "demo-feature", "ux-new-a.html")

    assert (mockup.project, mockup.slug, mockup.name) == ("demo", "demo-feature", "ux-new-a.html")
    assert mockup.html == MOCKUP.decode("utf-8")
    assert mockup.size == len(MOCKUP)
    assert mockup.sha256 == hashlib.sha256(MOCKUP).hexdigest()


@pytest.mark.parametrize("name", ["spec.md", "../x.html", "ux-a.md", "x.html"])
def test_refuses_ux_mockup_name_before_any_read_when_not_a_mockup(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    models, reader, _ = read_models({DEMO: a_demo_hub()}, DEMO)
    reads: list[str] = []
    monkeypatch.setattr(
        reader, "read_feature_mockup", lambda *args, **kwargs: reads.append(str(args))
    )

    with pytest.raises(EntityNotFoundError):
        models.ux_mockup("demo", "demo-feature", name)

    assert reads == []


@pytest.mark.parametrize(
    "unread",
    [
        None,
        UnreadHubFile(message="cannot read: over 1048576 bytes", is_missing=False),
    ],
    ids=["missing", "unreadable"],
)
def test_names_mockup_id_when_mockup_unread(
    unread: UnreadHubFile | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    models, reader, _ = read_models({DEMO: a_demo_hub()}, DEMO)
    if unread is not None:
        monkeypatch.setattr(reader, "read_feature_mockup", lambda *args, **kwargs: unread)

    with pytest.raises(EntityNotFoundError) as raised:
        models.ux_mockup("demo", "demo-feature", "ux-new-a.html")

    assert (raised.value.entity, raised.value.entity_id) == (
        "ux mockup",
        "demo/demo-feature/ux-new-a.html",
    )


def test_reads_now_note_when_present() -> None:
    models, _, _ = read_models({DEMO: a_demo_hub()}, DEMO)

    now = models.project_now("demo")

    assert [item.text for item in now.focus] == ["Ship it."]
    assert now.source_path == "brain/now.md"
    assert now.problem is None


def test_reports_now_problem_when_note_unreadable() -> None:
    hub = a_demo_hub()
    hub.now = UnreadHubFile(message="cannot read: denied", is_missing=False)
    models, _, _ = read_models({DEMO: hub}, DEMO)

    now = models.project_now("demo")

    assert now.problem == "cannot read: denied"
    assert now.focus == ()


def test_gives_empty_now_when_note_missing() -> None:
    hub = a_demo_hub()
    hub.now = UnreadHubFile(message="cannot read: missing", is_missing=True)
    models, _, _ = read_models({DEMO: hub}, DEMO)

    now = models.project_now("demo")

    assert (now.focus, now.source_path, now.problem) == ((), None, None)


def test_lists_repos_with_agents_md_when_checkout_read() -> None:
    models, _, _ = read_models({DEMO: a_demo_hub()}, DEMO)

    [repo] = models.project_repos("demo").items

    assert (repo.name, repo.dir, repo.github) == ("demo-api", "demo-api", "acme/demo-api")
    assert (repo.agents_md_present, repo.agents_md_lines) == (True, 42)
    assert repo.default_branch == "main"


def test_lists_features_with_problem_when_one_malformed() -> None:
    models, _, _ = read_models({DEMO: a_demo_hub()}, DEMO)

    features = models.list_features(Scope()).items

    assert [(feature.slug, feature.problem is None) for feature in features] == [
        ("demo-feature", True),
        ("broken", False),
    ]
    assert models.list_features(Scope(project="other")).items == ()
    detail = models.get_feature("demo", "demo-feature")
    assert [row.id for row in detail.ac_rows] == ["AC-7.1"]


def test_lists_findings_in_doctor_shape_when_scoped() -> None:
    models, reader, _ = read_models({DEMO: a_demo_hub()}, DEMO, OTHER)
    models.refresh()

    findings = models.doctor_findings(Scope(project="demo")).items
    again = models.doctor_findings(Scope()).items

    assert findings
    assert {finding.project for finding in findings} == {"demo"}
    assert findings[0].severity in set(Severity)
    assert again == findings
    assert reader.snapshots == {DEMO: 1}


def test_answers_null_health_when_never_refreshed() -> None:
    hub = a_demo_hub()
    hub.lock = a_lock()
    models, reader, _ = read_models({DEMO: hub}, DEMO)

    [card] = models.list_projects().items
    detail = models.get_project("demo")
    [view] = models.list_hubs().items
    findings = models.doctor_findings(Scope())

    assert card.hub_health is None
    assert card.checked_at is None
    # A lock matching the pin is named from the doctor's lock.drift: unknown until the check.
    assert (detail.lock_state, detail.checked_at) == (None, None)
    assert (view.lock_state, view.checked_at) == (None, None)
    assert (findings.items, findings.checked_at) == ((), None)
    assert reader.snapshots == {}


def test_carries_checked_at_on_card_detail_hub_and_findings_when_refreshed() -> None:
    models, _, _ = read_models({DEMO: a_demo_hub()}, DEMO)
    models.refresh()

    [card] = models.list_projects().items
    detail = models.get_project("demo")
    [view] = models.list_hubs().items
    findings = models.doctor_findings(Scope(project="demo"))

    # The clock reads NOW throughout, so the run that the refresh made ended at NOW.
    assert (card.checked_at, detail.checked_at, view.checked_at, findings.checked_at) == (
        NOW,
        NOW,
        NOW,
        NOW,
    )


class CountingFiles(FakeHubFileReader):
    """A reader that notes each hub file read and doctor run asked of it."""

    def __init__(self, hubs: dict[str, FakeHub]) -> None:
        super().__init__(hubs)
        self.calls: list[str] = []

    def read_hub_json(self, hub_path: str) -> bytes | UnreadHubFile:
        self.calls.append("read_hub_json")
        return super().read_hub_json(hub_path)

    def read_lock(self, hub_path: str) -> LockState | None:
        self.calls.append("read_lock")
        return super().read_lock(hub_path)

    def modified_times(self, hub_path: str, paths: Sequence[str]) -> tuple[int | None, ...]:
        self.calls.append("modified_times")
        return super().modified_times(hub_path, paths)

    def doctor_snapshot(self, hub_path: str, **kwargs: Any) -> DoctorSnapshot:
        self.calls.append("doctor_snapshot")
        return super().doctor_snapshot(hub_path, **kwargs)


class CountingRegistry(InMemoryHubRegistry):
    """A registry that counts its reads."""

    def __init__(self) -> None:
        super().__init__(clock=lambda: NOW)
        self.reads = 0

    def entries(self) -> tuple[RegisteredHub, ...]:
        self.reads += 1
        return super().entries()


def test_reads_no_hub_file_when_projects_listed_after_refresh() -> None:
    hub = a_demo_hub()
    hub.lock = a_lock()
    registry = CountingRegistry()
    registry.add(DEMO)
    reader = CountingFiles({DEMO: hub})
    models = HubFilesReadModels(
        registry=registry,
        reader=reader,
        activity=FakeActivity(),
        running_version=RUNNING,
        settings=SETTINGS,
        clock=lambda: NOW,
    )
    models.refresh()
    assert {"read_hub_json", "read_lock", "doctor_snapshot"} <= set(reader.calls)
    assert registry.reads > 0
    reader.calls.clear()
    registry.reads = 0

    models.list_projects()
    models.list_hubs()
    models.get_project("demo")
    models.doctor_findings(Scope(project="demo"))
    list(models.project_hubs())

    assert reader.calls == []
    assert registry.reads == 0


def test_raises_not_found_when_scoped_project_has_no_readable_hub() -> None:
    # OTHER is registered but its hub.json cannot be read: no readable hub names "other".
    models, _, _ = read_models({DEMO: a_demo_hub()}, DEMO, OTHER)

    with pytest.raises(EntityNotFoundError) as raised:
        models.doctor_findings(Scope(project="other"))

    assert raised.value.entity_id == "other"


class Clock:
    """The read models' clock: ``NOW`` until the test moves it."""

    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class FailingDoctor(FakeHubFileReader):
    """A reader whose doctor run raises for the hubs in ``failing``."""

    def __init__(self, hubs: dict[str, FakeHub]) -> None:
        super().__init__(hubs)
        self.failing: set[str] = set()

    def doctor_snapshot(self, hub_path: str, **kwargs: Any) -> DoctorSnapshot:
        if hub_path in self.failing:
            msg = "disk gone"
            raise OSError(msg)
        return super().doctor_snapshot(hub_path, **kwargs)


def clocked_read_models(reader: FakeHubFileReader, clock: Clock, *paths: str) -> HubFilesReadModels:
    registry = InMemoryHubRegistry(clock=lambda: NOW)
    for path in paths:
        registry.add(path)
    return HubFilesReadModels(
        registry=registry,
        reader=reader,
        activity=FakeActivity(),
        running_version=RUNNING,
        settings=SETTINGS,
        clock=clock,
    )


def test_dates_findings_by_oldest_check_when_scope_spans_two_hubs() -> None:
    """The unscoped findings' ``checked_at`` is None while one hub that names a project has no
    check, then the older of the two hubs' checks."""
    clock = Clock()
    other = a_demo_hub()
    other.hub_json = hub_json_bytes(pin=RUNNING, name="other")
    reader = FailingDoctor({DEMO: a_demo_hub(), OTHER: other})
    reader.failing.add(OTHER)
    models = clocked_read_models(reader, clock, DEMO, OTHER)
    models.refresh()
    one_checked = {card.name: card.checked_at for card in models.list_projects().items}
    while_unchecked = models.doctor_findings(Scope()).checked_at
    reader.failing.clear()
    # OTHER's failed run is retried at the next tick; DEMO's check is 2 s old, within 10 s.
    clock.now = NOW + timedelta(seconds=2)
    models.refresh()
    both_checked = {card.name: card.checked_at for card in models.list_projects().items}

    findings = models.doctor_findings(Scope())

    assert one_checked == {"demo": NOW, "other": None}
    assert while_unchecked is None
    assert both_checked == {"demo": NOW, "other": NOW + timedelta(seconds=2)}
    assert findings.checked_at == NOW


@pytest.mark.parametrize(
    "paths",
    [
        # The only hub's folder moved: it is listed, but its hub.json cannot be read.
        pytest.param((OTHER,), id="moved-hub"),
        pytest.param((), id="no-hub"),
    ],
)
def test_dates_findings_by_last_refresh_when_no_scoped_hub_names_project(
    paths: tuple[str, ...],
) -> None:
    """With no hub in scope that names a project, the unscoped findings' ``checked_at`` is when
    the snapshot's last refresh ended (None only before the first one), so a screen waiting for
    a check stops waiting."""
    clock = Clock()
    models = clocked_read_models(FakeHubFileReader({}), clock, *paths)
    assert len(models.list_hubs().items) == len(paths)
    assert models.list_projects().items == ()
    never_refreshed = models.doctor_findings(Scope())
    models.refresh()
    first = models.doctor_findings(Scope())
    clock.now = NOW + timedelta(seconds=2)
    models.refresh()

    latest = models.doctor_findings(Scope())

    assert (never_refreshed.items, never_refreshed.checked_at) == ((), None)
    assert (first.items, first.checked_at) == ((), NOW)
    assert (latest.items, latest.checked_at) == ((), NOW + timedelta(seconds=2))


class ListingReader(FakeHubFileReader):
    """A reader whose listing holds what an adapter must never list, unsorted."""

    def brain_tree(self, hub_path: str) -> BrainListing:
        del hub_path
        return BrainListing(
            entries=(
                BrainEntry(path="playbooks/x.md", size=3),
                BrainEntry(path="auto/workspace/me.md", size=1),
                BrainEntry(path=".hidden/x.md", size=1),
                BrainEntry(path="notes.txt", size=1),
                BrainEntry(path="index.md", size=5),
            ),
            truncated=True,
            skipped=2,
        )


def a_brain_hub() -> FakeHub:
    hub = a_demo_hub()
    hub.brain = {
        "index.md": b"# Brain\n",
        "decisions/index.md": DECISIONS,
        "auto/workspace/me.md": b"personal",
        "linked.md": b"# elsewhere\n",
        "big.md": b"x" * (MAX_NOTE_BYTES + 1),
    }
    hub.brain_links = frozenset({"linked.md"})
    return hub


def test_lists_brain_when_hub_registered() -> None:
    models, _, _ = read_models({DEMO: a_brain_hub()}, DEMO)

    tree = models.brain_tree("demo")

    assert tree.project == "demo"
    assert [entry.path for entry in tree.entries] == ["big.md", "decisions/index.md", "index.md"]
    assert (tree.truncated, tree.skipped) == (False, 0)


def test_excludes_auto_and_sorts_when_reader_lists_them() -> None:
    registry = InMemoryHubRegistry(clock=lambda: NOW)
    registry.add(DEMO)
    models = HubFilesReadModels(
        registry=registry,
        reader=ListingReader({DEMO: a_demo_hub()}),
        activity=FakeActivity(),
        running_version=RUNNING,
        settings=SETTINGS,
        clock=lambda: NOW,
    )

    tree = models.brain_tree("demo")

    assert [entry.path for entry in tree.entries] == ["index.md", "playbooks/x.md"]
    assert (tree.truncated, tree.skipped) == (True, 2)


def test_raises_not_found_when_brain_project_unknown() -> None:
    models, _, _ = read_models({DEMO: a_brain_hub()}, DEMO)

    with pytest.raises(EntityNotFoundError):
        models.brain_tree("nope")
    with pytest.raises(EntityNotFoundError):
        models.brain_note("nope", "index.md")


def test_returns_note_when_path_valid() -> None:
    models, _, _ = read_models({DEMO: a_brain_hub()}, DEMO)

    note = models.brain_note("demo", "decisions/index.md")

    assert (note.project, note.path, note.size) == ("demo", "decisions/index.md", len(DECISIONS))
    assert note.frontmatter == {"type": "decision-log", "tags": ["a", "b"]}
    assert note.frontmatter_problem is None
    assert note.markdown == "# Decisions\n"


def test_returns_hash_of_file_bytes_when_note_read() -> None:
    """AC-269.17."""
    models, _, _ = read_models({DEMO: a_brain_hub()}, DEMO)

    note = models.brain_note("demo", "decisions/index.md")

    assert note.sha256 == hashlib.sha256(DECISIONS).hexdigest()


def test_reports_frontmatter_problem_when_note_frontmatter_unclosed() -> None:
    hub = a_brain_hub()
    hub.brain["open.md"] = b"---\ntype: x\n# no fence\n\xff"
    models, _, _ = read_models({DEMO: hub}, DEMO)

    note = models.brain_note("demo", "open.md")

    assert note.frontmatter == {}
    assert note.frontmatter_problem is not None
    assert note.markdown.startswith("---\ntype: x")
    assert note.markdown.endswith("\ufffd")


@pytest.mark.parametrize("path", ["linked.md", "absent.md", "auto/workspace/me.md", "auto/x.txt"])
def test_raises_not_found_when_note_is_link(path: str) -> None:
    models, _, _ = read_models({DEMO: a_brain_hub()}, DEMO)

    with pytest.raises(BrainNoteNotFoundError) as raised:
        models.brain_note("demo", path)

    assert (raised.value.project, raised.value.path) == ("demo", path)


def test_raises_too_large_when_note_over_cap() -> None:
    models, _, _ = read_models({DEMO: a_brain_hub()}, DEMO)

    with pytest.raises(BrainNoteTooLargeError) as raised:
        models.brain_note("demo", "big.md")

    assert (raised.value.size, raised.value.limit) == (MAX_NOTE_BYTES + 1, MAX_NOTE_BYTES)


@pytest.mark.parametrize("path", ["../hub.json", "/etc/passwd", "x.txt", "a/../../x.md"])
def test_refuses_note_when_path_outside_brain_rules(path: str) -> None:
    models, _, _ = read_models({DEMO: a_brain_hub()}, DEMO)

    with pytest.raises(BrainPathError):
        models.brain_note("demo", path)


def test_lists_records_when_feature_detail_read() -> None:
    models, _, _ = read_models({DEMO: a_demo_hub()}, DEMO)

    detail = models.get_feature("demo", "demo-feature")

    assert [(record.name, record.present) for record in detail.records] == [
        ("spec", True),
        ("research", False),
        ("plan", False),
        ("eval", False),
        ("issues", False),
    ]


TICKET_RECORD = (
    b'{"tickets": [{"key": "T1", "id": "DEM-1", "order": 1},'
    b' {"key": "T2", "id": "DEM-2", "blocked_by": ["T1"], "order": 2}],'
    b' "acs": [{"id": "AC-7.1", "description": "d", "passes": true, "ticket": "T1"}]}'
)


def a_ticket_hub(**tracker: str) -> FakeHub:
    document = json.loads(hub_json_bytes(pin=RUNNING))
    document["tracker"].update(tracker)
    return FakeHub(
        hub_json=json.dumps(document).encode(),
        lock=LockAbsent(),
        features=(
            FeatureFolder(
                slug="ticketed",
                files=("spec.md", "research.md", "plan.md", "features.json"),
                features_json=TICKET_RECORD,
            ),
        ),
    )


TICKET_REQUEST = SnapshotRequest.of(project="demo", transport="api", ids=("DEM-2", "DEM-1"))


def test_fetches_tickets_when_feature_known() -> None:
    counting = CountingTrackerReader(InMemoryTrackerReader(a_seeded_issue_board()))
    snapshots = InMemoryTicketSnapshots(counting)
    models, _, _ = read_models({DEMO: a_ticket_hub()}, DEMO, ticket_snapshots=snapshots)

    tickets = models.feature_tickets("demo", "ticketed")

    assert (tickets.project, tickets.slug, tickets.source, tickets.notice) == (
        "demo",
        "ticketed",
        "linear",
        None,
    )
    assert [(row.ref, row.state is not None) for row in tickets.tickets] == [
        ("DEM-1", True),
        ("DEM-2", True),
    ]
    assert snapshots.calls == [("fetch", TICKET_REQUEST)]
    assert counting.count == 1
    with pytest.raises(EntityNotFoundError):
        models.feature_tickets("demo", "nope")
    with pytest.raises(EntityNotFoundError):
        models.feature_tickets("nope", "ticketed")


def test_serves_plan_when_no_ticket_snapshots_wired() -> None:
    models, _, _ = read_models({DEMO: a_ticket_hub()}, DEMO)

    tickets = models.feature_tickets("demo", "ticketed")

    assert (tickets.source, tickets.notice) == ("plan", NOT_CONNECTED_NOTICE)
    assert models.get_feature("demo", "ticketed").tickets_source == "plan"


def test_reads_linear_when_hub_uses_mcp_transport() -> None:
    """AC-816.1 (ADR 0060): an MCP hub's tickets are read like any other once a reader is wired."""
    snapshots = InMemoryTicketSnapshots(InMemoryTrackerReader(a_seeded_issue_board()))
    models, _, _ = read_models(
        {DEMO: a_ticket_hub(transport="mcp")}, DEMO, ticket_snapshots=snapshots
    )

    tickets = models.feature_tickets("demo", "ticketed")

    assert (tickets.source, tickets.notice) == ("linear", None)
    assert [request.transport for _, request in snapshots.calls] == ["mcp"]


def test_links_ticket_pull_request_when_review_names_hub_repo() -> None:
    review = b"---\ntype: review\nticket: DEM-1\noutcome: approved\npr: demo-api#12\n---\n"
    hub = a_ticket_hub()
    hub.features = (
        replace(hub.features[0], reviews=(RecordHead(name="dem-1.md", head=review, problem=None),)),
    )
    models, _, _ = read_models({DEMO: hub}, DEMO)

    tickets = models.feature_tickets("demo", "ticketed")

    assert [(row.ref, row.pr_url) for row in tickets.tickets] == [
        ("DEM-1", "https://github.com/acme/demo-api/pull/12"),
        ("DEM-2", None),
    ]


def test_reads_warm_snapshot_when_features_listed() -> None:
    counting = CountingTrackerReader(InMemoryTrackerReader(a_seeded_issue_board()))
    snapshots = InMemoryTicketSnapshots(counting)
    models, _, _ = read_models({DEMO: a_ticket_hub()}, DEMO, ticket_snapshots=snapshots)

    cold = models.list_features(Scope()).items[0]
    tickets = models.feature_tickets("demo", "ticketed")
    warm = models.list_features(Scope()).items[0]
    detail = models.get_feature("demo", "ticketed")

    assert cold.tickets_source == "plan"
    assert (warm.tickets_source, detail.tickets_source) == ("linear", "linear")
    assert warm.golden_path == detail.golden_path == tickets.golden_path
    assert warm.phase == detail.phase == tickets.golden_path.phase
    assert [kind for kind, _ in snapshots.calls] == ["cached", "fetch", "cached", "cached"]
    assert {request for _, request in snapshots.calls} == {TICKET_REQUEST}
    assert counting.count == 1


def test_lists_ticket_requests_when_features_name_tickets() -> None:
    """AGH-613: what the ticket warmer reads, one request per feature that names tickets in each
    valid project, with its hub's transport, as the tickets route asks; from the feature folders
    only, never through the ticket cache. A hub whose transport is ``mcp`` is left out without
    listing its folders: the warmer reads what it read before ADR 0060, and the feature page
    reads that hub's tickets on demand."""
    snapshots = InMemoryTicketSnapshots(InMemoryTrackerReader(a_seeded_issue_board()))
    demo = a_ticket_hub(transport="mcp")
    other = replace(a_ticket_hub(), hub_json=hub_json_bytes(pin=RUNNING, name="other"))
    # "demo-feature" names no ticket and "broken" cannot be parsed.
    other.features = (*other.features, *a_demo_hub().features)
    models, reader, _ = read_models(
        {DEMO: demo, OTHER: other}, DEMO, OTHER, ticket_snapshots=snapshots
    )

    requests = models.ticket_requests()

    assert requests == (SnapshotRequest(project="other", transport="api", ids=("DEM-1", "DEM-2")),)
    assert ("*", OTHER) in reader.feature_reads
    assert ("*", DEMO) not in reader.feature_reads
    assert snapshots.calls == []


def test_reads_only_named_folder_when_one_feature_read() -> None:
    snapshots = InMemoryTicketSnapshots(InMemoryTrackerReader(a_seeded_issue_board()))
    models, reader, _ = read_models({DEMO: a_ticket_hub()}, DEMO, ticket_snapshots=snapshots)

    models.get_feature("demo", "ticketed")
    models.feature_tickets("demo", "ticketed")
    with pytest.raises(EntityNotFoundError):
        models.get_feature("demo", "nope")

    assert reader.feature_reads == [("ticketed", DEMO), ("ticketed", DEMO), ("nope", DEMO)]
    # AGH-402 review S1/Q1: only the tickets route reads the folder's tickets/ records.
    assert reader.ticket_reads == ["ticketed"]


# two-level-flows A7 (AGH-405): one ticket's records, read with the folder's tickets/ records.
def test_serves_ticket_records_when_ticket_of_feature() -> None:
    models, reader, _ = read_models({DEMO: a_ticket_hub()}, DEMO)

    found = models.ticket_records("demo", "ticketed", "t2")

    assert (found.project, found.slug, found.ticket, found.preflight) == (
        "demo",
        "ticketed",
        "t2",
        None,
    )
    assert reader.ticket_reads == ["ticketed"]
    with pytest.raises(EntityNotFoundError):
        models.ticket_records("demo", "ticketed", "DEM-99")
    with pytest.raises(EntityNotFoundError):
        models.ticket_records("demo", "nope", "T2")


def test_reads_skill_catalog_when_project_known() -> None:
    hub = fake_hub_of(a_skills_fixture_tree(), hub_json=hub_json_bytes(pin=RUNNING))
    usage = a_skill_usage()

    class Usage:
        def skill_usage(self, project: str) -> SkillUsage:
            assert project == "demo"
            return usage

    registry = InMemoryHubRegistry(clock=lambda: NOW)
    registry.add(DEMO)
    models = HubFilesReadModels(
        registry=registry,
        reader=FakeHubFileReader({DEMO: hub}),
        activity=FakeActivity(),
        running_version=RUNNING,
        settings=SETTINGS,
        clock=lambda: NOW,
        usage=Usage(),
    )

    catalog = models.skill_catalog("demo")
    names = models.skill_item_names("demo")
    detail = models.skill_detail("demo", kind=ItemKind.SKILL, source="hub-workflow", name="alpha")
    reference = next(bundled for bundled in detail.files if bundled.path == "references/r.md")
    text = models.skill_file(
        "demo", kind=ItemKind.SKILL, source="hub-workflow", name="alpha", file_id=reference.id
    )

    assert catalog.project == "demo"
    assert "skill/hub-workflow/alpha" in {item.id for item in catalog.items}
    assert names == {(item.kind, item.name) for item in catalog.items}
    assert detail.usage is not None
    assert detail.usage.count == 3
    assert text.text == "# R\n\nRead on demand.\n"
    with pytest.raises(EntityNotFoundError) as unknown:
        models.skill_catalog("nope")
    assert unknown.value.entity == "project"


def test_captures_skill_units_when_capture_given() -> None:
    hub = fake_hub_of(a_skills_fixture_tree(), hub_json=hub_json_bytes(pin=RUNNING))
    reader = FakeHubFileReader({DEMO: hub})
    store = InMemoryItemVersionStore()
    registry = InMemoryHubRegistry(clock=lambda: NOW)
    registry.add(DEMO)
    models = HubFilesReadModels(
        registry=registry,
        reader=reader,
        activity=FakeActivity(),
        running_version=RUNNING,
        settings=SETTINGS,
        clock=lambda: NOW,
        capture=CaptureItemVersions(store, reader, lambda: NOW),
    )

    models.skill_catalog("demo")
    marked = models.marked_skill_unit("demo", kind=ItemKind.AGENT, source="demo", name="scout")

    assert marked is not None
    unit = marked.unit
    assert unit.unit_path == "plugin/demo/agents/scout.md"
    last = store.last("demo", unit.unit_path)
    assert last is not None
    assert last.first


def test_resolves_item_lookups_without_doctor_when_lock_matches_pin() -> None:
    # AGH-298 (AC-295.6, A11): the item writes' and history's lookups read the registry and
    # hub.json only, never the hub card's lock view and its doctor drift check.
    hub = fake_hub_of(a_skills_fixture_tree(), hub_json=hub_json_bytes(pin=RUNNING))
    hub.lock = a_lock()
    models, reader, _ = read_models({DEMO: hub, OTHER: a_demo_hub()}, DEMO, OTHER)
    reader.hubs[OTHER].lock = a_lock()

    assert list(models.project_hubs()) == [("demo", DEMO)]
    names = models.skill_item_names("demo")
    marked = models.marked_skill_unit("demo", kind=ItemKind.AGENT, source="demo", name="scout")
    with pytest.raises(EntityNotFoundError) as unknown:
        models.marked_skill_unit("nope", kind=ItemKind.AGENT, source="demo", name="scout")

    assert (ItemKind.AGENT, "scout") in names
    assert marked is not None
    assert marked.unit.unit_path == "plugin/demo/agents/scout.md"
    assert unknown.value.entity == "project"
    assert reader.snapshots == {}
    # The refresh runs the doctor for each hub that names a project, the card's included.
    models.refresh()
    models.list_hubs()
    assert reader.snapshots == {DEMO: 1, OTHER: 1}


# AGH-330 Q5: one read time for the whole list.
def test_reads_clock_once_when_features_listed() -> None:
    registry = InMemoryHubRegistry(clock=lambda: NOW)
    registry.add(DEMO)
    reads: list[datetime] = []

    def clock() -> datetime:
        reads.append(NOW)
        return NOW

    models = HubFilesReadModels(
        registry=registry,
        reader=FakeHubFileReader({DEMO: a_demo_hub()}),
        activity=FakeActivity(),
        running_version=RUNNING,
        settings=SETTINGS,
        clock=clock,
    )

    assert len(models.list_features(Scope()).items) == 2
    assert len(reads) == 1


def _usage_models(hubs: dict[str, FakeHub]) -> HubFilesReadModels:
    usage = a_skill_usage(
        windows_by_skill={
            "alpha": UsageWindows(runs_7d=1, runs_30d=3, runs_90d=4, last_used_at=NOW),
        }
    )

    class Usage:
        def skill_usage(self, project: str) -> SkillUsage:
            return usage if project == "demo" else a_skill_usage()

    registry = InMemoryHubRegistry(clock=lambda: NOW)
    for path in hubs:
        registry.add(path)
    return HubFilesReadModels(
        registry=registry,
        reader=FakeHubFileReader(hubs),
        activity=FakeActivity(),
        running_version=RUNNING,
        settings=SETTINGS,
        clock=lambda: NOW,
        usage=Usage(),
    )


def test_reports_usage_of_every_project_when_no_scope() -> None:
    demo = fake_hub_of(a_skills_fixture_tree(), hub_json=hub_json_bytes(pin=RUNNING))
    other = fake_hub_of(
        {".claude/agents/scout.md": b"---\nname: scout\ndescription: Looks.\n---\nGo.\n"},
        hub_json=hub_json_bytes(pin=RUNNING, name="other"),
    )
    models = _usage_models({DEMO: demo, OTHER: other})

    report = models.skill_usage_report(Scope(), days=30)
    scoped = models.skill_usage_report(Scope(project="other"), days=7)

    assert report.days == 30
    assert [(row.project, row.kind, row.name, row.runs_30d) for row in report.items] == [
        ("demo", ItemKind.AGENT, "local-agent", 0),
        ("demo", ItemKind.SKILL, "local-one", 0),
        ("other", ItemKind.AGENT, "scout", 0),
        ("demo", ItemKind.SKILL, "alpha", 3),
    ]
    assert not report.truncated
    assert [(row.project, row.name) for row in scoped.items] == [("other", "scout")]
    assert scoped.days == 7


def test_reports_no_usage_when_scope_names_unknown_project() -> None:
    demo = fake_hub_of(a_skills_fixture_tree(), hub_json=hub_json_bytes(pin=RUNNING))
    models = _usage_models({DEMO: demo})

    report = models.skill_usage_report(Scope(project="nope"), days=90)

    assert (report.days, report.items, report.truncated) == (90, (), False)
