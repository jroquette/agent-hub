"""Simple ``hub`` commands make no network call; plain ``hub brief``, which calls gh on purpose,
is caught doing so.

Each command runs as ``python -m agent_hub.cli`` in the ``hub init`` hub of the cli conftest
(``demo_hub``), committed once as ``make perf``'s temp hub is, under the outbound probe
(``agent_hub.core.testing.outbound_probe``): its sitecustomize refuses and records any socket call
that leaves the machine and leaves a marker in each interpreter it loads in, a recording proxy
stands behind every proxy variable, and recording stand-ins for gh, uv, uvx, claude, curl, wget
and ssh come first on ``PATH``, in an environment built from scratch. A simple command passes
when it exits 0 with its usual output, the marker names its process, nothing it started still
runs within ``EXIT_WAIT`` (the logs are read only then) and nothing was recorded.

The installed ``hub`` runs ``agent_hub.cli.console.main``, which lists workflows on a path of its
own (AGH-638), so ``workflow list`` also runs through a launcher that calls it.
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
    LOADED_LOG,
    kill_processes_left,
    outbound_calls,
    outbound_env,
    processes_left,
    recording_proxy,
    write_stubs,
)

# A command that has not ended by then is hung, not slow.
COMMAND_TIMEOUT = 60.0
# How long a case waits, once the command has ended, for what it started to end.
EXIT_WAIT = 10.0
GIT_IDENTITY = (
    "-c",
    "user.name=Jane Doe",
    "-c",
    "user.email=jane@example.com",
    "-c",
    "commit.gpgsign=false",
)

# The commands ``make perf`` times, each with what the docs say it prints in this hub: its whole
# output, the installed version, for ``--version``; else a text its output holds: Typer's usage
# line, the brief's repos heading (environments.md), the README's repo line for ``demo_hub``'s
# repo, the action and scenario ``hub init`` seeds (SPEC), and a built-in workflow
# (hub-doctor.md). No text is documented for ``hub env list`` in a hub with no environment, so its
# exit code is the check.
SIMPLE_COMMANDS = [
    pytest.param(("--version",), version("agent-hub-cli"), None, id="version"),
    pytest.param(("--help",), None, "Usage", id="help"),
    pytest.param(("brief", "--no-network"), None, "## Repos", id="brief-no-network"),
    pytest.param(("repo", "list"), None, "demo-api (acme/demo-api", id="repo-list"),
    pytest.param(("env", "list"), None, None, id="env-list"),
    pytest.param(("action", "list"), None, "demo-get-status", id="action-list"),
    pytest.param(("scenario", "list"), None, "demo-service-up", id="scenario-list"),
    pytest.param(("workflow", "list"), None, "issue-to-pr", id="workflow-list"),
]
# A file named ``hub`` that calls the console entry as the installed script does. At exit it
# notes, beside itself, whether the run loaded Typer: it does not when the console listed the
# workflows on its own path.
CONSOLE_LAUNCHER = """\
import atexit
import sys
from pathlib import Path

atexit.register(
    lambda: Path(sys.argv[0]).with_name("typer-loaded").write_text(str("typer" in sys.modules))
)
from agent_hub.cli.console import main

sys.exit(main())
"""

pytestmark = pytest.mark.usefixtures("no_process_left")


@pytest.fixture
def no_process_left(tmp_path: Path) -> Iterator[None]:
    """After the case, kill what it left running, as ``processes_left`` finds it (each process
    whose command line names the case's folder, each Python child the probe loaded in), until
    nothing is left: a failing case leaves nothing behind."""
    yield
    still = kill_processes_left(tmp_path / "probe", tmp_path, timeout=EXIT_WAIT)
    assert still == [], "still running after the kill:\n" + "\n".join(still)


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
    args: Sequence[str],
    *,
    hub: Path,
    env: Mapping[str, str],
    entry: Sequence[str] = ("-m", "agent_hub.cli"),
) -> tuple[int, subprocess.CompletedProcess[str]]:
    """``python -m agent_hub.cli``, or this interpreter on ``entry``, with ``args`` in ``hub``, no
    stdin: its process id, and what it gave. A command still running at ``COMMAND_TIMEOUT`` is
    killed and reaped, then the timeout raised."""
    argv = [sys.executable, *entry, *args]
    with subprocess.Popen(  # noqa: S603 - this interpreter, fixed arguments
        argv,
        cwd=hub,
        env=dict(env),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
    ) as process:
        try:
            stdout, stderr = process.communicate(timeout=COMMAND_TIMEOUT)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise
    return process.pid, subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)


def loaded_pids(folder: Path) -> set[int]:
    """The process ids in the probe's marker log: each interpreter it loaded in."""
    lines = (folder / LOADED_LOG).read_text(encoding="utf-8").splitlines()
    return {json.loads(line)["pid"] for line in lines}


@pytest.mark.parametrize(("args", "output", "shown"), SIMPLE_COMMANDS)
def test_makes_no_network_call_when_simple_command_runs(
    args: tuple[str, ...],
    output: str | None,
    shown: str | None,
    *,
    committed_hub: Path,
    tmp_path: Path,
) -> None:
    folder = tmp_path / "probe"

    with probed(folder) as env:
        pid, completed = run_hub(args, hub=committed_hub, env=env)
        # A call is logged when it is made: a detached child's, after the command has exited.
        left = processes_left(folder, tmp_path, timeout=EXIT_WAIT)
        assert left == [], f"hub {' '.join(args)} left running:\n" + "\n".join(left)
    calls = outbound_calls(folder)

    assert completed.returncode == 0, completed.stderr
    assert output is None or completed.stdout.strip() == output, completed.stdout
    assert shown is None or shown in completed.stdout, completed.stdout
    assert pid in loaded_pids(folder), "the probe did not load in the command's process"
    assert calls == [], f"hub {' '.join(args)} called out"


def test_makes_no_network_call_when_console_lists_workflows(
    *, committed_hub: Path, tmp_path: Path
) -> None:
    folder = tmp_path / "probe"
    launcher = tmp_path / "console" / "hub"
    launcher.parent.mkdir()
    launcher.write_text(CONSOLE_LAUNCHER, encoding="utf-8")

    with probed(folder) as env:
        pid, completed = run_hub(
            ("workflow", "list"), hub=committed_hub, env=env, entry=(str(launcher),)
        )
        left = processes_left(folder, tmp_path, timeout=EXIT_WAIT)
        assert left == [], "the console's workflow list left running:\n" + "\n".join(left)
    calls = outbound_calls(folder)

    assert completed.returncode == 0, completed.stderr
    assert "issue-to-pr" in completed.stdout, completed.stdout
    typer_loaded = (launcher.parent / "typer-loaded").read_text(encoding="utf-8")
    assert typer_loaded == "False", "the console handed the listing over to the Typer app"
    assert pid in loaded_pids(folder), "the probe did not load in the console's process"
    assert calls == [], "the console's workflow list called out"


def test_records_gh_calls_when_brief_uses_network(*, committed_hub: Path, tmp_path: Path) -> None:
    folder = tmp_path / "probe"

    with probed(folder) as env:
        run_hub(("brief",), hub=committed_hub, env=env)
        left = processes_left(folder, tmp_path, timeout=EXIT_WAIT)
        assert left == [], "hub brief left running:\n" + "\n".join(left)
    calls = outbound_calls(folder)

    # README: plain hub brief asks gh for its PR and CI lines. Every call is the stand-in gh,
    # named by the brief's own process.
    assert len(calls) >= 1, calls
    assert [call for call in calls if "gh " not in call or "brief" not in call] == [], calls
