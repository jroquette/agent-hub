"""``/scenario-runs``: the investigation session hub web starts for a paused scenario run
(P-7, AM-2, AM-9, AC-350.20, AC-350.22, AC-350.41)."""

import json
import os
import shutil
import subprocess
import threading
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from agent_hub.api import scenario_catalog, scenario_investigation
from agent_hub.api.agent_session_runtime import HubCredentials
from agent_hub.api.run_launcher import ScenarioLaunch
from agent_hub.api.scenario_catalog import ScenarioCatalog, ScenarioCommands
from agent_hub.api.scenario_investigation import InvestigationRestrictions, ScenarioInvestigations
from agent_hub.core.agent_sessions import errors as session_errors
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
from agent_hub.core.item_versions.item_version_ports import ItemWriteResult
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
from agent_hub.core.workflows.launch import RunConflictError, RunLaunchError
from agent_hub.generator.action_discovery import discover_actions
from agent_hub.generator.finding_issues import HeldIssue as HeldFindingIssue
from agent_hub.generator.finding_issues import IssueMarked, marked_issue, retake_issue
from agent_hub.generator.scenario_yaml import render_document
from agent_hub.generator.workflow_yaml import load_workflow_bytes

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

    def set_breakpoints(self, hub_path: str, run_id: str, addresses: tuple[str, ...]) -> None:
        self.calls.append(("break", (run_id, addresses)))

    def debug(self, hub_path: str, run_id: str, *, command: str) -> None:
        self.calls.append(("debug", (run_id, command)))

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


def test_fills_required_input_from_environment_value_when_body_leaves_it_out(
    scenarios: Any,
) -> None:
    # hub.local.json sets a value on hub.json's local: the developer's, never a secret.
    fake = scenarios.reader.hubs[str(scenarios.hub)]
    fake.local = LocalConfig.model_validate({"environments": {"local": {"values": {"ref": "T-7"}}}})
    scenarios.launcher.plan_output = (0, a_plan_output(draft=False))

    detail = scenarios.client.get("/api/v1/scenarios/demo/order-walk").json()
    planned = _post(scenarios, "/scenarios/demo/order-walk/plan", {"environment": "local"})
    started = _post(scenarios, "/scenarios/demo/order-walk/runs", {"environment": "local"})
    elsewhere = _post(scenarios, "/scenarios/demo/order-walk/runs", {"environment": "staging"})

    assert detail["environments"][0] == {
        "name": "local",
        "access": "write",
        "production": False,
        "values": {"ref": "T-7"},
    }
    assert planned.status_code == 200, planned.text
    assert started.status_code == 202, started.text
    # The child is given only the body's inputs: it fills the environment's values itself.
    assert scenarios.launcher.calls[0] == ("plan", ("order-walk", "local", {}))
    (kind, spec) = scenarios.launcher.calls[1]
    assert (kind, spec.environment, spec.inputs) == ("start", "local", {})
    # staging has no value for the required input: refused before any child runs.
    assert elsewhere.status_code == 422, elsewhere.text
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
        {"name": "local", "access": "write", "production": False, "values": {}},
        {"name": "staging", "access": "ask", "production": False, "values": {}},
        {"name": "live", "access": "read", "production": True, "values": {}},
    ]
    shown = [(run["run_id"], run["environment"], run["mode"]) for run in detail["runs"]]
    # A run whose record cannot be read names neither.
    assert shown == [(WALK_RUN, "live", "interactive"), ("walk-0", None, None)]
    assert (item["last_run"]["environment"], item["last_run"]["mode"]) == ("live", "interactive")


def test_shows_step_keys_file_and_action_facts_when_scenarios_detail_read(scenarios: Any) -> None:
    detail = scenarios.client.get("/api/v1/scenarios/demo/order-walk").json()

    send, held = detail["steps"]
    assert send["with"] == {"target": "api", "ref": "$INPUTS.ref"}
    assert (send["every"], send["until_when"], send["retry"]) == (None, None, None)
    assert (held["every"], held["timeout"]) == ("10s", "5m")
    assert held["until_when"] == "$self.output.status == 'ON_HOLD'"
    assert held["capture"] == {"order_id": "$self.output.order"}
    assert detail["path"] == "scenarios/demo/order-walk.yaml"
    assert detail["document_text"] == WALK
    # One entry per distinct action, as the steps name it; a committed hub has no draft.
    by_ref = {action["ref"]: action for action in detail["actions"]}
    assert list(by_ref) == ["send-order", "demo/get-order"]
    get_order = by_ref["demo/get-order"]
    assert (get_order["effect"], get_order["runtime"], get_order["draft"]) == ("read", "sh", False)
    assert get_order["script"] == "actions/demo/scripts/get-order.sh"
    assert get_order["path"] == "actions/demo/get-order.yaml"
    assert [item["name"] for item in get_order["inputs"]] == ["target", "ref"]
    assert get_order["script_text"].startswith("printf")
    assert get_order["accept_command"] is None


def test_names_problem_and_draft_when_scenarios_detail_action_changes(scenarios: Any) -> None:
    (scenarios.hub / "actions" / "demo" / "scripts" / "send-order.sh").write_text("echo changed\n")
    (scenarios.hub / "actions" / "demo" / "get-order.yaml").unlink()

    detail = scenarios.client.get("/api/v1/scenarios/demo/order-walk")

    assert detail.status_code == 200, detail.text
    by_ref = {action["ref"]: action for action in detail.json()["actions"]}
    assert by_ref["send-order"]["draft"] is True
    assert "git add" in by_ref["send-order"]["accept_command"]
    assert "unknown action" in by_ref["demo/get-order"]["problem"]


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


def test_refuses_mode_change_when_investigation_session_settings_posted(
    wired: Any, investigation: Any
) -> None:
    """An investigation session keeps mode ``default``: allowed writes keep asking (E-13, E-15)."""
    rig, _hub = investigation(a_record())
    started = wired.client.post(ROUTE, json={}, headers=_origin(wired)).json()
    session = f"/api/v1/agent-sessions/{started['agent_session_id']}"

    mode = wired.client.post(
        f"{session}/settings", json={"mode": "acceptEdits"}, headers=_origin(wired)
    )
    model = wired.client.post(
        f"{session}/settings", json={"model": "sonnet"}, headers=_origin(wired)
    )
    shown = wired.client.get(session)

    assert mode.status_code == 409, mode.text
    assert mode.headers["content-type"] == "application/problem+json"
    assert mode.json()["type"] == "urn:agent-hub:problem:agent-session-mode-locked"
    assert model.status_code == 200, model.text
    assert shown.json()["restricted"] is True
    assert shown.json()["mode"] == "default"
    assert not [call for call in rig.driver.calls if call.method == "set_mode"]


def test_keeps_restricted_in_every_view_when_investigation_session_commanded(
    wired: Any, investigation: Any
) -> None:
    """Each view of a restricted session says so, not only its read (review Q2)."""
    _rig, _hub = investigation(a_record())
    started = wired.client.post(ROUTE, json={}, headers=_origin(wired)).json()
    session = f"/api/v1/agent-sessions/{started['agent_session_id']}"

    model = wired.client.post(
        f"{session}/settings", json={"model": "sonnet"}, headers=_origin(wired)
    )
    listed = wired.client.get("/api/v1/agent-sessions")
    closed = wired.client.post(f"{session}/close", json={}, headers=_origin(wired))

    assert model.status_code == 200, model.text
    assert model.json()["restricted"] is True
    (item,) = [row for row in listed.json()["items"] if row["id"] == started["agent_session_id"]]
    assert item["restricted"] is True
    assert closed.status_code == 200, closed.text
    assert closed.json()["restricted"] is True


def test_refuses_mode_change_when_investigation_session_reopened_after_restart(
    wired: Any, investigation: Any
) -> None:
    """A restart forgets the restriction; the reopen rebuilds it, and the mode stays fixed
    (review Q5, E-13)."""
    session_id, fresh, _hub = _start_and_restart(wired, investigation)

    reopened = _message(wired, session_id)
    mode = wired.client.post(
        f"/api/v1/agent-sessions/{session_id}/settings",
        json={"mode": "acceptEdits"},
        headers=_origin(wired),
    )

    assert reopened.status_code == 202, reopened.text
    assert mode.status_code == 409, mode.text
    assert mode.json()["type"] == "urn:agent-hub:problem:agent-session-mode-locked"
    assert not [call for call in fresh.driver.calls if call.method == "set_mode"]


def test_marks_restricted_before_reopen_when_investigation_session_read_after_restart(
    wired: Any, investigation: Any
) -> None:
    """After a restart, an ended investigation session reads restricted before any reopen,
    so its page offers no mode switch (review round 3, Q7)."""
    session_id, fresh, _hub = _start_and_restart(wired, investigation)

    shown = wired.client.get(f"/api/v1/agent-sessions/{session_id}")
    again = wired.client.get(f"/api/v1/agent-sessions/{session_id}")

    assert shown.status_code == 200, shown.text
    assert shown.json()["status"] == "ended"
    assert shown.json()["restricted"] is True
    assert again.json()["restricted"] is True
    assert _starts(fresh) == []


# What a read learns of a forgotten session's restriction (review round 4, Q1 to Q3).


