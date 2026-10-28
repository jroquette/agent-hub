"""SQL statements and new connections per request on the key routes (AGH-600), on the composed
app over a SQLite file and a registered synthetic hub.

Each route is read once to warm it, then measured with ``count_sql`` at 20 and again at 200
sessions (the 180 more appended in between, the route warmed again). The counts must be the
same at both sizes, so an N+1 fails here, and equal the pinned literal, so one extra query
fails too. The routes that still ask one query per session are strict xfails until their fix.
A statement is anything sent through a cursor, ``BEGIN`` included; the store's engines have no
pool (``NullPool``), so every checkout opens a new connection.
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


def _measured(
    composed: Any, path: str, count_sql: Callable[[], AbstractContextManager[Any]]
) -> Counts:
    warm = composed.client.get(path)
    assert warm.status_code == 200, warm.text
    with count_sql() as counts:
        response = composed.client.get(path)
    assert response.status_code == 200, response.text
    return Counts(counts.statements, counts.connections)


def _at_both_sizes(
    world: Any, path: str, count_sql: Callable[[], AbstractContextManager[Any]]
) -> tuple[Counts, Counts]:
    _sessions(world, range(FEW))
    few = _measured(world, path, count_sql)
    _sessions(world, range(FEW, MANY))
    many = _measured(world, path, count_sql)
    return few, many


# The lookup of each session's agent-session link (``link_of``) costs one connection and two
# statements (``BEGIN``, ``SELECT``) per session it is asked for.
ISSUE_N_PLUS_ONE = pytest.mark.xfail(
    strict=True, raises=AssertionError, reason="N+1: link_of per session, fixed by AGH-610"
)
LISTED_N_PLUS_ONE = pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="N+1: link_of per listed session (_decorated), as AGH-610",
)

# A pinned route asserts its literal counts; an N+1 route (pinned None) asserts only that they
# stay the same, so its strict xfail passes, and fails CI, once the fix lands: then pin it.
ROUTES = [
    pytest.param("/api/v1/projects", Counts(2, 1), id="projects"),
    pytest.param("/api/v1/features?project=demo", Counts(0, 0), id="features"),
    pytest.param(
        f"/api/v1/features/demo/{FEATURE}", None, id="feature-detail", marks=ISSUE_N_PLUS_ONE
    ),
    pytest.param("/api/v1/sessions", None, id="sessions", marks=LISTED_N_PLUS_ONE),
    pytest.param(
        f"/api/v1/sessions?issue={FEATURE_ISSUE}",
        None,
        id="sessions-of-issue",
        marks=ISSUE_N_PLUS_ONE,
    ),
    pytest.param("/api/v1/live-sessions", None, id="live-sessions", marks=LISTED_N_PLUS_ONE),
    pytest.param("/api/v1/projects/demo/skills", Counts(2, 1), id="skills"),
    pytest.param("/api/v1/doctor/findings?project=demo", Counts(0, 0), id="doctor-findings"),
]


@pytest.mark.parametrize(("path", "pinned"), ROUTES)
def test_keeps_sql_counts_when_sessions_grow_tenfold(
    world: Any,
    count_sql: Callable[[], AbstractContextManager[Any]],
    *,
    path: str,
    pinned: Counts | None,
) -> None:
    few, many = _at_both_sizes(world, path, count_sql)

    assert few == many, (few, many)
    if pinned is not None:
        assert few == pinned, few


def test_counts_statements_and_connection_when_block_runs_two_statements(
    tmp_path: Path, count_sql: Callable[[], AbstractContextManager[Any]]
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'counted.db'}", poolclass=NullPool)

    with count_sql() as counts, engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        connection.execute(text("SELECT 2"))
    with engine.connect() as connection:
        connection.execute(text("SELECT 3"))

    assert (counts.statements, counts.connections) == (2, 1)
