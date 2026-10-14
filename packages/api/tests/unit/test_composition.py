import asyncio
import json
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent_hub.api import composition
from agent_hub.api.agent_session_runtime import (
    INSTALL_EXTRA,
    UnavailableCloudLauncher,
    UnavailableSessionDriver,
)
from agent_hub.api.composition import (
    HUB_CONFIG_INVALID,
    HUB_LOCAL_INVALID,
    NO_AUTHOR,
    CachedAvailability,
    RegisteredHubFacts,
    TicketReaders,
    build_app,
    claude_adapters,
    default_brain_changes,
    ticket_snapshots,
    web_url,
)
from agent_hub.api.settings import ApiSettings
from agent_hub.api.ticket_snapshots import REQUEST_TIMEOUT_SECONDS
from agent_hub.claude_sessions.cloud_launcher import ClaudeCloudLauncher
from agent_hub.claude_sessions.sdk_driver import ClaudeSdkSessionDriver
from agent_hub.core.agent_sessions.agent_session import AgentSessionStatus, EndReason
from agent_hub.core.agent_sessions.cloud import CloudSessions
from agent_hub.core.agent_sessions.control import AgentSessionControl
from agent_hub.core.agent_sessions.links import AgentSessionLinks
from agent_hub.core.features.ticket_snapshots import SnapshotRequest, TrackerTransport
from agent_hub.core.hub_config.local_config import LocalConfig, LocalProject
from agent_hub.core.hub_config.problems import ConfigProblem
from agent_hub.core.hubs.hub_registry import HubRegistryError, UnreadHubFile
from agent_hub.core.hubs.registered_hub import RegisteredHub
from agent_hub.core.learnings.brain_change_requests import CommitAuthor
from agent_hub.core.learnings.learning_ports import LearningHub
from agent_hub.core.learnings.read_learnings import HUB_NOT_REGISTERED, UnavailableHub
from agent_hub.core.sessions.session_label import LabelRules
from agent_hub.core.testing.brain_fakes import FakeBrainOrigin, InMemoryBrainChangeRequests
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.core.testing.hub_fakes import (
    FakeHub,
    FakeHubFileReader,
    InMemoryHubRegistry,
    hub_json_bytes,
)
from agent_hub.core.testing.read_model_builders import AGENT_SESSION_ID, an_agent_session
from agent_hub.core.testing.session_driver_fakes import InMemorySessionDriver
from agent_hub.core.testing.tracker_reader_fakes import (
    CountingTrackerReader,
    InMemoryTrackerReader,
    a_seeded_issue_board,
)
from agent_hub.storage.agent_session_store import open_agent_session_store
from agent_hub.storage.event_store import open_event_store

RUNNING = "0.9.0"
HUB = "/work/demo-hub"
STOPPED_AT = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)


def _without(*keys: str) -> bytes:
    document: dict[str, Any] = a_hub_document()
    document["platform"]["version"] = RUNNING
    for key in keys:
        del document["project"][key]
    return json.dumps(document).encode()


class _Clock:
    def __init__(self) -> None:
        self.at = 100.0

    def __call__(self) -> float:
        return self.at


def _facts(
    hubs: dict[str, FakeHub],
    *,
    git: Mapping[str, str] | None = None,
    clock: _Clock | None = None,
) -> tuple[RegisteredHubFacts, FakeHubFileReader]:
    registry = InMemoryHubRegistry()
    for path in hubs:
        registry.add(path)
    reader = FakeHubFileReader(hubs)
    facts = RegisteredHubFacts(
        registry=registry,
        reader=reader,
        running_version=RUNNING,
        read_git=lambda _path: lambda _keys: dict(git or {}),
        clock=clock or _Clock(),
    )
    return facts, reader


def test_names_hub_when_project_registered() -> None:
    facts, _ = _facts({HUB: FakeHub(hub_json=hub_json_bytes(pin=RUNNING))})

    assert facts.hub_of("demo") == LearningHub(
        project="demo",
        path=HUB,
        hub_repo="acme/demo-hub",
        default_branch="main",
        branch_prefix="jdoe/",
        author=CommitAuthor(name="Jane Doe", email="jane@example.com"),
    )


