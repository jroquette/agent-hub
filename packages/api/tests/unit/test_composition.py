import json
from collections.abc import Mapping
from typing import Any

import pytest

from agent_hub.api.composition import (
    HUB_CONFIG_INVALID,
    HUB_LOCAL_INVALID,
    NO_AUTHOR,
    CachedAvailability,
    RegisteredHubFacts,
    TicketReaders,
    default_brain_changes,
    ticket_snapshots,
)
from agent_hub.api.ticket_snapshots import REQUEST_TIMEOUT_SECONDS
from agent_hub.core.features.ticket_snapshots import SnapshotRequest, TrackerTransport
from agent_hub.core.hub_config.local_config import LocalConfig, LocalProject
from agent_hub.core.hub_config.problems import ConfigProblem
from agent_hub.core.hubs.hub_registry import HubRegistryError, UnreadHubFile
from agent_hub.core.hubs.registered_hub import RegisteredHub
from agent_hub.core.learnings.brain_change_requests import CommitAuthor
from agent_hub.core.learnings.learning_ports import LearningHub
from agent_hub.core.learnings.read_learnings import HUB_NOT_REGISTERED, UnavailableHub
from agent_hub.core.sessions.session_label import LabelRules
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.core.testing.hub_fakes import (
    FakeHub,
    FakeHubFileReader,
    InMemoryHubRegistry,
    hub_json_bytes,
)
from agent_hub.core.testing.tracker_reader_fakes import (
    CountingTrackerReader,
    InMemoryTrackerReader,
    a_seeded_issue_board,
)

RUNNING = "0.9.0"
HUB = "/work/demo-hub"


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
