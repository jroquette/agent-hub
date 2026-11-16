import pytest

from agent_hub.api.dependencies import parse_filter
from agent_hub.api.rfc9457 import InvalidParameterError
from agent_hub.core.readmodels.filters import PageRequest, SessionFilter


def test_builds_filter_when_parameters_valid() -> None:
    assert parse_filter(PageRequest, project="demo", limit=5) == PageRequest(
        project="demo", limit=5
    )


def test_names_first_field_of_rule_when_cross_field_rule_fails() -> None:
    with pytest.raises(InvalidParameterError) as raised:
        parse_filter(SessionFilter, cost_min=5, cost_max=1)

    assert raised.value.parameter == "cost_min"
    assert "cost_min must not be above cost_max" in raised.value.reason


def test_names_field_when_single_field_invalid() -> None:
    with pytest.raises(InvalidParameterError) as raised:
        parse_filter(PageRequest, limit=0)

    assert raised.value.parameter == "limit"


@pytest.mark.parametrize(
    "path",
    ["/api/v1/sessions", "/api/v1/hubs", "/api/v1/events/stream", "/api/v1/collector/status"],
)
def test_answers_not_implemented_naming_route_when_port_not_wired(
    client: object, path: str
) -> None:
    response = client.get(path)  # type: ignore[attr-defined]

    assert response.status_code == 501
    assert response.json()["detail"].endswith("is not implemented in this build")
