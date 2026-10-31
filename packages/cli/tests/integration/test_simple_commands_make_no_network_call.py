"""Simple ``hub`` commands make no network call; plain ``hub brief``, which calls gh on purpose,
is caught doing so.

Each command runs as ``python -m agent_hub.cli`` in the ``hub init`` hub of the cli conftest
(``demo_hub``), committed once as ``make perf``'s temp hub is, under the outbound probe
(``agent_hub.core.testing.outbound_probe``): its sitecustomize refuses and records any socket call
that leaves the machine and leaves a marker in each interpreter it loads in, a recording proxy
stands behind every proxy variable, and recording stand-ins for gh, uv, uvx, claude, curl, wget
and ssh come first on ``PATH``, in an environment built from scratch. A simple command passes
when it exits 0 with its usual output, the marker names its process and nothing was recorded.
"""

import contextlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator, Mapping, Sequence
from importlib.metadata import version
from pathlib import Path

import pytest

from agent_hub.core.testing.outbound_probe import (
    outbound_calls,
    outbound_env,
    recording_proxy,
    write_stubs,
)

# The probe's marker log in its folder: one JSON object (``pid``, ``ppid``, ``argv``) for each
# interpreter the probe loaded in.
LOADED_MARKERS = "loaded.jsonl"
# A command that has not ended by then is hung, not slow.
COMMAND_TIMEOUT = 60.0
GIT_IDENTITY = (
    "-c",
    "user.name=Jane Doe",
    "-c",
    "user.email=jane@example.com",
    "-c",
    "commit.gpgsign=false",
)

# The commands ``make perf`` times, each with a text the docs say its output holds in this hub:
# the installed version, Typer's usage line, the brief's repos heading (environments.md), the
# README's repo line for ``demo_hub``'s repo, the action and scenario ``hub init`` seeds (SPEC),
# and a built-in workflow (hub-doctor.md). No text is documented for ``hub env list`` in a hub
# with no environment, so its exit code is the check.
SIMPLE_COMMANDS = [
    pytest.param(("--version",), version("agent-hub-cli"), id="version"),
    pytest.param(("--help",), "Usage", id="help"),
    pytest.param(("brief", "--no-network"), "## Repos", id="brief-no-network"),
    pytest.param(("repo", "list"), "demo-api (acme/demo-api", id="repo-list"),
    pytest.param(("env", "list"), None, id="env-list"),
    pytest.param(("action", "list"), "demo-get-status", id="action-list"),
    pytest.param(("scenario", "list"), "demo-service-up", id="scenario-list"),
    pytest.param(("workflow", "list"), "issue-to-pr", id="workflow-list"),
]


@pytest.fixture
def committed_hub(demo_hub: Path, tmp_path: Path) -> Path:
    """``demo_hub`` as a git checkout with one commit, as ``make perf``'s temp hub is."""
    git = shutil.which("git")
    assert git is not None, "git is needed to commit the hub"
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path / "git-home"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_ALLOW_PROTOCOL": "file",
    }
    for args in (
        ("init", "--quiet"),
        ("add", "--all"),
        (*GIT_IDENTITY, "commit", "--quiet", "--message", "Create the hub"),
    ):
        subprocess.run(  # noqa: S603 - git from PATH, fixed arguments, a tmp_path checkout
            [git, *args], cwd=demo_hub, env=env, check=True, capture_output=True
        )
    return demo_hub


@contextlib.contextmanager
def probed(folder: Path) -> Iterator[dict[str, str]]:
    """The probe's environment for a child, with its recorder serving until the block ends."""
    folder.mkdir()
    write_stubs(folder)
    with recording_proxy(folder) as port:
        yield outbound_env(folder, port, os.environ.get("PATH", os.defpath))


def run_hub(
    args: Sequence[str], *, hub: Path, env: Mapping[str, str]
) -> tuple[int, subprocess.CompletedProcess[str]]:
    """``python -m agent_hub.cli`` with ``args`` in ``hub``: its process id, and what it gave."""
    argv = [sys.executable, "-m", "agent_hub.cli", *args]
    process = subprocess.Popen(  # noqa: S603 - this interpreter, fixed arguments
        argv,
        cwd=hub,
        env=dict(env),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
    )
    stdout, stderr = process.communicate(timeout=COMMAND_TIMEOUT)
    return process.pid, subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)


def loaded_pids(folder: Path) -> set[int]:
    """The process ids in the probe's marker log: each interpreter it loaded in."""
    lines = (folder / LOADED_MARKERS).read_text(encoding="utf-8").splitlines()
    return {json.loads(line)["pid"] for line in lines}


@pytest.mark.parametrize(("args", "shown"), SIMPLE_COMMANDS)
def test_makes_no_network_call_when_simple_command_runs(
    args: tuple[str, ...], shown: str | None, *, committed_hub: Path, tmp_path: Path
) -> None:
    folder = tmp_path / "probe"

    with probed(folder) as env:
        pid, completed = run_hub(args, hub=committed_hub, env=env)
    calls = outbound_calls(folder)

    assert completed.returncode == 0, completed.stderr
    assert shown is None or shown in completed.stdout, completed.stdout
    assert pid in loaded_pids(folder), "the probe did not load in the command's process"
    assert calls == [], f"hub {' '.join(args)} called out"


def test_records_gh_calls_when_brief_uses_network(*, committed_hub: Path, tmp_path: Path) -> None:
    folder = tmp_path / "probe"

    with probed(folder) as env:
        run_hub(("brief",), hub=committed_hub, env=env)
    calls = outbound_calls(folder)

    # README: plain hub brief asks gh for its PR and CI lines. Every call is the stand-in gh,
    # named by the brief's own process.
    assert len(calls) >= 1, calls
    assert [call for call in calls if "gh " not in call or "brief" not in call] == [], calls
