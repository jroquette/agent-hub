from datetime import UTC, datetime, timedelta

from agent_hub.core.doctor.registry import REGISTRY
from agent_hub.core.doctor.run_rules import Selection, run_rules, select_rules
from agent_hub.core.doctor.snapshot import ConfigFailure
from agent_hub.core.doctor.config_rules import config_state
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
