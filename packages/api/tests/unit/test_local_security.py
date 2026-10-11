from typing import Any

import pytest

from agent_hub.api.local_security import (
    CONTENT_SECURITY_POLICY,
    allowed_hosts,
    allowed_origins,
)


def test_allows_loopback_names_with_port_when_hosts_listed() -> None:
    assert allowed_hosts(7420) == {"127.0.0.1:7420", "localhost:7420", "[::1]:7420"}


def test_allows_http_origins_of_hosts_when_origins_listed() -> None:
    assert allowed_origins(8001) == {
        "http://127.0.0.1:8001",
        "http://localhost:8001",
        "http://[::1]:8001",
    }


@pytest.mark.parametrize("directive", ["script-src", "style-src", "font-src", "connect-src"])
def test_limits_directive_to_self_when_policy_built(directive: str) -> None:
    assert f"{directive} 'self'" in CONTENT_SECURITY_POLICY.split("; ")


@pytest.mark.parametrize(
    "host", ["attacker.example", "127.0.0.1", "127.0.0.1:7421", "localhost.attacker.example:7420"]
)
def test_answers_forbidden_problem_when_host_not_loopback_at_port(client: Any, host: str) -> None:
    response = client.get("/api/v1/openapi.json", headers={"Host": host})

    assert response.status_code == 403
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["title"] == "Forbidden host"


@pytest.mark.parametrize("host", ["127.0.0.1:7420", "localhost:7420", "[::1]:7420"])
def test_serves_request_when_host_is_loopback_at_port(client: Any, host: str) -> None:
    response = client.get("/api/v1/openapi.json", headers={"Host": host})

    assert response.status_code == 200
