from agent_hub.cli.child_process import git_env

# ``git rev-parse --local-env-vars`` (git 2.43) without the GIT_CONFIG* variables, which the
# caller keeps on purpose (a test's own config, a hook's -c values).
LOCATION_VARIABLES = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_OBJECT_DIRECTORY",
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_IMPLICIT_WORK_TREE",
    "GIT_GRAFT_FILE",
    "GIT_INDEX_FILE",
    "GIT_NO_REPLACE_OBJECTS",
    "GIT_REPLACE_REF_BASE",
    "GIT_PREFIX",
    "GIT_SHALLOW_FILE",
    "GIT_COMMON_DIR",
)


def test_drops_location_variables_when_git_env_built() -> None:
    environ = {name: "/decoy" for name in LOCATION_VARIABLES} | {
        "PATH": "/bin",
        "HOME": "/home/jdoe",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_COUNT": "0",
        "GIT_CEILING_DIRECTORIES": "/home",
    }

    env = git_env(environ, optional_locks=True)

    assert env == {
        "PATH": "/bin",
        "HOME": "/home/jdoe",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_COUNT": "0",
        "GIT_CEILING_DIRECTORIES": "/home",
    }
    # The caller's mapping is left as it was.
    assert all(environ[name] == "/decoy" for name in LOCATION_VARIABLES)


def test_sets_optional_locks_when_asked() -> None:
    environ = {"PATH": "/bin"}

    assert git_env(environ, optional_locks=False) == {"PATH": "/bin", "GIT_OPTIONAL_LOCKS": "0"}
    assert git_env(environ, optional_locks=True) == {"PATH": "/bin"}
