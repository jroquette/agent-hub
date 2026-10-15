from datetime import UTC, datetime, timedelta

from agent_hub.core.doctor.config_rules import config_state
from agent_hub.core.doctor.registry import REGISTRY
from agent_hub.core.doctor.run_rules import Selection, run_rules, select_rules
from agent_hub.core.doctor.snapshot import ConfigFailure
from agent_hub.core.hub_config.doctor_rules import CONFIG_SCHEMA_RULE, PLATFORM_VERSION_RULE
from agent_hub.core.hub_config.local_config import LocalConfig
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hubs.doctor_cache import DOCTOR_TTL, DoctorCache, run_doctor
from agent_hub.core.hubs.hub_registry import UnreadHubFile
from agent_hub.core.testing.hub_fakes import FakeHub, FakeHubFileReader, hub_json_bytes

RUNNING = "4.5.6"
HUB = "/hubs/demo-hub"
START = datetime(2026, 10, 9, 14, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now


def a_reader(**changes: object) -> FakeHubFileReader:
    hub = FakeHub(
        hub_json=hub_json_bytes(pin=RUNNING),
        files={"AGENTS.md": b"# Demo\n"},
        mtimes={"hub.json": 1, "hub.lock": 2, "AGENTS.md": 3},
    )
    for name, value in changes.items():
        setattr(hub, name, value)
    return FakeHubFileReader({HUB: hub})


def test_runs_every_rule_like_hub_doctor_when_config_valid() -> None:
    reader = a_reader()

    run = run_doctor(reader, HUB, running_version=RUNNING)

    config = config_state(hub_json_bytes(pin=RUNNING), running_version=RUNNING)
    assert isinstance(config, HubConfig)
    selection = select_rules(REGISTRY, config=config, only=())
    assert isinstance(selection, Selection)
    snapshot = reader.doctor_snapshot(
        HUB, config=config, running_version=RUNNING, selection=selection, local=LocalConfig()
    )
    assert run.findings == run_rules(selection, snapshot)
    assert {"hub.json", "hub.lock", "hub.local.json", "AGENTS.md"} <= set(run.watched)


def test_reports_pin_finding_only_when_pinned_to_other_version() -> None:
    reader = a_reader(hub_json=hub_json_bytes(pin="0.1.0"))

    run = run_doctor(reader, HUB, running_version=RUNNING)

    assert [finding.rule for finding in run.findings] == [PLATFORM_VERSION_RULE]
    assert reader.snapshots == {}


def test_reports_schema_finding_when_hub_json_unreadable() -> None:
    unread = UnreadHubFile(
        message='cannot read "/hubs/demo-hub/hub.json": denied', is_missing=False
    )
    reader = a_reader(hub_json=unread)

    run = run_doctor(reader, HUB, running_version=RUNNING)

    assert [(finding.rule, finding.message) for finding in run.findings] == [
        (CONFIG_SCHEMA_RULE, f"$: {unread.message}")
    ]
    assert isinstance(config_state((), running_version=RUNNING), ConfigFailure)


def test_reuses_findings_when_nothing_changed_within_ttl() -> None:
    reader = a_reader()
    clock = Clock()
    cache = DoctorCache(reader, running_version=RUNNING, clock=clock)

    first = cache.findings(HUB)
    clock.now += DOCTOR_TTL - timedelta(seconds=1)
    second = cache.findings(HUB)

    assert first == second
    assert reader.snapshots == {HUB: 1}


def test_runs_again_when_ttl_passed() -> None:
    reader = a_reader()
    clock = Clock()
    cache = DoctorCache(reader, running_version=RUNNING, clock=clock)

    cache.findings(HUB)
    clock.now += DOCTOR_TTL
    cache.findings(HUB)

    assert reader.snapshots == {HUB: 2}


def test_runs_again_when_watched_file_modified() -> None:
    reader = a_reader()
    cache = DoctorCache(reader, running_version=RUNNING, clock=Clock())

    cache.findings(HUB)
    reader.hubs[HUB].mtimes["AGENTS.md"] = 99
    cache.findings(HUB)

    assert reader.snapshots == {HUB: 2}


def test_watches_workflow_folders_when_hub_has_workflows() -> None:
    # AGH-227: workflows.valid reads every file under workflows/, so a file added or removed
    # there (its folder's time) makes the run stale, as an edit (the file's own time) does.
    reader = a_reader(files={"AGENTS.md": b"# Demo\n", "workflows/demo/fixtures/a.yaml": b"x\n"})

    run = run_doctor(reader, HUB, running_version=RUNNING)

    assert {"workflows", "workflows/demo", "workflows/demo/fixtures"} <= set(run.watched)
    assert "workflows/demo/fixtures/a.yaml" in run.watched


def test_watches_workflows_folder_when_hub_has_no_workflow() -> None:
    assert "workflows" in run_doctor(a_reader(), HUB, running_version=RUNNING).watched


def test_runs_again_when_workflow_added() -> None:
    reader = a_reader(
        files={"AGENTS.md": b"# Demo\n", "workflows/demo/lint.yaml": b"x\n"},
        mtimes={"hub.json": 1, "workflows": 4, "workflows/demo": 5},
    )
    cache = DoctorCache(reader, running_version=RUNNING, clock=Clock())

    cache.findings(HUB)
    reader.hubs[HUB].mtimes["workflows/demo"] = 6
    cache.findings(HUB)

    assert reader.snapshots == {HUB: 2}


def test_watches_empty_pack_folder_when_workflows_listed() -> None:
    # F2: a pack folder git does not list (empty, or untracked) is watched from the listing of
    # workflows/ itself, so a workflow added to it makes the run stale.
    reader = a_reader(folders=("workflows/empty",))

    run = run_doctor(reader, HUB, running_version=RUNNING)

    assert "workflows/empty" in run.watched


def test_watches_at_most_three_levels_when_workflow_paths_nest_deeply() -> None:
    deep = "workflows/demo/fixtures/a/b/c.yaml"
    reader = a_reader(files={"AGENTS.md": b"# Demo\n", deep: b"x\n"})

    watched = set(run_doctor(reader, HUB, running_version=RUNNING).watched)

    assert {"workflows", "workflows/demo", "workflows/demo/fixtures", deep} <= watched
    assert "workflows/demo/fixtures/a" not in watched
    assert "workflows/demo/fixtures/a/b" not in watched
