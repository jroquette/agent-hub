"""Run budgets of the control plane (spec NFRs) on the composed app, at 10,000 events in 200
sessions built in ``tmp_path``: a hook POST p95 under 50 ms, a read endpoint p95 under 300 ms;
and AGH-201's: a session's problems p95 under 150 ms at 5,000 events, a brain note under 100 ms
and the brain tree under 150 ms in a hub of 2,000 notes; AGH-136's: a feature's tickets under
100 ms on a warm snapshot cache with 50 tickets; AGH-164's: the skills catalog under 150 ms and
a skill's detail under 100 ms, warm, with 200 skills beside the 10,000 events.

Each read follows an append, so it folds again (the memo is keyed by the high-water mark): the
budget holds while sessions are live, not only on a warm memo. The first read after start-up,
which loads every event once, is left out.
"""

import asyncio
import http.client
import json
import math
import statistics
import threading
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from agent_hub.api.app import create_app
from agent_hub.api.dependencies import ApiPorts
from agent_hub.api.server import LoopbackServer, bind_loopback
from agent_hub.api.session_token import cookie_name
from agent_hub.core.agent_sessions.driver import DriverEvent, DriverHandle, TextBlock, TextDelta
from agent_hub.core.events.event import Event
from agent_hub.core.testing.agent_session_rig import build_rig
from agent_hub.core.testing.builders import an_event
from agent_hub.core.testing.hook_inputs import a_hook_input, an_envelope
from agent_hub.core.testing.read_model_builders import WORKDIR_ID
from agent_hub.core.testing.session_driver_fakes import InMemorySessionDriver
from agent_hub.core.testing.session_scenarios import SCENARIO_START, a_session_events
from agent_hub.tracker_linear.graphql_reader import BATCH_SIZE

SESSIONS = 200
EVENTS = 10_000
HOOK_P95_MS = 50
READ_P95_MS = 300
READS = (
    "/api/v1/sessions",
    "/api/v1/sessions/session-100",
    "/api/v1/sessions/session-100/events",
    "/api/v1/sessions/session-100/summary",
    "/api/v1/live-sessions",
    "/api/v1/workflow-runs",
    "/api/v1/approvals",
    "/api/v1/learnings",
    "/api/v1/needs-you",
    "/api/v1/activity",
    "/api/v1/search?q=Bash",
    "/api/v1/collector/status",
)


def _ten_thousand_events() -> list[Event]:
    # Half the sessions hold 51 events, half 49: 3 + 2 per tool call.
    events: list[Event] = []
    for number in range(SESSIONS):
        tools = tuple(("Bash", {"command": f"make t{i}"}) for i in range(24 - number % 2))
        start = SCENARIO_START + timedelta(minutes=3 * number)
        events += a_session_events(f"session-{number:03d}", start=start, tools=tools)
    assert len(events) == EVENTS
    return events


def _p95(samples: list[float]) -> float:
    return statistics.quantiles(samples, n=20, method="inclusive")[-1]


def _timed(call: Callable[[], Any]) -> tuple[float, Any]:
    started = time.perf_counter()
    result = call()
    return (time.perf_counter() - started) * 1000, result


@pytest.fixture
def loaded(composed: Any) -> Any:
    for start in range(0, EVENTS, 2_000):
        composed.store.append(_ten_thousand_events()[start : start + 2_000])
    assert composed.client.get("/api/v1/sessions").status_code == 200
    return composed


def test_answers_hook_within_budget_when_store_holds_ten_thousand_events(loaded: Any) -> None:
    samples: list[float] = []
    for number in range(40):
        hook = a_hook_input("PreToolUse", tool_use_id=f"toolu_perf_{number}")
        envelope = an_envelope(hook).model_dump(mode="json")
        elapsed, response = _timed(
            lambda e=envelope: loaded.client.post("/api/v1/events/hooks", json=e)
        )
        assert response.status_code == 202
        samples.append(elapsed)

    assert _p95(samples) < HOOK_P95_MS, samples


