"""``/scenario-runs``: the investigation session hub web starts for a paused scenario run
(P-7, AM-2, AM-9, AC-350.20, AC-350.22, AC-350.41)."""

import json
import shutil
import subprocess
import threading
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from agent_hub.api import scenario_investigation
from agent_hub.api.agent_session_runtime import HubCredentials
from agent_hub.api.run_launcher import ScenarioLaunch
from agent_hub.api.scenario_catalog import ScenarioCatalog, ScenarioCommands
from agent_hub.api.scenario_investigation import InvestigationRestrictions, ScenarioInvestigations
from agent_hub.core.agent_sessions.agent_session import AgentSessionStatus, EndReason
from agent_hub.core.agent_sessions.driver import PastSession, StartSpec
from agent_hub.core.agent_sessions.errors import SessionsUnavailableError
from agent_hub.core.errors import TrackerError
from agent_hub.core.hub_config.effective_environments import (
    EffectiveEnvironments,
    effective_environments,
)
from agent_hub.core.hub_config.local_config import LocalConfig
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ConfigProblem
from agent_hub.core.hubs.hub_registry import HubRegistryError
from agent_hub.core.readmodels.filters import RunFilter
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.scenarios import investigation as proposals
from agent_hub.core.scenarios.investigation import tool_verdict
from agent_hub.core.scenarios.workaround import plan_option
from agent_hub.core.testing import read_model_builders
from agent_hub.core.testing.agent_session_rig import Rig, build_rig
from agent_hub.core.testing.agent_session_store_fakes import InMemoryAgentSessionStore
from agent_hub.core.testing.builders import an_environments_document
from agent_hub.core.testing.fakes import FakeTrackerBackend, InMemoryTrackerClient, TrackerState
from agent_hub.core.testing.hub_fakes import FakeHub, FakeHubFileReader, InMemoryHubRegistry
from agent_hub.core.testing.read_model_builders import WORKDIR_ID
from agent_hub.core.testing.session_driver_fakes import InMemorySessionDriver
from agent_hub.core.workflows.gates import GateAnswer
from agent_hub.generator.action_discovery import discover_actions
from agent_hub.generator.finding_issues import HeldIssue as HeldFindingIssue
from agent_hub.generator.finding_issues import IssueMarked, marked_issue, retake_issue

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


def a_reader(
    hub: Path, *, local: tuple[ConfigProblem, ...] | None = None
) -> tuple[InMemoryHubRegistry, FakeHubFileReader]:
    document = an_environments_document()
    document["platform"]["version"] = RUNNING
    document["environments"]["staging"]["credentials"] = {
        "aws_profile": "demo-staging",
        "env": ["DEMO_DB_URL"],
        "env_file": ENV_FILE,
    }
    registry = InMemoryHubRegistry()
    registry.add(str(hub))
    fake = FakeHub(hub_json=json.dumps(document).encode())
    if local is not None:
        fake.local = local
    return registry, FakeHubFileReader({str(hub): fake})


@pytest.fixture
def investigation(wired: Any, tmp_path: Path) -> Any:
    """Wires the investigation route over a real control (fake driver) and a tmp hub."""

    def wire(
        record: list[dict[str, Any]],
        *,
        local: tuple[ConfigProblem, ...] | None = None,
        driver: InMemorySessionDriver | None = None,
        store: InMemoryAgentSessionStore | None = None,
        hub: Path | None = None,
    ) -> tuple[Rig, Path]:
        hub = hub or a_hub(tmp_path, record)
        registry, reader = a_reader(hub, local=local)
        credentials = HubCredentials(registry=registry, reader=reader, running_version=RUNNING)
        restrictions = InvestigationRestrictions(credentials)
        rig = build_rig(
            hidden_environment=credentials.names,
            restriction_of=restrictions.restriction_of,
            driver=driver,
            store=store,
        )
        investigations = ScenarioInvestigations(control=rig.control, restrictions=restrictions)
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
    # Reads stay in the hub and its declared repos, never the folder holding them (E-13).
    assert spec.tool_policy.read_roots == (
        str(hub.resolve()),
        str((hub.parent / "demo-api").resolve()),
    )
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


LINK = Path(".agent-runs", "workflows", RUN, "investigation-1.session")
UNKNOWN_SESSION = "01929a4e-7a11-7c00-8a00-00000000beef"


def _started(response: Any) -> tuple[int, bool]:
    return response.status_code, response.json().get("started")


@pytest.mark.parametrize("content", ["", f"{UNKNOWN_SESSION}\n"])
def test_takes_link_over_when_investigation_link_empty_or_unknown(
    wired: Any, investigation: Any, tmp_path: Path, *, content: str
) -> None:
    hub = a_hub(tmp_path, a_record())
    (hub / LINK).write_text(content, encoding="utf-8")
    rig, _hub = investigation(a_record(), hub=hub)

    response = wired.client.post(ROUTE, json={}, headers=_origin(wired))

    assert _started(response) == (201, True)
    assert response.json()["agent_session_id"] != UNKNOWN_SESSION
    assert (hub / LINK).read_text(encoding="utf-8").strip() == response.json()["agent_session_id"]
    assert len(_starts(rig)) == 1


class _RefusingDriver(InMemorySessionDriver):
    async def start(self, spec: StartSpec) -> Any:  # noqa: ARG002 -- the port's signature
        raise SessionsUnavailableError("claude is not installed")


def test_removes_link_when_investigation_start_fails(wired: Any, investigation: Any) -> None:
    _rig, hub = investigation(a_record(), driver=_RefusingDriver())

    response = wired.client.post(ROUTE, json={}, headers=_origin(wired))

    assert response.status_code == 503
    assert not (hub / LINK).exists()


