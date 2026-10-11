"""Fixtures of the api tests: settings under tmp_path and an in-process client."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_hub.api.app import create_app
from agent_hub.api.settings import ApiSettings

FIXED_NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


@pytest.fixture
def api_settings(tmp_path: Path) -> ApiSettings:
    return ApiSettings(
        db_path=tmp_path / "agent-hub.db",
        registry_path=tmp_path / "hubs.json",
        port=7420,
        running_version="0.8.0",
        clock=lambda: FIXED_NOW,
    )


@pytest.fixture
def client(api_settings: ApiSettings) -> Iterator[TestClient]:
    with TestClient(create_app(api_settings), raise_server_exceptions=False) as test_client:
        yield test_client