def test_takes_identity_from_local_config_when_hub_local_sets_it() -> None:
    local = LocalConfig(
        project=LocalProject(
            branch_prefix="mo/", author_name="Mo Local", author_email="mo@example.com"
        )
    )
    facts, _ = _facts({HUB: FakeHub(hub_json=hub_json_bytes(pin=RUNNING), local=local)})

    hub = facts.hub_of("demo")

    assert isinstance(hub, LearningHub)
    assert (hub.branch_prefix, hub.author) == (
        "mo/",
        CommitAuthor(name="Mo Local", email="mo@example.com"),
    )


def test_takes_author_from_git_when_files_leave_it_out() -> None:
    hub_json = _without("author_name", "author_email", "branch_prefix")
    git = {"author_name": "Git Person", "author_email": "gitp@example.com"}
    facts, _ = _facts({HUB: FakeHub(hub_json=hub_json)}, git=git)

    hub = facts.hub_of("demo")

    assert isinstance(hub, LearningHub)
    assert (hub.branch_prefix, hub.author.email) == ("gitp/", "gitp@example.com")


def test_says_no_author_when_identity_unset() -> None:
    hub_json = _without("author_name", "author_email")
    facts, _ = _facts({HUB: FakeHub(hub_json=hub_json)})

    assert facts.hub_of("demo") == UnavailableHub(reason=NO_AUTHOR, path=HUB)


def test_says_not_registered_when_project_unknown() -> None:
    facts, _ = _facts({HUB: FakeHub(hub_json=hub_json_bytes(pin=RUNNING))})

    assert facts.hub_of("other") == UnavailableHub(reason=HUB_NOT_REGISTERED)
    assert facts.label_rules_of("other") is None


def test_keeps_path_when_hub_json_invalid() -> None:
    hub_json = b'{"schema_version": 1, "project": {"name": "demo"}}'
    facts, _ = _facts({HUB: FakeHub(hub_json=hub_json)})

    assert facts.hub_of("demo") == UnavailableHub(reason=HUB_CONFIG_INVALID, path=HUB)
    assert facts.label_rules_of("demo") is None


def test_says_local_invalid_when_hub_local_unreadable() -> None:
    local = (ConfigProblem(path="$", message="not JSON"),)
    facts, _ = _facts({HUB: FakeHub(hub_json=hub_json_bytes(pin=RUNNING), local=local)})

    assert facts.hub_of("demo") == UnavailableHub(reason=HUB_LOCAL_INVALID, path=HUB)
    assert facts.label_rules_of("demo") == LabelRules(teams=("DEM",), branch_prefix="jdoe/")


def test_prefers_valid_hub_when_two_hubs_name_project() -> None:
    facts, _ = _facts(
        {
            "/work/broken": FakeHub(hub_json=b'{"project": {"name": "demo"}}'),
            HUB: FakeHub(hub_json=hub_json_bytes(pin=RUNNING)),
            "/work/second": FakeHub(hub_json=hub_json_bytes(pin=RUNNING, hub_repo="acme/x")),
        }
    )

    assert facts.hub_of("demo").path == HUB


def test_returns_label_rules_when_hub_registered() -> None:
    facts, _ = _facts({HUB: FakeHub(hub_json=hub_json_bytes(pin=RUNNING))})

    assert facts.label_rules_of("demo") == LabelRules(teams=("DEM",), branch_prefix="jdoe/")


def test_reuses_hub_reads_when_within_time_to_live() -> None:
    clock = _Clock()
    facts, reader = _facts({HUB: FakeHub(hub_json=hub_json_bytes(pin=RUNNING))}, clock=clock)
    facts.hub_of("demo")
    reader.hubs[HUB].hub_json = hub_json_bytes(pin=RUNNING, hub_repo="acme/moved")

    clock.at += 1
    kept = facts.hub_of("demo")
    clock.at += 10
    reread = facts.hub_of("demo")

    assert isinstance(kept, LearningHub)
    assert isinstance(reread, LearningHub)
    assert (kept.hub_repo, reread.hub_repo) == ("acme/demo-hub", "acme/moved")


class _BrokenRegistry:
    def entries(self) -> tuple[RegisteredHub, ...]:
        raise HubRegistryError("hubs.json is not JSON")


def test_says_not_registered_when_registry_unreadable() -> None:
    facts = RegisteredHubFacts(
        registry=_BrokenRegistry(),  # type: ignore[arg-type]
        reader=FakeHubFileReader(),
        running_version=RUNNING,
    )

    assert facts.hub_of("demo") == UnavailableHub(reason=HUB_NOT_REGISTERED)


