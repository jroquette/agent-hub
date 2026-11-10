"""SQL statements and new connections per request on the key routes, on the composed app over a
SQLite file and a registered synthetic hub.

Each route is read once to warm it, then measured with ``count_sql`` at 20 and again at 200
sessions (the 180 more appended in between, the route warmed again); ``?issue=``, which looks at
every session in scope, at 2,000. Every fifth session is driven by an ended agent session of
``hub web``, half of those with a stored first prompt, so each route shows links with and
without one at both sizes. The counts must be the same at both sizes, so an N+1 fails here
(AC-2), and equal the pinned literal, so one extra query fails too. Each read also checks one
value of the response at each size, so a route that stops seeing the sessions fails rather than
passing with fewer queries. A bad status or value fails through ``pytest.fail``.
A statement is anything sent through a cursor, ``BEGIN`` included; a connection is a new DB-API
connection a pool opens, so a warm route, served by its engines' idle connections, opens none.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager, closing
from datetime import timedelta
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from agent_hub.core.agent_sessions.agent_session import AgentSessionStatus, EndReason
from agent_hub.core.testing.read_model_builders import a_log_record, an_agent_session
from agent_hub.core.testing.seeded_shadows import seeded_workflows
from agent_hub.core.testing.session_scenarios import a_session_events
from agent_hub.storage.agent_session_store import open_agent_session_store

FEW = 20
# The demo hub's findings: two, plus one workflows.shadow warning per workflow hub init seeded.
DOCTOR_FINDINGS = 2 + len(seeded_workflows())
MANY = 200
ISSUE_MANY = 2_000
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
# A first prompt with no slash command names no issue, so a link changes no session's label.
LINKED_PROMPT = "Look at the export."


class Counts(NamedTuple):
    statements: int
    connections: int


class Seen(NamedTuple):
    """The value a route's response shows at ``FEW`` sessions and at its larger size."""

    few: int
    many: int


type Reading = Callable[[Any], int]


def _skill_uses(body: Any) -> int:
    return next(item["usage"]["count"] for item in body["items"] if item["name"] == "create-plan")


def _linked(body: Any) -> int:
    return len([item for item in body["items"] if item["agent_session_id"] is not None])


def _sessions(composed: Any, numbers: range, *, size: int) -> None:
    """Sessions on the hub's branch prefix and team: the even ones about ``FEATURE_ISSUE``, the
    odd ones about an issue of their own; every third one still live; each uses a skill.

    Session ``n`` starts ``n`` seconds after the first; in a world of ``size`` sessions the
    first starts early enough that the last starts 8 min 41 s before the frozen clock, as at
    200, so none starts after it."""
    start = composed.settings.clock() - timedelta(minutes=12, seconds=size - MANY)
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


def _links(composed: Any, numbers: range) -> None:
    """Every fifth session driven by an ended agent session of ``hub web``; those with
    ``number % 20 < 10`` have a stored first prompt, the others none."""
    ended_at = composed.settings.clock() - timedelta(minutes=1)
    with closing(open_agent_session_store(composed.settings.db_path)) as agent_sessions:
        for number in numbers:
            if number % 5 != 0:
                continue
            agent_session_id = f"01929a4e-7a11-7c00-8a00-{number:012d}"
            agent_sessions.create(
                an_agent_session(
                    id=agent_session_id,
                    claude_session_id=f"session-{number:03d}",
                    status=AgentSessionStatus.ENDED,
                    end_reason=EndReason.CLOSED,
                    ended_at=ended_at,
                    last_seq=0,
                )
            )
            if number % 20 < 10:
                prompt = a_log_record("user.message", 1, body={"text": LINKED_PROMPT})
                agent_sessions.append(agent_session_id, [prompt])


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
    # The findings come from the hub's background check (AGH-608): one tick runs it.
    composed.refresh()
    return composed


def _ok(response: Any) -> Any:
    if response.status_code != 200:
        pytest.fail(f"{response.status_code}: {response.text}")
    return response.json()


def _counted(
    composed: Any,
    path: str,
    count_sql: Callable[[], AbstractContextManager[Any]],
    *,
    reading: Reading,
    expected: int,
) -> Counts:
    with count_sql() as counts:
        response = composed.client.get(path)
    seen = reading(_ok(response))
    if seen != expected:
        pytest.fail(f"{path} shows {seen}, expected {expected}")
    return Counts(counts.statements, counts.connections)


def _measured(
    composed: Any,
    path: str,
    count_sql: Callable[[], AbstractContextManager[Any]],
    *,
    reading: Reading,
    expected: int,
) -> Counts:
    _ok(composed.client.get(path))
    return _counted(composed, path, count_sql, reading=reading, expected=expected)