def test_answers_reads_within_budget_when_each_read_follows_an_append(loaded: Any) -> None:
    samples: list[float] = []
    for round_number in range(2):
        for number, path in enumerate(READS):
            moment = SCENARIO_START + timedelta(days=2, seconds=100 * round_number + number)
            loaded.store.append([an_event(session="session-001", timestamp=moment)])
            elapsed, response = _timed(lambda p=path: loaded.client.get(p))
            assert response.status_code == 200, (path, response.text)
            samples.append(elapsed)

    assert _p95(samples) < READ_P95_MS, dict(zip(READS * 2, samples, strict=True))


# AGH-201 budgets (AC-201.44): the problems of a 5,000-event session, one brain note, and the
# brain tree of a hub holding 2,000 notes.
BIG_SESSION_EVENTS = 5_000
PROBLEMS_P95_MS = 150
BRAIN_NOTE_P95_MS = 100
BRAIN_TREE_P95_MS = 150
BRAIN_NOTES = 2_000
SAMPLES = 40


def _big_session() -> list[Event]:
    # A start, a prompt and 2 per tool call; every seventh call fails, so both recovered and
    # continued problems exist.
    tools = tuple(("Bash", {"command": f"make t{i % 50}"}) for i in range(2_499))
    failed = frozenset(range(0, len(tools), 7))
    events = a_session_events("session-big", tools=tools, failed_tools=failed, ended=False)
    assert len(events) == BIG_SESSION_EVENTS
    return events


def test_answers_problems_within_budget_when_session_holds_five_thousand_events(
    composed: Any,
) -> None:
    # As above, each read follows an append, here to another live session: the snapshot is
    # folded again while the 5,000-event session's own fold is reused (keyed by its events).
    composed.store.append(_big_session())
    assert composed.client.get("/api/v1/sessions/session-big/problems").status_code == 200
    samples: list[float] = []
    for number in range(SAMPLES):
        moment = SCENARIO_START + timedelta(days=1, seconds=number)
        composed.store.append([an_event(session="session-other", timestamp=moment)])
        elapsed, response = _timed(
            lambda: composed.client.get("/api/v1/sessions/session-big/problems")
        )
        assert response.status_code == 200, response.text
        assert response.json()["items"]
        samples.append(elapsed)

    assert _p95(samples) < PROBLEMS_P95_MS, samples


@pytest.fixture
def big_brain(composed: Any, make_hub: Callable[..., Path]) -> Any:
    hub = make_hub()
    for number in range(BRAIN_NOTES):
        folder = hub / "brain" / "learnings" / f"group-{number % 40:02d}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"note-{number:04d}.md").write_text(
            f"---\ntype: learning\n---\n# Note {number}\n\n" + "Text. " * 200, encoding="utf-8"
        )
    assert (
        composed.client.post(
            "/api/v1/hubs", json={"path": str(hub)}, headers={"Origin": "http://127.0.0.1:7420"}
        ).status_code
        == 201
    )
    return composed


def test_answers_brain_note_within_budget_when_hub_brain_holds_two_thousand_notes(
    big_brain: Any,
) -> None:
    path = {"path": "learnings/group-07/note-0007.md"}
    assert big_brain.client.get("/api/v1/projects/demo/brain/note", params=path).status_code == 200
    samples: list[float] = []
    for _ in range(SAMPLES):
        elapsed, response = _timed(
            lambda: big_brain.client.get("/api/v1/projects/demo/brain/note", params=path)
        )
        assert response.status_code == 200, response.text
        samples.append(elapsed)

    assert _p95(samples) < BRAIN_NOTE_P95_MS, samples


def test_answers_brain_tree_within_budget_when_hub_brain_holds_two_thousand_notes(
    big_brain: Any,
) -> None:
    assert big_brain.client.get("/api/v1/projects/demo/brain").status_code == 200
    samples: list[float] = []
    for _ in range(SAMPLES):
        elapsed, response = _timed(lambda: big_brain.client.get("/api/v1/projects/demo/brain"))
        assert response.status_code == 200, response.text
        samples.append(elapsed)

    assert _p95(samples) < BRAIN_TREE_P95_MS, samples