def test_skips_unreadable_hub_when_hub_json_missing() -> None:
    missing = UnreadHubFile(message="cannot read", is_missing=True)
    facts, _ = _facts({HUB: FakeHub(hub_json=missing)})

    assert facts.hub_of("demo") == UnavailableHub(reason=HUB_NOT_REGISTERED)


class _Checks:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, hub_path: str) -> str | None:
        self.calls.append(hub_path)
        return f"checked {len(self.calls)}"


def test_caches_availability_per_hub_when_within_time_to_live() -> None:
    clock = _Clock()
    checks = _Checks()
    availability = CachedAvailability(checks, ttl=10.0, clock=clock)

    first = availability(HUB)
    clock.at += 5
    again = availability(HUB)
    other = availability("/work/other-hub")

    assert (first, again, other) == ("checked 1", "checked 1", "checked 2")
    assert checks.calls == [HUB, "/work/other-hub"]


def test_checks_availability_again_when_time_to_live_passed() -> None:
    clock = _Clock()
    checks = _Checks()
    availability = CachedAvailability(checks, ttl=10.0, clock=clock)

    availability(HUB)
    clock.at += 10

    assert availability(HUB) == "checked 2"


def test_says_read_only_when_running_in_container(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_HUB_IN_CONTAINER", "1")

    assert default_brain_changes().availability(HUB) == "Hub is read-only here"


# A synthetic key: never a real one.
KEY = "lin_api_synthetic0000"


def _with_transport(transport: TrackerTransport) -> bytes:
    document: dict[str, Any] = a_hub_document()
    document["platform"]["version"] = RUNNING
    document["tracker"]["transport"] = transport
    return json.dumps(document).encode()


def _request(transport: TrackerTransport = "api") -> SnapshotRequest:
    return SnapshotRequest.of(project="demo", transport=transport, ids=("DEM-2", "DEM-1"))


def _registered(transport: TrackerTransport = "api") -> RegisteredHubFacts:
    facts, _ = _facts({HUB: FakeHub(hub_json=_with_transport(transport))})
    return facts


def test_wires_tickets_when_app_built() -> None:
    reader = CountingTrackerReader(InMemoryTrackerReader(a_seeded_issue_board()))
    snapshots = ticket_snapshots(
        _registered(), environ={"LINEAR_API_KEY": KEY}, tracker_reader=reader
    )

    read = snapshots.fetch(_request())

    assert (read.source, read.failure) == ("linear", None)
    assert read.snapshot is not None
    assert [summary.id for summary in read.snapshot.summaries] == ["DEM-1", "DEM-2"]
    assert reader.calls == [("DEM-1", "DEM-2")]


def test_builds_no_reader_when_transport_mcp() -> None:
    reader = InMemoryTrackerReader(a_seeded_issue_board())
    environ = {"LINEAR_API_KEY": KEY}
    asked_mcp = TicketReaders(_registered(), environ=environ, reader=reader)
    hub_says_mcp = TicketReaders(_registered("mcp"), environ=environ, reader=reader)

    assert asked_mcp(_request("mcp")) is None
    assert hub_says_mcp(_request("api")) is None
    assert (
        ticket_snapshots(_registered("mcp"), environ=environ, tracker_reader=reader)
        .fetch(_request())
        .failure
        == "not_connected"
    )


def test_builds_no_reader_when_key_missing() -> None:
    reader = InMemoryTrackerReader(a_seeded_issue_board())
    readers = TicketReaders(_registered(), environ={"LINEAR_API_KEY": ""}, reader=reader)
    unset = TicketReaders(_registered(), environ={}, reader=reader)

    assert readers(_request()) is None
    assert unset(_request()) is None


def test_builds_reader_when_key_set_and_transport_api() -> None:
    reader = InMemoryTrackerReader(a_seeded_issue_board())
    readers = TicketReaders(_registered(), environ={"LINEAR_API_KEY": KEY}, reader=reader)

    assert readers(_request()) is reader


class _RecordingPost:
    def __init__(self) -> None:
        self.calls: list[tuple[str, float]] = []

    def __call__(
        self, url: str, headers: Mapping[str, str], body: bytes, *, timeout_s: float
    ) -> tuple[int, bytes]:
        self.calls.append((headers["Authorization"], timeout_s))
        return 401, b'{"errors": [{"message": "Authentication required"}]}'


def test_reads_key_at_call_time_when_set_after_app_built() -> None:
    environ: dict[str, str] = {}
    post = _RecordingPost()
    snapshots = ticket_snapshots(_registered(), environ=environ, linear_post=post)

    before = snapshots.fetch(_request())
    environ["LINEAR_API_KEY"] = KEY
    after = snapshots.fetch(_request())

    assert (before.failure, after.failure) == ("not_connected", "unauthorized")
    assert post.calls == [(KEY, REQUEST_TIMEOUT_SECONDS)]
    assert KEY not in f"{before.detail} {after.detail}"


def test_names_tracker_transport_when_hub_registered() -> None:
    facts = _registered("mcp")

    assert facts.tracker_transport_of("demo") == "mcp"
    assert facts.tracker_transport_of("other") is None


# Agent sessions (CP)


def _session_settings(tmp_path: Path, **fields: Any) -> ApiSettings:
    return ApiSettings(
        db_path=tmp_path / "agent-hub.db",
        registry_path=tmp_path / "hubs.json",
        port=7420,
        running_version=RUNNING,
        clock=lambda: STOPPED_AT,
        **fields,
    )


def _build(settings: ApiSettings, tmp_path: Path, **options: Any) -> Any:
    return build_app(
        settings,
        projects_root=tmp_path / "projects",
        web_dist=tmp_path / "web_dist",
        brain_changes=InMemoryBrainChangeRequests(FakeBrainOrigin()),
        environ={},
        **options,
    )


def test_wires_unavailable_driver_when_extra_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "agent_hub.claude_sessions.sdk_driver", None)

    driver, launcher = claude_adapters({})

    assert isinstance(driver, UnavailableSessionDriver)
    assert isinstance(launcher, UnavailableCloudLauncher)
    capabilities = asyncio.run(driver.capabilities())
    assert (capabilities.available, capabilities.reason) == (False, INSTALL_EXTRA)


