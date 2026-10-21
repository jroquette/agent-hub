import json
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from agent_hub.api.agent_session_runtime import HubCredentials
from agent_hub.core.agent_sessions.agent_session import (
    AgentSessionList,
    AgentSessionStatus,
    CloudSessionList,
    MessageAccepted,
    ResumableList,
    WorkdirList,
)
from agent_hub.core.agent_sessions.cloud import CloudSessionCommands
from agent_hub.core.agent_sessions.control import AgentSessionCommands
from agent_hub.core.agent_sessions.driver import DriverCapabilities
from agent_hub.core.agent_sessions.records import LogRecord, LogRecordPage
from agent_hub.core.hub_config.problems import ConfigProblem
from agent_hub.core.testing.agent_session_rig import build_rig
from agent_hub.core.testing.agent_session_store_fakes import InMemoryAgentSessionStore
from agent_hub.core.testing.builders import an_environments_document
from agent_hub.core.testing.hub_fakes import FakeHub, FakeHubFileReader, InMemoryHubRegistry
from agent_hub.core.testing.read_model_builders import (
    AGENT_SESSION_ID,
    STARTED,
    WORKDIR_ID,
    a_cloud_session,
    a_log_record,
    a_workdir,
    an_agent_session,
)

# Writes need the server's own Origin (local_security.py).
OWN_ORIGIN = {"Origin": "http://127.0.0.1:7420"}
BASE = "/api/v1/agent-sessions"
RUNNING = "0.9.0"
ONE = f"{BASE}/{AGENT_SESSION_ID}"


def _control() -> Mock:
    control = Mock(spec=AgentSessionCommands)
    session = an_agent_session()
    control.workdirs.return_value = WorkdirList(items=(a_workdir(),))
    control.capabilities.return_value = DriverCapabilities(available=True, engine="in-memory")
    control.resumable.return_value = ResumableList(items=())
    control.list_sessions.return_value = AgentSessionList(items=(session,))
    control.create.return_value = session
    control.snapshot.return_value = session
    control.delete.return_value = None
    control.events.return_value = LogRecordPage(items=(a_log_record(),), next_after=None)
    control.send.return_value = MessageAccepted(seq=5)
    for method in ("interrupt", "stop_task", "answer", "change_settings", "close"):
        getattr(control, method).return_value = session
    return control


def _cloud() -> Mock:
    cloud = Mock(spec=CloudSessionCommands)
    cloud.list_cloud.return_value = CloudSessionList(items=(a_cloud_session(),))
    cloud.start.return_value = a_cloud_session()
    cloud.follow_up.return_value = a_cloud_session(followups=1)
    return cloud


@pytest.fixture
def ports(wired: Any) -> tuple[Mock, Mock]:
    control, cloud = _control(), _cloud()
    wired.wire(agent_sessions=control, cloud_sessions=cloud)
    return control, cloud


def test_routes_cloud_path_when_id_route_registered(wired: Any, ports: tuple[Mock, Mock]) -> None:
    control, cloud = ports

    response = wired.client.get(f"{BASE}/cloud", params={"project": "demo"})

    assert response.status_code == 200
    assert response.json() == CloudSessionList(items=(a_cloud_session(),)).model_dump(mode="json")
    cloud.list_cloud.assert_awaited_once_with("demo")
    assert control.mock_calls == []


def test_answers_not_implemented_when_control_not_wired(wired: Any) -> None:
    listed = wired.client.get(BASE)
    started = wired.client.post(
        f"{BASE}/cloud",
        json={"project": "demo", "workdir_id": WORKDIR_ID, "task": "Upgrade the linter"},
        headers=OWN_ORIGIN,
    )

    assert (listed.status_code, started.status_code) == (501, 501)
    assert listed.headers["content-type"] == "application/problem+json"


@pytest.mark.parametrize(
    ("method", "path", "body", "status", "port_method"),
    [
        ("get", f"{BASE}/workdirs?project=demo", None, 200, "workdirs"),
        ("get", f"{BASE}/capabilities", None, 200, "capabilities"),
        ("get", f"{BASE}/resumable?project=demo&workdir_id={WORKDIR_ID}", None, 200, "resumable"),
        ("get", f"{BASE}?status=idle", None, 200, "list_sessions"),
        ("post", BASE, {"project": "demo", "workdir_id": WORKDIR_ID}, 201, "create"),
        ("get", ONE, None, 200, "snapshot"),
        ("delete", ONE, None, 204, "delete"),
        ("get", f"{ONE}/events?after=2&limit=50", None, 200, "events"),
        ("post", f"{ONE}/messages", {"text": "Run the tests."}, 202, "send"),
        ("post", f"{ONE}/interrupt", {}, 202, "interrupt"),
        ("post", f"{ONE}/tasks/task-1/stop", {}, 202, "stop_task"),
        ("post", f"{ONE}/permissions/req-1", {"decision": "allow"}, 200, "answer"),
        ("post", f"{ONE}/settings", {"mode": "plan"}, 200, "change_settings"),
        ("post", f"{ONE}/close", {}, 200, "close"),
    ],
)
def test_calls_one_control_method_when_route_requested(
    wired: Any,
    ports: tuple[Mock, Mock],
    *,
    method: str,
    path: str,
    body: dict[str, object] | None,
    status: int,
    port_method: str,
) -> None:
    control, _ = ports
    extra: dict[str, Any] = {"headers": OWN_ORIGIN} if method != "get" else {}
    if body is not None:
        extra["json"] = body

    response = wired.client.request(method.upper(), path, **extra)

    assert response.status_code == status, response.text
    getattr(control, port_method).assert_awaited_once()
    assert len(control.mock_calls) == 1


