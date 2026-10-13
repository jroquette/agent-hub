"""Run budgets of the control plane (spec NFRs) on the composed app, at 10,000 events in 200
sessions built in ``tmp_path``: a hook POST p95 under 50 ms, a read endpoint p95 under 300 ms;
and AGH-201's: a session's problems p95 under 150 ms at 5,000 events, a brain note under 100 ms
and the brain tree under 150 ms in a hub of 2,000 notes; AGH-136's: a feature's tickets under
100 ms on a warm snapshot cache with 50 tickets.

Each read follows an append, so it folds again (the memo is keyed by the high-water mark): the
budget holds while sessions are live, not only on a warm memo. The first read after start-up,
which loads every event once, is left out.
"""

import math
import statistics
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.events.event import Event
from agent_hub.core.testing.builders import an_event
from agent_hub.core.testing.hook_inputs import a_hook_input, an_envelope
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
    assert composed.client.post("/api/v1/hubs", json={"path": str(hub)}).status_code == 201
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
