"""The review-incoming scripts' shared setup: each script loaded in process, and a hub (its
``hub.json``) beside a real git clone with ``origin/main`` and the review ref of PR 7."""

import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from types import ModuleType

import pytest

SCRIPTS = Path(str(files("agent_hub.core").joinpath("workflows/builtin/review-incoming/scripts")))
REF = "refs/agent-hub/review/7"


def load(name: str) -> ModuleType:
    # Named as its folder places it, so coverage of agent_hub.core measures it.
    module_name = f"agent_hub.core.workflows.builtin.review-incoming.scripts.{name}"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # No __pycache__ beside the pack's files: the pack is seeded into hubs file by file.
    writes, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = writes
    return module


def git(folder: Path, *args: str) -> str:
    done = subprocess.run(  # noqa: S603 - git from PATH, fixed arguments
        ["git", "-c", "user.name=T", "-c", "user.email=t@example.com", *args],  # noqa: S607
        cwd=folder,
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


@dataclass
class Clone:
    """A hub and its repo's clone: ``base`` is ``origin/main``, ``head`` the review ref's commit."""

    hub: Path
    repo: Path
    base: str
    head: str

    def commit(self, changes: dict[str, str], *, ref: str = REF) -> str:
        """A commit on ``base`` with ``changes`` (path to text, or "" to delete), left in ``ref``
        alone; the clone stays on ``main`` with a clean status."""
        git(self.repo, "checkout", "-q", "--detach", self.base)
        for name, text in changes.items():
            path = self.repo / name
            if text:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            else:
                path.unlink()
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "change")
        head = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "update-ref", ref, head)
        self.head = head
        return head

    def git(self, *args: str) -> str:
        return git(self.repo, *args)

    def state(self) -> tuple[str, ...]:
        """What a read-only script must leave as it was."""
        return (
            git(self.repo, "rev-parse", "HEAD"),
            git(self.repo, "branch", "-a"),
            git(self.repo, "status", "--porcelain", "--ignored"),
            git(self.repo, "worktree", "list", "--porcelain"),
            git(self.repo, "for-each-ref"),
        )


@pytest.fixture
def script() -> Callable[[str], ModuleType]:
    """``script(name)``: the pack script ``name`` loaded in process."""
    return load


@pytest.fixture
def clone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Clone:
    """The hub as the cwd (scripts read ``hub.json`` there) and ``../api``, its clone."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    hub, repo = tmp_path / "hub", tmp_path / "api"
    hub.mkdir()
    config = {
        "tracker": {"kind": "linear", "team": "DEM"},
        "repos": [{"dir": "api", "github": "example/api", "check": "make check"}],
    }
    (hub / "hub.json").write_text(json.dumps(config), encoding="utf-8")
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "app").mkdir()
    (repo / "app/core.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "update-ref", "refs/remotes/origin/main", base)
    found = Clone(hub, repo, base, base)
    found.commit({"app/run.py": "def run(job):\n    return job()\n"})
    monkeypatch.chdir(hub)
    return found