def _at_both_sizes(
    world: Any,
    path: str,
    count_sql: Callable[[], AbstractContextManager[Any]],
    *,
    reading: Reading,
    seen: Seen,
    size: int,
) -> tuple[Counts, Counts]:
    _sessions(world, range(FEW), size=size)
    _links(world, range(FEW))
    few = _measured(world, path, count_sql, reading=reading, expected=seen.few)
    _sessions(world, range(FEW, size), size=size)
    _links(world, range(FEW, size))
    many = _measured(world, path, count_sql, reading=reading, expected=seen.many)
    return few, many


# A warm read costs the store's mark (``BEGIN``, ``SELECT``); a route that shows links adds one
# ``links_of`` and one ``first_records`` (the linked sessions with no stored prompt are asked
# again on every read), two statements each. The ``first_records`` pins hold while a lookup asks
# at most 500 links (one chunk): ``?issue=`` at 2,000 sessions finds 400 and asks them all on
# first sight.
# Every third session is live; half are about ``FEATURE_ISSUE``; the sessions page holds 50.
ROUTES = [
    pytest.param(
        "/api/v1/projects",
        Counts(2, 0),
        lambda body: body["items"][0]["live_sessions"],
        Seen(7, 67),
        MANY,
        id="projects",
    ),
    pytest.param(
        "/api/v1/features?project=demo",
        Counts(0, 0),
        lambda body: len(body["items"]),
        Seen(1, 1),
        MANY,
        id="features",
    ),
    pytest.param(
        f"/api/v1/features/demo/{FEATURE}",
        Counts(6, 0),
        lambda body: body["cost"]["sessions"],
        Seen(10, 100),
        MANY,
        id="feature-detail",
    ),
    pytest.param(
        "/api/v1/sessions",
        Counts(6, 0),
        lambda body: len(body["items"]),
        Seen(20, 50),
        MANY,
        id="sessions",
    ),
    pytest.param(
        f"/api/v1/sessions?issue={FEATURE_ISSUE}",
        Counts(6, 0),
        lambda body: len(body["items"]),
        Seen(10, 50),
        ISSUE_MANY,
        id="sessions-of-issue",
    ),
    pytest.param(
        "/api/v1/live-sessions",
        Counts(6, 0),
        lambda body: len(body["items"]),
        Seen(7, 67),
        MANY,
        id="live-sessions",
    ),
    pytest.param(
        "/api/v1/projects/demo/skills",
        Counts(2, 0),
        _skill_uses,
        Seen(20, 200),
        MANY,
        id="skills",
    ),
    pytest.param(
        "/api/v1/doctor/findings?project=demo",
        Counts(0, 0),
        lambda body: len(body["items"]),
        Seen(DOCTOR_FINDINGS, DOCTOR_FINDINGS),
        MANY,
        id="doctor-findings",
    ),
]


@pytest.mark.parametrize(("path", "pinned", "reading", "seen", "size"), ROUTES)
def test_keeps_sql_counts_when_sessions_grow_tenfold(  # noqa: PLR0913 -- one per param
    world: Any,
    count_sql: Callable[[], AbstractContextManager[Any]],
    *,
    path: str,
    pinned: Counts,
    reading: Reading,
    seen: Seen,
    size: int,
) -> None:
    """AC-2: a route's statements and connections do not grow with the sessions, linked ones
    included (AC-9, AC-10)."""
    few, many = _at_both_sizes(world, path, count_sql, reading=reading, seen=seen, size=size)

    assert few == many, (few, many)
    assert few == pinned, few


# The sessions page shows the 50 newest (150 to 199 at 200), ``?issue=`` the 50 newest even
# ones (100 to 198); every fifth session is linked.
@pytest.mark.parametrize(
    ("path", "linked"),
    [
        pytest.param("/api/v1/sessions", Seen(4, 10), id="sessions"),
        pytest.param(
            f"/api/v1/sessions?issue={FEATURE_ISSUE}", Seen(2, 10), id="sessions-of-issue"
        ),
    ],
)
def test_reads_new_link_prompts_in_one_batch_when_links_first_seen(
    world: Any,
    count_sql: Callable[[], AbstractContextManager[Any]],
    *,
    path: str,
    linked: Seen,
) -> None:
    """AC-11: links stored after the route is warm are read on first sight, their prompts in
    one batch, in the same statements at 20 and at 200 sessions."""
    cold = []
    for numbers, shown in ((range(FEW), linked.few), (range(FEW, MANY), linked.many)):
        _sessions(world, numbers, size=MANY)
        _ok(world.client.get(path))
        _links(world, numbers)
        cold.append(_counted(world, path, count_sql, reading=_linked, expected=shown))

    assert cold == [Counts(6, 0), Counts(6, 0)], cold


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