def test_stops_session_when_investigation_link_write_fails(
    wired: Any, investigation: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, hub = investigation(a_record())

    def refuse(_link: Path, _session_id: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("agent_hub.api.scenario_investigation._write_link", refuse)

    response = wired.client.post(ROUTE, json={}, headers=_origin(wired))

    assert response.status_code == 500
    assert [call.method for call in rig.driver.calls].count("close") == 1
    (session,) = rig.store.list(project=None, status=None, kind="local")
    assert session.status == "ended"
    assert (hub / LINK).exists()


def test_returns_409_conflict_when_investigation_hub_local_invalid(
    wired: Any, investigation: Any
) -> None:
    problem = ConfigProblem(path="hub.local.json", message="not valid JSON")
    rig, hub = investigation(a_record(), local=(problem,))

    response = wired.client.post(ROUTE, json={}, headers=_origin(wired))

    assert response.status_code == 409
    assert response.json()["code"] == "hub_local_invalid"
    assert "hub.local.json" in response.json()["detail"]
    assert _starts(rig) == []
    assert not (hub / LINK).exists()


def test_returns_422_record_problem_when_investigation_record_too_large_or_broken(
    wired: Any, investigation: Any, tmp_path: Path
) -> None:
    rig, hub = investigation(a_record())
    records = hub / ".agent-runs" / "workflows" / RUN / "records.jsonl"
    # The API's bound on a scenario run's record: 8 MiB.
    records.write_bytes(b" " * (8 * 1024 * 1024) + b"\n")
    too_large = wired.client.post(ROUTE, json={}, headers=_origin(wired))
    records.write_text("not one JSON object\n{}\n", encoding="utf-8")
    broken = wired.client.post(ROUTE, json={}, headers=_origin(wired))

    assert (too_large.status_code, too_large.json()["code"]) == (422, "record_too_large")
    assert (broken.status_code, broken.json()["code"]) == (422, "record_unreadable")
    assert _starts(rig) == []


def test_denies_other_tools_when_investigation_session_policy_built(
    wired: Any, investigation: Any
) -> None:
    rig, _hub = investigation(a_record())
    wired.client.post(ROUTE, json={}, headers=_origin(wired))
    (spec,) = _starts(rig)
    assert spec.tool_policy is not None

    for tool in ("Edit", "MultiEdit", "WebFetch", "Task", "NotebookEdit", "mcp__demo__query"):
        assert not tool_verdict(spec.tool_policy, tool, {"file_path": "README.md"}).allowed


def _restart(rig: Rig, session_id: str) -> tuple[InMemorySessionDriver, InMemoryAgentSessionStore]:
    """A restarted server's store and driver: a fresh store holding only the session's row,
    ended ``server_stopped`` (so the first control's pump, still running, never touches it),
    and a driver that still lists its Claude conversation."""
    row = rig.store.get(session_id)
    claude = row.claude_session_id
    assert claude is not None
    ended = row.model_copy(
        update={
            "status": AgentSessionStatus.ENDED,
            "end_reason": EndReason.SERVER_STOPPED,
            "ended_at": rig.clock(),
            "last_seq": 0,
            "open_permission": None,
        }
    )
    store = InMemoryAgentSessionStore()
    store.create(ended)
    past = PastSession(session_id=claude, last_activity=rig.clock(), cwd="/hubs/demo-hub")
    return InMemorySessionDriver(past_sessions=[past]), store


def test_keeps_restriction_when_investigation_session_reopened_after_restart(
    wired: Any, investigation: Any
) -> None:
    first, hub = investigation(a_record())
    session_id = wired.client.post(ROUTE, json={}, headers=_origin(wired)).json()[
        "agent_session_id"
    ]
    driver, store = _restart(first, session_id)
    fresh, _hub = investigation(a_record(), driver=driver, store=store, hub=hub)

    sent = wired.client.post(
        f"/api/v1/agent-sessions/{session_id}/messages",
        json={"text": "Go on."},
        headers=_origin(wired),
    )

    assert sent.status_code == 202
    (spec,) = _starts(fresh)
    assert spec.resume is not None
    assert spec.tool_policy is not None
    assert spec.tool_policy.run_id == RUN
    assert spec.system_prompt is not None
    assert f"./hub scenario propose --run {RUN}" in spec.system_prompt
    assert "DEMO_DB_URL" in spec.hidden_environment.env


def test_refuses_reopen_when_investigation_restriction_cannot_be_rebuilt(
    wired: Any, investigation: Any
) -> None:
    first, hub = investigation(a_record())
    session_id = wired.client.post(ROUTE, json={}, headers=_origin(wired)).json()[
        "agent_session_id"
    ]
    driver, store = _restart(first, session_id)
    records = hub / ".agent-runs" / "workflows" / RUN / "records.jsonl"
    records.write_text("not one JSON object\n{}\n", encoding="utf-8")
    fresh, _hub = investigation(a_record(), driver=driver, store=store, hub=hub)

    sent = wired.client.post(
        f"/api/v1/agent-sessions/{session_id}/messages",
        json={"text": "Go on."},
        headers=_origin(wired),
    )

    assert sent.status_code == 409
    assert sent.json()["type"] == "urn:agent-hub:problem:agent-session-restriction-unavailable"
    assert _starts(fresh) == []


def _start_and_restart(wired: Any, investigation: Any, **wiring: Any) -> tuple[str, Rig, Path]:
    """Start the investigation, then wire a restarted server (``wiring`` changes it)."""
    first, hub = investigation(a_record())
    session_id = wired.client.post(ROUTE, json={}, headers=_origin(wired)).json()[
        "agent_session_id"
    ]
    driver, store = _restart(first, session_id)
    wiring.setdefault("driver", driver)
    fresh, _hub = investigation(a_record(), store=store, hub=hub, **wiring)
    return session_id, fresh, hub


def _message(wired: Any, session_id: str) -> Any:
    return wired.client.post(
        f"/api/v1/agent-sessions/{session_id}/messages",
        json={"text": "Go on."},
        headers=_origin(wired),
    )


LOCAL_PROBLEM = ConfigProblem(path="hub.local.json", message="not valid JSON")


def test_refuses_reopen_when_investigation_hub_local_invalid(
    wired: Any, investigation: Any
) -> None:
    session_id, fresh, _hub = _start_and_restart(wired, investigation, local=(LOCAL_PROBLEM,))

    sent = _message(wired, session_id)

    assert sent.status_code == 409
    assert sent.json()["code"] == "hub_local_invalid"
    assert _starts(fresh) == []
    assert fresh.store.get(session_id).status == "ended"


def test_refuses_reopen_when_ordinary_session_hub_local_invalid(
    wired: Any, investigation: Any
) -> None:
    first, hub = investigation(a_record())
    created = wired.client.post(
        "/api/v1/agent-sessions",
        json={"project": "demo", "workdir_id": WORKDIR_ID, "prompt": "Hello."},
        headers=_origin(wired),
    )
    session_id = created.json()["id"]
    driver, store = _restart(first, session_id)
    fresh, _hub = investigation(
        a_record(), store=store, hub=hub, driver=driver, local=(LOCAL_PROBLEM,)
    )

    sent = _message(wired, session_id)

    assert sent.status_code == 409
    assert sent.json()["code"] == "hub_local_invalid"
    assert _starts(fresh) == []
    assert fresh.store.get(session_id).status == "ended"


def test_refuses_reopen_when_investigation_runs_folder_unreadable(
    wired: Any, investigation: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id, fresh, hub = _start_and_restart(wired, investigation)
    runs = hub / ".agent-runs" / "workflows"
    listed = scenario_investigation._entries

    def refuse(folder: Path) -> list[Path]:
        if folder == runs:
            raise PermissionError(13, "Permission denied")
        return listed(folder)

    monkeypatch.setattr(scenario_investigation, "_entries", refuse)

    sent = _message(wired, session_id)

    assert sent.status_code == 409
    assert sent.json()["type"] == "urn:agent-hub:problem:agent-session-restriction-unavailable"
    assert "investigation session" not in sent.json()["detail"]
    assert _starts(fresh) == []


def test_skips_vanished_run_folder_when_investigation_restriction_scanned(
    wired: Any, investigation: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id, fresh, hub = _start_and_restart(wired, investigation)
    gone = hub / ".agent-runs" / "workflows" / "gone-run"
    gone.mkdir()
    (gone / "investigation-1.session").write_text(f"{UNKNOWN_SESSION}\n", encoding="utf-8")
    listed = scenario_investigation._entries

    def vanish(folder: Path) -> list[Path]:
        if folder == gone:
            raise FileNotFoundError(2, "No such file or directory")
        return listed(folder)

    monkeypatch.setattr(scenario_investigation, "_entries", vanish)

    sent = _message(wired, session_id)

    assert sent.status_code == 202
    (spec,) = _starts(fresh)
    assert spec.tool_policy is not None


def test_refuses_reopen_when_investigation_link_unreadable(
    wired: Any, investigation: Any, tmp_path: Path
) -> None:
    session_id, fresh, hub = _start_and_restart(wired, investigation)
    other = hub / ".agent-runs" / "workflows" / "other-run"
    other.mkdir()
    (other / "investigation-1.session").symlink_to(tmp_path / "elsewhere")

    sent = _message(wired, session_id)

    assert sent.status_code == 409
    assert sent.json()["type"] == "urn:agent-hub:problem:agent-session-restriction-unavailable"
    assert _starts(fresh) == []


class _UnlistingDriver(InMemorySessionDriver):
    async def list_resumable(self, cwd: str) -> Any:  # noqa: ARG002 -- the port's signature
        raise SessionsUnavailableError("claude is not installed")


def test_keeps_link_when_investigation_resumable_unreadable(wired: Any, investigation: Any) -> None:
    session_id, fresh, hub = _start_and_restart(wired, investigation, driver=_UnlistingDriver())

    response = wired.client.post(ROUTE, json={}, headers=_origin(wired))

    assert response.status_code == 503
    assert _starts(fresh) == []
    assert (hub / LINK).read_text(encoding="utf-8").strip() == session_id


class _UnreadableRegistry(InMemoryHubRegistry):
    def entries(self) -> Any:
        raise HubRegistryError("the hub registry is not valid JSON")


def test_names_registry_when_credential_injection_registry_unreadable(wired: Any) -> None:
    credentials = HubCredentials(
        registry=_UnreadableRegistry(), reader=FakeHubFileReader({}), running_version=RUNNING
    )
    rig = build_rig(hidden_environment=credentials.names)
    wired.wire(agent_sessions=rig.control)

    response = wired.client.post(
        "/api/v1/agent-sessions",
        json={"project": "demo", "workdir_id": WORKDIR_ID},
        headers=_origin(wired),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "hub_registry_unreadable"
    assert "registry" in response.json()["detail"]
    assert "hub.local.json" not in response.json()["detail"]
    assert _starts(rig) == []


def test_returns_409_conflict_when_investigation_policy_refused(
    wired: Any, investigation: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, hub = investigation(a_record())
    # A hub that is the home folder: reads there would reach the developer's own credentials.
    monkeypatch.setenv("HOME", str(hub))

    response = wired.client.post(ROUTE, json={}, headers=_origin(wired))

    assert response.status_code == 409
    assert response.json()["code"] == "workspace_root"
    assert response.json()["type"] == "urn:agent-hub:problem:workflow-run-workspace-root"
    assert _starts(rig) == []
    assert not (hub / LINK).exists()


def a_second_investigation_record() -> list[dict[str, Any]]:
    """A scenario run whose first investigation was retried and whose second is open."""
    return [
        *a_record(),
        {"event": "decision", "node": GATE, "attempt": 1, "choice": "retry"},
        {"event": "step_end", "node": GATE, "attempt": 1, "status": "ok"},
        {"event": "step_start", "node": STEP, "attempt": 2},
        {"event": "step_end", "node": STEP, "attempt": 2, "status": "failed"}
        | {"failure_kind": "timeout"},
        {"event": "investigation", "step": STEP, "gate": GATE, "number": 2}
        | {"step_attempt": 2, "failure_kind": "timeout"},
        {"event": "gate", "node": GATE, "attempt": 2, "form": "choice"},
    ]


def test_finds_later_link_when_investigation_earlier_link_vanishes(
    wired: Any, investigation: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = a_second_investigation_record()
    first, hub = investigation(record)
    started = wired.client.post(ROUTE, json={}, headers=_origin(wired)).json()
    assert started["investigation"] == 2
    folder = hub / ".agent-runs" / "workflows" / RUN
    vanishing = folder / "investigation-1.session"
    vanishing.write_text(f"{UNKNOWN_SESSION}\n", encoding="utf-8")
    driver, store = _restart(first, started["agent_session_id"])
    fresh, _hub = investigation(record, store=store, hub=hub, driver=driver)
    read = scenario_investigation._read_link

    def vanish(link: Path) -> str | None:
        if link == vanishing:
            raise FileNotFoundError(2, "No such file or directory")
        return read(link)

    monkeypatch.setattr(scenario_investigation, "_read_link", vanish)

    sent = _message(wired, started["agent_session_id"])

    assert sent.status_code == 202
    (spec,) = _starts(fresh)
    assert spec.tool_policy is not None
    assert spec.tool_policy.run_id == RUN


# The scenario routes (plan T12; AC-350.21 (API), .22, .23, .30; AM-5, AM-7, AM-8, AM-14).
# A tmp hub holds the ``demo`` pack's actions and the ``order-walk`` scenario, committed in a
# git checkout with its own identity; the launcher is a fake that records each call (its
# ``resume`` appends what the CLI would), so no child process runs.

ACTION_DOCUMENT = """\
version: 1
name: {name}
description: A demo {effect}
effect: {effect}
runtime: sh
script: scripts/{name}.sh
inputs:
  target: {{type: service, required: true}}
  ref: {{type: string}}
output_format:
  type: object
  properties: {{order: {{type: string}}, status: {{type: string}}}}
"""
WALK = """\
version: 1
kind: scenario
name: order-walk
revision: 1
description: One demo order from send to hold
inputs:
  ref: {type: string, required: true}
nodes:
  - id: send-order
    type: action
    action: send-order
    with: {target: api, ref: $INPUTS.ref}
  - id: order-held
    type: expect
    depends_on: [send-order]
    action: demo/get-order
    with: {target: api, ref: $INPUTS.ref}
    every: 10s
    timeout: 5m
    until_when: "$self.output.status == 'ON_HOLD'"
    capture: {order_id: $self.output.order}
"""
WALK_RUN = "walk-2"
WALK_GATE = "order-held__investigation"
WALK_RECORDS = Path(".agent-runs", "workflows", WALK_RUN, "records.jsonl")


def _git(hub: Path, *args: str) -> None:
    found = shutil.which("git")
    assert found is not None
    identity = ("-c", "user.name=Demo Dev", "-c", "user.email=dev@example.com")
    subprocess.run([found, *identity, *args], cwd=hub, check=True, capture_output=True)  # noqa: S603 - absolute git, fixed arguments


def write_action(hub: Path, name: str, effect: str) -> None:
    pack = hub / "actions" / "demo"
    (pack / "scripts").mkdir(parents=True, exist_ok=True)
    (pack / f"{name}.yaml").write_text(ACTION_DOCUMENT.format(name=name, effect=effect))
    (pack / "scripts" / f"{name}.sh").write_text('printf \'{"summary": "would act"}\'\n')


def a_walk_document() -> dict[str, Any]:
    document = an_environments_document()
    document["platform"]["version"] = RUNNING
    return document


def a_walk_hub(tmp_path: Path) -> Path:
    """A committed hub: ``get-order`` (read), ``send-order`` and ``release-hold`` (writes) and
    the scenario ``order-walk``."""
    hub = tmp_path / "work" / "walk-hub"
    hub.mkdir(parents=True)
    (hub / "hub.json").write_text(json.dumps(a_walk_document()), encoding="utf-8")
    write_action(hub, "get-order", "read")
    write_action(hub, "send-order", "write")
    write_action(hub, "release-hold", "write")
    scenario = hub / "scenarios" / "demo" / "order-walk.yaml"
    scenario.parent.mkdir(parents=True)
    scenario.write_text(WALK)
    _git(hub, "init", "-q", "-b", "main")
    _git(hub, "add", "-A")
    _git(hub, "commit", "-q", "-m", "demo hub")
    return hub


def a_walk_view() -> EffectiveEnvironments:
    return effective_environments(HubConfig.model_validate(a_walk_document()), LocalConfig())


def option_line(hub: Path, option: str, *steps: dict[str, Any], environment: str) -> dict[str, Any]:
    """An option as ``hub scenario propose`` records it: its steps planned now, origin agent."""
    planned = plan_option(
        tuple(proposals.ProposedStep(action=step["action"], inputs=step["with"]) for step in steps),
        entries=discover_actions(hub).actions,
        pack="demo",
        view=a_walk_view(),
        environment=environment,
    )
    return {
        "option_id": option,
        "summary": f"Option {option}",
        "steps": list(steps),
        "plan": [step.model_dump(mode="json") for step in planned],
    }


def a_paused_walk(
    hub: Path, *options: dict[str, Any], environment: str = "live", proposal: int = 1
) -> list[dict[str, Any]]:
    """``order-walk`` paused at its first investigation with one proposal of ``options``."""
    return [
        {"event": "start", "run": WALK_RUN, "workflow": "scenario:order-walk"}
        | {"kind": "scenario", "scenario": "order-walk", "pack": "demo"}
        | {"environment": environment, "mode": "interactive", "ts": "2026-10-22T10:00:00+00:00"},
        {"event": "step_start", "node": "order-held", "attempt": 1},
        {"event": "expect.poll", "node": "order-held", "attempt": 1, "poll": 1, "held": False}
        | {"output": {"status": "OPEN"}},
        {"event": "step_end", "node": "order-held", "attempt": 1, "status": "failed"}
        | {"failure_kind": "timeout"},
        {"event": "investigation", "step": "order-held", "gate": WALK_GATE, "number": 1}
        | {"step_attempt": 1, "failure_kind": "timeout"},
        {"event": "gate", "node": WALK_GATE, "attempt": 1, "form": "choice"},
        a_proposal_line(proposal, *options),
    ]


def a_proposal_line(proposal: int, *options: dict[str, Any]) -> dict[str, Any]:
    finding = {"finding_id": "f1", "title": "Order stays on hold", "text": "The queue is stuck."}
    return {
        "event": "proposal",
        "gate": WALK_GATE,
        "number": 1,
        "proposal": proposal,
        "findings": [finding | {"evidence": "status OPEN after 30 polls"}],
        "options": list(options),
    }


def write_records(hub: Path, records: list[dict[str, Any]]) -> None:
    path = hub / WALK_RECORDS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(line) + "\n" for line in records), encoding="utf-8")


def append_records(hub: Path, *records: dict[str, Any]) -> None:
    with (hub / WALK_RECORDS).open("a", encoding="utf-8") as file:
        file.writelines(json.dumps(line) + "\n" for line in records)


class FakeScenarioLauncher:
    """The scenario launcher's calls, in order; ``resume`` appends the CLI's lines for the
    answer ``decide`` recorded (``stop`` ends the run cancelled)."""

    def __init__(self, hub: Path) -> None:
        self.hub = hub
        self.calls: list[tuple[str, object]] = []
        self.plan_output: tuple[int, bytes] = (0, b"{}")
        self.answer: GateAnswer | None = None

    def start_scenario(self, spec: ScenarioLaunch) -> None:
        self.calls.append(("start", spec))

    def plan_scenario(
        self, hub_path: str, name: str, *, environment: str, inputs: dict[str, str]
    ) -> tuple[int, bytes]:
        self.calls.append(("plan", (name, environment, inputs)))
        return self.plan_output

    def decide(self, hub_path: str, run_id: str, *, gate_id: str, answer: GateAnswer) -> None:
        self.calls.append(("decide", (run_id, gate_id, answer.choice, answer.text)))
        self.answer = answer
        node, attempt = gate_id.split(":")[1], int(gate_id.split(":")[2])
        decision = {"event": "decision", "gate_id": gate_id, "node": node, "attempt": attempt}
        append_records(
            self.hub,
            decision | {"choice": answer.choice, "text": answer.text, "approver": "demo"},
        )

    def resume(self, hub_path: str, run_id: str, *, issue: str | None) -> None:
        self.calls.append(("resume", run_id))
        if self.answer is not None and self.answer.choice == "stop":
            closed = {"event": "step_end", "node": WALK_GATE, "attempt": 1, "status": "ok"}
            append_records(self.hub, closed, {"event": "end", "status": "cancelled"})

    def live_runs(self, hub_path: str) -> dict[str, str | None]:
        return {}


@pytest.fixture
def scenarios(wired: Any, tmp_path: Path) -> Any:
    """The scenario routes over a committed tmp hub, a fake launcher and a fake tracker."""
    hub = a_walk_hub(tmp_path)
    registry = InMemoryHubRegistry()
    registry.add(str(hub))
    reader = FakeHubFileReader({str(hub): FakeHub(hub_json=json.dumps(a_walk_document()).encode())})
    credentials = HubCredentials(registry=registry, reader=reader, running_version=RUNNING)
    backend = FakeTrackerBackend(states={"DEM": (TrackerState(name="Todo", type="unstarted"),)})
    launcher = FakeScenarioLauncher(hub)
    catalog = ScenarioCatalog(credentials=credentials, runs=wired.events)
    commands = ScenarioCommands(
        catalog=catalog,
        launcher=launcher,
        lock=threading.Lock(),
        tracker_of=lambda _config, _hub: InMemoryTrackerClient(backend),
        today=lambda: date(2026, 10, 22),
        mint=lambda: "walk-9",
    )
    wired.wire(scenario_reads=catalog, scenario_commands=commands)
    wired.hub, wired.launcher, wired.backend = hub, launcher, backend
    wired.reader, wired.catalog = reader, catalog
    return wired


def _post(wired: Any, path: str, body: dict[str, Any]) -> Any:
    return wired.client.post(f"/api/v1{path}", json=body, headers=_origin(wired))


READ_OPTION = {"action": "get-order", "with": {"target": "api"}}
WRITE_OPTION = {"action": "release-hold", "with": {"target": "api"}}


def test_lists_scenarios_when_hub_has_scenarios(scenarios: Any) -> None:
    scenarios.events.runs.append(
        read_model_builders.a_run(
            id="walk-1", workflow="scenario:order-walk", status="failed", issue=None
        )
    )

    listed = scenarios.client.get("/api/v1/scenarios", params={"project": "demo"})
    detail = scenarios.client.get("/api/v1/scenarios/demo/order-walk")
    unknown = scenarios.client.get("/api/v1/scenarios/demo/nope")

    assert listed.status_code == 200, listed.text
    (item,) = listed.json()["items"]
    assert (item["name"], item["pack"], item["node_count"]) == ("order-walk", "demo", 2)
    assert item["last_run"]["run_id"] == "walk-1"
    assert item["last_run"]["status"] == "failed"
    assert listed.json()["problems"] == []
    assert detail.status_code == 200, detail.text
    steps = [(step["id"], step["type"], step["action"]) for step in detail.json()["steps"]]
    assert steps == [
        ("send-order", "action", "send-order"),
        ("order-held", "expect", "demo/get-order"),
    ]
    assert [run["run_id"] for run in detail.json()["runs"]] == ["walk-1"]
    assert unknown.status_code == 404
    assert (
        "list_runs",
        RunFilter(project="demo", kind="scenario", limit=200),
    ) in scenarios.events.calls


def a_plan_output(*, draft: bool) -> bytes:
    row = {
        "step": "order-held",
        "type": "expect",
        "action": "demo/get-order",
        "effect": "read",
        "args": {"target": "api", "ref": "<$CTX.order_id from send-order>"},
        "endpoints": {"target": {"service": "demo-api/api", "url": "http://localhost:8000"}} | {},
        "every": "10s",
        "timeout": "5m",
        "content_hash": "sha256:" + "1" * 64,
        "draft": draft,
        "decision": "deny" if draft else "allow",
        "reason_kind": "draft" if draft else "table",
        "reason": "draft action: commit it to run" if draft else None,
        "plan": "draft action: commit it to run" if draft else "runs with values known at run time",
    }
    row["endpoints"]["target"]["resource"] = None
    plan = {
        "scenario": "order-walk",
        "environment": "local",
        "access": "write",
        "production": False,
        "denied": draft,
        "problems": [],
        "rows": [row],
    }
    return json.dumps(plan).encode()


def test_returns_plan_rows_when_scenarios_plan_asked(scenarios: Any) -> None:
    scenarios.launcher.plan_output = (0, a_plan_output(draft=False))
    body = {"environment": "local", "inputs": {"ref": "T-1"}}

    planned = _post(scenarios, "/scenarios/demo/order-walk/plan", body)
    scenarios.launcher.plan_output = (1, a_plan_output(draft=True))
    drafted = _post(scenarios, "/scenarios/demo/order-walk/plan", body)
    missing = _post(scenarios, "/scenarios/demo/order-walk/plan", {"environment": "local"})

    assert planned.status_code == 200, planned.text
    (row,) = planned.json()["rows"]
    assert row["args"]["ref"] == "<$CTX.order_id from send-order>"
    assert row["endpoints"]["target"]["service"] == "demo-api/api"
    assert (row["decision"], row["needs_acceptance"], row["accept_command"]) == (
        "allow",
        False,
        None,
    )
    assert row["plan"] == "runs with values known at run time"
    assert scenarios.launcher.calls[0] == ("plan", ("order-walk", "local", {"ref": "T-1"}))
    (draft,) = drafted.json()["rows"]
    assert drafted.json()["denied"] is True
    assert (draft["decision"], draft["needs_acceptance"]) == ("deny", True)
    assert draft["accept_command"] == (
        "git add -- actions/demo/get-order.yaml actions/demo/scripts/get-order.sh"
        " && git commit -m 'Accept action demo/get-order'"
    )
    # An input the scenario requires is checked before any child runs.
    assert missing.status_code == 422
    assert len(scenarios.launcher.calls) == 2


def test_returns_409_conflict_with_steps_when_scenarios_start_denied(scenarios: Any) -> None:
    path = "/scenarios/demo/order-walk/runs"

    denied = _post(scenarios, path, {"environment": "live", "inputs": {"ref": "T-1"}})
    undeclared = _post(scenarios, path, {"environment": "nowhere", "inputs": {"ref": "T-1"}})
    started = _post(scenarios, path, {"environment": "local", "inputs": {"ref": "T-1"}})

    assert denied.status_code == 409, denied.text
    assert denied.headers["content-type"] == "application/problem+json"
    assert denied.json()["code"] == "denied"
    assert denied.json()["steps"] == ["send-order"]
    assert "step send-order: deny (live is a production environment" in denied.json()["detail"]
    assert "no scenario run was created" in denied.json()["detail"]
    assert (undeclared.status_code, undeclared.json()["code"]) == (409, "undeclared_environment")
    assert started.status_code == 202, started.text
    assert started.json() == {"run_id": "walk-9", "project": "demo", "action": "start"}
    assert started.headers["Location"] == "/api/v1/scenario-runs/walk-9"
    ((kind, spec),) = scenarios.launcher.calls
    assert kind == "start"
    assert (spec.name, spec.environment, spec.mode, spec.inputs) == (
        "order-walk",
        "local",
        "interactive",
        {"ref": "T-1"},
    )


def test_returns_422_record_problem_when_scenario_record_too_large(scenarios: Any) -> None:
    write_records(scenarios.hub, a_paused_walk(scenarios.hub))
    shown = scenarios.client.get(f"/api/v1/scenario-runs/{WALK_RUN}")
    # The API's bound on a scenario run's record: 8 MiB; a torn last line is dropped.
    path = scenarios.hub / WALK_RECORDS
    path.write_bytes(path.read_bytes() + b'{"event": "end", "sta')
    torn = scenarios.client.get(f"/api/v1/scenario-runs/{WALK_RUN}")
    path.write_bytes(b" " * (8 * 1024 * 1024) + b"\n")
    too_large = scenarios.client.get(f"/api/v1/scenario-runs/{WALK_RUN}")

    assert shown.status_code == 200, shown.text
    body = shown.json()
    assert (body["scenario"], body["environment"], body["status"]) == ("order-walk", "live", None)
    assert body["open_investigation"] == 1
    assert [item["event"] for item in body["timeline"]][:2] == ["start", "step_start"]
    assert body["polls"] == [
        {"node": "order-held", "attempt": 1, "poll": 1, "held": False, "at": None}
    ]
    assert [finding["finding_id"] for finding in body["findings"]] == ["f1"]
    assert torn.status_code == 200
    assert torn.json()["status"] is None
    assert (too_large.status_code, too_large.json()["code"]) == (422, "record_too_large")


def test_returns_409_conflict_when_workaround_pick_refused(scenarios: Any) -> None:
    hub = scenarios.hub
    options = (
        option_line(hub, "o1", READ_OPTION, environment="live"),
        option_line(hub, "o2", WRITE_OPTION, environment="live"),
    )
    write_records(hub, a_paused_walk(hub, *options))
    answer = f"/scenario-runs/{WALK_RUN}/answer"

    shown = scenarios.client.get(f"/api/v1/scenario-runs/{WALK_RUN}").json()
    refused = _post(scenarios, answer, {"choice": "pick", "option": "o2"})
    unknown = _post(scenarios, answer, {"choice": "pick", "option": "o7"})
    nothing_recorded = list(scenarios.launcher.calls)
    picked = _post(scenarios, answer, {"choice": "pick", "option": "o1"})

    options_shown = {item["option_id"]: item for item in shown["proposal"]["options"]}
    assert (options_shown["o1"]["pickable"], options_shown["o2"]["pickable"]) == (True, False)
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "pick_refused"
    assert refused.json()["detail"] == (
        "option o2 cannot be picked: step 1 (demo/release-hold): live is a production"
        " environment: writes and destroys are denied"
    )
    assert options_shown["o2"]["refusal"] == refused.json()["detail"]
    assert (unknown.status_code, unknown.json()["code"]) == (409, "pick_refused")
    assert nothing_recorded == []
    assert picked.status_code == 202, picked.text
    gate = f"{WALK_RUN}:{WALK_GATE}:1"
    assert scenarios.launcher.calls == [
        ("decide", (WALK_RUN, gate, "pick", "o1")),
        ("resume", WALK_RUN),
    ]


def test_resumes_when_investigation_retry(scenarios: Any) -> None:
    write_records(scenarios.hub, a_paused_walk(scenarios.hub))
    answer = f"/scenario-runs/{WALK_RUN}/answer"

    with_option = _post(scenarios, answer, {"choice": "retry", "option": "o1"})
    retried = _post(scenarios, answer, {"choice": "retry"})
    again = _post(scenarios, answer, {"choice": "retry"})

    assert with_option.status_code == 422
    assert retried.status_code == 202, retried.text
    assert retried.json()["choice"] == "retry"
    assert retried.headers["Location"] == f"/api/v1/scenario-runs/{WALK_RUN}"
    gate = f"{WALK_RUN}:{WALK_GATE}:1"
    assert scenarios.launcher.calls == [
        ("decide", (WALK_RUN, gate, "retry", None)),
        ("resume", WALK_RUN),
    ]
    # Answered: the investigation is no longer open to an answer.
    assert (again.status_code, again.json()["code"]) == (409, "not_paused")


def test_ends_cancelled_when_investigation_stop(scenarios: Any) -> None:
    write_records(scenarios.hub, a_paused_walk(scenarios.hub))

    stopped = _post(scenarios, f"/scenario-runs/{WALK_RUN}/answer", {"choice": "stop"})
    shown = scenarios.client.get(f"/api/v1/scenario-runs/{WALK_RUN}").json()

    assert stopped.status_code == 202, stopped.text
    assert [name for name, _ in scenarios.launcher.calls] == ["decide", "resume"]
    assert shown["status"] == "cancelled"
    assert shown["open_investigation"] is None
    # Findings are kept whatever the end.
    assert [finding["finding_id"] for finding in shown["findings"]] == ["f1"]
    (decision,) = shown["decisions"]
    assert (decision["node"], decision["choice"]) == (WALK_GATE, "stop")


RENDER = ACTION_DOCUMENT.format(name="render-invoice-pdf", effect="read")


def test_shows_needs_acceptance_when_draft_action_from_agent(scenarios: Any) -> None:
    hub = scenarios.hub
    # What the investigation's agent writes under actions/<pack>/: a draft until committed.
    (hub / "actions" / "demo" / "render-invoice-pdf.yaml").write_text(RENDER)
    (hub / "actions" / "demo" / "scripts" / "render-invoice-pdf.sh").write_text("exit 0\n")
    render = {"action": "render-invoice-pdf", "with": {"target": "api"}}
    write_records(
        hub,
        a_paused_walk(
            hub, option_line(hub, "o1", render, environment="staging"), environment="staging"
        ),
    )
    answer = f"/scenario-runs/{WALK_RUN}/answer"

    shown = scenarios.client.get(f"/api/v1/scenario-runs/{WALK_RUN}").json()
    refused = _post(scenarios, answer, {"choice": "pick", "option": "o1"})
    _git(hub, "add", "-A")
    _git(hub, "commit", "-q", "-m", "accept render-invoice-pdf")
    # Committed, a new proposal pins its hash and the option can be picked.
    append_records(hub, a_proposal_line(2, option_line(hub, "o1", render, environment="staging")))
    again = scenarios.client.get(f"/api/v1/scenario-runs/{WALK_RUN}").json()
    picked = _post(scenarios, answer, {"choice": "pick", "option": "o1"})

    (option,) = shown["proposal"]["options"]
    assert option["needs_acceptance"] is True
    assert option["pickable"] is False
    assert option["refusal"] == (
        "option o1 cannot be picked: step 1 (demo/render-invoice-pdf): draft action: commit it"
        " to run"
    )
    assert option["accept_commands"] == [
        "git add -- actions/demo/render-invoice-pdf.yaml actions/demo/scripts/render-invoice-pdf.sh"
        " && git commit -m 'Accept action demo/render-invoice-pdf'"
    ]
    assert (refused.status_code, refused.json()["code"]) == (409, "pick_refused")
    (accepted,) = again["proposal"]["options"]
    assert (accepted["needs_acceptance"], accepted["pickable"]) == (False, True)
    assert accepted["accept_commands"] == []
    assert picked.status_code == 202, picked.text


def test_creates_issue_when_scenarios_finding_issue_posted(scenarios: Any) -> None:
    write_records(scenarios.hub, a_paused_walk(scenarios.hub))
    path = f"/scenario-runs/{WALK_RUN}/findings/f1/issue"

    drafted = _post(scenarios, path, {})
    created = _post(scenarios, path, {"confirm": True})
    again = _post(scenarios, path, {"confirm": True})
    unknown = _post(scenarios, f"/scenario-runs/{WALK_RUN}/findings/f9/issue", {"confirm": True})
    loose = _post(scenarios, path, {"confirm": "yes"})

    assert drafted.status_code == 200, drafted.text
    assert drafted.json()["title"] == "Scenario order-walk: Order stays on hold"
    assert drafted.json()["created"] is None
    assert f"{WALK_RECORDS.as_posix()}" in drafted.json()["description"]
    assert created.status_code == 201, created.text
    issue = created.json()["created"]
    assert issue["id"].startswith("DEM-")
    (stored,) = scenarios.backend.issues.values()
    assert (stored.title, stored.id) == (drafted.json()["title"], issue["id"])
    assert (again.status_code, again.json()["code"]) == (409, "issue_exists")
    assert issue["id"] in again.json()["detail"]
    assert unknown.status_code == 404
    assert loose.status_code == 422
    assert len(scenarios.backend.issues) == 1


def test_writes_note_when_scenarios_finding_inbox_posted(scenarios: Any) -> None:
    write_records(scenarios.hub, a_paused_walk(scenarios.hub))
    path = f"/scenario-runs/{WALK_RUN}/findings/f1/inbox"

    written = _post(scenarios, path, {})
    again = _post(scenarios, path, {})

    assert written.status_code == 201, written.text
    note = written.json()["path"]
    assert note == "brain/_inbox/2026-10-22-scenario-order-walk-f1.md"
    text = (scenarios.hub / note).read_text(encoding="utf-8")
    assert "provenance: agent-from-external" in text
    assert (again.status_code, again.json()["code"]) == (409, "note_exists")
    assert (scenarios.hub / note).read_text(encoding="utf-8") == text


# Review round 1 (AGH-363, erratum E-14): the tracker from the effective config, the failure
# paths of the writes, and a run detail that stays readable.


class FailingTracker(InMemoryTrackerClient):
    """A tracker whose create fails, counting the attempts."""

    def __init__(self, backend: FakeTrackerBackend) -> None:
        super().__init__(backend)
        self.attempts = 0

    def create_issue(self, team: str, title: str, description: str) -> Any:
        self.attempts += 1
        raise TrackerError(
            operation="create_issue", cause="the tracker did not answer", fix="retry"
        )


def rewire_tracker(wired: Any, tracker_of: Any) -> None:
    commands = ScenarioCommands(
        catalog=wired.catalog,
        launcher=wired.launcher,
        lock=threading.Lock(),
        tracker_of=tracker_of,
        today=lambda: date(2026, 10, 22),
        mint=lambda: "walk-9",
    )
    wired.wire(scenario_commands=commands)


def test_uses_local_transport_when_scenarios_finding_issue_confirmed(scenarios: Any) -> None:
    write_records(scenarios.hub, a_paused_walk(scenarios.hub))
    seen: list[str] = []

    def tracker_of(config: HubConfig, _hub: str) -> Any:
        seen.append(config.tracker.transport)
        return InMemoryTrackerClient(scenarios.backend)

    rewire_tracker(scenarios, tracker_of)
    fake = scenarios.reader.hubs[str(scenarios.hub)]
    fake.local = LocalConfig.model_validate({"tracker": {"transport": "mcp"}})
    path = f"/scenario-runs/{WALK_RUN}/findings/f1/issue"

    created = _post(scenarios, path, {"confirm": True})
    fake.local = (ConfigProblem(path="hub.local.json", message="not valid JSON"),)
    refused = _post(scenarios, path, {"confirm": True})

    assert created.status_code == 201, created.text
    assert seen == ["mcp"]
    assert (refused.status_code, refused.json()["code"]) == (409, "hub_local_invalid")
    assert len(scenarios.backend.issues) == 1


def test_returns_502_problem_when_scenarios_finding_issue_create_fails(scenarios: Any) -> None:
    write_records(scenarios.hub, a_paused_walk(scenarios.hub))
    failing = FailingTracker(scenarios.backend)
    rewire_tracker(scenarios, lambda _config, _hub: failing)
    path = f"/scenario-runs/{WALK_RUN}/findings/f1/issue"

    failed = _post(scenarios, path, {"confirm": True})
    again = _post(scenarios, path, {"confirm": True})

    assert failed.status_code == 502, failed.text
    assert failed.json()["type"] == "urn:agent-hub:problem:scenario-run-issue-failed"
    assert (again.status_code, again.json()["code"]) == (409, "issue_exists")
    assert failing.attempts == 1
    assert scenarios.backend.issues == {}


def test_returns_409_conflict_when_scenarios_tracker_not_connected(scenarios: Any) -> None:
    write_records(scenarios.hub, a_paused_walk(scenarios.hub))
    rewire_tracker(scenarios, lambda _config, _hub: None)

    refused = _post(scenarios, f"/scenario-runs/{WALK_RUN}/findings/f1/issue", {"confirm": True})

    assert (refused.status_code, refused.json()["code"]) == (409, "tracker_not_connected")
    assert not (scenarios.hub / WALK_RECORDS).with_name("finding-f1.issue").exists()


class LiveLauncher(FakeScenarioLauncher):
    def live_runs(self, hub_path: str) -> dict[str, str | None]:
        return {WALK_RUN: None}


def test_returns_409_conflict_when_investigation_answer_run_in_use(scenarios: Any) -> None:
    write_records(scenarios.hub, a_paused_walk(scenarios.hub))
    launcher = LiveLauncher(scenarios.hub)
    scenarios.launcher = launcher
    rewire_tracker(scenarios, lambda _config, _hub: None)

    refused = _post(scenarios, f"/scenario-runs/{WALK_RUN}/answer", {"choice": "retry"})

    assert (refused.status_code, refused.json()["code"]) == (409, "in_use")
    assert launcher.calls == []


def test_keeps_run_readable_when_scenarios_hub_json_unreadable(
    scenarios: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = scenarios.hub
    write_records(hub, a_paused_walk(hub, option_line(hub, "o1", READ_OPTION, environment="live")))

    def unreadable(_hub: str, project: str) -> EffectiveEnvironments:
        raise EntityNotFoundError(entity="project", entity_id=project)

    monkeypatch.setattr(scenarios.catalog.credentials, "environments_of", unreadable)

    shown = scenarios.client.get(f"/api/v1/scenario-runs/{WALK_RUN}")

    assert shown.status_code == 200, shown.text
    (option,) = shown.json()["proposal"]["options"]
    assert option["pickable"] is False
    assert option["refusal"] == "hub.json cannot be read, so the options cannot be planned now"


def test_reads_no_actions_when_scenarios_run_answered_without_drafts(
    scenarios: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = scenarios.hub
    paused = a_paused_walk(hub, option_line(hub, "o1", READ_OPTION, environment="live"))
    stopped = {"event": "decision", "node": WALK_GATE, "attempt": 1, "choice": "stop"}
    write_records(hub, [*paused, stopped])
    reads: list[Path] = []
    real = discover_actions

    def counted(root: Path) -> Any:
        reads.append(root)
        return real(root)

    monkeypatch.setattr("agent_hub.api.scenario_catalog.discover_actions", counted)

    shown = scenarios.client.get(f"/api/v1/scenario-runs/{WALK_RUN}")

    assert shown.status_code == 200, shown.text
    assert shown.json()["proposal"]["options"][0]["refusal"] is not None
    assert reads == []


# Review round 2 (E-14): the draft needs no hub.local.json; a local file that conflicts with
# hub.json refuses as one that cannot be read.


def test_answers_draft_when_scenarios_finding_issue_local_file_broken(scenarios: Any) -> None:
    write_records(scenarios.hub, a_paused_walk(scenarios.hub))
    fake = scenarios.reader.hubs[str(scenarios.hub)]
    fake.local = (ConfigProblem(path="hub.local.json", message="not valid JSON"),)
    path = f"/scenario-runs/{WALK_RUN}/findings/f1/issue"

    drafted = _post(scenarios, path, {})
    confirmed = _post(scenarios, path, {"confirm": True})

    assert drafted.status_code == 200, drafted.text
    assert (drafted.json()["team"], drafted.json()["created"]) == ("DEM", None)
    assert drafted.json()["title"] == "Scenario order-walk: Order stays on hold"
    assert (confirmed.status_code, confirmed.json()["code"]) == (409, "hub_local_invalid")
    assert scenarios.backend.issues == {}


def test_returns_409_conflict_when_scenarios_local_file_loosens_environment(
    scenarios: Any,
) -> None:
    # hub.local.json parses, but loosens hub.json's staging (ask) to write.
    fake = scenarios.reader.hubs[str(scenarios.hub)]
    fake.local = LocalConfig.model_validate({"environments": {"staging": {"access": "write"}}})
    body = {"environment": "staging", "inputs": {"ref": "T-1"}}

    hub = scenarios.hub
    write_records(hub, a_paused_walk(hub, option_line(hub, "o1", READ_OPTION, environment="live")))
    planned = _post(scenarios, "/scenarios/demo/order-walk/plan", body)
    started = _post(scenarios, "/scenarios/demo/order-walk/runs", body)
    shown = scenarios.client.get(f"/api/v1/scenario-runs/{WALK_RUN}")

    assert (planned.status_code, planned.json()["code"]) == (409, "hub_local_invalid")
    assert (started.status_code, started.json()["code"]) == (409, "hub_local_invalid")
    assert scenarios.launcher.calls == []
    # E-14: the run's detail stays readable, its options shown, not pickable, with a reason.
    assert shown.status_code == 200, shown.text
    (option,) = shown.json()["proposal"]["options"]
    assert (option["pickable"], option["refusal"]) == (False, scenario_catalog_unreadable())


class PeekingTracker(InMemoryTrackerClient):
    """A tracker that, mid-create, sees whether a terminal retry could take the claim."""

    def __init__(self, backend: FakeTrackerBackend, folder: Path) -> None:
        super().__init__(backend)
        self.folder = folder
        self.seen: list[str] = []

    def create_issue(self, team: str, title: str, description: str) -> Any:
        unfinished = marked_issue(self.folder, "f1")
        assert unfinished is not None
        standing = retake_issue(self.folder, unfinished)
        self.seen.append(standing.state if isinstance(standing, IssueMarked) else "taken")
        return super().create_issue(team, title, description)


def test_holds_claim_when_scenarios_finding_issue_create_running(scenarios: Any) -> None:
    # E-14: a running create is never retaken; hub web holds the claim's lock across it.
    write_records(scenarios.hub, a_paused_walk(scenarios.hub))
    peeking = PeekingTracker(scenarios.backend, (scenarios.hub / WALK_RECORDS).parent)
    rewire_tracker(scenarios, lambda _config, _hub: peeking)

    created = _post(scenarios, f"/scenario-runs/{WALK_RUN}/findings/f1/issue", {"confirm": True})

    assert created.status_code == 201, created.text
    assert peeking.seen == ["a create of finding f1's issue is running"]
    assert len(scenarios.backend.issues) == 1


def test_names_conflict_when_scenarios_local_file_invalid(scenarios: Any) -> None:
    # The problem covers a file that cannot be read and one that conflicts with hub.json,
    # and names no session when a plan, a start or an issue refuses (E-14).
    hub = scenarios.hub
    write_records(hub, a_paused_walk(hub, option_line(hub, "o1", READ_OPTION, environment="live")))
    fake = scenarios.reader.hubs[str(hub)]
    fake.local = LocalConfig.model_validate({"environments": {"staging": {"access": "write"}}})
    body = {"environment": "staging", "inputs": {"ref": "T-1"}}

    planned = _post(scenarios, "/scenarios/demo/order-walk/plan", body)
    issued = _post(scenarios, f"/scenario-runs/{WALK_RUN}/findings/f1/issue", {"confirm": True})
    shown = scenarios.client.get(f"/api/v1/scenario-runs/{WALK_RUN}")

    for refused in (planned, issued):
        assert refused.status_code == 409, refused.text
        assert refused.json()["title"] == "hub.local.json cannot be read or conflicts with hub.json"
        assert "conflicts with hub.json" in refused.json()["detail"]
        assert "session" not in refused.json()["detail"]
    # The run's detail stays readable: options shown, not pickable, with the reason.
    assert shown.status_code == 200, shown.text
    (option,) = shown.json()["proposal"]["options"]
    assert option["pickable"] is False
    assert option["refusal"] == (
        "hub.local.json cannot be read or conflicts with hub.json, so the options cannot be"
        " planned now"
    )


def scenario_catalog_unreadable() -> str:
    return (
        "hub.local.json cannot be read or conflicts with hub.json, so the options cannot be"
        " planned now"
    )


# Review round 4: a create whose record fails, and a tracker that raises anything else.


class UnrecordableTracker(InMemoryTrackerClient):
    """A tracker that creates the issue, while its marker turns into a folder."""

    def __init__(self, backend: FakeTrackerBackend, folder: Path) -> None:
        super().__init__(backend)
        self.folder = folder

    def create_issue(self, team: str, title: str, description: str) -> Any:
        marker = self.folder / "finding-f1.issue"
        marker.unlink()
        marker.mkdir()
        return super().create_issue(team, title, description)


def test_answers_unrecorded_issue_when_scenarios_finding_issue_record_fails(
    scenarios: Any,
) -> None:
    write_records(scenarios.hub, a_paused_walk(scenarios.hub))
    folder = (scenarios.hub / WALK_RECORDS).parent
    rewire_tracker(scenarios, lambda _config, _hub: UnrecordableTracker(scenarios.backend, folder))

    created = _post(scenarios, f"/scenario-runs/{WALK_RUN}/findings/f1/issue", {"confirm": True})

    assert created.status_code == 201, created.text
    body = created.json()
    (stored,) = scenarios.backend.issues.values()
    assert body["created"]["id"] == stored.id
    assert body["recorded"] is False
    assert body["warning"].startswith(
        f"the issue {stored.id} was created but could not be recorded"
    )
    assert body["warning"].endswith("do not create it again")


class BrokenTracker(InMemoryTrackerClient):
    def create_issue(self, team: str, title: str, description: str) -> Any:
        raise RuntimeError("the adapter broke")


def test_leaves_retryable_marker_when_scenarios_tracker_raises_other_error(
    scenarios: Any,
) -> None:
    write_records(scenarios.hub, a_paused_walk(scenarios.hub))
    folder = (scenarios.hub / WALK_RECORDS).parent
    rewire_tracker(scenarios, lambda _config, _hub: BrokenTracker(scenarios.backend))

    broken = _post(scenarios, f"/scenario-runs/{WALK_RUN}/findings/f1/issue", {"confirm": True})
    unfinished = marked_issue(folder, "f1")

    assert broken.status_code == 500
    assert unfinished is not None
    assert (unfinished.issue_id, unfinished.failed, unfinished.running) == (None, False, False)
    retaken = retake_issue(folder, unfinished)
    assert isinstance(retaken, HeldFindingIssue)
    retaken.release()


# The read fields the Scenarios screens need (AGH-350 E-15, plan T13): all read-only.
LINKED_SESSION = "0192f00d-0000-7000-8000-000000000001"


def test_lists_environments_and_run_facts_when_scenarios_detail_read(scenarios: Any) -> None:
    scenarios.events.runs.append(
        read_model_builders.a_run(
            id=WALK_RUN, workflow="scenario:order-walk", status="running", issue=None
        )
    )
    scenarios.events.runs.append(
        read_model_builders.a_run(id="walk-0", workflow="scenario:order-walk", issue=None)
    )
    write_records(scenarios.hub, a_paused_walk(scenarios.hub))

    detail = scenarios.client.get("/api/v1/scenarios/demo/order-walk").json()
    (item,) = scenarios.client.get("/api/v1/scenarios").json()["items"]

    assert detail["environments"] == [
        {"name": "local", "access": "write", "production": False},
        {"name": "staging", "access": "ask", "production": False},
        {"name": "live", "access": "read", "production": True},
    ]
    shown = [(run["run_id"], run["environment"], run["mode"]) for run in detail["runs"]]
    # A run whose record cannot be read names neither.
    assert shown == [(WALK_RUN, "live", "interactive"), ("walk-0", None, None)]
    assert (item["last_run"]["environment"], item["last_run"]["mode"]) == ("live", "interactive")


def test_lists_no_environments_when_scenarios_local_file_invalid(scenarios: Any) -> None:
    fake = scenarios.reader.hubs[str(scenarios.hub)]
    fake.local = LocalConfig.model_validate({"environments": {"staging": {"access": "write"}}})

    detail = scenarios.client.get("/api/v1/scenarios/demo/order-walk")

    assert detail.status_code == 200, detail.text
    assert detail.json()["environments"] == []


def test_names_session_reads_and_action_facts_when_scenarios_run_read(scenarios: Any) -> None:
    hub = scenarios.hub
    records = a_paused_walk(hub)
    records.insert(
        3,
        {"event": "action", "node": "order-held", "attempt": 1, "poll": 1}
        | {"action": "demo/get-order", "environment": "live", "effect": "read"}
        | {"origin": "author", "decision": "allow", "content_hash": "sha256:" + "1" * 64}
        | {"reason_kind": "table", "inputs": {"ref": "T-1"}, "status": "ok", "failure_kind": None},
    )
    records.append(
        {"event": "agent_action", "gate": WALK_GATE, "number": 1, "item": "", "status": "ok"}
        | {"action": "demo/get-order", "effect": "read", "origin": "agent", "decision": "allow"}
        | {"output": {"status": "OPEN"}}
    )
    write_records(hub, records)
    link = hub / WALK_RECORDS.parent / "investigation-1.session"
    link.write_text(f"{LINKED_SESSION}\n", encoding="ascii")

    body = scenarios.client.get(f"/api/v1/scenario-runs/{WALK_RUN}").json()

    (investigation,) = body["investigations"]
    assert investigation["agent_session_id"] == LINKED_SESSION
    read = body["timeline"][-1]
    assert (read["event"], read["action"], read["effect"]) == (
        "agent_action",
        "demo/get-order",
        "read",
    )
    (call,) = body["actions"]
    assert (call["node"], call["action"], call["effect"], call["decision"]) == (
        "order-held",
        "demo/get-order",
        "read",
        "allow",
    )
    assert (call["origin"], call["poll"], call["status"]) == ("author", 1, "ok")
    assert "T-1" not in json.dumps(body["actions"])


def test_names_no_session_when_scenarios_investigation_link_missing_or_link(
    scenarios: Any, tmp_path: Path
) -> None:
    write_records(scenarios.hub, a_paused_walk(scenarios.hub))
    unlinked = scenarios.client.get(f"/api/v1/scenario-runs/{WALK_RUN}").json()
    target = tmp_path / "elsewhere.session"
    target.write_text(f"{LINKED_SESSION}\n", encoding="ascii")
    (scenarios.hub / WALK_RECORDS.parent / "investigation-1.session").symlink_to(target)

    through_link = scenarios.client.get(f"/api/v1/scenario-runs/{WALK_RUN}").json()

    assert unlinked["investigations"][0]["agent_session_id"] is None
    # Never read through a link.
    assert through_link["investigations"][0]["agent_session_id"] is None


def test_shows_run_environment_and_access_when_workflow_run_environment_recorded(
    scenarios: Any,
) -> None:
    events = scenarios.events
    events.runs.append(read_model_builders.a_run(id="flow-1", workflow="sync", issue=None))
    events.runs.append(read_model_builders.a_run(id="flow-2", workflow="sync", issue=None))
    events.runs.append(read_model_builders.a_run(id="flow-3", workflow="sync", issue=None))
    for run, environment in (("flow-1", "live"), ("flow-3", "gone")):
        folder = scenarios.hub / ".agent-runs" / "workflows" / run
        folder.mkdir(parents=True)
        start = {"event": "start", "run": run, "workflow": "sync", "environment": environment}
        (folder / "records.jsonl").write_text(json.dumps(start) + "\n", encoding="utf-8")

    declared = scenarios.client.get("/api/v1/workflow-runs/flow-1")
    without = scenarios.client.get("/api/v1/workflow-runs/flow-2")
    undeclared = scenarios.client.get("/api/v1/workflow-runs/flow-3")

    assert declared.status_code == 200, declared.text
    assert declared.json()["environment"] == {"name": "live", "access": "read", "production": True}
    # No record, or a record without an environment: the run reads as before.
    assert "environment" not in without.json()
    assert undeclared.json()["environment"] == {"name": "gone", "access": None, "production": None}