class CountingRestrictions:
    """``restriction_of`` with its calls counted per session; ``fail`` raises before the
    real read, once each."""

    def __init__(self, restrictions: InvestigationRestrictions) -> None:
        self.restrictions = restrictions
        self.calls: dict[str, int] = {}
        self.fail: list[Exception] = []

    def restriction_of(self, session: Any) -> Any:
        self.calls[session.id] = self.calls.get(session.id, 0) + 1
        if self.fail:
            raise self.fail.pop(0)
        return self.restrictions.restriction_of(session)


def _counted(wired: Any, tmp_path: Path) -> tuple[Rig, CountingRestrictions]:
    hub = a_hub(tmp_path, a_record())
    registry, reader = a_reader(hub)
    credentials = HubCredentials(registry=registry, reader=reader, running_version=RUNNING)
    counting = CountingRestrictions(InvestigationRestrictions(credentials))
    rig = build_rig(hidden_environment=credentials.names, restriction_of=counting.restriction_of)
    wired.wire(agent_sessions=rig.control)
    return rig, counting


def _plain_session(wired: Any) -> str:
    created = wired.client.post(
        "/api/v1/agent-sessions",
        json={"project": "demo", "workdir_id": WORKDIR_ID},
        headers=_origin(wired),
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def test_asks_restriction_once_when_plain_session_read_twice(wired: Any, tmp_path: Path) -> None:
    _rig, counting = _counted(wired, tmp_path)
    session_id = _plain_session(wired)

    first = wired.client.get(f"/api/v1/agent-sessions/{session_id}")
    second = wired.client.get(f"/api/v1/agent-sessions/{session_id}")

    assert "restricted" not in first.json()
    assert "restricted" not in second.json()
    assert counting.calls[session_id] == 1


def test_keeps_plain_session_unmarked_when_restriction_read_fails_once(
    wired: Any, tmp_path: Path
) -> None:
    """A transient read error marks nothing and is asked again (review round 4, Q1)."""
    _rig, counting = _counted(wired, tmp_path)
    session_id = _plain_session(wired)
    counting.fail.append(
        session_errors.RestrictionUnreadableError(session_id, "the runs cannot be read")
    )

    first = wired.client.get(f"/api/v1/agent-sessions/{session_id}")
    second = wired.client.get(f"/api/v1/agent-sessions/{session_id}")
    third = wired.client.get(f"/api/v1/agent-sessions/{session_id}")

    assert ["restricted" in reply.json() for reply in (first, second, third)] == [False] * 3
    assert counting.calls[session_id] == 2


def test_asks_unbuilt_restriction_once_when_session_read_twice(wired: Any, tmp_path: Path) -> None:
    """A link that cannot be rebuilt marks the session and is not asked again (Q1)."""
    _rig, counting = _counted(wired, tmp_path)
    session_id = _plain_session(wired)
    counting.fail.append(session_errors.SessionRestrictionError(session_id, "cannot be rebuilt"))

    first = wired.client.get(f"/api/v1/agent-sessions/{session_id}")
    second = wired.client.get(f"/api/v1/agent-sessions/{session_id}")

    assert (first.json()["restricted"], second.json()["restricted"]) == (True, True)
    assert counting.calls[session_id] == 1


def test_marks_restricted_without_reopen_when_investigation_link_cannot_be_rebuilt(
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

    shown = wired.client.get(f"/api/v1/agent-sessions/{session_id}")

    assert shown.status_code == 200, shown.text
    assert shown.json()["restricted"] is True
    assert _starts(fresh) == []


def test_tells_unread_hub_apart_when_restriction_of_project_unregistered(tmp_path: Path) -> None:
    """``restriction_of`` answers None only after scanning the project's runs; a project no
    registered hub names is unknown, not "none" (review round 4, Q2)."""
    hub = a_hub(tmp_path, a_record())
    registry, reader = a_reader(hub)
    restrictions = InvestigationRestrictions(
        HubCredentials(registry=registry, reader=reader, running_version=RUNNING)
    )
    plain = read_model_builders.an_agent_session(id=UNKNOWN_SESSION, project="demo")
    elsewhere = read_model_builders.an_agent_session(id=UNKNOWN_SESSION, project="nowhere")

    assert restrictions.restriction_of(plain) is None
    with pytest.raises(session_errors.RestrictionUnreadableError) as raised:
        restrictions.restriction_of(elsewhere)
    assert raised.value.agent_session_id == UNKNOWN_SESSION


def test_clears_unbuilt_mark_when_unlinked_session_reopened_free(
    wired: Any, investigation: Any
) -> None:
    """A forgotten session marked by a link that cannot be rebuilt, whose link then goes,
    reopens free and no longer reads restricted (review round 5, Q3)."""
    session_id, fresh, hub = _start_and_restart(wired, investigation)
    folder = hub / ".agent-runs" / "workflows" / RUN
    records = folder / "records.jsonl"
    kept = records.read_text(encoding="utf-8")
    records.write_text("not one JSON object\n{}\n", encoding="utf-8")
    marked = wired.client.get(f"/api/v1/agent-sessions/{session_id}")
    (folder / "investigation-1.session").unlink()
    records.write_text(kept, encoding="utf-8")

    sent = _message(wired, session_id)
    shown = wired.client.get(f"/api/v1/agent-sessions/{session_id}")

    assert marked.json()["restricted"] is True
    assert sent.status_code == 202, sent.text
    (spec,) = _starts(fresh)
    assert spec.tool_policy is None
    assert "restricted" not in shown.json()


def test_refuses_reopen_when_project_hub_unregistered_between_reads(
    wired: Any, investigation: Any, tmp_path: Path
) -> None:
    """The registry changes between the reopen's listing and the restriction's read: no hub
    names the project any more, so whether the session is held cannot be told and the reopen
    is refused, never resumed without its tool policy (fail closed, review round 5, Q2)."""
    first, hub = investigation(a_record())
    session_id = wired.client.post(ROUTE, json={}, headers=_origin(wired)).json()[
        "agent_session_id"
    ]
    driver, store = _restart(first, session_id)
    registry, reader = a_reader(hub)
    credentials = HubCredentials(registry=registry, reader=reader, running_version=RUNNING)
    unregistered = HubCredentials(
        registry=InMemoryHubRegistry(), reader=reader, running_version=RUNNING
    )
    fresh = build_rig(
        hidden_environment=credentials.names,
        restriction_of=InvestigationRestrictions(unregistered).restriction_of,
        driver=driver,
        store=store,
    )
    wired.wire(agent_sessions=fresh.control)

    sent = _message(wired, session_id)

    assert sent.status_code == 409, sent.text
    assert sent.json()["type"] == "urn:agent-hub:problem:agent-session-restriction-unavailable"
    assert _starts(fresh) == []
    assert fresh.store.get(session_id).status == AgentSessionStatus.ENDED


# The scenario builder: validate, the action library and save.


class _DiskWrites:
    """``ItemVersionWrites.write_file`` over the tmp hub: writes the file, records nothing."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def write_file(self, hub_path: str, unit: Any, content: bytes) -> Any:
        self.calls.append(unit.unit_path)
        target = Path(hub_path) / unit.unit_path
        target.parent.mkdir(parents=True, exist_ok=True)
        changed = not target.exists() or target.read_bytes() != content
        target.write_bytes(content)
        return ItemWriteResult(changed=changed, versioned=True, reason=None, version=None)


def _walk_document(scenarios: Any) -> dict[str, Any]:
    detail = scenarios.client.get("/api/v1/scenarios/demo/order-walk").json()
    document: dict[str, Any] = detail["document"]
    return document


def test_places_problems_on_nodes_when_builder_validates(scenarios: Any) -> None:
    document = _walk_document(scenarios)
    document["nodes"].append({"id": "lost", "type": "action", "action": "no-such"})
    document["nodes"].append(
        {"id": "early", "type": "action", "action": "send-order", "with": {"ref": "$CTX.nope"}}
    )

    checked = _post(
        scenarios, "/projects/demo/scenarios/validate", {"pack": "demo", "document": document}
    )

    assert checked.status_code == 200, checked.text
    body = checked.json()
    assert body["loads"] is False
    assert body["yaml"].startswith("version: 1\nkind: scenario\nname: order-walk\n")
    by_node = {problem["node"]: problem["message"] for problem in body["problems"]}
    assert "unknown action 'no-such'" in by_node["lost"]
    assert "early" in by_node
    assert [node["id"] for node in body["nodes"]] == ["send-order", "order-held", "lost", "early"]


def test_loads_when_builder_validates_scenario_unchanged(scenarios: Any) -> None:
    document = _walk_document(scenarios)

    body = _post(
        scenarios, "/projects/demo/scenarios/validate", {"pack": "demo", "document": document}
    ).json()

    assert (body["loads"], body["problems"]) == (True, [])


def test_lists_actions_with_output_fields_and_users_when_library_read(scenarios: Any) -> None:
    library = scenarios.client.get("/api/v1/projects/demo/actions")

    assert library.status_code == 200, library.text
    items = {item["action"]["ref"]: item for item in library.json()["items"]}
    assert list(items) == ["demo/get-order", "demo/release-hold", "demo/send-order"]
    get_order = items["demo/get-order"]
    assert [field["path"] for field in get_order["output_fields"]] == ["order", "status"]
    assert get_order["used_by"] == ["order-walk"]
    assert items["demo/release-hold"]["used_by"] == []


def test_writes_next_revision_when_builder_saves(scenarios: Any) -> None:
    writes = _DiskWrites()
    scenarios.wire(item_version_writes=writes)
    detail = scenarios.client.get("/api/v1/scenarios/demo/order-walk").json()
    document = detail["document"]
    document["description"] = "Edited in the builder"

    saved = scenarios.client.put(
        "/api/v1/scenarios/demo/order-walk",
        json={"pack": "demo", "document": document, "base_content_hash": detail["content_hash"]},
        headers=_origin(scenarios),
    )

    assert saved.status_code == 200, saved.text
    assert (saved.json()["revision"], saved.json()["path"]) == (2, "scenarios/demo/order-walk.yaml")
    assert writes.calls == ["scenarios/demo/order-walk.yaml"]
    reread = scenarios.client.get("/api/v1/scenarios/demo/order-walk").json()
    assert (reread["description"], reread["revision"]) == ("Edited in the builder", 2)


def test_refuses_stale_invalid_and_taken_when_builder_saves(scenarios: Any) -> None:
    writes = _DiskWrites()
    scenarios.wire(item_version_writes=writes)
    document = _walk_document(scenarios)

    def put(name: str, body: dict[str, Any]) -> Any:
        return scenarios.client.put(
            f"/api/v1/scenarios/demo/{name}", json=body, headers=_origin(scenarios)
        )

    stale = put(
        "order-walk", {"pack": "demo", "document": document, "base_content_hash": "sha256:old"}
    )
    broken = dict(document, nodes=[{"id": "x", "type": "action", "action": "no-such"}])
    invalid = put("fresh", {"pack": "demo", "document": broken})
    taken = put("order-walk", {"pack": "other", "document": document})

    assert (stale.status_code, stale.json()["code"]) == (409, "stale_document")
    assert (invalid.status_code, invalid.json()["code"]) == (409, "document_invalid")
    assert (taken.status_code, taken.json()["code"]) == (409, "name_taken")
    assert writes.calls == []


TREE = """\
version: 2
kind: scenario
name: order-tree
revision: 1
description: One demo order as blocks
inputs:
  ref:
    type: string
    required: true
stages:
- name: Send
  steps:
  - do: send-order
    with:
      target: api
      ref: $INPUTS.ref
  - wait_until: demo/get-order
    with:
      target: api
      ref: $INPUTS.ref
    until: $self.output.status == 'ON_HOLD'
    every: 10s
    timeout: 5m
"""


def _a_tree(scenarios: Any, text: str = TREE) -> Path:
    path: Path = scenarios.hub / "scenarios" / "demo" / "order-tree.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _put(scenarios: Any, name: str, document: dict[str, Any], *, base: str | None) -> Any:
    return scenarios.client.put(
        f"/api/v1/scenarios/demo/{name}",
        json={"pack": "demo", "document": document, "base_content_hash": base},
        headers=_origin(scenarios),
    )


def test_writes_nothing_when_saved_unchanged(scenarios: Any) -> None:
    writes = _DiskWrites()
    scenarios.wire(item_version_writes=writes)
    path = _a_tree(scenarios)
    detail = scenarios.client.get("/api/v1/scenarios/demo/order-tree").json()

    saved = _put(scenarios, "order-tree", detail["document"], base=detail["content_hash"])

    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert (body["changed"], body["versioned"], body["revision"]) == (False, False, 1)
    assert body["content_hash"] == detail["content_hash"]
    assert body["yaml"] == TREE
    assert writes.calls == []
    assert path.read_text(encoding="utf-8") == TREE


def test_keeps_revision_when_graph_saved_again_unchanged(scenarios: Any) -> None:
    writes = _DiskWrites()
    scenarios.wire(item_version_writes=writes)
    detail = scenarios.client.get("/api/v1/scenarios/demo/order-walk").json()
    first = _put(scenarios, "order-walk", detail["document"], base=detail["content_hash"]).json()
    path = scenarios.hub / "scenarios" / "demo" / "order-walk.yaml"
    written = path.read_bytes()

    again = _put(scenarios, "order-walk", detail["document"], base=first["content_hash"]).json()

    assert (first["changed"], first["revision"]) == (True, 2)
    assert (again["changed"], again["revision"]) == (False, 2)
    assert again["content_hash"] == first["content_hash"]
    assert writes.calls == ["scenarios/demo/order-walk.yaml"]
    assert path.read_bytes() == written


def test_writes_next_revision_when_tree_saved_with_an_edit(scenarios: Any) -> None:
    writes = _DiskWrites()
    scenarios.wire(item_version_writes=writes)
    path = _a_tree(scenarios)
    detail = scenarios.client.get("/api/v1/scenarios/demo/order-tree").json()
    document = detail["document"]
    document["description"] = "Edited in the builder"

    saved = _put(scenarios, "order-tree", document, base=detail["content_hash"])

    assert saved.status_code == 200, saved.text
    assert (saved.json()["changed"], saved.json()["revision"]) == (True, 2)
    expected = TREE.replace("revision: 1", "revision: 2").replace(
        "One demo order as blocks", "Edited in the builder"
    )
    assert path.read_text(encoding="utf-8") == expected


def test_places_action_problems_on_tree_nodes_when_builder_validates(scenarios: Any) -> None:
    document = _walk_document(scenarios)
    _a_tree(scenarios)
    tree = scenarios.client.get("/api/v1/scenarios/demo/order-tree").json()["document"]
    tree["stages"][0]["steps"].append({"id": "lost", "do": "no-such"})

    body = _post(
        scenarios, "/projects/demo/scenarios/validate", {"pack": "demo", "document": tree}
    ).json()
    unchanged = _post(
        scenarios, "/projects/demo/scenarios/validate", {"pack": "demo", "document": document}
    ).json()

    assert body["loads"] is False
    assert body["yaml"].startswith("version: 2\nkind: scenario\nname: order-tree\n")
    by_node = {problem["node"]: problem for problem in body["problems"]}
    assert "unknown action 'no-such'" in by_node["lost"]["message"]
    assert by_node["lost"]["key"] == "stages[0].steps[2].do"
    assert (unchanged["loads"], unchanged["problems"]) == (True, [])


def test_lists_tree_scenarios_as_users_when_library_read(scenarios: Any) -> None:
    _a_tree(scenarios)

    library = scenarios.client.get("/api/v1/projects/demo/actions").json()

    items = {item["action"]["ref"]: item for item in library["items"]}
    assert items["demo/get-order"]["used_by"] == ["order-tree", "order-walk"]
    assert items["demo/send-order"]["used_by"] == ["order-tree", "order-walk"]


def test_reads_checks_and_drops_claudes_proposal_when_builder_reviews(scenarios: Any) -> None:
    route = "/api/v1/scenarios/demo/order-walk/proposal"
    missing = scenarios.client.get(route)
    proposal = (
        scenarios.hub / ".agent-runs" / "proposals" / "scenarios" / "demo" / "order-walk.yaml"
    )
    proposal.parent.mkdir(parents=True)
    proposal.write_text(WALK.replace("One demo order from send to hold", "Proposed by Claude"))

    shown = scenarios.client.get(route)
    dropped = _post(scenarios, "/scenarios/demo/order-walk/proposal/dismiss", {})

    assert missing.status_code == 404
    assert shown.status_code == 200, shown.text
    body = shown.json()
    assert body["path"] == ".agent-runs/proposals/scenarios/demo/order-walk.yaml"
    assert body["document"]["description"] == "Proposed by Claude"
    assert body["check"]["loads"] is True
    assert dropped.status_code == 204
    assert not proposal.exists()


NEW_ACTION = {
    "pack": "demo",
    "name": "render-invoice-pdf",
    "description": "Render the invoice PDF and upload it",
    "effect": "write",
    "runtime": "python",
    "inputs": [{"name": "invoice_no", "type": "string", "required": True}],
    "outputs": [{"name": "pdf_key", "type": "string"}],
    "script_text": "import json, sys\nprint(json.dumps({'summary': 'render'}))\n",
}


def test_writes_draft_action_when_builder_creates_one(scenarios: Any) -> None:
    writes = _DiskWrites()
    scenarios.wire(item_version_writes=writes)

    created = _post(scenarios, "/projects/demo/actions", NEW_ACTION)
    again = _post(scenarios, "/projects/demo/actions", NEW_ACTION)
    bad = _post(
        scenarios,
        "/projects/demo/actions",
        dict(NEW_ACTION, name="bad-schema", outputs=[{"name": "x", "type": "nope"}]),
    )

    assert created.status_code == 201, created.text
    body = created.json()
    assert (body["name"], body["effect"], body["draft"]) == ("render-invoice-pdf", "write", True)
    assert body["script"] == "actions/demo/scripts/render_invoice_pdf.py"
    assert [item["name"] for item in body["inputs"]] == ["invoice_no"]
    assert writes.calls == [
        "actions/demo/scripts/render_invoice_pdf.py",
        "actions/demo/render-invoice-pdf.yaml",
    ]
    assert (again.status_code, again.json()["code"]) == (409, "name_taken")
    assert bad.status_code == 422


def test_rewrites_action_when_builder_edits_one(scenarios: Any) -> None:
    writes = _DiskWrites()
    scenarios.wire(item_version_writes=writes)
    body = dict(
        NEW_ACTION, name="get-order", runtime="sh", effect="read", description="Read it again"
    )

    edited = scenarios.client.put(
        "/api/v1/projects/demo/actions/demo/get-order", json=body, headers=_origin(scenarios)
    )
    missing = scenarios.client.put(
        "/api/v1/projects/demo/actions/demo/nope", json=body, headers=_origin(scenarios)
    )

    assert edited.status_code == 200, edited.text
    assert (edited.json()["description"], edited.json()["draft"]) == ("Read it again", True)
    # The script keeps its file (same runtime), so a scenario that calls it keeps working.
    assert writes.calls == ["actions/demo/scripts/get-order.sh", "actions/demo/get-order.yaml"]
    assert (missing.status_code, missing.json()["code"]) == (409, "unknown_action")


def test_writes_nothing_when_builder_saves_unchanged_document(scenarios: Any) -> None:
    writes = _DiskWrites()
    scenarios.wire(item_version_writes=writes)
    detail = scenarios.client.get("/api/v1/scenarios/demo/order-walk").json()
    first = scenarios.client.put(
        "/api/v1/scenarios/demo/order-walk",
        json={
            "pack": "demo",
            "document": detail["document"],
            "base_content_hash": detail["content_hash"],
        },
        headers=_origin(scenarios),
    ).json()
    # The file is now the canonical YAML: the same document again writes nothing.
    reread = scenarios.client.get("/api/v1/scenarios/demo/order-walk").json()

    again = scenarios.client.put(
        "/api/v1/scenarios/demo/order-walk",
        json={
            "pack": "demo",
            "document": reread["document"],
            "base_content_hash": reread["content_hash"],
        },
        headers=_origin(scenarios),
    )

    assert again.status_code == 200, again.text
    body = again.json()
    assert (body["changed"], body["versioned"]) == (False, False)
    assert body["revision"] == first["revision"]
    assert body["content_hash"] == reread["content_hash"]
    assert writes.calls == ["scenarios/demo/order-walk.yaml"]


def test_shows_problem_when_claudes_proposal_holds_an_alias(scenarios: Any) -> None:
    proposal = (
        scenarios.hub / ".agent-runs" / "proposals" / "scenarios" / "demo" / "order-walk.yaml"
    )
    proposal.parent.mkdir(parents=True)
    # An alias would expand with every level: the strict loader refuses it unread.
    proposal.write_text("a: &a [x, x]\nb: [*a, *a]\nnodes: []\n")

    shown = scenarios.client.get("/api/v1/scenarios/demo/order-walk/proposal")

    assert shown.status_code == 200, shown.text
    body = shown.json()
    assert body["document"] is None
    assert "alias" in body["problem"] or "anchor" in body["problem"]


def test_refuses_dismiss_when_a_proposal_folder_is_a_link(scenarios: Any, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "order-walk.yaml").write_text("kept")
    folder = scenarios.hub / ".agent-runs" / "proposals" / "scenarios"
    folder.mkdir(parents=True)
    (folder / "demo").symlink_to(outside)

    dropped = _post(scenarios, "/scenarios/demo/order-walk/proposal/dismiss", {})

    assert (dropped.status_code, dropped.json()["code"]) == (409, "link_in_path")
    assert (outside / "order-walk.yaml").read_text() == "kept"


def test_refuses_action_write_when_script_is_shared_or_taken(scenarios: Any) -> None:
    writes = _DiskWrites()
    scenarios.wire(item_version_writes=writes)
    pack = scenarios.hub / "actions" / "demo"
    shared = (pack / "send-order.yaml").read_text().replace("send-order.sh", "get-order.sh")
    (pack / "send-order.yaml").write_text(shared)
    (pack / "scripts" / "taken_one.sh").write_text("echo hand-written\n")
    body = dict(NEW_ACTION, name="get-order", runtime="sh", effect="read")

    edited = scenarios.client.put(
        "/api/v1/projects/demo/actions/demo/get-order", json=body, headers=_origin(scenarios)
    )
    clobber = _post(
        scenarios, "/projects/demo/actions", dict(NEW_ACTION, name="taken-one", runtime="sh")
    )

    assert (edited.status_code, edited.json()["code"]) == (409, "script_shared")
    assert "send-order" in edited.json()["detail"]
    assert (clobber.status_code, clobber.json()["code"]) == (409, "name_taken")
    assert writes.calls == []


def test_reads_no_proposal_when_its_path_is_a_fifo(scenarios: Any) -> None:
    folder = scenarios.hub / ".agent-runs" / "proposals" / "scenarios" / "demo"
    folder.mkdir(parents=True)
    os.mkfifo(folder / "order-walk.yaml")

    # Opened without blocking and refused as not a regular file.
    shown = scenarios.client.get("/api/v1/scenarios/demo/order-walk/proposal")

    assert shown.status_code == 404


LOOP_WALK = """\
version: 1
kind: scenario
name: loop-walk
revision: 1
description: Release the hold until the order reads done
inputs:
  ref: {type: string, required: true}
nodes:
  - id: retry-release
    type: loop_group
    max_iterations: 3
    until_when: "$check.output.status == 'DONE'"
    nodes:
      - id: release
        type: action
        action: release-hold
        with: {target: api, ref: $INPUTS.ref}
      - id: check
        type: action
        action: get-order
        depends_on: [release]
        with: {target: api, ref: $INPUTS.ref}
"""


def test_lists_repeat_body_actions_when_scenarios_detail_read(scenarios: Any) -> None:
    (scenarios.hub / "scenarios" / "demo" / "loop-walk.yaml").write_text(LOOP_WALK)

    detail = scenarios.client.get("/api/v1/scenarios/demo/loop-walk")

    assert detail.status_code == 200, detail.text
    assert [action["ref"] for action in detail.json()["actions"]] == ["release-hold", "get-order"]


def test_keeps_text_values_when_scenarios_detail_document_read(scenarios: Any) -> None:
    # The strict loader keeps a date-like description and on, 012 and 1:30 as text.
    path = scenarios.hub / "scenarios" / "demo" / "order-walk.yaml"
    path.write_text(
        WALK.replace(
            "description: One demo order from send to hold", "description: 2026-10-23"
        ).replace("with: {target: api, ref: $INPUTS.ref}", "with: {target: api, ref: 012}", 1)
    )

    detail = scenarios.client.get("/api/v1/scenarios/demo/order-walk")

    assert detail.status_code == 200, detail.text
    document = detail.json()["document"]
    assert document["description"] == "2026-10-23"
    assert document["nodes"][0]["with"]["ref"] == "012"


def test_keeps_number_like_text_as_text_when_builder_renders() -> None:
    document = {"version": 1, "kind": "scenario", "name": "n", "description": "1e5", "x": "true"}

    loaded = load_workflow_bytes(render_document(document).encode(), source="n.yaml").document

    assert (loaded["description"], loaded["x"]) == ("1e5", "true")


def test_refuses_unchanged_save_when_document_no_longer_loads(scenarios: Any) -> None:
    writes = _DiskWrites()
    scenarios.wire(item_version_writes=writes)
    detail = scenarios.client.get("/api/v1/scenarios/demo/order-walk").json()
    body = {
        "pack": "demo",
        "document": detail["document"],
        "base_content_hash": detail["content_hash"],
    }
    scenarios.client.put("/api/v1/scenarios/demo/order-walk", json=body, headers=_origin(scenarios))
    reread = scenarios.client.get("/api/v1/scenarios/demo/order-walk").json()
    (scenarios.hub / "actions" / "demo" / "get-order.yaml").unlink()

    again = scenarios.client.put(
        "/api/v1/scenarios/demo/order-walk",
        json={
            "pack": "demo",
            "document": reread["document"],
            "base_content_hash": reread["content_hash"],
        },
        headers=_origin(scenarios),
    )

    assert (again.status_code, again.json()["code"]) == (409, "document_invalid")


def test_refuses_action_write_when_script_named_another_way_or_runtime_moves_onto_a_file(
    scenarios: Any,
) -> None:
    writes = _DiskWrites()
    scenarios.wire(item_version_writes=writes)
    pack = scenarios.hub / "actions" / "demo"
    other = (pack / "send-order.yaml").read_text().replace("send-order.sh", "./get-order.sh")
    (pack / "send-order.yaml").write_text(other)
    (pack / "scripts" / "release_hold.py").write_text("print('hand-written')\n")
    shared = dict(NEW_ACTION, name="get-order", runtime="sh", effect="read")
    moved = dict(NEW_ACTION, name="release-hold", runtime="python", effect="write")

    edited = scenarios.client.put(
        "/api/v1/projects/demo/actions/demo/get-order", json=shared, headers=_origin(scenarios)
    )
    rewritten = scenarios.client.put(
        "/api/v1/projects/demo/actions/demo/release-hold", json=moved, headers=_origin(scenarios)
    )

    assert (edited.status_code, edited.json()["code"]) == (409, "script_shared")
    assert (rewritten.status_code, rewritten.json()["code"]) == (409, "name_taken")
    assert writes.calls == []


def test_refuses_proposal_when_over_the_size_bound(scenarios: Any) -> None:
    proposal = (
        scenarios.hub / ".agent-runs" / "proposals" / "scenarios" / "demo" / "order-walk.yaml"
    )
    proposal.parent.mkdir(parents=True)
    proposal.write_text(WALK + "# " + "x" * (256 << 10) + "\n")

    body = scenarios.client.get("/api/v1/scenarios/demo/order-walk/proposal").json()

    assert body["document"] is None
    assert body["problem"] == "the proposal is over 256 KiB"


# Debugging a scenario run written as blocks, its values and migrate (ADR 0049; AC-507.13 (API),
# .16, .17 (API); docs/API.md § Scenarios, Debugging and migration). The run
# ``tree-1`` of ``order-debug`` pins the tree below in its snapshot; the fake launcher records
# each CLI child it is asked for, so no child process runs.

DEBUG_TREE = """\
version: 2
kind: scenario
name: order-debug
revision: 1
description: One demo order, debugged block by block
inputs:
  ref:
    type: string
    required: true
stages:
- name: Send
  steps:
  - do: send-order
    with:
      target: api
      ref: $INPUTS.ref
  - wait_until: demo/get-order
    with:
      target: api
      ref: $INPUTS.ref
    until: $self.output.status == 'ON_HOLD'
    every: 10s
    timeout: 5m
- name: Check
  steps:
  - you: Confirm the hold, then approve.
"""
DEBUG_RUN = "tree-1"
DEBUG_FOLDER = Path(".agent-runs", "workflows", DEBUG_RUN)
OPEN = {"order": "o-1", "status": "OPEN"}
HELD = {"order": "o-1", "status": "ON_HOLD"}
CALLED = {"target": "api", "ref": "T-1"}
DEBUG_PAUSE = {
    "event": "debug.pause",
    "node": "check--1",
    "block": "2.1",
    "reason": "breakpoint",
    "number": 1,
    "pass": {"layer": 2, "ends": {}, "before": {}, "changed": [], "stale": [], "gate": None},
    "gates": {},
    "asks": {},
}


def a_debug_run(
    hub: Path, *, environment: str = "local", paused: bool = True
) -> list[dict[str, Any]]:
    """``order-debug`` run in ``environment``: its breakpoint on 2.1, its first two blocks
    finished (the Wait until after two polls), then paused before 2.1 (or still running)."""
    (hub / "scenarios" / "demo" / "order-debug.yaml").write_text(DEBUG_TREE, encoding="utf-8")
    snapshot = hub / DEBUG_FOLDER / "snapshot"
    snapshot.mkdir(parents=True, exist_ok=True)
    pinned = load_workflow_bytes(DEBUG_TREE.encode(), source="order-debug.yaml").document
    (snapshot / "workflow.json").write_text(json.dumps(dict(pinned)), encoding="utf-8")
    records: list[dict[str, Any]] = [
        {"event": "start", "run": DEBUG_RUN, "workflow": "scenario:order-debug"}
        | {"kind": "scenario", "scenario": "order-debug", "pack": "demo"}
        | {"environment": environment, "mode": "interactive", "ts": "2026-10-24T10:00:00+00:00"},
        {"event": "inputs", "inputs": {"ref": "T-1"}},
        {"event": "debug.breakpoints", "addresses": ["2.1"]},
        {"event": "step_start", "node": "send--1", "attempt": 1},
        {"event": "action", "node": "send--1", "attempt": 1, "action": "demo/send-order"}
        | {"effect": "write", "inputs": CALLED, "status": "ok"},
        {"event": "step_end", "node": "send--1", "attempt": 1, "status": "ok", "output": OPEN},
        {"event": "step_start", "node": "send--2", "attempt": 1},
        {"event": "action_start", "node": "send--2", "attempt": 1, "poll": 1},
        {"event": "expect.poll", "node": "send--2", "attempt": 1, "poll": 1, "held": False}
        | {"output": OPEN},
        {"event": "action_start", "node": "send--2", "attempt": 1, "poll": 2},
        {"event": "expect.poll", "node": "send--2", "attempt": 1, "poll": 2, "held": True}
        | {"output": HELD},
        {"event": "action", "node": "send--2", "attempt": 1, "poll": 2, "action": "demo/get-order"}
        | {"effect": "read", "inputs": CALLED, "status": "ok"},
        {"event": "step_end", "node": "send--2", "attempt": 1, "status": "ok", "output": HELD},
    ]
    if paused:
        records += [{"event": "held", "groups": {}}, DEBUG_PAUSE]
    path = hub / DEBUG_FOLDER / "records.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in records), encoding="utf-8")
    return records


def _put_json(wired: Any, path: str, body: dict[str, Any]) -> Any:
    return wired.client.put(f"/api/v1{path}", json=body, headers=_origin(wired))


def _recorded(hub: Path) -> bytes:
    return (hub / DEBUG_FOLDER / "records.jsonl").read_bytes()


def test_shows_version_and_blocks_when_a_tree_scenario_detail_read(scenarios: Any) -> None:
    a_debug_run(scenarios.hub)

    tree = scenarios.client.get("/api/v1/scenarios/demo/order-debug").json()
    graph = scenarios.client.get("/api/v1/scenarios/demo/order-walk").json()

    assert tree["version"] == 2
    shown = [(b["address"], b["kind"], tuple(b["entry_nodes"])) for b in tree["blocks"]]
    assert shown == [
        ("1", "stage", ("send--1",)),
        ("1.1", "do", ("send--1",)),
        ("1.2", "wait_until", ("send--2",)),
        ("2", "stage", ("check--1",)),
        ("2.1", "you", ("check--1",)),
    ]
    assert (tree["blocks"][0]["label"], tree["blocks"][3]["label"]) == ("Send", "Check")
    assert (graph["version"], graph["blocks"]) == (1, [])


def test_shows_debug_pause_breakpoints_and_stepping_when_a_paused_run_read(scenarios: Any) -> None:
    a_debug_run(scenarios.hub)
    paused = scenarios.client.get(f"/api/v1/scenario-runs/{DEBUG_RUN}").json()
    with (scenarios.hub / DEBUG_FOLDER / "records.jsonl").open("a", encoding="utf-8") as file:
        file.write(json.dumps({"event": "debug.command", "command": "step"} | {"number": 1}))
        file.write("\n" + json.dumps({"event": "resume"}) + "\n")
    stepping = scenarios.client.get(f"/api/v1/scenario-runs/{DEBUG_RUN}").json()

    assert paused["debug"] == {"block": "2.1", "node": "check--1", "reason": "breakpoint"} | {
        "number": 1,
        "at": None,
    }
    assert (paused["breakpoints"], paused["stepping"]) == (["2.1"], False)
    assert (stepping["debug"], stepping["stepping"]) == (None, True)
    # The run view stays metadata: no action input or output.
    assert "T-1" not in json.dumps(paused)


def test_gives_the_pinned_trees_blocks_and_each_lines_block_when_a_tree_run_read(
    scenarios: Any,
) -> None:
    records = a_debug_run(scenarios.hub)
    # A gate is its step's block; a line about no node (the start) has no block.
    asked = [
        {"event": "step_start", "node": "send--1__ask", "attempt": 1},
        {"event": "step_end", "node": "send--1__ask", "attempt": 1, "status": "ok"},
    ]
    records[3:3] = asked
    path = scenarios.hub / DEBUG_FOLDER / "records.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in records), encoding="utf-8")
    # The file now drops the stage Check (2, 2.1) and adds a third block to Send (1.3).
    edited = DEBUG_TREE.split("- name: Check\n")[0] + "  - you: Look again.\n"
    (scenarios.hub / "scenarios" / "demo" / "order-debug.yaml").write_text(edited)
    write_records(scenarios.hub, a_paused_walk(scenarios.hub, environment="local"))

    run = scenarios.client.get(f"/api/v1/scenario-runs/{DEBUG_RUN}").json()
    graph = scenarios.client.get(f"/api/v1/scenario-runs/{WALK_RUN}").json()

    assert run["blocks"] == [
        {"address": "1", "kind": "stage", "label": "Send"},
        {"address": "1.1", "kind": "do", "label": "send-order"},
        {"address": "1.2", "kind": "wait_until", "label": "demo/get-order"},
        {"address": "2", "kind": "stage", "label": "Check"},
        {"address": "2.1", "kind": "you", "label": "Confirm the hold, then approve."},
    ]
    shown = [(entry["event"], entry["node"], entry["block"]) for entry in run["timeline"]]
    assert shown == [
        ("start", None, None),
        ("step_start", "send--1__ask", "1.1"),
        ("step_end", "send--1__ask", "1.1"),
        ("step_start", "send--1", "1.1"),
        ("step_end", "send--1", "1.1"),
        ("step_start", "send--2", "1.2"),
        ("step_end", "send--2", "1.2"),
    ]
    # A graph run has no block: its lines name nodes only.
    assert graph["blocks"] == []
    assert {entry["block"] for entry in graph["timeline"]} == {None}


def test_sets_breakpoints_through_the_cli_when_blocks_of_the_pinned_tree_put(
    scenarios: Any,
) -> None:
    a_debug_run(scenarios.hub)
    route = f"/scenario-runs/{DEBUG_RUN}/breakpoints"

    written = _put_json(scenarios, route, {"blocks": ["2", "1.2", "2"]})
    cleared = _put_json(scenarios, route, {"blocks": []})
    unknown = _put_json(scenarios, route, {"blocks": ["1.2", "9.9"]})
    option = _put_json(scenarios, route, {"blocks": ["--set"]})
    too_many = _put_json(scenarios, route, {"blocks": ["1.1"] * 513})

    assert written.status_code == 200, written.text
    # In the pinned tree's order, each once.
    assert written.json() == {"run_id": DEBUG_RUN, "blocks": ["1.2", "2"]}
    assert cleared.json() == {"run_id": DEBUG_RUN, "blocks": []}
    assert unknown.status_code == 422, unknown.text
    body = unknown.json()
    assert (body["type"], body["code"]) == (
        "urn:agent-hub:problem:workflow-run-unknown-block",
        "unknown_block",
    )
    assert body["block"] == "9.9"
    assert "9.9" in body["detail"]
    # An address outside the grammar never reaches the CLI's argv (no option such as --set).
    assert (option.status_code, too_many.status_code) == (422, 422)
    assert scenarios.launcher.calls == [
        ("break", (DEBUG_RUN, ("1.2", "2"))),
        ("break", (DEBUG_RUN, ())),
    ]


def test_checks_breakpoints_against_the_pinned_tree_when_the_scenario_file_changed(
    scenarios: Any,
) -> None:
    a_debug_run(scenarios.hub)
    # The file now drops the stage Check (2, 2.1) and adds a third block to Send (1.3).
    edited = DEBUG_TREE.split("- name: Check\n")[0] + "  - you: Look again.\n"
    (scenarios.hub / "scenarios" / "demo" / "order-debug.yaml").write_text(edited)
    route = f"/scenario-runs/{DEBUG_RUN}/breakpoints"

    pinned = _put_json(scenarios, route, {"blocks": ["2.1"]})
    added = _put_json(scenarios, route, {"blocks": ["1.3"]})

    assert pinned.status_code == 200, pinned.text
    assert pinned.json()["blocks"] == ["2.1"]
    assert (added.status_code, added.json()["code"], added.json()["block"]) == (
        422,
        "unknown_block",
        "1.3",
    )
    assert scenarios.launcher.calls == [("break", (DEBUG_RUN, ("2.1",)))]


def test_pins_debug_bounds_when_the_routes_are_built() -> None:
    # docs/API.md § Debugging and migration: an address is at most 64 characters, a body at
    # most 512 of them, and a run's pinned tree is read up to 1 MiB.
    assert scenario_catalog.MAX_ADDRESS_CHARS == 64
    assert scenario_catalog.MAX_BREAKPOINTS == 512
    assert scenario_catalog.SNAPSHOT_BYTES == 1024 * 1024


def test_enforces_the_address_bound_at_the_body_when_an_address_fits_the_grammar(
    scenarios: Any,
) -> None:
    a_debug_run(scenarios.hub)
    route = f"/scenario-runs/{DEBUG_RUN}/breakpoints"
    longest = "11" + ".1" * 31
    over = "1" + ".1" * 32

    at_bound = _put_json(scenarios, route, {"blocks": [longest]})
    past_bound = _put_json(scenarios, route, {"blocks": [over]})

    assert (len(longest), len(over)) == (64, 65)
    # The longest address reaches the pinned tree, which does not hold it; one past is the body's.
    assert (at_bound.status_code, at_bound.json()["code"]) == (422, "unknown_block")
    assert past_bound.status_code == 422, past_bound.text
    assert past_bound.json().get("code") != "unknown_block"
    assert scenarios.launcher.calls == []


def test_names_the_unreadable_snapshot_when_breakpoints_put_on_a_tree_run_without_one(
    scenarios: Any,
) -> None:
    a_debug_run(scenarios.hub)
    snapshot = scenarios.hub / DEBUG_FOLDER / "snapshot" / "workflow.json"
    route = f"/scenario-runs/{DEBUG_RUN}/breakpoints"

    snapshot.write_text("{not json", encoding="utf-8")
    broken = _put_json(scenarios, route, {"blocks": ["2.1"]})
    snapshot.unlink()
    missing = _put_json(scenarios, route, {"blocks": ["2.1"]})

    for refused in (broken, missing):
        assert (refused.status_code, refused.json()["code"]) == (422, "unknown_block")
        assert "pinned tree cannot be read" in refused.json()["detail"]
        assert "version 2" not in refused.json()["detail"]
    assert scenarios.launcher.calls == []


class RefusingBreakLauncher(FakeScenarioLauncher):
    def set_breakpoints(self, hub_path: str, run_id: str, addresses: tuple[str, ...]) -> None:
        super().set_breakpoints(hub_path, run_id, addresses)
        reason = "hub scenario break refused the breakpoints"
        raise RunConflictError(code="refused", reason=reason, run_id=run_id)


class StalledBreakLauncher(FakeScenarioLauncher):
    def set_breakpoints(self, hub_path: str, run_id: str, addresses: tuple[str, ...]) -> None:
        super().set_breakpoints(hub_path, run_id, addresses)
        raise RunLaunchError("hub scenario break did not finish: TimeoutExpired")


@pytest.mark.parametrize(
    ("launcher", "status", "code"),
    [(RefusingBreakLauncher, 409, "refused"), (StalledBreakLauncher, 502, "launch-failed")],
)
def test_gives_the_clis_refusal_when_hub_scenario_break_refuses_or_stalls(
    scenarios: Any, *, launcher: type[FakeScenarioLauncher], status: int, code: str
) -> None:
    a_debug_run(scenarios.hub)
    scenarios.launcher = launcher(scenarios.hub)
    rewire_tracker(scenarios, lambda _config, _hub: None)

    refused = _put_json(scenarios, f"/scenario-runs/{DEBUG_RUN}/breakpoints", {"blocks": ["2"]})

    assert refused.status_code == status, refused.text
    assert refused.json()["type"] == f"urn:agent-hub:problem:workflow-run-{code}"
    assert scenarios.launcher.calls == [("break", (DEBUG_RUN, ("2",)))]


@pytest.mark.parametrize("command", ["step", "continue"])
def test_refuses_step_and_continue_when_the_debug_pause_line_cannot_be_read(
    scenarios: Any, command: str
) -> None:
    records = a_debug_run(scenarios.hub, paused=False)
    unreadable = {key: value for key, value in DEBUG_PAUSE.items() if key != "pass"}
    lines = [*records, {"event": "held", "groups": {}}, unreadable]
    path = scenarios.hub / DEBUG_FOLDER / "records.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    before = _recorded(scenarios.hub)

    refused = _post(scenarios, f"/scenario-runs/{DEBUG_RUN}/{command}", {})

    assert (refused.status_code, refused.json()["code"]) == (422, "record_unreadable")
    assert scenarios.launcher.calls == []
    assert _recorded(scenarios.hub) == before


def test_refuses_breakpoints_when_the_run_ended_or_is_a_graph_run(scenarios: Any) -> None:
    a_debug_run(scenarios.hub)
    with (scenarios.hub / DEBUG_FOLDER / "records.jsonl").open("a", encoding="utf-8") as file:
        file.write(json.dumps({"event": "end", "status": "done"}) + "\n")
    write_records(scenarios.hub, a_paused_walk(scenarios.hub))
    # The graph run pins its version-1 document, as every run pins its scenario.
    walk = (scenarios.hub / "scenarios" / "demo" / "order-walk.yaml").read_bytes()
    pinned = load_workflow_bytes(walk, source="order-walk.yaml").document
    snapshot = scenarios.hub / WALK_RECORDS.parent / "snapshot"
    snapshot.mkdir(parents=True, exist_ok=True)
    (snapshot / "workflow.json").write_text(json.dumps(dict(pinned)), encoding="utf-8")

    ended = _put_json(scenarios, f"/scenario-runs/{DEBUG_RUN}/breakpoints", {"blocks": ["2.1"]})
    graph = _put_json(scenarios, f"/scenario-runs/{WALK_RUN}/breakpoints", {"blocks": ["1"]})

    assert (ended.status_code, ended.json()["code"]) == (409, "ended")
    assert (graph.status_code, graph.json()["code"]) == (422, "unknown_block")
    assert "version 2" in graph.json()["detail"]
    assert scenarios.launcher.calls == []


def test_steps_and_continues_through_the_cli_only_when_the_run_is_in_a_debug_pause(
    scenarios: Any,
) -> None:
    a_debug_run(scenarios.hub)
    write_records(scenarios.hub, a_paused_walk(scenarios.hub))

    stepped = _post(scenarios, f"/scenario-runs/{DEBUG_RUN}/step", {})
    continued = _post(scenarios, f"/scenario-runs/{DEBUG_RUN}/continue", {})
    at_gate = _post(scenarios, f"/scenario-runs/{WALK_RUN}/step", {})
    a_debug_run(scenarios.hub, paused=False)
    running = _post(scenarios, f"/scenario-runs/{DEBUG_RUN}/continue", {})

    assert stepped.status_code == 202, stepped.text
    assert stepped.json() == {"run_id": DEBUG_RUN, "project": "demo", "action": "step"}
    assert stepped.headers["Location"] == f"/api/v1/scenario-runs/{DEBUG_RUN}"
    assert continued.json()["action"] == "continue"
    # A gate keeps its own paths; a run past its pause is not in one.
    assert (at_gate.status_code, at_gate.json()["code"]) == (409, "not_debug_paused")
    assert (running.status_code, running.json()["code"]) == (409, "not_debug_paused")
    assert scenarios.launcher.calls == [
        ("debug", (DEBUG_RUN, "step")),
        ("debug", (DEBUG_RUN, "continue")),
    ]


class LiveDebugLauncher(FakeScenarioLauncher):
    def live_runs(self, hub_path: str) -> dict[str, str | None]:
        return {DEBUG_RUN: None}


def test_refuses_step_when_the_runs_child_still_runs(scenarios: Any) -> None:
    a_debug_run(scenarios.hub)
    launcher = LiveDebugLauncher(scenarios.hub)
    scenarios.launcher = launcher
    rewire_tracker(scenarios, lambda _config, _hub: None)

    refused = _post(scenarios, f"/scenario-runs/{DEBUG_RUN}/step", {})

    assert (refused.status_code, refused.json()["code"]) == (409, "in_use")
    assert launcher.calls == []


def test_refuses_debug_routes_and_records_nothing_when_the_environment_is_production(
    scenarios: Any,
) -> None:
    a_debug_run(scenarios.hub, environment="live")
    before = _recorded(scenarios.hub)
    run = f"/scenario-runs/{DEBUG_RUN}"
    start = {"environment": "live", "inputs": {"ref": "T-1"}, "breakpoints": ["1.2"]}

    breakpoints = _put_json(scenarios, f"{run}/breakpoints", {"blocks": ["1.2"]})
    stepped = _post(scenarios, f"{run}/step", {})
    continued = _post(scenarios, f"{run}/continue", {})
    values = scenarios.client.get(f"/api/v1{run}/values")
    started = _post(scenarios, "/scenarios/demo/order-debug/runs", start)
    cleared = _put_json(scenarios, f"{run}/breakpoints", {"blocks": []})

    for refused in (breakpoints, stepped, continued, values, started):
        assert refused.status_code == 409, refused.text
        body = refused.json()
        assert body["type"] == "urn:agent-hub:problem:workflow-run-debug-production"
        assert "live is a production environment" in body["detail"]
    # Clearing breakpoints stays allowed there; nothing else reached a child or the record.
    assert cleared.status_code == 200, cleared.text
    assert scenarios.launcher.calls == [("break", (DEBUG_RUN, ()))]
    assert _recorded(scenarios.hub) == before


def test_gives_inputs_and_finished_blocks_when_values_read_while_paused(scenarios: Any) -> None:
    a_debug_run(scenarios.hub)

    values = scenarios.client.get(f"/api/v1/scenario-runs/{DEBUG_RUN}/values")

    assert values.status_code == 200, values.text
    assert values.json() == {
        "run_id": DEBUG_RUN,
        "inputs": {"ref": "T-1"},
        "blocks": [
            {"address": "1.1", "node": "send--1", "attempt": 1, "status": "ok"}
            | {"with": CALLED, "output": OPEN, "polls": 0, "last_poll": None},
            {"address": "1.2", "node": "send--2", "attempt": 1, "status": "ok"}
            | {"with": CALLED, "output": HELD, "polls": 2, "last_poll": HELD},
        ],
    }


NESTED_TREE = """\
version: 2
kind: scenario
name: order-debug
revision: 2
description: One demo order, included and polled
inputs:
  ref:
    type: string
    required: true
stages:
- name: Send
  steps:
  - do: send-order
    with:
      target: api
      ref: $INPUTS.ref
  - include: order-walk
    with:
      ref: $INPUTS.ref
  - repeat:
      max: 2
      until: $poll.output.status == 'ON_HOLD'
      steps:
      - wait_until: demo/get-order
        id: poll
        with:
          target: api
          ref: $INPUTS.ref
        until: $self.output.status != ''
        every: 10s
        timeout: 5m
"""


def test_gives_each_node_its_blocks_address_when_values_read_of_gates_includes_and_repeats(
    scenarios: Any,
) -> None:
    a_debug_run(scenarios.hub)
    pinned = load_workflow_bytes(NESTED_TREE.encode(), source="order-debug.yaml").document
    snapshot = scenarios.hub / DEBUG_FOLDER / "snapshot" / "workflow.json"
    snapshot.write_text(json.dumps(dict(pinned)), encoding="utf-8")
    # A gate is its step's block, an included node its include's, a Repeat body node
    # (``<group>__<id>``) its own block's, and a gate on a body node that node's block.
    nodes = ("send--1__ask", "send--1", "send--2__send-order", "send--2__order-held")
    nodes += ("send--3__poll__ask", "send--3__poll", "send--3")
    records = [
        {"event": "start", "run": DEBUG_RUN, "workflow": "scenario:order-debug"}
        | {"kind": "scenario", "scenario": "order-debug", "pack": "demo"}
        | {"environment": "local", "mode": "interactive", "ts": "2026-10-24T10:00:00+00:00"},
        {"event": "inputs", "inputs": {"ref": "T-1"}},
        *({"event": "step_end", "node": node, "attempt": 1, "status": "ok"} for node in nodes),
        {"event": "held", "groups": {}},
    ]
    path = scenarios.hub / DEBUG_FOLDER / "records.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in records), encoding="utf-8")

    values = scenarios.client.get(f"/api/v1/scenario-runs/{DEBUG_RUN}/values")

    assert values.status_code == 200, values.text
    shown = [(block["node"], block["address"]) for block in values.json()["blocks"]]
    assert shown == [
        ("send--1__ask", "1.1"),
        ("send--1", "1.1"),
        ("send--2__send-order", "1.2"),
        ("send--2__order-held", "1.2"),
        ("send--3__poll__ask", "1.3.1"),
        ("send--3__poll", "1.3.1"),
        ("send--3", "1.3"),
    ]


def test_refuses_values_when_the_run_is_not_paused(scenarios: Any) -> None:
    a_debug_run(scenarios.hub, paused=False)
    running = scenarios.client.get(f"/api/v1/scenario-runs/{DEBUG_RUN}/values")
    write_records(scenarios.hub, a_paused_walk(scenarios.hub, environment="local"))
    at_gate = scenarios.client.get(f"/api/v1/scenario-runs/{WALK_RUN}/values")
    append_records(scenarios.hub, {"event": "end", "status": "cancelled"})
    ended = scenarios.client.get(f"/api/v1/scenario-runs/{WALK_RUN}/values")

    assert (running.status_code, running.json()["code"]) == (409, "not_paused")
    # A gate pause shows its values too; a version-1 run's blocks have no address.
    assert at_gate.status_code == 200, at_gate.text
    (polled,) = at_gate.json()["blocks"]
    assert (polled["address"], polled["node"], polled["status"]) == (None, "order-held", "failed")
    assert (ended.status_code, ended.json()["code"]) == (409, "not_paused")


def test_needs_the_launch_cookie_and_own_origin_when_values_read(scenarios: Any) -> None:
    a_debug_run(scenarios.hub)
    route = f"/api/v1/scenario-runs/{DEBUG_RUN}/values"

    foreign = scenarios.client.get(route, headers={"Origin": "http://127.0.0.1:9999"})
    scenarios.client.cookies.clear()
    unsigned = scenarios.client.get(route)
    view = scenarios.client.get(f"/api/v1/scenario-runs/{DEBUG_RUN}")

    assert foreign.status_code == 403
    assert "scenario run's values" in foreign.json()["detail"]
    assert unsigned.status_code == 401
    assert unsigned.json()["type"] == "urn:agent-hub:problem:agent-session-unauthorized"
    assert "scenario run's values" in unsigned.json()["detail"]
    # The run view itself needs no cookie.
    assert view.status_code == 200


def test_refuses_debug_routes_and_migrate_without_the_cookie_when_a_path_ends_with_a_newline(
    scenarios: Any,
) -> None:
    a_debug_run(scenarios.hub)
    scenarios.wire(item_version_writes=_DiskWrites())
    before = _recorded(scenarios.hub)
    walk = (scenarios.hub / "scenarios" / "demo" / "order-walk.yaml").read_bytes()
    run = f"/api/v1/scenario-runs/{DEBUG_RUN}"
    scenarios.client.cookies.clear()
    origin = _origin(scenarios)

    refused = (
        scenarios.client.get(f"{run}/values%0A"),
        scenarios.client.put(f"{run}/breakpoints%0A", json={"blocks": ["1"]}, headers=origin),
        scenarios.client.post(f"{run}/step%0A", headers=origin),
        scenarios.client.post(f"{run}/continue%0A", headers=origin),
        scenarios.client.post(
            "/api/v1/scenarios/demo/order-walk/migrate%0A", json={}, headers=origin
        ),
    )

    for response in refused:
        assert response.status_code == 404, response.text
        assert "T-1" not in response.text
    assert scenarios.launcher.calls == []
    assert _recorded(scenarios.hub) == before
    assert (scenarios.hub / "scenarios" / "demo" / "order-walk.yaml").read_bytes() == walk


def test_starts_with_breakpoints_in_tree_order_when_a_tree_run_asked(scenarios: Any) -> None:
    a_debug_run(scenarios.hub)
    path = "/scenarios/demo/order-debug/runs"
    body = {"environment": "local", "inputs": {"ref": "T-1"}}

    started = _post(scenarios, path, body | {"breakpoints": ["2", "1.2"]})
    unknown = _post(scenarios, path, body | {"breakpoints": ["3"]})
    graph = _post(scenarios, "/scenarios/demo/order-walk/runs", body | {"breakpoints": ["1"]})

    assert started.status_code == 202, started.text
    ((kind, spec),) = scenarios.launcher.calls
    assert (kind, spec.name, spec.breakpoints) == ("start", "order-debug", ("1.2", "2"))
    assert (unknown.status_code, unknown.json()["code"]) == (422, "unknown_block")
    assert (graph.status_code, graph.json()["code"]) == (422, "unknown_block")


LOST_TREE = DEBUG_TREE.replace("name: order-debug", "name: order-lost").replace(
    "  - do: send-order\n", "  - do: no-such\n"
)


def test_names_the_block_and_the_environment_when_a_start_is_refused(scenarios: Any) -> None:
    (scenarios.hub / "scenarios" / "demo" / "order-lost.yaml").write_text(LOST_TREE)

    body = {"environment": "local", "inputs": {"ref": "T-1"}}
    lost = _post(scenarios, "/scenarios/demo/order-lost/runs", body)
    missing = _post(scenarios, "/scenarios/demo/order-walk/runs", {"environment": "staging"})
    planned = _post(scenarios, "/scenarios/demo/order-walk/plan", {"environment": "staging"})

    assert (lost.status_code, lost.json()["code"]) == (409, "plan_problem")
    assert "block 1.1 (stages[0].steps[0]): unknown action 'no-such'" in lost.json()["detail"]
    assert "send--1" not in lost.json()["detail"]
    for refused in (missing, planned):
        assert refused.status_code == 422, refused.text
        assert 'as a value of environment "staging"' in refused.json()["detail"]
    assert scenarios.launcher.calls == []


EITHER_WALK = """\
version: 1
kind: scenario
name: either-walk
revision: 3
description: Either read lets the last one run
inputs:
  ref: {type: string, required: true}
nodes:
  - id: first
    type: action
    action: get-order
    with: {target: api, ref: $INPUTS.ref}
  - id: second
    type: action
    action: get-order
    with: {target: api, ref: $INPUTS.ref}
  - id: after
    type: action
    action: get-order
    depends_on: [first, second]
    trigger_rule: one_success
    with: {target: api, ref: $INPUTS.ref}
"""


def test_writes_the_tree_when_a_graph_scenario_is_migrated(scenarios: Any) -> None:
    writes = _DiskWrites()
    scenarios.wire(item_version_writes=writes)
    path = scenarios.hub / "scenarios" / "demo" / "order-walk.yaml"
    detail = scenarios.client.get("/api/v1/scenarios/demo/order-walk").json()
    route = "/scenarios/demo/order-walk/migrate"

    checked = _post(scenarios, route, {"check": True})
    unchanged = path.read_text(encoding="utf-8")
    migrated = _post(scenarios, route, {"base_content_hash": detail["content_hash"]})
    reread = scenarios.client.get("/api/v1/scenarios/demo/order-walk").json()

    assert checked.status_code == 200, checked.text
    body = checked.json()
    assert (body["path"], body["written"], body["problems"]) == (
        "scenarios/demo/order-walk.yaml",
        False,
        [],
    )
    assert body["yaml"].startswith("version: 2\nkind: scenario\nname: order-walk\nrevision: 1\n")
    assert body["content_hash"] == detail["content_hash"]
    assert unchanged == WALK
    assert migrated.status_code == 200, migrated.text
    assert (migrated.json()["written"], migrated.json()["yaml"]) == (True, body["yaml"])
    assert path.read_text(encoding="utf-8") == body["yaml"]
    assert writes.calls == ["scenarios/demo/order-walk.yaml"]
    assert migrated.json()["content_hash"] == reread["content_hash"]
    assert (reread["version"], reread["revision"]) == (2, 1)
    assert [step["id"] for step in reread["steps"]] == ["send-order", "order-held"]


def test_writes_nothing_when_migrate_is_stale_already_a_tree_or_cannot_map_a_node(
    scenarios: Any,
) -> None:
    writes = _DiskWrites()
    scenarios.wire(item_version_writes=writes)
    a_debug_run(scenarios.hub)
    either = scenarios.hub / "scenarios" / "demo" / "either-walk.yaml"
    either.write_text(EITHER_WALK, encoding="utf-8")

    stale = _post(scenarios, "/scenarios/demo/order-walk/migrate", {"base_content_hash": "x"})
    tree = _post(scenarios, "/scenarios/demo/order-debug/migrate", {})
    unmapped = _post(scenarios, "/scenarios/demo/either-walk/migrate", {})

    assert (stale.status_code, stale.json()["code"]) == (409, "stale_document")
    assert (tree.status_code, tree.json()["code"]) == (409, "scenario_already_tree")
    assert unmapped.status_code == 200, unmapped.text
    body = unmapped.json()
    assert (body["written"], body["yaml"]) == (False, None)
    nodes = {problem["node"] for problem in body["problems"]}
    assert "after" in nodes
    assert any("trigger_rule" in problem["message"] for problem in body["problems"])
    assert either.read_text(encoding="utf-8") == EITHER_WALK
    assert writes.calls == []


def _graph_named(name: str) -> dict[str, Any]:
    walk = WALK.replace("name: order-walk", f"name: {name}")
    return dict(load_workflow_bytes(walk.encode(), source=f"{name}.yaml").document)


def test_gives_the_refusal_when_migrate_is_asked_with_the_hash_read_of_a_json_file(
    scenarios: Any,
) -> None:
    writes = _DiskWrites()
    scenarios.wire(item_version_writes=writes)
    path = scenarios.hub / "scenarios" / "demo" / "walk-json.json"
    path.write_text(json.dumps(_graph_named("walk-json")), encoding="utf-8")
    detail = scenarios.client.get("/api/v1/scenarios/demo/walk-json").json()
    route = "/scenarios/demo/walk-json/migrate"
    read = {"base_content_hash": detail["content_hash"]}

    checked = _post(scenarios, route, {"check": True} | read)
    written = _post(scenarios, route, read)
    stale = _post(scenarios, route, {"check": True, "base_content_hash": "sha256:0"})

    assert detail["content_hash"] is not None
    for refused in (checked, written):
        assert refused.status_code == 200, refused.text
        body = refused.json()
        assert (body["written"], body["yaml"], body["content_hash"]) == (
            False,
            None,
            detail["content_hash"],
        )
        assert body["problems"] == [
            {"node": None, "message": "it is a JSON file: migrate rewrites a .yaml file in place"}
        ]
    # The JSON file's bytes are still read, so a file that changed is stale all the same.
    assert (stale.status_code, stale.json()["code"]) == (409, "stale_document")
    assert writes.calls == []


def test_gives_the_refusal_when_migrate_is_asked_of_a_link_or_a_path_the_writer_refuses(
    scenarios: Any,
) -> None:
    writes = _DiskWrites()
    scenarios.wire(item_version_writes=writes)
    pack = scenarios.hub / "scenarios" / "demo"
    (pack / "kept").mkdir()
    target = pack / "kept" / "walk-link.yaml"
    target.write_text(WALK.replace("name: order-walk", "name: walk-link"), encoding="utf-8")
    (pack / "walk-link.yaml").symlink_to(Path("kept", "walk-link.yaml"))
    slashed = scenarios.hub / "scenarios" / "de\\mo" / "walk-slash.yaml"
    slashed.parent.mkdir()
    slashed.write_text(WALK.replace("name: order-walk", "name: walk-slash"), encoding="utf-8")
    slash_hash = scenarios.client.get("/api/v1/scenarios/demo/walk-slash").json()["content_hash"]
    a_hash = {"base_content_hash": "sha256:0"}

    link = _post(scenarios, "/scenarios/demo/walk-link/migrate", {})
    link_hashed = _post(scenarios, "/scenarios/demo/walk-link/migrate", a_hash)
    slash = _post(
        scenarios, "/scenarios/demo/walk-slash/migrate", {"base_content_hash": slash_hash}
    )

    # A link is never read, so no hash can match it: its refusal is the answer.
    for refused in (link, link_hashed):
        assert refused.status_code == 200, refused.text
        assert (refused.json()["written"], refused.json()["content_hash"]) == (False, None)
        (problem,) = refused.json()["problems"]
        assert problem["node"] is None
        assert problem["message"].startswith("it is a link")
    assert slash.status_code == 200, slash.text
    assert slash.json()["content_hash"] == slash_hash
    (problem,) = slash.json()["problems"]
    assert problem["node"] is None
    assert "backslash" in problem["message"]
    assert target.read_text(encoding="utf-8").startswith("version: 1\n")
    assert writes.calls == []
