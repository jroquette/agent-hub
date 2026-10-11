"""Fixtures of the api integration tests: the app as ``hub web`` composes it (``build_app``) on
a temp event database, a temp hub registry and a temp ``~/.claude/projects``."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent_hub.api.composition import build_app
from agent_hub.api.settings import ApiSettings
from agent_hub.core.events.event import Event
from agent_hub.storage.event_store import SqliteEventStore, open_event_store

COMPOSED_PORT = 7420
COMPOSED_URL = f"http://127.0.0.1:{COMPOSED_PORT}"
COMPOSED_NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


@dataclass
class Composed:
    """The composed app's client and what it reads and writes, for a test to inspect."""

    client: TestClient
    settings: ApiSettings
    projects: Path
    store: SqliteEventStore

    def rows(self) -> list[Event]:
        """Every stored event, in append order."""
        return self.store.read_all()


@pytest.fixture
def projects_root(tmp_path: Path) -> Path:
    """A temp ``~/.claude/projects`` with one project folder."""
    root = tmp_path / "home" / ".claude" / "projects"
    (root / "-work-demo-api").mkdir(parents=True)
    return root


@pytest.fixture
def composed_settings(tmp_path: Path) -> ApiSettings:
    return ApiSettings(
        db_path=tmp_path / "data" / "agent-hub.db",
        registry_path=tmp_path / "config" / "agent-hub" / "hubs.json",
        port=COMPOSED_PORT,
        running_version="0.8.0",
        clock=lambda: COMPOSED_NOW,
    )


type ComposedOpener = Callable[..., Any]


@pytest.fixture
def open_composed(
    composed_settings: ApiSettings, projects_root: Path, web_dist: Path
) -> Iterator[Callable[..., Composed]]:
    """Opens ``build_app`` on the temp paths; ``build_app`` keywords may be overridden."""
    clients: list[TestClient] = []

    def opened(settings: ApiSettings = composed_settings, **options: Any) -> Composed:
        app = build_app(
            settings,
            **({"projects_root": projects_root, "web_dist": web_dist} | options),
        )
        client = TestClient(app, base_url=COMPOSED_URL, raise_server_exceptions=False)
        client.__enter__()
        clients.append(client)
        return Composed(
            client=client,
            settings=settings,
            projects=projects_root,
            store=open_event_store(settings.db_path),
        )

    yield opened
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def composed(open_composed: Callable[..., Composed]) -> Composed:
    """The composed app on the temp paths."""
    return open_composed()