# AGH-136 budget (AC-136.37): a feature's tickets route on a warm snapshot cache, 50 tickets
# chained by "blocked by" in the plan and Linear.
TICKETS = 50
TICKETS_P95_MS = 100


def test_answers_tickets_within_budget_when_cache_warm_with_fifty_tickets(
    open_tickets: Any, tickets_kit: Any
) -> None:
    planned = [
        {
            "key": f"t{number}",
            "id": f"DEM-{number}",
            "title": f"Ticket {number}",
            "repo": "demo-api",
            "order": number,
            "blocked_by": [f"t{number - 1}"] if number > 1 else [],
        }
        for number in range(1, TICKETS + 1)
    ]
    issues = {
        f"DEM-{number}": tickets_kit.LinearIssue(
            f"Ticket {number}",
            state=("Done", "completed") if number <= 10 else ("Todo", "unstarted"),
            blocked_by=(f"DEM-{number - 1}",) if number > 1 else (),
        )
        for number in range(1, TICKETS + 1)
    }
    world = open_tickets(record=tickets_kit.a_ticket_record(planned), issues=issues)
    warm = world.tickets()
    assert warm.status_code == 200, warm.text
    assert (warm.json()["source"], len(warm.json()["tickets"])) == ("linear", TICKETS)
    samples: list[float] = []
    for _ in range(SAMPLES):
        elapsed, response = _timed(world.tickets)
        assert response.status_code == 200, response.text
        samples.append(elapsed)

    # One snapshot read, sent as batches of BATCH_SIZE ids: the warm samples call Linear no more.
    assert world.linear.count == math.ceil(TICKETS / BATCH_SIZE)
    assert _p95(samples) < TICKETS_P95_MS, samples


# The agent-session stream (spec NFR, AC-165.51): a delta reaches the browser within 50 ms (p95)
# and 100 ms (p99) of the driver emitting it, on a real loopback server, the deltas paced as a
# model streams them (1 ms apart).

DELTAS = 1_000
DELTA_GAP_SECONDS = 0.001
DELTA_P95_MS = 50
DELTA_P99_MS = 100
STREAM_TOKEN = "s" * 43


class _StampingDriver(InMemorySessionDriver):
    """The in-memory driver, noting when it emits each delta (keyed by its text)."""

    def __init__(self, **options: Any) -> None:
        super().__init__(**options)
        self.emitted: dict[str, float] = {}

    async def events(self, handle: DriverHandle) -> AsyncIterator[DriverEvent]:
        async for event in super().events(handle):
            if isinstance(event, TextDelta):
                await asyncio.sleep(DELTA_GAP_SECONDS)
                self.emitted[event.text] = time.perf_counter()
            yield event


def _request(port: int, method: str, path: str, *, body: object | None = None) -> Any:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {
        "Cookie": f"{cookie_name(port)}={STREAM_TOKEN}",
        "Origin": f"http://127.0.0.1:{port}",
        "Content-Type": "application/json",
    }
    connection.request(
        method, path, body=None if body is None else json.dumps(body), headers=headers
    )
    return connection, connection.getresponse()


def _arrivals(response: Any) -> dict[str, float]:
    """When each delta of the stream arrives, until the turn's result."""
    arrived: dict[str, float] = {}
    event = ""
    while True:
        line = response.readline().decode("utf-8").rstrip("\n")
        if line.startswith("event: "):
            event = line.removeprefix("event: ")
        elif line.startswith("data: ") and event == "delta":
            arrived[json.loads(line.removeprefix("data: "))["text"]] = time.perf_counter()
        elif line.startswith("data: ") and event == "record.result":
            return arrived


