"""``hub web`` closes its stores' SQLite connections when it stops (AGH-609 AC-8, Q2).

The composed app, sessions on as the ``composed`` fixture builds it, runs inside a
``TestClient`` context over a registered ``make_hub()`` hub, which has no schedules, so no
background tick holds a connection; ``hub_world`` makes it a git checkout, which the knowledge
search reads. Its routes read each store: the events, the agent sessions (signed in with a
synthetic launch token) and the knowledge index, which opens on the first search. Every DB-API
connection a pool opened, from before ``build_app`` to after the context exits, must be closed
by then. The pool events do not hand over their pool, so connections are told apart by ``id``:
one still open cannot share its ``id`` with another live connection.
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.pool import Pool

from agent_hub.api.composition import build_app
from agent_hub.api.session_token import cookie_name
from agent_hub.api.settings import ApiSettings
from agent_hub.storage.knowledge_index import FTS5_MISSING, fts5_available

TOKEN: Final = "s" * 43
READS: Final = (
    "/api/v1/sessions",
    "/api/v1/projects",
    "/api/v1/agent-sessions",
    "/api/v1/projects/demo/knowledge/search?q=worktrees",
)


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


@pytest.mark.skipif(not fts5_available(), reason=FTS5_MISSING)
def test_closes_every_store_connection_when_app_stops(
    composed_settings: ApiSettings,
    *,
    projects_root: Path,
    web_dist: Path,
    hub_world: Any,
) -> None:
    """AC-8: once the lifespan has ended, every connection the pools opened is closed."""
    hub: Path = hub_world.hub
    settings = replace(composed_settings, session_token=TOKEN)
    origin = f"http://127.0.0.1:{settings.port}"
    with _pool_connections() as connections:
        app = build_app(settings, projects_root=projects_root, web_dist=web_dist)
        with TestClient(app, base_url=origin, raise_server_exceptions=False) as client:
            client.cookies.set(cookie_name(settings.port), TOKEN)
            registered = client.post(
                "/api/v1/hubs", json={"path": str(hub)}, headers={"Origin": origin}
            )
            assert registered.status_code == 201, registered.text
            opened_before_reads = connections.opened
            answers = [client.get(path) for path in READS]
            assert [answer.status_code for answer in answers] == [200] * len(READS), [
                answer.text for answer in answers
            ]
            assert connections.opened > opened_before_reads, "no read reached a database"

    assert connections.still_open == set(), (
        f"{len(connections.still_open)} of {connections.opened} connections left open"
    )
