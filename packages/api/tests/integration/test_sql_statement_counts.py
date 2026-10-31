"""SQL statements and new connections per request on the key routes, on the composed app over a
SQLite file and a registered synthetic hub.

Each route is read once to warm it, then measured with ``count_sql`` at 20 and again at 200
sessions (the 180 more appended in between, the route warmed again). The counts must be the
same at both sizes, so an N+1 fails here (AC-2), and equal the pinned literal, so one extra
query fails too. The routes that still ask one query per session are strict xfails until their
fix. Each read also checks one value of the response at each size, so a route that stops seeing
the sessions fails rather than passing with fewer queries. A bad status or value fails through
``pytest.fail``, outside the xfails' ``raises=AssertionError``: only the count check can be the
expected failure.
A statement is anything sent through a cursor, ``BEGIN`` included; a connection is a new DB-API
connection a pool opens, so a warm route, served by its engines' idle connections, opens none.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import timedelta
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from agent_hub.core.testing.session_scenarios import a_session_events

FEW = 20
MANY = 200
ORIGIN = {"Origin": "http://127.0.0.1:7420"}
FEATURE = "export"
FEATURE_ISSUE = "DEM-7"
SPEC = f"""---
type: spec
process_size: bounded
repos: [demo-api]
linear: [{FEATURE_ISSUE}]
---
# Spec
"""
RECORD = (
    '{"feature": "export", "linear": ["DEM-7"], "acs": [{"id": "AC-7.1", "description": "One",'
    ' "repo": "demo-api", "verification": "make check", "passes": true, "evidence": "run"}]}'
)


class Counts(NamedTuple):
    statements: int
    connections: int


class Seen(NamedTuple):
    """The value a route's response shows at ``FEW`` and at ``MANY`` sessions."""

    few: int
    many: int


type Reading = Callable[[Any], int]


def _skill_uses(body: Any) -> int:
    return next(item["usage"]["count"] for item in body["items"] if item["name"] == "create-plan")


def _sessions(composed: Any, numbers: range) -> None:
    """Sessions on the hub's branch prefix and team: the even ones about ``FEATURE_ISSUE``, the
    odd ones about an issue of their own; every third one still live; each uses a skill."""
    start = composed.settings.clock() - timedelta(minutes=12)
    events = []
    for number in numbers:
        issue = "dem-7" if number % 2 == 0 else f"dem-{100 + number}"
        events += a_session_events(
            f"session-{number:03d}",
            start=start + timedelta(seconds=number),
            tools=(("Skill", {"skill": "create-plan"}), ("Bash", {"command": "make check"})),
            ended=number % 3 != 0,
            git_branch=f"jdoe/{issue}-work",
        )
    composed.store.append(events)


@pytest.fixture
def world(composed: Any, make_hub: Callable[..., Path]) -> Any:
    hub = make_hub()
    folder = hub / "brain" / "features" / FEATURE
    folder.mkdir(parents=True)
    for name, body in {
        "spec.md": SPEC,
        "research.md": "# Research\n",
        "plan.md": "# Plan\n",
        "features.json": RECORD,
    }.items():
        (folder / name).write_text(body, encoding="utf-8")
    assert (
        composed.client.post("/api/v1/hubs", json={"path": str(hub)}, headers=ORIGIN).status_code
        == 201
    )
    return composed


def _ok(response: Any) -> Any:
    if response.status_code != 200:
        pytest.fail(f"{response.status_code}: {response.text}")
    return response.json()


def _measured(
    composed: Any,
    path: str,
    count_sql: Callable[[], AbstractContextManager[Any]],
    *,
    reading: Reading,
    expected: int,
) -> Counts:
    _ok(composed.client.get(path))
    with count_sql() as counts:
        response = composed.client.get(path)
    seen = reading(_ok(response))
    if seen != expected:
        pytest.fail(f"{path} shows {seen}, expected {expected}")
    return Counts(counts.statements, counts.connections)


