"""AGH-835 (ADR 0061): when ``hub sync`` may point git at the hub's ``.githooks``."""

import pytest

from agent_hub.core.hub_files.git_hooks import HooksPath, hooks_path_action


@pytest.mark.parametrize(
    ("current", "action"),
    [
        pytest.param(None, HooksPath.SET, id="unset"),
        pytest.param("", HooksPath.SET, id="empty"),
        pytest.param(".git/hooks", HooksPath.SET, id="git-default"),
        pytest.param(".githooks", HooksPath.KEEP, id="ours"),
        pytest.param(".githooks/", HooksPath.KEEP, id="ours-slash"),
        pytest.param(".husky", HooksPath.FOREIGN, id="husky"),
    ],
)
def test_decides_action_when_hooks_path_read(current: str | None, action: HooksPath) -> None:
    assert hooks_path_action(current) is action
