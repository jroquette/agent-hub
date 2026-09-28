"""Keeps every cli test away from the real event database: home and XDG data dir under tmp_path."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_data_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # A test that needs other values passes them to CliRunner.invoke(env=...), None unsets one.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("AGENT_HUB_DB", raising=False)