def _at_both_sizes(
    world: Any,
    path: str,
    count_sql: Callable[[], AbstractContextManager[Any]],
    *,
    reading: Reading,
    seen: Seen,
) -> tuple[Counts, Counts]:
    _sessions(world, range(FEW))
    few = _measured(world, path, count_sql, reading=reading, expected=seen.few)
    _sessions(world, range(FEW, MANY))
    many = _measured(world, path, count_sql, reading=reading, expected=seen.many)
    return few, many


# The lookup of each session's agent-session link (``link_of``) costs one connection and two
# statements (``BEGIN``, ``SELECT``) per session it is asked for.
ISSUE_N_PLUS_ONE = pytest.mark.xfail(
    strict=True, raises=AssertionError, reason="N+1: link_of per session, fixed by AGH-610"
)
LISTED_N_PLUS_ONE = pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="N+1: link_of per listed session (_decorated), fixed by AGH-610",
)

# A pinned route asserts its literal counts; an N+1 route (pinned None) asserts only that they
# stay the same, so its strict xfail passes, and fails CI, once the fix lands: then pin it.
# Every third session is live; half are about ``FEATURE_ISSUE``; the sessions page holds 50.
ROUTES = [
    pytest.param(
        "/api/v1/projects",
        Counts(2, 0),
        lambda body: body["items"][0]["live_sessions"],
        Seen(7, 67),
        id="projects",
    ),
    pytest.param(
        "/api/v1/features?project=demo",
        Counts(0, 0),
        lambda body: len(body["items"]),
        Seen(1, 1),
        id="features",
    ),
    pytest.param(
        f"/api/v1/features/demo/{FEATURE}",
        None,
        lambda body: body["cost"]["sessions"],
        Seen(10, 100),
        id="feature-detail",
        marks=ISSUE_N_PLUS_ONE,
    ),
    pytest.param(
        "/api/v1/sessions",
        None,
        lambda body: len(body["items"]),
        Seen(20, 50),
        id="sessions",
        marks=LISTED_N_PLUS_ONE,
    ),
    pytest.param(
        f"/api/v1/sessions?issue={FEATURE_ISSUE}",
        None,
        lambda body: len(body["items"]),
        Seen(10, 50),
        id="sessions-of-issue",
        marks=ISSUE_N_PLUS_ONE,
    ),
    pytest.param(
        "/api/v1/live-sessions",
        None,
        lambda body: len(body["items"]),
        Seen(7, 67),
        id="live-sessions",
        marks=LISTED_N_PLUS_ONE,
    ),
    pytest.param(
        "/api/v1/projects/demo/skills", Counts(2, 0), _skill_uses, Seen(20, 200), id="skills"
    ),
    pytest.param(
        "/api/v1/doctor/findings?project=demo",
        Counts(0, 0),
        lambda body: len(body["items"]),
        Seen(2, 2),
        id="doctor-findings",
    ),
]


@pytest.mark.parametrize(("path", "pinned", "reading", "seen"), ROUTES)
def test_keeps_sql_counts_when_sessions_grow_tenfold(  # noqa: PLR0913 -- one per param
    world: Any,
    count_sql: Callable[[], AbstractContextManager[Any]],
    *,
    path: str,
    pinned: Counts | None,
    reading: Reading,
    seen: Seen,
) -> None:
    """AC-2: a route's statements and connections do not grow with the sessions."""
    few, many = _at_both_sizes(world, path, count_sql, reading=reading, seen=seen)

    assert few == many, (few, many)
    if pinned is not None:
        assert few == pinned, few


def test_counts_statements_and_connection_when_block_runs_two_statements(
    tmp_path: Path, count_sql: Callable[[], AbstractContextManager[Any]]
) -> None:
    """AC-1: ``count_sql`` counts the block's statements and connections, nothing after it."""
    engine = create_engine(f"sqlite:///{tmp_path / 'counted.db'}", poolclass=NullPool)

    with count_sql() as counts, engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        connection.execute(text("SELECT 2"))
    with engine.connect() as connection:
        connection.execute(text("SELECT 3"))

    assert (counts.statements, counts.connections) == (2, 1)