def test_sets_location_when_session_created(wired: Any, ports: tuple[Mock, Mock]) -> None:
    response = wired.client.post(
        BASE, json={"project": "demo", "workdir_id": WORKDIR_ID}, headers=OWN_ORIGIN
    )

    assert response.headers["location"] == ONE


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (BASE, {"project": "demo", "workdir_id": "../../etc"}),
        (BASE, {"project": "demo", "workdir_id": WORKDIR_ID, "mode": "bypassPermissions"}),
        (BASE, {"project": "demo", "workdir_id": WORKDIR_ID, "model": "a b"}),
        (f"{ONE}/messages", {"text": ""}),
        (f"{ONE}/permissions/req-1", {"decision": "always"}),
        (f"{ONE}/permissions/req%201", {"decision": "allow"}),
        (f"{ONE}/tasks/task%201/stop", {}),
        (f"{ONE}/tasks/{'t' * 65}/stop", {}),
        (f"{ONE}/settings", {}),
        (f"{BASE}/cloud", {"project": "demo", "workdir_id": WORKDIR_ID, "task": "-x"}),
    ],
)
def test_refuses_body_when_invalid_and_calls_no_port(
    wired: Any, ports: tuple[Mock, Mock], *, path: str, body: dict[str, object]
) -> None:
    control, cloud = ports

    response = wired.client.post(path, json=body, headers=OWN_ORIGIN)

    assert response.status_code in {400, 422}, response.text
    assert control.mock_calls == []
    assert cloud.mock_calls == []


def test_answers_not_found_when_id_not_a_uuid(wired: Any, ports: tuple[Mock, Mock]) -> None:
    control, _ = ports

    response = wired.client.get(f"{BASE}/not-a-uuid")

    assert response.status_code == 404
    assert control.mock_calls == []


def test_passes_cloud_commands_when_cloud_routes_called(
    wired: Any, ports: tuple[Mock, Mock]
) -> None:
    _, cloud = ports
    task = {"project": "demo", "workdir_id": WORKDIR_ID, "task": "Upgrade the linter"}

    started = wired.client.post(f"{BASE}/cloud", json=task, headers=OWN_ORIGIN)
    followed = wired.client.post(
        f"{BASE}/cloud/cse_01synthetic/messages", json={"text": "Also the docs"}, headers=OWN_ORIGIN
    )

    assert (started.status_code, followed.status_code) == (201, 200)
    assert followed.json()["followups"] == 1
    assert cloud.follow_up.await_args.args[0] == "cse_01synthetic"


WRITERS_SPEC = "brain/features/real_cost/spec.md"
WRITERS_ABSOLUTE = f"/work/demo-hub/{WRITERS_SPEC}"
OLDEST, READER, NEWEST, OTHER = (f"01929a4e-7a11-7c00-8a00-00000000c00{n}" for n in range(1, 5))


def _tool_call(seq: int, name: str, path: str) -> LogRecord:
    body = {"tool_use_id": f"t{seq}", "name": name, "input": {"file_path": path}}
    return a_log_record("tool.call", seq, body=body)


def _writers_store() -> InMemoryAgentSessionStore:
    """Four ended sessions, a minute apart: the oldest wrote the spec, the next only read it,
    the newest edited it, and the last wrote a file whose path only ends like it."""
    store = InMemoryAgentSessionStore()
    calls = {
        OLDEST: [_tool_call(1, "Write", WRITERS_ABSOLUTE)],
        READER: [_tool_call(1, "Read", WRITERS_ABSOLUTE)],
        NEWEST: [_tool_call(1, "Edit", WRITERS_ABSOLUTE)],
        OTHER: [_tool_call(1, "Write", "/work/demo-hub/xbrain/features/real_cost/spec.md")],
    }
    for minutes, (agent_session_id, records) in enumerate(calls.items()):
        at = STARTED + timedelta(minutes=minutes)
        store.create(
            an_agent_session(
                id=agent_session_id,
                created_at=at,
                updated_at=at,
                last_seq=0,
                status=AgentSessionStatus.ENDED,
                claude_session_id=None,
            )
        )
        store.append(agent_session_id, records)
    return store


