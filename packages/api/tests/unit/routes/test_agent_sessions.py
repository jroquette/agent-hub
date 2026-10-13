from typing import Any
from unittest.mock import Mock

import pytest

from agent_hub.core.agent_sessions.agent_session import (
    AgentSessionList,
    CloudSessionList,
    MessageAccepted,
    ResumableList,
    WorkdirList,
)
from agent_hub.core.agent_sessions.cloud import CloudSessionCommands
from agent_hub.core.agent_sessions.control import AgentSessionCommands
from agent_hub.core.agent_sessions.driver import DriverCapabilities
from agent_hub.core.agent_sessions.records import LogRecordPage
from agent_hub.core.testing.read_model_builders import (
    AGENT_SESSION_ID,
    WORKDIR_ID,
    a_cloud_session,
    a_log_record,
    a_workdir,
    an_agent_session,
)

# Writes need the server's own Origin (local_security.py).
OWN_ORIGIN = {"Origin": "http://127.0.0.1:7420"}
BASE = "/api/v1/agent-sessions"
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
    for method in ("interrupt", "answer", "change_settings", "close"):
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
        ("post", f"{ONE}/interrupt", None, 202, "interrupt"),
        ("post", f"{ONE}/permissions/req-1", {"decision": "allow"}, 200, "answer"),
        ("post", f"{ONE}/settings", {"mode": "plan"}, 200, "change_settings"),
        ("post", f"{ONE}/close", None, 200, "close"),
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
