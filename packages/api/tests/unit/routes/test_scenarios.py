"""``/scenario-runs``: the investigation session hub web starts for a paused scenario run
(P-7, AM-2, AM-9, AC-350.20, AC-350.22, AC-350.41)."""

import json
from pathlib import Path
from typing import Any

import pytest

from agent_hub.api.agent_session_runtime import HubCredentials
from agent_hub.api.scenario_investigation import ScenarioInvestigations
from agent_hub.core.agent_sessions.driver import StartSpec
from agent_hub.core.testing.agent_session_rig import Rig, build_rig
from agent_hub.core.testing.builders import an_environments_document
from agent_hub.core.testing.hub_fakes import FakeHub, FakeHubFileReader, InMemoryHubRegistry

RUNNING = "0.9.0"
RUN = "walk-1"
STEP = "order-held"
GATE = f"{STEP}__investigation"
ROUTE = f"/api/v1/scenario-runs/{RUN}/investigation"
ENV_FILE = "demo-api/environment/.env.staging"
# Built at run time from parts: a synthetic value, never a literal secret in the repo.
SECRET = "x-sec" + "ret-y"


def a_record(*, paused: bool = True) -> list[dict[str, Any]]:
    """A scenario run's record: paused at its first investigation, or ended after it."""
    record: list[dict[str, Any]] = [
        {"event": "start", "run": RUN, "scenario": "order-walk", "environment": "staging"}
        | {"mode": "interactive", "kind": "scenario", "ts": "2026-10-21T10:00:00+00:00"},
        {"event": "step_start", "node": STEP, "attempt": 1},
        {"event": "step_end", "node": STEP, "attempt": 1, "status": "failed"}
        | {"failure_kind": "timeout"},
        {"event": "investigation", "step": STEP, "gate": GATE, "number": 1}
        | {"step_attempt": 1, "failure_kind": "timeout"},
        {"event": "gate", "node": GATE, "attempt": 1, "form": "choice"},
    ]
    if not paused:
        record += [
            {"event": "decision", "node": GATE, "attempt": 1, "choice": "stop"},
            {"event": "step_end", "node": GATE, "attempt": 1, "status": "ok"},
            {"event": "end", "status": "cancelled"},
        ]
    return record


def a_hub(tmp_path: Path, record: list[dict[str, Any]]) -> Path:
    """A hub ``demo`` whose ``staging`` reads the env file of its sibling repo, and the run."""
    hub = tmp_path / "work" / "demo-hub"
    (hub / "actions" / "orders").mkdir(parents=True)
    env_file = tmp_path / "work" / ENV_FILE
    env_file.parent.mkdir(parents=True)
    env_file.write_text(f"DEMO_DB_URL={SECRET}\n", encoding="utf-8")
    folder = hub / ".agent-runs" / "workflows" / RUN
    folder.mkdir(parents=True)
    lines = "".join(json.dumps(line) + "\n" for line in record)
    (folder / "records.jsonl").write_text(lines, encoding="utf-8")
    return hub


def a_reader(hub: Path) -> tuple[InMemoryHubRegistry, FakeHubFileReader]:
    document = an_environments_document()
    document["platform"]["version"] = RUNNING
    document["environments"]["staging"]["credentials"] = {
        "aws_profile": "demo-staging",
        "env": ["DEMO_DB_URL"],
        "env_file": ENV_FILE,
    }
    registry = InMemoryHubRegistry()
    registry.add(str(hub))
    return registry, FakeHubFileReader({str(hub): FakeHub(hub_json=json.dumps(document).encode())})


@pytest.fixture
def investigation(wired: Any, tmp_path: Path) -> Any:
    """Wires the investigation route over a real control (fake driver) and a tmp hub."""

    def wire(record: list[dict[str, Any]]) -> tuple[Rig, Path]:
        hub = a_hub(tmp_path, record)
        registry, reader = a_reader(hub)
        credentials = HubCredentials(registry=registry, reader=reader, running_version=RUNNING)
        rig = build_rig(hidden_environment=credentials.names)
        investigations = ScenarioInvestigations(
            hubs=lambda: [("demo", str(hub))], control=rig.control, credentials=credentials
        )
        wired.wire(agent_sessions=rig.control, scenario_investigations=investigations)
        return rig, hub

    return wire


def _origin(wired: Any) -> dict[str, str]:
    """The server's own ``Origin`` (the strict writes want it): the test client's base URL."""
    return {"Origin": str(wired.client.base_url).rstrip("/")}


def _starts(rig: Rig) -> list[StartSpec]:
    return [call.args[0] for call in rig.driver.calls if call.method == "start"]  # type: ignore[misc]


def test_starts_one_read_only_session_when_investigation_requested_twice(
    wired: Any, investigation: Any
) -> None:
    rig, hub = investigation(a_record())

    first = wired.client.post(ROUTE, json={}, headers=_origin(wired))
    second = wired.client.post(ROUTE, json={}, headers=_origin(wired))

    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["agent_session_id"] == second.json()["agent_session_id"]
    assert (first.json()["started"], second.json()["started"]) == (True, False)
    assert first.json()["investigation"] == 1
    assert first.headers["Location"] == f"/api/v1/agent-sessions/{first.json()['agent_session_id']}"
    (spec,) = _starts(rig)
    env_file = (hub.parent / ENV_FILE).resolve()
    assert spec.mode == "default"
    assert spec.cwd == "/hubs/demo-hub"
    assert spec.tool_policy is not None
    assert spec.tool_policy.env_files == (str(env_file),)
    assert spec.tool_policy.run_id == RUN
    assert spec.tool_policy.workdir == str(hub.resolve())
    assert spec.hidden_environment.env == frozenset({"DEMO_DB_URL", "DEMO_LIVE_DB_URL"})
    assert "demo-staging" in spec.hidden_environment.aws_profiles
    assert spec.system_prompt is not None
    assert f"./hub scenario propose --run {RUN}" in spec.system_prompt
    assert "./hub action run" in spec.system_prompt
    assert SECRET not in spec.model_dump_json()
    assert SECRET not in first.text + second.text
    link = hub / ".agent-runs" / "workflows" / RUN / "investigation-1.session"
    assert link.read_text(encoding="utf-8").strip() == first.json()["agent_session_id"]


def test_returns_409_conflict_when_investigation_run_not_paused(
    wired: Any, investigation: Any
) -> None:
    rig, hub = investigation(a_record(paused=False))

    response = wired.client.post(ROUTE, json={}, headers=_origin(wired))
    unknown = wired.client.post(
        "/api/v1/scenario-runs/other-run/investigation", json={}, headers=_origin(wired)
    )

    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "not_paused"
    assert unknown.status_code == 404
    assert _starts(rig) == []
    assert not (hub / ".agent-runs" / "workflows" / RUN / "investigation-1.session").exists()


def test_sends_message_when_investigation_chat(wired: Any, investigation: Any) -> None:
    rig, _hub = investigation(a_record())
    started = wired.client.post(ROUTE, json={}, headers=_origin(wired)).json()

    sent = wired.client.post(
        f"/api/v1/agent-sessions/{started['agent_session_id']}/messages",
        json={"text": "Look at the order's queue first."},
        headers=_origin(wired),
    )

    assert sent.status_code == 202
    texts = [call.args[0] for call in rig.driver.calls if call.method == "send"]
    assert texts[-1] == "Look at the order's queue first."
