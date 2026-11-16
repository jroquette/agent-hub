from datetime import UTC, datetime
from typing import Any
from unittest.mock import Mock

import pytest

from agent_hub.core.environment_discovery.discovery import (
    DiscoveryNotFoundError,
    EnvironmentDiscovery,
    StartEnvironmentDiscovery,
)
from agent_hub.core.environment_discovery.environment_discoveries import EnvironmentDiscoveries
from agent_hub.core.readmodels.page import Page
from agent_hub.core.testing.read_model_builders import AGENT_SESSION_ID

OWN_ORIGIN = {"Origin": "http://127.0.0.1:7420"}
BASE = "/api/v1/projects/demo/environment-discoveries"
DISCOVERY_ID = "0123456789ab"


def _discovery() -> EnvironmentDiscovery:
    return EnvironmentDiscovery(
        id=DISCOVERY_ID,
        project="demo",
        agent_session_id=AGENT_SESSION_ID,
        repos=("demo-api",),
        environments=("staging",),
        suggest_environments=False,
        created_at=datetime(2026, 10, 20, 9, 0, tzinfo=UTC),
        state="running",
    )


@pytest.fixture
def discoveries(wired: Any) -> Mock:
    port = Mock(spec=EnvironmentDiscoveries)
    port.start.return_value = _discovery()
    port.list.return_value = Page(items=(_discovery(),), total_estimate=1)
    port.get.return_value = _discovery()
    port.discard.return_value = None
    wired.wire(environment_discoveries=port)
    return port


# AC-418.3
def test_starts_discovery_when_body_valid(wired: Any, discoveries: Mock) -> None:
    body = {"repos": ["demo-api"], "environments": ["staging"], "suggest_environments": True}

    response = wired.client.post(BASE, json=body, headers=OWN_ORIGIN)

    assert response.status_code == 200, response.text
    assert response.json()["state"] == "running"
    discoveries.start.assert_awaited_once_with(
        "demo", StartEnvironmentDiscovery.model_validate(body)
    )


# AC-418.3
def test_refuses_start_when_no_repo_picked(wired: Any, discoveries: Mock) -> None:
    response = wired.client.post(BASE, json={"repos": []}, headers=OWN_ORIGIN)

    assert response.status_code == 422
    discoveries.start.assert_not_awaited()


# AC-418.7
def test_refuses_start_when_origin_is_another_site(wired: Any, discoveries: Mock) -> None:
    response = wired.client.post(
        BASE, json={"repos": ["demo-api"]}, headers={"Origin": "http://evil.example"}
    )

    assert response.status_code == 403
    discoveries.start.assert_not_awaited()


# AC-418.6
def test_lists_discoveries_when_asked(wired: Any, discoveries: Mock) -> None:
    response = wired.client.get(BASE)

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [DISCOVERY_ID]
    discoveries.list.assert_awaited_once_with("demo")


# AC-418.6
def test_answers_not_found_when_discovery_unknown(wired: Any, discoveries: Mock) -> None:
    discoveries.get.side_effect = DiscoveryNotFoundError(DISCOVERY_ID)

    response = wired.client.get(f"{BASE}/{DISCOVERY_ID}")

    assert response.status_code == 404
    assert response.json()["title"] == "Discovery not found"


# AC-418.6
def test_refuses_id_when_not_twelve_hex_digits(wired: Any, discoveries: Mock) -> None:
    response = wired.client.get(f"{BASE}/..%2Fsecrets")

    assert response.status_code in {404, 422}
    discoveries.get.assert_not_awaited()


# AC-418.6
def test_discards_discovery_when_deleted(wired: Any, discoveries: Mock) -> None:
    response = wired.client.delete(f"{BASE}/{DISCOVERY_ID}", headers=OWN_ORIGIN)

    assert response.status_code == 204
    discoveries.discard.assert_awaited_once_with("demo", DISCOVERY_ID)


# AC-418.7
def test_refuses_discovery_reads_when_cookie_missing(wired: Any, discoveries: Mock) -> None:
    wired.client.cookies.clear()

    response = wired.client.get(BASE)

    assert response.status_code == 401
    discoveries.list.assert_not_awaited()
