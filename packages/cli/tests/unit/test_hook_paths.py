from pathlib import Path

import pytest

from agent_hub.cli.errors import HomeDirectoryNotFoundError, ProjectsRootError
from agent_hub.cli.hook_paths import claude_projects_root, default_spool_folder


def _unexpected_account_home() -> str | None:
    msg = "the account home is looked up only when HOME is unusable"
    raise AssertionError(msg)


def test_uses_xdg_state_home_when_absolute(tmp_path: Path) -> None:
    environ = {"XDG_STATE_HOME": str(tmp_path / "state"), "HOME": str(tmp_path / "home")}

    folder = default_spool_folder(environ, account_home=_unexpected_account_home)

    assert folder == tmp_path / "state" / "agent-hub"


@pytest.mark.parametrize("state_home", ["", "relative/state"])
def test_uses_home_state_folder_when_xdg_state_home_relative(
    tmp_path: Path, state_home: str
) -> None:
    environ = {"XDG_STATE_HOME": state_home, "HOME": str(tmp_path / "home")}

    folder = default_spool_folder(environ, account_home=_unexpected_account_home)

    assert folder == tmp_path / "home" / ".local" / "state" / "agent-hub"


def test_raises_when_no_home_for_spool_resolvable() -> None:
    with pytest.raises(HomeDirectoryNotFoundError):
        default_spool_folder({"HOME": ""}, account_home=lambda: None)


def test_uses_projects_variable_when_absolute(tmp_path: Path) -> None:
    environ = {"AGENT_HUB_CLAUDE_PROJECTS": str(tmp_path / "projects"), "HOME": "/nowhere"}

    assert claude_projects_root(environ) == tmp_path / "projects"


def test_raises_when_projects_variable_relative() -> None:
    with pytest.raises(ProjectsRootError):
        claude_projects_root({"AGENT_HUB_CLAUDE_PROJECTS": "claude/projects", "HOME": "/home/x"})
