from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from agent_hub.core.doctor.snapshot import LockAbsent
from agent_hub.core.events.event import EventSource
from agent_hub.core.features.feature_status import FeatureFolder
from agent_hub.core.hub_config.doctor_rules import LOCK_DRIFT_RULE, Severity
from agent_hub.core.hub_files.hub_lock import HubLock, ManagedFileEntry
from agent_hub.core.hubs.hub_read_models import HubFilesReadModels
from agent_hub.core.hubs.hub_registry import HubConflictError, HubInvalidError, UnreadHubFile
from agent_hub.core.projects.project_views import ProjectActivity
from agent_hub.core.readmodels.filters import Scope
from agent_hub.core.readmodels.read_ports import EntityNotFoundError, HubReadModels
from agent_hub.core.readmodels.settings_view import SettingsView
from agent_hub.core.runner.run_record import Stage
from agent_hub.core.testing.hub_fakes import (
    FakeHub,
    FakeHubFileReader,
    InMemoryHubRegistry,
    hub_json_bytes,
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
    hubs: dict[str, FakeHub], *paths: str
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
