from pathlib import Path

import pytest

from agent_hub.cli.errors import HomeDirectoryNotFoundError
from agent_hub.cli.registry_path import default_registry_path


def _unexpected_account_home() -> str | None:
    msg = "the account home is looked up only when HOME is unusable"
    raise AssertionError(msg)


def test_uses_xdg_config_home_when_absolute(tmp_path: Path) -> None:
    environ = {"XDG_CONFIG_HOME": str(tmp_path / "config"), "HOME": str(tmp_path / "home")}

    path = default_registry_path(environ, account_home=_unexpected_account_home)

    assert path == tmp_path / "config" / "agent-hub" / "hubs.json"


@pytest.mark.parametrize("config_home", ["", "relative/config"])
def test_uses_home_config_when_xdg_config_home_relative(tmp_path: Path, config_home: str) -> None:
    environ = {"XDG_CONFIG_HOME": config_home, "HOME": str(tmp_path / "home")}

    path = default_registry_path(environ, account_home=_unexpected_account_home)

    assert path == tmp_path / "home" / ".config" / "agent-hub" / "hubs.json"


def test_uses_account_home_when_home_unusable(tmp_path: Path) -> None:
    def account_home() -> str:
        return str(tmp_path / "account")

    path = default_registry_path({"HOME": "relative"}, account_home=account_home)

    assert path == tmp_path / "account" / ".config" / "agent-hub" / "hubs.json"


def test_raises_when_no_home_resolvable() -> None:
    with pytest.raises(HomeDirectoryNotFoundError):
        default_registry_path({"HOME": ""}, account_home=lambda: None)
