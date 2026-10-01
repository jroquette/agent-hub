from agent_hub.cli.child_process import git_env

LOCATION_VARIABLES = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")


def test_drops_location_variables_when_git_env_built() -> None:
    environ = {name: "/decoy" for name in LOCATION_VARIABLES} | {
        "PATH": "/bin",
        "HOME": "/home/jdoe",
        "GIT_CONFIG_NOSYSTEM": "1",
    }

    env = git_env(environ, optional_locks=True)

    assert env == {"PATH": "/bin", "HOME": "/home/jdoe", "GIT_CONFIG_NOSYSTEM": "1"}
    # The caller's mapping is left as it was.
    assert all(environ[name] == "/decoy" for name in LOCATION_VARIABLES)


def test_sets_optional_locks_when_asked() -> None:
    environ = {"PATH": "/bin"}

    assert git_env(environ, optional_locks=False) == {"PATH": "/bin", "GIT_OPTIONAL_LOCKS": "0"}
    assert git_env(environ, optional_locks=True) == {"PATH": "/bin"}
