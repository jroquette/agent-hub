import sqlite3
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

    result = run([str(installed_hub.executable), "--version"], env=installed_hub.env)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == cli_project["project"]["version"]


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
