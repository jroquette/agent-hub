"""Run budgets of the control plane (spec NFRs) on the composed app, at 10,000 events in 200
sessions built in ``tmp_path``: a hook POST p95 under 50 ms, a read endpoint p95 under 300 ms.

Each read follows an append, so it folds again (the memo is keyed by the high-water mark): the
budget holds while sessions are live, not only on a warm memo. The first read after start-up,
which loads every event once, is left out.
"""

import statistics
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest

from agent_hub.core.events.event import Event
from agent_hub.core.testing.builders import an_event
from agent_hub.core.testing.hook_inputs import a_hook_input, an_envelope
from agent_hub.core.testing.session_scenarios import SCENARIO_START, a_session_events

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
