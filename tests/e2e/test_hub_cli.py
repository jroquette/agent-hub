import os
import sqlite3
import subprocess
import tomllib
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from subprocess import CompletedProcess

from alembic.script import ScriptDirectory
from typer.testing import CliRunner

from agent_hub.cli.main import app
from agent_hub.core.testing.builders import an_event, events_to_jsonl
from agent_hub.storage.migration import alembic_config
from tests.e2e.conftest import REPO_ROOT, InstalledHub

EVENT_COUNT = 3
# The hub-init spec's DEMO_FLAGS: every value given, so git is never asked.
DEMO_FLAGS = (
    "demo",
    "--repos",
    "acme/demo-api",
    "--tracker",
    "linear:DEM",
    "--branch-prefix",
    "jdoe/",
    "--author-name",
    "Jane Doe",
    "--author-email",
    "jane@example.com",
    "--hub-repo",
    "acme/demo-hub",
)
# The golden harness's mode variables: the installed hub never inherits them.
DROPPED_VARIABLES = ("GOLDEN_UPDATE", "GOLDEN_KEEP", "CI")


def test_prints_version_when_installed_as_uv_tool(
    installed_hub: InstalledHub, repo_root: Path, run: Callable[..., CompletedProcess[str]]
) -> None:
    cli_project = tomllib.loads((repo_root / "packages/cli/pyproject.toml").read_text())
    meta_project = tomllib.loads((repo_root / "packages/agent-hub/pyproject.toml").read_text())

    result = run([str(installed_hub.executable), "--version"], env=installed_hub.env)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == cli_project["project"]["version"]
    assert result.stdout.strip() == meta_project["project"]["version"]


def test_collects_twice_when_installed_as_uv_tool(
    tmp_path: Path, installed_hub: InstalledHub, run: Callable[..., CompletedProcess[str]]
) -> None:
    events_file = tmp_path / "events.jsonl"
    events_file.write_text(events_to_jsonl(an_event() for _ in range(EVENT_COUNT)))
    data_home = tmp_path / "xdg"
    # The default database path, under tmp_path, and a working directory outside the repo, so
    # the installed package has to bring its own migrations.
    env = {**installed_hub.env, "HOME": str(tmp_path / "home"), "XDG_DATA_HOME": str(data_home)}
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    assert not work_dir.resolve().is_relative_to(REPO_ROOT)
    command = [str(installed_hub.executable), "collect", str(events_file)]

    first = run(command, env=env, cwd=work_dir)
    second = run(command, env=env, cwd=work_dir)

    assert (first.returncode, first.stderr) == (0, ""), first.stderr
    assert first.stdout == f"appended {EVENT_COUNT}, duplicates 0\n"
    assert (second.returncode, second.stderr) == (0, ""), second.stderr
    assert second.stdout == f"appended 0, duplicates {EVENT_COUNT}\n"
    database = data_home / "agent-hub" / "agent-hub.db"
    assert database.is_file()
    head = ScriptDirectory.from_config(alembic_config("sqlite://")).get_current_head()
    # Read-only, so a missing file fails here instead of being created empty.
    with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as connection:
        versions = connection.execute("SELECT version_num FROM alembic_version").fetchall()
    assert versions == [(head,)]
    assert head is not None


def test_writes_same_lock_when_installed_hub_inits(
    tmp_path: Path, installed_hub: InstalledHub, run: Callable[..., CompletedProcess[str]]
) -> None:
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    assert not work_dir.resolve().is_relative_to(REPO_ROOT)
    env = {**installed_hub.env, "HOME": str(tmp_path / "home")}
    for variable in DROPPED_VARIABLES:
        env.pop(variable, None)
    installed_root = work_dir / "hub"
    in_process_root = tmp_path / "in-process"

    result = run(
        [str(installed_hub.executable), "init", *DEMO_FLAGS, "--dir", str(installed_root)],
        env=env,
        cwd=work_dir,
    )
    in_process = CliRunner().invoke(app, ["init", *DEMO_FLAGS, "--dir", str(in_process_root)])

    assert (result.returncode, result.stderr) == (0, ""), result.stderr
    assert result.stdout.startswith("created ")
    assert in_process.exit_code == 0, in_process.stderr
    lock = (installed_root / "hub.lock").read_bytes()
    assert lock == (in_process_root / "hub.lock").read_bytes()
    assert b'"lock_version": 1' in lock


def test_prints_up_to_date_when_installed_hub_syncs_fresh_init(
    tmp_path: Path, installed_hub: InstalledHub, run: Callable[..., CompletedProcess[str]]
) -> None:
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    assert not work_dir.resolve().is_relative_to(REPO_ROOT)
    env = {**installed_hub.env, "HOME": str(tmp_path / "home")}
    for variable in DROPPED_VARIABLES:
        env.pop(variable, None)
    root = work_dir / "t"
    initialized = run(
        [str(installed_hub.executable), "init", *DEMO_FLAGS, "--dir", str(root)],
        env=env,
        cwd=work_dir,
    )
    assert (initialized.returncode, initialized.stderr) == (0, ""), initialized.stderr

    result = run([str(installed_hub.executable), "sync"], env=env, cwd=root)

    assert (result.returncode, result.stdout, result.stderr) == (0, "up to date\n", "")


