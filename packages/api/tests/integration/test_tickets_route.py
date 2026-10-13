"""``GET /features/{project}/{slug}/tickets`` on the composed app (AGH-136), Linear faked at the
HTTP transport (``build_app(linear_post=...)``) with a synthetic key: the cache (AC-136.3), the
plan fallback and stale reads (AC-136.4), the key never shown (AC-136.5) and redacted titles
with no write anywhere (AC-136.6). Nothing reaches the network."""

import json
import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

PLAN_TITLES = ["Planned api work", "Planned web work", "Planned docs"]
PROBLEM_TYPE = "urn:agent-hub:problem:tracker-"
# Requests that wait on a stream, never answered in full by the test client.
STREAMS = "/stream"


def test_calls_reader_once_when_cache_read_in_bursts(tickets_world: Any) -> None:
    linear = tickets_world.linear

    first, second = tickets_world.tickets(), tickets_world.tickets()
    tickets_world.clock.advance(30)
    within_ttl = tickets_world.tickets()

    assert [r.status_code for r in (first, second, within_ttl)] == [200, 200, 200]
    assert {r.json()["source"] for r in (first, second, within_ttl)} == {"linear"}
    assert linear.count == 1

    tickets_world.clock.advance(31)
    linear.entered.clear()
    linear.gate = threading.Event()
    answers: list[Any] = []
    lock = threading.Lock()

    def read() -> None:
        response = tickets_world.tickets()
        with lock:
            answers.append(response)

    burst = [threading.Thread(target=read) for _ in range(8)]
    for thread in burst:
        thread.start()
    assert linear.entered.wait(timeout=10)
    time.sleep(0.2)  # the other seven reach the cache while the first read is in flight
    linear.gate.set()
    for thread in burst:
        thread.join(timeout=30)

    assert [r.status_code for r in answers] == [200] * 8
    assert {(r.json()["source"], r.json()["stale"]) for r in answers} == {("linear", False)}
    assert linear.count == 2

    linear.gate = None
    tickets_world.clock.advance(61)
    after_ttl = tickets_world.tickets()

    assert (after_ttl.status_code, after_ttl.json()["source"]) == (200, "linear")
    assert linear.count == 3


def _plain(world: Any) -> None:
    world.environ.clear()


def _status(status: int) -> Callable[[Any], None]:
    def failing(world: Any) -> None:
        world.linear.fail = status

    return failing


def _fail(mode: str) -> Callable[[Any], None]:
    def failing(world: Any) -> None:
        world.linear.fail = mode

    return failing


# (case, how Linear fails, the failure kind, the problem status, requests made)
FALLBACKS = [
    ("no-key", _plain, "not_connected", 503, 0),
    ("401", _status(401), "unauthorized", 401, 1),
    ("timeout", _fail("timeout"), "timeout", 504, 1),
    ("429", _status(429), "rate_limited", 429, 1),
    ("500", _status(500), "unavailable", 500, 1),
    ("malformed", _fail("malformed"), "unexpected", 502, 1),
]


def _assert_plan_fallback(body: dict[str, Any], kind: str, status: int) -> None:
    assert (body["source"], body["stale"], body["as_of"]) == ("plan", False, None)
    assert body["notice"]
    assert body["notice"].startswith("From the plan (features.json)")
    assert [row["title"] for row in body["tickets"]] == PLAN_TITLES
    assert all(row["state"] is None for row in body["tickets"])
    problem = body["tracker_problem"]
    assert problem is not None
    assert set(problem) == {"type", "title", "status", "detail"}
    assert (problem["type"], problem["status"]) == (f"{PROBLEM_TYPE}{kind}", status)
    assert problem["title"]
    assert problem["detail"]


@pytest.mark.parametrize(
    ("fails", "kind", "status", "requests"),
    [case[1:] for case in FALLBACKS],
    ids=[case[0] for case in FALLBACKS],
)
def test_serves_plan_fallback_when_linear_fails(
    tickets_world: Any, *, fails: Callable[[Any], None], kind: str, status: int, requests: int
) -> None:
    fails(tickets_world)

    response = tickets_world.tickets()

    assert response.status_code == 200, response.text
    _assert_plan_fallback(response.json(), kind, status)
    assert tickets_world.linear.count == requests
    assert tickets_world.linear.timeouts == [10.0] * requests


@pytest.mark.parametrize(
    ("fails", "kind", "status"),
    [case[1:4] for case in FALLBACKS if case[0] != "no-key"],
    ids=[case[0] for case in FALLBACKS if case[0] != "no-key"],
)
def test_serves_stale_linear_fallback_when_linear_fails_after_a_success(
    tickets_world: Any, *, fails: Callable[[Any], None], kind: str, status: int
) -> None:
    good = tickets_world.tickets().json()
    tickets_world.clock.advance(61)
    fails(tickets_world)

    response = tickets_world.tickets()

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["source"], body["stale"], body["as_of"]) == ("linear", True, good["as_of"])
    assert body["tickets"] == good["tickets"]
    assert "the latest read failed" in body["notice"]
    problem = body["tracker_problem"]
    assert (problem["type"], problem["status"]) == (f"{PROBLEM_TYPE}{kind}", status)
    assert tickets_world.linear.count == 2


