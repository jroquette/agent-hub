from agent_hub.cli import brief_command


def test_pins_git_timeout_when_module_loaded() -> None:
    assert brief_command.BRIEF_GIT_TIMEOUT == 6


def test_pins_gh_timeout_when_module_loaded() -> None:
    assert brief_command.BRIEF_GH_TIMEOUT == 6


def test_pins_gh_workers_when_module_loaded() -> None:
    assert brief_command.MAX_GH_WORKERS == 8
