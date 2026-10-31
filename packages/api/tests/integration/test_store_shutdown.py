"""``hub web`` closes its stores' SQLite connections when it stops (AGH-609 AC-8, Q2).

The composed app, sessions on with the in-memory driver, runs inside a ``TestClient`` context
over a registered ``make_hub()`` hub, which has no schedules, so no background tick holds a
connection; ``hub_world`` makes it a git checkout, which the knowledge search reads. Its routes
read each store: the events, the agent sessions (signed in with a synthetic launch token) and,
when SQLite has FTS5, the knowledge index, which opens on the first search. One agent session
is left idle, so the app's stop writes its end (``server_stopped``) before the stores close: a
store closed before that write would open a connection for it and keep it. Every DB-API
connection a pool opened, from before ``build_app`` to after the context exits, must be closed
by then. The pool events do not hand over their pool, so connections are told apart by ``id``:
one still open cannot share its ``id`` with another live connection.
"""

import threading
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.pool import Pool

from agent_hub.api.composition import build_app
from agent_hub.api.session_token import cookie_name
from agent_hub.api.settings import ApiSettings
from agent_hub.core.agent_sessions.agent_session import EndReason
from agent_hub.core.testing.session_driver_fakes import InMemorySessionDriver
from agent_hub.storage.agent_session_store import open_agent_session_store
from agent_hub.storage.knowledge_index import fts5_available

TOKEN: Final = "s" * 43
SESSIONS: Final = "/api/v1/agent-sessions"
READS: Final = ("/api/v1/sessions", "/api/v1/projects", SESSIONS)
# The knowledge index opens on the first search; without FTS5 it cannot, so only the other
# stores are read (the storage tests skip the index the same way).
SEARCH: Final = "/api/v1/projects/demo/knowledge/search?q=worktrees"
TURN_SECONDS: Final = 5.0


def _idle_session(client: TestClient, origin: str) -> str:
    """Start an agent session in the hub's own folder; its id once its first turn has ended."""
    workdirs = client.get(f"{SESSIONS}/workdirs", params={"project": "demo"}).json()["items"]
    created = client.post(
        SESSIONS,
        json={"project": "demo", "workdir_id": workdirs[0]["workdir_id"], "prompt": "Go."},
        headers={"Origin": origin},
    )
    assert created.status_code == 201, created.text
    session_id: str = created.json()["id"]
    deadline = time.monotonic() + TURN_SECONDS
    while (status := client.get(f"{SESSIONS}/{session_id}").json()["status"]) != "idle":
        assert time.monotonic() < deadline, status
        time.sleep(0.005)
    return session_id


@dataclass
class _PoolConnections:
    """The DB-API connections the pools opened while the block ran, and those not closed."""

    opened: int = 0
    still_open: set[int] = field(default_factory=set)
    _guard: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def connected(self, dbapi_connection: object) -> None:
        with self._guard:
            self.opened += 1
            self.still_open.add(id(dbapi_connection))

    def closed(self, dbapi_connection: object) -> None:
        with self._guard:
            self.still_open.discard(id(dbapi_connection))


@contextmanager
def _pool_connections() -> Iterator[_PoolConnections]:
    """Every pool's ``connect`` and ``close`` events while the block runs.

    The listeners are class-level (``Pool``), so they reach the pools the app builds, whatever
    thread a route runs in; they are removed when the block ends.
    """
    connections = _PoolConnections()

    def on_connect(dbapi_connection: object, *_: object) -> None:
        connections.connected(dbapi_connection)

    def on_close(dbapi_connection: object, *_: object) -> None:
        connections.closed(dbapi_connection)

    event.listen(Pool, "connect", on_connect)
    event.listen(Pool, "close", on_close)
    try:
        yield connections
    finally:
        event.remove(Pool, "connect", on_connect)
        event.remove(Pool, "close", on_close)


def test_closes_every_store_connection_when_app_stops(
    composed_settings: ApiSettings,
    *,
    projects_root: Path,
    web_dist: Path,
    hub_world: Any,
) -> None:
    """AC-8: once the lifespan has ended, every connection the pools opened is closed, also
    those the stop wrote the idle session's end through."""
    hub: Path = hub_world.hub
    settings = replace(composed_settings, session_token=TOKEN)
    origin = f"http://127.0.0.1:{settings.port}"
    fts5 = fts5_available()
    reads = (*READS, SEARCH) if fts5 else READS
    with _pool_connections() as connections:
        app = build_app(
            settings,
            projects_root=projects_root,
            web_dist=web_dist,
            session_driver=InMemorySessionDriver(),
            environ={},
        )
        with TestClient(app, base_url=origin, raise_server_exceptions=False) as client:
            client.cookies.set(cookie_name(settings.port), TOKEN)
            registered = client.post(
                "/api/v1/hubs", json={"path": str(hub)}, headers={"Origin": origin}
            )
            assert registered.status_code == 201, registered.text
            opened_before_reads = connections.opened
            answers = [client.get(path) for path in reads]
            assert [answer.status_code for answer in answers] == [200] * len(reads), [
                answer.text for answer in answers
            ]
            if fts5:
                # The other stores connected when build_app opened them: only the search's lazy
                # index opens a connection here.
                assert connections.opened > opened_before_reads, "no read reached a database"
            session_id = _idle_session(client, origin)

    assert connections.still_open == set(), (
        f"{len(connections.still_open)} of {connections.opened} connections left open"
    )
    with closing(open_agent_session_store(settings.db_path)) as store:
        assert store.get(session_id).end_reason == EndReason.SERVER_STOPPED
