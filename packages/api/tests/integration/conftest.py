"""Fixtures of the api integration tests: the app as ``hub web`` composes it (``build_app``) on
a temp event database, a temp hub registry and a temp ``~/.claude/projects``, and synthetic
hubs written by ``hub init --config``."""

import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from agent_hub.api.composition import build_app
from agent_hub.api.settings import ApiSettings
from agent_hub.cli.main import app as hub_cli
from agent_hub.core.events.event import Event
from agent_hub.core.json_form import dump_json
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.storage.event_store import SqliteEventStore, open_event_store

COMPOSED_PORT = 7420
COMPOSED_URL = f"http://127.0.0.1:{COMPOSED_PORT}"
COMPOSED_NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
# The pin a synthetic hub carries and the version the composed app runs: the CLI's, so the
# doctor rules that compare them agree with ``hub doctor``.
RUNNING_VERSION = version("agent-hub-cli")


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
        running_version=RUNNING_VERSION,
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


type HubFactory = Callable[..., Path]


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """``HOME`` under ``tmp_path`` and no git config from the machine or a caller."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    for variable in [name for name in os.environ if name.startswith("GIT_")]:
        monkeypatch.delenv(variable)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    return home


@pytest.fixture
def make_hub(tmp_path: Path, isolated_home: Path) -> HubFactory:
    """Writes a synthetic hub with ``hub init --config`` in ``tmp_path / <folder>``.

    The document is ``a_hub_document`` without modules, pinned to the running CLI, named
    ``project``; ``change`` may edit it before it is written.
    """

    def make(
        project: str = "demo",
        *,
        folder: str | None = None,
        change: Callable[[dict[str, Any]], None] | None = None,
    ) -> Path:
        document = a_hub_document()
        del document["modules"]
        document["platform"]["version"] = RUNNING_VERSION
        document["project"]["name"] = project
        if change is not None:
            change(document)
        base = tmp_path / f"{folder or project}-config"
        base.mkdir()
        config = base / "hub.json"
        config.write_bytes(dump_json(document))
        root = tmp_path / (folder or f"{project}-hub")
        result = CliRunner().invoke(hub_cli, ["init", "--config", str(config), "--dir", str(root)])
        assert result.exit_code == 0, result.output
        return root

    return make
