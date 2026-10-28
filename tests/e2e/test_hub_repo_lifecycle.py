"""AGH-578 (AC-7): the installed ``hub repo`` adds, changes and removes a repo of a scratch hub,
and ``hub sync`` follows each change to a clean ``hub sync --check``."""

from collections.abc import Callable, Sequence
from pathlib import Path
from subprocess import CompletedProcess

from tests.e2e.conftest import REPO_ROOT, InstalledHub
from tests.e2e.test_hub_cli import DEMO_FLAGS, DROPPED_VARIABLES

ADDED_REPO = "demo-web"


def test_syncs_clean_when_repo_added_changed_and_removed(
    tmp_path: Path, installed_hub: InstalledHub, run: Callable[..., CompletedProcess[str]]
) -> None:
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    assert not work_dir.resolve().is_relative_to(REPO_ROOT)
    root = work_dir / "t"
    env = {**installed_hub.env, "HOME": str(tmp_path / "home"), "AGENT_HUB_ROOT": str(root)}
    for variable in DROPPED_VARIABLES:
        env.pop(variable, None)
    hub = str(installed_hub.executable)

    def ok(command: Sequence[str], *, cwd: Path) -> str:
        result = run([hub, *command], env=env, cwd=cwd)
        assert result.returncode == 0, (command, result.stdout, result.stderr)
        return result.stdout

    def synced_agents() -> str:
        ok(["sync"], cwd=root)
        ok(["sync", "--check"], cwd=root)
        return (root / "AGENTS.md").read_text(encoding="utf-8")

    ok(["init", *DEMO_FLAGS, "--dir", str(root)], cwd=work_dir)
    assert ADDED_REPO not in synced_agents()

    # The repo commands find the hub through AGENT_HUB_ROOT, run from outside it.
    ok(
        ["repo", "add", ADDED_REPO, "--github", f"acme/{ADDED_REPO}", "--check", "make check"],
        cwd=work_dir,
    )
    assert ADDED_REPO in synced_agents()

    ok(["repo", "set", ADDED_REPO, "--role", "app"], cwd=work_dir)
    listed = ok(["repo", "list"], cwd=work_dir)
    assert f"{ADDED_REPO} (acme/{ADDED_REPO}, app, " in listed, listed
    assert ADDED_REPO in synced_agents()

    ok(["repo", "remove", ADDED_REPO], cwd=work_dir)
    assert ADDED_REPO not in synced_agents()
