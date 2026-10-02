import pytest

from agent_hub.cli.run_children import push_env

OVERRIDES = [
    ("core.fsmonitor", "false"),
    ("push.gpgSign", "false"),
    ("core.hooksPath", "/dev/null"),
]


def pairs(env: dict[str, str]) -> list[tuple[str, str]]:
    count = int(env["GIT_CONFIG_COUNT"])
    return [(env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"]) for i in range(count)]


def test_adds_overrides_when_caller_sets_none() -> None:
    token = "y" * 8
    env = push_env({"PATH": "/bin", "LINEAR_API_KEY": "x", "GH_TOKEN": token})

    assert pairs(env) == OVERRIDES
    assert env["GH_TOKEN"] == token
    assert "LINEAR_API_KEY" not in env


def test_keeps_other_git_config_variables_when_overrides_added() -> None:
    env = push_env({"GIT_CONFIG_GLOBAL": "/home/x/.gitconfig", "GIT_CONFIG_NOSYSTEM": "1"})

    assert env["GIT_CONFIG_GLOBAL"] == "/home/x/.gitconfig"
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"


def test_appends_overrides_when_caller_sets_some() -> None:
    caller = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "user.name", "GIT_CONFIG_VALUE_0": "J"}

    assert pairs(push_env(caller)) == [("user.name", "J"), *OVERRIDES]


@pytest.mark.parametrize("count", ["", "x", "-1"])
def test_replaces_count_when_caller_count_invalid(count: str) -> None:
    env = push_env(
        {"GIT_CONFIG_COUNT": count, "GIT_CONFIG_KEY_0": "user.name", "GIT_CONFIG_GLOBAL": "/g"}
    )

    assert pairs(env) == OVERRIDES
    assert env["GIT_CONFIG_GLOBAL"] == "/g"