def test_streams_delta_within_budget_when_thousand_deltas_emitted_agent_session_stream(
    api_settings: Any, web_dist: Path
) -> None:
    turn = tuple(TextDelta(block=0, index=n, text=f"d{n:04d} ") for n in range(DELTAS))
    driver = _StampingDriver(replies={"Go.": (*turn, TextBlock(block=0, text="done"))})
    rig = build_rig(driver=driver)
    sock = bind_loopback(0)
    port = sock.getsockname()[1]
    settings = replace(api_settings, port=port, session_token=STREAM_TOKEN)
    server = LoopbackServer(
        create_app(settings, ports=ApiPorts(agent_sessions=rig.control), web_dist=web_dist), sock
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        base = "/api/v1/agent-sessions"
        _, created = _request(
            port, "POST", base, body={"project": "demo", "workdir_id": WORKDIR_ID}
        )
        session_id = json.loads(created.read())["id"]
        stream_connection, stream = _request(port, "GET", f"{base}/{session_id}/stream")
        assert stream.status == 200
        assert stream.readline() == b"retry: 3000\n"
        sender = threading.Thread(
            target=lambda: _request(
                port, "POST", f"{base}/{session_id}/messages", body={"text": "Go."}
            )
        )
        sender.start()
        arrived = _arrivals(stream)
        sender.join(timeout=10)
        stream_connection.close()
        _request(port, "POST", f"{base}/{session_id}/close", body={})
    finally:
        server.stop()
        thread.join(timeout=10)

    assert len(arrived) == DELTAS
    latencies = [(arrived[text] - driver.emitted[text]) * 1000 for text in arrived]
    p95 = statistics.quantiles(latencies, n=100, method="inclusive")[94]
    p99 = statistics.quantiles(latencies, n=100, method="inclusive")[98]
    assert p95 < DELTA_P95_MS, (p95, p99)
    assert p99 < DELTA_P99_MS, (p95, p99)


# AGH-164 budget (AC-164.26): a hub of 200 skills beside 10,000 events in 200 sessions, read
# warm: the catalog under 150 ms, a skill's detail under 100 ms.
HUB_SKILLS = 200
SKILL_CATALOG_P95_MS = 150
SKILL_DETAIL_P95_MS = 100


@pytest.fixture
def skills_loaded(loaded: Any, make_hub: Callable[..., Path]) -> Any:
    hub = make_hub()
    body = "".join(
        f"{step}. **Step {step}**: run `make check` and ask the `evaluator` agent.\n"
        for step in range(1, 21)
    )
    for number in range(HUB_SKILLS):
        folder = hub / "plugin" / "demo" / "skills" / f"s-{number:03d}"
        (folder / "references").mkdir(parents=True)
        (folder / "SKILL.md").write_text(
            f"---\nname: s-{number:03d}\ndescription: Skill {number}.\n---\n# S\n\n{body}",
            encoding="utf-8",
        )
        (folder / "references" / "r.md").write_text("# R\n", encoding="utf-8")
    assert (
        loaded.client.post(
            "/api/v1/hubs", json={"path": str(hub)}, headers={"Origin": "http://127.0.0.1:7420"}
        ).status_code
        == 201
    )
    return loaded


def _warm_p95(composed: Any, path: str) -> tuple[float, list[float]]:
    assert composed.client.get(path).status_code == 200
    samples: list[float] = []
    for _ in range(SAMPLES):
        elapsed, response = _timed(lambda: composed.client.get(path))
        assert response.status_code == 200, response.text
        samples.append(elapsed)
    return _p95(samples), samples


def test_answers_skills_within_budget_when_two_hundred_skills_and_ten_thousand_events(
    skills_loaded: Any,
) -> None:
    catalog = skills_loaded.client.get("/api/v1/projects/demo/skills")
    assert catalog.status_code == 200, catalog.text
    assert len([item for item in catalog.json()["items"] if item["source"] == "demo"]) >= HUB_SKILLS

    catalog_p95, catalog_samples = _warm_p95(skills_loaded, "/api/v1/projects/demo/skills")
    detail_p95, detail_samples = _warm_p95(
        skills_loaded, "/api/v1/projects/demo/skills/skill/demo/s-100"
    )

    assert catalog_p95 < SKILL_CATALOG_P95_MS, catalog_samples
    assert detail_p95 < SKILL_DETAIL_P95_MS, detail_samples
