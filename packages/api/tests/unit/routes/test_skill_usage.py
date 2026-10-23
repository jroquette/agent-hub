from typing import Any

from agent_hub.core.readmodels.filters import Scope
from agent_hub.core.testing.read_model_builders import a_usage_report

USAGE = "/api/v1/skill-usage"


def test_returns_usage_report_when_port_answers(wired: Any) -> None:
    wired.hubs.skill_usage_reports["demo"] = a_usage_report()

    response = wired.client.get(USAGE, params={"project": "demo"})

    assert response.status_code == 200, response.text
    assert response.json() == a_usage_report().model_dump(mode="json")
    assert wired.hubs.calls[-1] == ("skill_usage_report", (Scope(project="demo"), 30))


def test_passes_usage_window_when_days_given(wired: Any) -> None:
    response = wired.client.get(USAGE, params={"days": 7})

    assert response.status_code == 200, response.text
    assert response.json() == {"days": 7, "items": [], "truncated": False}
    assert wired.hubs.calls[-1] == ("skill_usage_report", (Scope(), 7))


def test_answers_400_for_usage_when_days_not_a_window(wired: Any) -> None:
    response = wired.client.get(USAGE, params={"days": 14})

    assert response.status_code == 400
    assert response.headers["content-type"] == "application/problem+json"
    assert [(e["location"], e["parameter"]) for e in response.json()["errors"]] == [
        ("query", "days")
    ]
    assert not [call for call in wired.hubs.calls if call[0] == "skill_usage_report"]
