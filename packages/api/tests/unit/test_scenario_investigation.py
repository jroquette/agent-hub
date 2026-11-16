import json
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from agent_hub.api.agent_session_runtime import HubCredentials
from agent_hub.api.scenario_investigation import InvestigationRestrictions, ScenarioInvestigations
from agent_hub.core.agent_sessions.agent_session import CreateAgentSession, WorkdirList
from agent_hub.core.agent_sessions.control import AgentSessionCommands
from agent_hub.core.testing.builders import an_environments_document
from agent_hub.core.testing.hub_fakes import FakeHub, FakeHubFileReader, InMemoryHubRegistry
from agent_hub.core.testing.read_model_builders import a_workdir, an_agent_session

pytestmark = pytest.mark.anyio

RUNNING = "0.9.0"
RUN = "walk-1"
STEP = "order-held"
GATE = f"{STEP}__investigation"


def a_paused_record() -> list[dict[str, Any]]:
    """A scenario run's record, paused at its first investigation."""
    return [
        {"event": "start", "run": RUN, "scenario": "order-walk", "environment": "staging"}
        | {"mode": "interactive", "kind": "scenario", "ts": "2026-10-21T10:00:00+00:00"},
        {"event": "step_start", "node": STEP, "attempt": 1},
        {"event": "step_end", "node": STEP, "attempt": 1, "status": "failed"}
        | {"failure_kind": "timeout"},
        {"event": "investigation", "step": STEP, "gate": GATE, "number": 1}
        | {"step_attempt": 1, "failure_kind": "timeout"},
        {"event": "gate", "node": GATE, "attempt": 1, "form": "choice"},
    ]


def a_hub(tmp_path: Path) -> Path:
    """A hub folder holding the paused run's record."""
    hub = tmp_path / "work" / "demo-hub"
    folder = hub / ".agent-runs" / "workflows" / RUN
    folder.mkdir(parents=True)
    lines = "".join(json.dumps(line) + "\n" for line in a_paused_record())
    (folder / "records.jsonl").write_text(lines, encoding="utf-8")
    return hub


def credentials_of(hub: Path) -> HubCredentials:
    """The credentials of ``hub``, registered and read through fakes."""
    document = an_environments_document()
    document["platform"]["version"] = RUNNING
    registry = InMemoryHubRegistry()
    registry.add(str(hub))
    reader = FakeHubFileReader({str(hub): FakeHub(hub_json=json.dumps(document).encode())})
    return HubCredentials(registry=registry, reader=reader, running_version=RUNNING)


def a_control() -> Mock:
    """A control that lists the hub's workdir and answers every start with one session."""
    control = Mock(spec=AgentSessionCommands)
    control.workdirs.return_value = WorkdirList(items=(a_workdir(),))
    control.create.return_value = an_agent_session()
    return control


async def test_starts_investigation_in_default_mode_when_server_starts_it(tmp_path: Path) -> None:
    control = a_control()
    restrictions = InvestigationRestrictions(credentials_of(a_hub(tmp_path)))
    investigations = ScenarioInvestigations(control=control, restrictions=restrictions)

    await investigations.open(RUN)

    control.create.assert_awaited_once()
    (request,) = control.create.await_args.args
    assert isinstance(request, CreateAgentSession)
    assert request.mode == "default"
