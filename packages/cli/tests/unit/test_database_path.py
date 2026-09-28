from pathlib import Path

import pytest

from agent_hub.cli.database_path import default_database_path


def test_uses_xdg_data_home_when_set(tmp_path: Path) -> None:
    environ = {"XDG_DATA_HOME": str(tmp_path / "xdg"), "HOME": str(tmp_path / "home")}

    assert default_database_path(environ) == tmp_path / "xdg" / "agent-hub" / "agent-hub.db"


def test_falls_back_to_home_when_xdg_unset(tmp_path: Path) -> None:
    environ = {"HOME": str(tmp_path / "home")}

    expected = tmp_path / "home" / ".local" / "share" / "agent-hub" / "agent-hub.db"
    assert default_database_path(environ) == expected


@pytest.mark.parametrize("xdg_data_home", ["", "relative/data"])
def test_falls_back_to_home_when_xdg_empty_or_relative(tmp_path: Path, xdg_data_home: str) -> None:
    # The XDG spec says a relative XDG_DATA_HOME is invalid and must be ignored.
    environ = {"XDG_DATA_HOME": xdg_data_home, "HOME": str(tmp_path / "home")}

    expected = tmp_path / "home" / ".local" / "share" / "agent-hub" / "agent-hub.db"
    assert default_database_path(environ) == expected


def test_uses_user_home_when_home_unset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path / "user"))

    expected = tmp_path / "user" / ".local" / "share" / "agent-hub" / "agent-hub.db"
    assert default_database_path({}) == expected