def test_serves_plan_fallback_when_key_removed_after_a_success(tickets_world: Any) -> None:
    # Not connected is not a failed read: the plan is served, never the last snapshot.
    tickets_world.tickets()
    tickets_world.environ.clear()

    body = tickets_world.tickets().json()

    _assert_plan_fallback(body, "not_connected", 503)
    assert tickets_world.linear.count == 1


def _get_paths(app: Any, slug: str) -> list[str]:
    """Every GET route of the app's schema with synthetic path values, streams left out."""
    values = {
        "project": "demo",
        "slug": slug,
        "session_id": "session-1",
        "approval_id": "approval-1",
        "learning_id": "learning-1",
        "run_id": "run-1",
        "hub_id": "hub-1",
    }
    paths = []
    for path, methods in app.openapi()["paths"].items():
        if "get" in methods and not path.endswith(STREAMS):
            paths.append(path.format(**values))
    return paths


KEY_SHAPES: dict[str, Callable[[str], str]] = {
    "linear-shaped": lambda key: key.replace("x" * 8, "Sentinel", 1),
    "unshaped": lambda key: "sentinel-" + "k7" * 16,
}


@pytest.mark.parametrize("shape", ["linear-shaped", "unshaped"])
def test_leaves_key_never_exposed_when_linear_echoes_it(
    open_tickets: Any, tickets_kit: Any, *, caplog: pytest.LogCaptureFixture, shape: str
) -> None:
    caplog.set_level(logging.DEBUG)
    sentinel = KEY_SHAPES[shape](tickets_kit.key)
    world = open_tickets(environ={"LINEAR_API_KEY": sentinel})
    world.linear.fail = 400
    world.linear.fail_body = json.dumps(
        {"errors": [{"message": f"Authentication failed for key {sentinel}"}]}
    ).encode()
    answers = [world.tickets()]
    world.clock.advance(61)
    world.linear.fail = 401
    world.linear.fail_body = f"bad key {sentinel}".encode()
    answers.append(world.tickets())
    paths = _get_paths(world.app.client.app, tickets_kit.slug)
    assert tickets_kit.path in paths

    answers += [world.app.client.get(path) for path in paths]

    assert answers[0].json()["tracker_problem"]["status"] == 400
    for response in answers:
        assert sentinel not in response.text, response.request.url
        assert sentinel not in str(response.headers), response.request.url
    logged = caplog.text + "".join(repr(record.args) for record in caplog.records)
    assert sentinel not in logged
    # The key goes to Linear only as the Authorization header, read from the environment: the
    # two reads above and the route sweep's.
    assert world.linear.count == 3
    for _url, headers, document in world.linear.requests:
        assert headers["Authorization"] == sentinel
        assert sentinel not in json.dumps(document)


def test_reads_key_from_environment_when_it_changes_while_serving(
    tickets_world: Any, tickets_kit: Any
) -> None:
    other = "lin_api_" + "y" * 40
    tickets_world.tickets()
    tickets_world.environ["LINEAR_API_KEY"] = other
    tickets_world.clock.advance(61)

    tickets_world.tickets()

    sent = [headers["Authorization"] for _url, headers, _doc in tickets_world.linear.requests]
    assert sent == [tickets_kit.key, other]


def _bytes_under(*roots: Path) -> dict[str, bytes]:
    return {
        str(path): path.read_bytes()
        for root in roots
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_keeps_privacy_when_titles_hold_secrets(open_tickets: Any, tickets_kit: Any) -> None:
    linear_key = "lin_api_" + "s3cr3t" * 7
    github_token = "ghp_" + "T0ken" * 8
    planned = [dict(ticket) for ticket in tickets_kit.planned]
    planned[2]["title"] = f"Document {github_token}"
    issues = tickets_kit.linear_issues()
    issues["DEM-1"].title = f"Rotate {linear_key} today"
    issues["DEM-2"].title = f"Revoke {github_token}"
    issues["OPS-9"].title = f"Blocker with {linear_key}"
    world = open_tickets(record=tickets_kit.a_ticket_record(planned), issues=issues)
    db_folder = world.app.settings.db_path.parent
    before = _bytes_under(db_folder, world.hub)

    linear = world.tickets()
    world.linear.fail = 500
    world.clock.advance(61)
    stale = world.tickets()
    world.environ.clear()
    plan = world.tickets()
    reads = [
        world.app.client.get("/api/v1/features", params={"project": "demo"}),
        world.app.client.get(f"/api/v1/features/demo/{tickets_kit.slug}"),
    ]

    for response in (linear, stale, plan, *reads):
        assert response.status_code == 200, response.text
        assert linear_key not in response.text
        assert github_token not in response.text
    titles = [row["title"] for row in linear.json()["tickets"]]
    assert titles == [
        "Rotate [redacted: linear key] today",
        "Revoke [redacted: github token]",
        "Document [redacted: github token]",
    ]
    assert [row["title"] for row in stale.json()["tickets"]] == titles
    blockers = linear.json()["planning"]["external_blockers"]
    assert [blocker["title"] for blocker in blockers] == ["Blocker with [redacted: linear key]"]
    assert plan.json()["tickets"][2]["title"] == "Document [redacted: github token]"
    assert _bytes_under(db_folder, world.hub) == before