def test_wires_claude_driver_when_extra_installed() -> None:
    driver, launcher = claude_adapters({"PATH": ""})

    assert isinstance(driver, ClaudeSdkSessionDriver)
    assert isinstance(launcher, ClaudeCloudLauncher)


def test_builds_no_control_when_in_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_driver(_environ: Mapping[str, str]) -> Any:
        msg = "no driver is built in the container"
        raise AssertionError(msg)

    monkeypatch.setattr(composition, "claude_adapters", no_driver)

    app = _build(_session_settings(tmp_path, sessions_off=True), tmp_path)

    ports = app.state.ports
    assert (ports.agent_sessions, ports.cloud_sessions, ports.agent_session_links) == (
        None,
        None,
        None,
    )


def test_wires_control_cloud_and_links_when_sessions_on(tmp_path: Path) -> None:
    app = _build(_session_settings(tmp_path), tmp_path, session_driver=InMemorySessionDriver())

    ports = app.state.ports
    assert isinstance(ports.agent_sessions, AgentSessionControl)
    assert isinstance(ports.cloud_sessions, CloudSessions)
    assert isinstance(ports.agent_session_links, AgentSessionLinks)


def test_ends_unfinished_sessions_when_app_starts(tmp_path: Path) -> None:
    settings = _session_settings(tmp_path)
    open_event_store(settings.db_path)
    store = open_agent_session_store(settings.db_path)
    store.create(an_agent_session(status=AgentSessionStatus.RUNNING, last_seq=0))
    app = _build(settings, tmp_path, session_driver=InMemorySessionDriver())

    before = store.get(AGENT_SESSION_ID)
    with TestClient(app):
        after = store.get(AGENT_SESSION_ID)

    assert before.status == AgentSessionStatus.RUNNING
    assert after.status == AgentSessionStatus.ENDED
    assert after.end_reason == EndReason.SERVER_STOPPED


def test_names_loopback_port_when_web_url_built(tmp_path: Path) -> None:
    assert web_url(_session_settings(tmp_path)) == "http://127.0.0.1:7420"


@pytest.mark.parametrize(
    ("bound", "url"),
    [
        ("127.0.0.2", "http://127.0.0.2:7420"),
        ("::1", "http://[::1]:7420"),
        ("0.0.0.0", "http://127.0.0.1:7420"),  # noqa: S104 -- the container's bind
        ("::", "http://127.0.0.1:7420"),
    ],
)
def test_names_bound_address_when_web_url_built_on_other_bind(
    tmp_path: Path, bound: str, url: str
) -> None:
    assert web_url(_session_settings(tmp_path, bound_host=bound)) == url
