"""``/scenario-runs``: the investigation session hub web starts for a paused scenario run
(P-7, AM-2, AM-9, AC-350.20, AC-350.22, AC-350.41)."""

import json
from pathlib import Path
from typing import Any

import pytest

from agent_hub.api import scenario_investigation
from agent_hub.api.agent_session_runtime import HubCredentials
from agent_hub.api.scenario_investigation import InvestigationRestrictions, ScenarioInvestigations
from agent_hub.core.agent_sessions.agent_session import AgentSessionStatus, EndReason
from agent_hub.core.agent_sessions.driver import PastSession, StartSpec
from agent_hub.core.agent_sessions.errors import SessionsUnavailableError
from agent_hub.core.hub_config.problems import ConfigProblem
from agent_hub.core.hubs.hub_registry import HubRegistryError
from agent_hub.core.scenarios.investigation import tool_verdict
from agent_hub.core.testing.agent_session_rig import Rig, build_rig
from agent_hub.core.testing.agent_session_store_fakes import InMemoryAgentSessionStore
from agent_hub.core.testing.builders import an_environments_document
from agent_hub.core.testing.hub_fakes import FakeHub, FakeHubFileReader, InMemoryHubRegistry
from agent_hub.core.testing.read_model_builders import WORKDIR_ID
from agent_hub.core.testing.session_driver_fakes import InMemorySessionDriver

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
