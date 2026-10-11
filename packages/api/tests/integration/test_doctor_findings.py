"""``/doctor/findings`` on the composed app equals ``hub doctor --json`` on the same hub
(AC-200.35, D22): the rules, their order and each finding's fields."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from agent_hub.cli.main import app as hub_cli

FIELDS = ("rule", "severity", "path", "line", "message", "fix")


def _doctor_json(hub: Path, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    monkeypatch.chdir(hub)
    result = CliRunner().invoke(hub_cli, ["doctor", "--json"])
    assert result.exit_code in {0, 1}, result.output
    findings: list[dict[str, Any]] = json.loads(result.stdout)["findings"]
    return findings


def _api_findings(composed: Any, project: str) -> list[dict[str, Any]]:
    response = composed.client.get("/api/v1/doctor/findings", params={"project": project})
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    assert {item["project"] for item in items} <= {project}
    return [{field: item[field] for field in FIELDS} for item in items]


def test_equals_doctor_json_when_registered_hub_has_findings(
    composed: Any, make_hub: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = make_hub()
    # A drifted managed file and a missing brain note give findings of several rules.
    (hub / "AGENTS.md").write_text("# edited by hand\n", encoding="utf-8")
    (hub / "brain" / "now.md").unlink()
    assert composed.client.post("/api/v1/hubs", json={"path": str(hub)}).status_code == 201

    from_api = _api_findings(composed, "demo")
    from_cli = _doctor_json(hub, monkeypatch)

    assert len({finding["rule"] for finding in from_cli}) > 1
    assert from_api == from_cli


def test_lists_only_scoped_project_when_two_hubs_registered(
    composed: Any, make_hub: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    demo, other = make_hub(), make_hub("other")
    for hub in (demo, other):
        assert composed.client.post("/api/v1/hubs", json={"path": str(hub)}).status_code == 201
    (other / "AGENTS.md").write_text("# edited by hand\n", encoding="utf-8")

    assert _api_findings(composed, "other") == _doctor_json(other, monkeypatch)
    assert _api_findings(composed, "demo") == _doctor_json(demo, monkeypatch)


def test_answers_not_found_problem_when_registered_hub_becomes_unreadable(
    composed: Any, make_hub: Callable[..., Path]
) -> None:
    hub = make_hub()
    assert composed.client.post("/api/v1/hubs", json={"path": str(hub)}).status_code == 201
    (hub / "hub.json").write_text("{not json", encoding="utf-8")

    response = composed.client.get("/api/v1/doctor/findings", params={"project": "demo"})

    assert response.status_code == 404, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert "demo" in response.json()["detail"]
    [view] = composed.client.get("/api/v1/hubs").json()["items"]
    assert view["valid"] is False
