import pwd
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_hub.cli import database_path
from agent_hub.cli.database_path import account_home_directory, default_database_path
from agent_hub.cli.errors import CliError, HomeDirectoryNotFoundError


def _unexpected_account_home() -> str | None:
    msg = "the account home is looked up only when HOME is unusable"
    raise AssertionError(msg)


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


def test_uses_account_home_when_home_unset(tmp_path: Path) -> None:
    def account_home() -> str:
        return str(tmp_path / "user")

    expected = tmp_path / "user" / ".local" / "share" / "agent-hub" / "agent-hub.db"
    assert default_database_path({}, account_home=account_home) == expected


@pytest.mark.parametrize("home", ["", "relative/home"], ids=["empty", "relative"])
def test_uses_account_home_when_home_empty_or_relative(tmp_path: Path, home: str) -> None:
    def account_home() -> str:
        return str(tmp_path / "user")

    expected = tmp_path / "user" / ".local" / "share" / "agent-hub" / "agent-hub.db"
    assert default_database_path({"HOME": home}, account_home=account_home) == expected


@pytest.mark.parametrize(
    "account_home", [None, "", "relative/user"], ids=["none", "empty", "relative"]
)
def test_raises_when_no_home_resolvable(account_home: str | None) -> None:
    with pytest.raises(HomeDirectoryNotFoundError) as caught:
        default_database_path({"HOME": ""}, account_home=lambda: account_home)

    assert str(caught.value) == "cannot resolve the home directory; pass --db or set AGENT_HUB_DB"
    assert isinstance(caught.value, CliError)


def test_looks_up_account_home_when_no_lookup_given(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(database_path, "account_home_directory", lambda: str(tmp_path / "user"))

    expected = tmp_path / "user" / ".local" / "share" / "agent-hub" / "agent-hub.db"
    assert default_database_path({"HOME": ""}) == expected


def test_returns_account_directory_when_account_known(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pwd, "getpwuid", lambda _uid: SimpleNamespace(pw_dir="/home/someone"))

    assert account_home_directory() == "/home/someone"


def test_returns_none_when_account_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    def unknown_account(uid: int) -> object:
        raise KeyError(uid)

    monkeypatch.setattr(pwd, "getpwuid", unknown_account)

    assert account_home_directory() is None


def test_skips_account_lookup_when_home_absolute(tmp_path: Path) -> None:
    environ = {"HOME": str(tmp_path / "home")}

    path = default_database_path(environ, account_home=_unexpected_account_home)

    assert path == tmp_path / "home" / ".local" / "share" / "agent-hub" / "agent-hub.db"