# AC-PG-33.1: ?wrote=<path> lists only the sessions with a tool call that wrote or edited that
# file, newest first; a relative path and the absolute one agree, and only whole segments match.
@pytest.mark.parametrize("wrote", [WRITERS_SPEC, WRITERS_ABSOLUTE])
def test_lists_only_writers_newest_first_when_wrote_given(wired: Any, wrote: str) -> None:
    wired.wire(agent_sessions=build_rig(store=_writers_store()).control)

    response = wired.client.get(BASE, params={"wrote": wrote})

    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["items"]] == [NEWEST, OLDEST]


# AC-PG-33.1: without wrote, every session is listed, newest first.
def test_lists_every_session_newest_first_when_wrote_absent(wired: Any) -> None:
    wired.wire(agent_sessions=build_rig(store=_writers_store()).control)

    response = wired.client.get(BASE)

    assert [item["id"] for item in response.json()["items"]] == [OTHER, NEWEST, READER, OLDEST]


# AC-PG-33.1: a path no session wrote lists nothing; a partial segment never matches.
@pytest.mark.parametrize("wrote", ["features/real_cost/plan.md", "cost/spec.md"])
def test_lists_nothing_when_no_session_wrote_path(wired: Any, wrote: str) -> None:
    wired.wire(agent_sessions=build_rig(store=_writers_store()).control)

    response = wired.client.get(BASE, params={"wrote": wrote})

    assert response.status_code == 200
    assert response.json()["items"] == []


# AC-PG-33.1: the route passes wrote on to the control as given.
def test_passes_wrote_when_sessions_listed(wired: Any, ports: tuple[Mock, Mock]) -> None:
    control, _ = ports

    response = wired.client.get(BASE, params={"wrote": WRITERS_SPEC, "project": "demo"})

    assert response.status_code == 200
    control.list_sessions.assert_awaited_once_with(project="demo", status=None, wrote=WRITERS_SPEC)


# AC-PG-33.1: an empty or too long wrote is refused before the control is called.
@pytest.mark.parametrize("wrote", ["", "x" * 1025])
def test_refuses_wrote_when_empty_or_too_long(
    wired: Any, ports: tuple[Mock, Mock], wrote: str
) -> None:
    control, _ = ports

    response = wired.client.get(BASE, params={"wrote": wrote})

    assert response.status_code == 400
    assert control.list_sessions.await_count == 0


def _hub_with_credentials(
    tmp_path: Path, *, local: tuple[ConfigProblem, ...] | None = None
) -> HubCredentials:
    """A registered hub ``demo`` whose ``staging`` declares a profile, a name and an env file."""
    hub = tmp_path / "work" / "demo-hub"
    hub.mkdir(parents=True)
    document = an_environments_document()
    document["platform"]["version"] = RUNNING
    document["environments"]["staging"]["credentials"] = {
        "aws_profile": "demo-staging",
        "env": ["DEMO_DB_URL"],
        "env_file": "demo-api/environment/.env.staging",
    }
    registry = InMemoryHubRegistry()
    registry.add(str(hub))
    fake = FakeHub(hub_json=json.dumps(document).encode())
    if local is not None:
        fake.local = local
    reader = FakeHubFileReader({str(hub): fake})
    return HubCredentials(registry=registry, reader=reader, running_version=RUNNING)


def test_hides_credentials_when_credential_injection_any_session(
    wired: Any, tmp_path: Path
) -> None:
    rig = build_rig(hidden_environment=_hub_with_credentials(tmp_path).names)
    wired.wire(agent_sessions=rig.control)

    response = wired.client.post(
        BASE, json={"project": "demo", "workdir_id": WORKDIR_ID}, headers=OWN_ORIGIN
    )

    assert response.status_code == 201
    (start,) = [call for call in rig.driver.calls if call.method == "start"]
    hidden = start.args[0].hidden_environment
    assert hidden.env == frozenset({"DEMO_DB_URL", "DEMO_LIVE_DB_URL"})
    assert hidden.aws_profiles == frozenset({"demo-staging", "demo-live-ro"})
    assert start.args[0].tool_policy is None
    assert start.args[0].system_prompt is None


def test_refuses_start_when_credential_injection_local_config_unreadable(
    wired: Any, tmp_path: Path
) -> None:
    problem = ConfigProblem(path="hub.local.json", message="not valid JSON")
    credentials = _hub_with_credentials(tmp_path, local=(problem,))
    rig = build_rig(hidden_environment=credentials.names)
    wired.wire(agent_sessions=rig.control)

    response = wired.client.post(
        BASE, json={"project": "demo", "workdir_id": WORKDIR_ID}, headers=OWN_ORIGIN
    )

    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["type"] == "urn:agent-hub:problem:hub-local-invalid"
    assert response.json()["code"] == "hub_local_invalid"
    assert "hub.local.json" in response.json()["detail"]
    assert [call for call in rig.driver.calls if call.method == "start"] == []
    assert rig.store.list(project=None, status=None, kind="local") == ()