def test_exits_zero_when_installed_hub_doctors_fresh_init(
    tmp_path: Path, installed_hub: InstalledHub, run: Callable[..., CompletedProcess[str]]
) -> None:
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    assert not work_dir.resolve().is_relative_to(REPO_ROOT)
    # DEMO's one repo next to the hub, empty, so the run stays clean once repos are read.
    (work_dir / "demo-api").mkdir()
    env = {**installed_hub.env, "HOME": str(tmp_path / "home")}
    # No harness mode, and no git location or config of the caller: git reads the test HOME only.
    for variable in [*DROPPED_VARIABLES, "XDG_CONFIG_HOME"]:
        env.pop(variable, None)
    for variable in [name for name in env if name.startswith("GIT_")]:
        env.pop(variable)
    root = work_dir / "t"
    initialized = run(
        [str(installed_hub.executable), "init", *DEMO_FLAGS, "--dir", str(root)],
        env=env,
        cwd=work_dir,
    )
    assert (initialized.returncode, initialized.stderr) == (0, ""), initialized.stderr

    result = run([str(installed_hub.executable), "doctor"], env=env, cwd=root)

    assert (result.returncode, result.stdout, result.stderr) == (
        0,
        "0 errors, 0 warnings, 0 infos\n",
        "",
    ), result.stderr


def shim_hub(
    tmp_path: Path, installed_hub: InstalledHub, run: Callable[..., CompletedProcess[str]]
) -> tuple[Path, dict[str, str]]:
    """A fresh ``init DEMO_FLAGS`` hub and an environment whose ``uvx`` is the installed hub.

    The fake ``uvx`` checks that ``--from`` names the pinned source of the installed version,
    written literally, then drops it and execs the installed ``hub`` with the rest.
    """
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    assert not work_dir.resolve().is_relative_to(REPO_ROOT)
    # DEMO's one repo next to the hub, empty, so the doctor run stays clean (hub-doctor E3a).
    (work_dir / "demo-api").mkdir()
    env = {**installed_hub.env, "HOME": str(tmp_path / "home")}
    for variable in [*DROPPED_VARIABLES, "XDG_CONFIG_HOME", "AGENT_HUB_ROOT"]:
        env.pop(variable, None)
    for variable in [name for name in env if name.startswith("GIT_")]:
        env.pop(variable)
    root = work_dir / "t"
    initialized = run(
        [str(installed_hub.executable), "init", *DEMO_FLAGS, "--dir", str(root)],
        env=env,
        cwd=work_dir,
    )
    assert (initialized.returncode, initialized.stderr) == (0, ""), initialized.stderr
    version = run([str(installed_hub.executable), "--version"], env=env).stdout.strip()
    source = (
        f"git+https://github.com/jroquette/agent-hub@v{version}#subdirectory=packages/agent-hub"
    )
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    uvx = fakes / "uvx"
    uvx.write_text(
        "#!/bin/sh\n"
        f'[ "$1" = --from ] && [ "$2" = "{source}" ] && [ "$3" = hub ] || {{\n'
        '  echo "fake uvx: unexpected call: $*" >&2\n'
        "  exit 90\n"
        "}\n"
        "shift 3\n"
        f'exec "{installed_hub.executable}" "$@"\n'
    )
    uvx.chmod(0o755)
    env["PATH"] = os.pathsep.join([str(fakes), env.get("PATH", os.defpath)])
    return root, env


def test_runs_doctor_and_sync_through_shim_when_fresh_init(
    tmp_path: Path, installed_hub: InstalledHub, run: Callable[..., CompletedProcess[str]]
) -> None:
    root, env = shim_hub(tmp_path, installed_hub, run)

    doctor = run([str(root / "hub"), "doctor"], env=env, cwd=root)
    sync = run([str(root / "hub"), "sync", "--check"], env=env, cwd=root)

    assert (doctor.returncode, doctor.stdout, doctor.stderr) == (
        0,
        "0 errors, 0 warnings, 0 infos\n",
        "",
    ), doctor.stderr
    assert sync.returncode == 0, sync.stdout + sync.stderr


def test_execs_claude_when_agent_runs(
    tmp_path: Path, installed_hub: InstalledHub, run: Callable[..., CompletedProcess[str]]
) -> None:
    root, env = shim_hub(tmp_path, installed_hub, run)
    claude = tmp_path / "fakes" / "claude"
    claude.write_text('#!/bin/sh\necho "$$"\nexit 7\n')
    claude.chmod(0o755)

    # ./agent → ./hub → uvx → the installed hub → claude, each an exec: one process throughout.
    process = subprocess.Popen(  # noqa: S603 - the rendered launcher, fixed arguments
        [str(root / "agent"), "--version"],
        cwd=root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout, stderr = process.communicate(timeout=120)

    assert process.returncode == 7, stderr
    assert stdout == f"{process.pid}\n"
    assert (root / "brain" / "auto" / "agent-context.md").is_file()
