import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from agent_hub.core.brain.brain_note import (
    BrainEntry,
    BrainNoteNotFoundError,
    BrainNoteTooLargeError,
)
from agent_hub.core.brain.brain_path import MAX_NOTE_BYTES, BrainPathError
from agent_hub.core.doctor.snapshot import LockAbsent
from agent_hub.core.events.event import EventSource
from agent_hub.core.features.feature_status import FeatureFolder
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
from agent_hub.core.projects.project_views import ProjectActivity
from agent_hub.core.readmodels.filters import Scope
from agent_hub.core.readmodels.read_ports import EntityNotFoundError, HubReadModels
from agent_hub.core.readmodels.settings_view import SettingsView
from agent_hub.core.runner.run_record import Stage
from agent_hub.core.skills.skill_view import ItemKind, SkillUsage
from agent_hub.core.testing.hub_fakes import (
    FakeHub,
    FakeHubFileReader,
    InMemoryHubRegistry,
    hub_json_bytes,
)
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
    ],
    ids=["project", "now", "repos", "feature-project", "feature-slug"],
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

    findings = models.doctor_findings(Scope(project="demo")).items
    again = models.doctor_findings(Scope()).items

    assert findings
    assert {finding.project for finding in findings} == {"demo"}
    assert findings[0].severity in set(Severity)
    assert again == findings
    assert reader.snapshots == {DEMO: 1}


def test_raises_not_found_when_scoped_project_has_no_readable_hub() -> None:
    # OTHER is registered but its hub.json cannot be read: no readable hub names "other".
    models, _, _ = read_models({DEMO: a_demo_hub()}, DEMO, OTHER)

    with pytest.raises(EntityNotFoundError) as raised:
        models.doctor_findings(Scope(project="other"))

    assert raised.value.entity_id == "other"


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


def test_asks_mcp_transport_when_hub_uses_it() -> None:
    snapshots = InMemoryTicketSnapshots(InMemoryTrackerReader(a_seeded_issue_board()))
    models, _, _ = read_models(
        {DEMO: a_ticket_hub(transport="mcp")}, DEMO, ticket_snapshots=snapshots
    )

    tickets = models.feature_tickets("demo", "ticketed")

    assert (tickets.source, tickets.notice) == ("plan", NOT_CONNECTED_NOTICE)
    assert [request.transport for _, request in snapshots.calls] == ["mcp"]


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


def test_reads_only_named_folder_when_one_feature_read() -> None:
    snapshots = InMemoryTicketSnapshots(InMemoryTrackerReader(a_seeded_issue_board()))
    models, reader, _ = read_models({DEMO: a_ticket_hub()}, DEMO, ticket_snapshots=snapshots)

    models.get_feature("demo", "ticketed")
    models.feature_tickets("demo", "ticketed")
    with pytest.raises(EntityNotFoundError):
        models.get_feature("demo", "nope")

    assert reader.feature_reads == [("ticketed", DEMO), ("ticketed", DEMO), ("nope", DEMO)]


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
    detail = models.skill_detail("demo", kind=ItemKind.SKILL, source="hub-workflow", name="alpha")
    reference = next(bundled for bundled in detail.files if bundled.path == "references/r.md")
    text = models.skill_file(
        "demo", kind=ItemKind.SKILL, source="hub-workflow", name="alpha", file_id=reference.id
    )

    assert catalog.project == "demo"
    assert "skill/hub-workflow/alpha" in {item.id for item in catalog.items}
    assert detail.usage is not None
    assert detail.usage.count == 3
    assert text.text == "# R\n\nRead on demand.\n"
    with pytest.raises(EntityNotFoundError) as unknown:
        models.skill_catalog("nope")
    assert unknown.value.entity == "project"
