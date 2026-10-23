"""The flaky pack's script tests' workspace: a temporary hub with a sibling git repo holding a tiny
pytest suite, its ``origin/main`` set to the commit, built at test time.
"""

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

# The suite the repo holds. In ``tests/test_x.py``: ``test_y`` reads the list ``test_a`` fills (an
# order dependence), ``test_p`` fails only under pytest-xdist, ``test_ok`` always passes. Each other
# file sits in a folder of its own, so the parallel mode of ``tests`` never runs it: ``test_slow``
# outlasts a short run timeout, ``test_loud`` fails with a large output, ``test_zz_gone`` ends the
# process before the summary is written.
SUITE = {
    "tests/test_x.py": """\
import os

STATE = []


def test_a():
    STATE.append(1)


def test_y():
    assert not STATE


def test_p():
    assert "PYTEST_XDIST_WORKER" not in os.environ


def test_ok():
    assert True
""",
    "slow/test_slow.py": """\
import time


def test_slow():
    time.sleep(30)
""",
    "loud/test_loud.py": """\
def test_loud():
    print("```" + "x" * 100_000)
    raise AssertionError("loud")
""",
    "gone/test_gone.py": """\
import os


def test_ok():
    assert True


def test_zz_gone():
    os._exit(0)
""",
}


def git(folder: Path, *args: str) -> str:
    done = subprocess.run(  # noqa: S603 - git from PATH, fixed arguments
        [  # noqa: S607 - git from PATH
            "git",
            "-c",
            "user.name=T",
            "-c",
            "user.email=t@example.com",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=folder,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


@dataclass(frozen=True)
class Workspace:
    """A hub (``hub``) and its repo ``demo-api`` (``repo``); ``config`` is what ``hub step config``
    prints for it, as the workflow passes it with ``--config``."""

    hub: Path
    repo: Path
    config: str

    def git(self, *args: str) -> str:
        return git(self.repo, *args)

    def state(self) -> tuple[str, str, str]:
        """The checkout's HEAD, status and worktree list: what a run must leave as it was."""
        return (
            self.git("rev-parse", "HEAD"),
            self.git("status", "--porcelain"),
            self.git("worktree", "list", "--porcelain"),
        )


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Workspace:
    # The pytest runs the script starts must not inherit this session's (xdist, coverage).
    for name in list(os.environ):
        if name.startswith(("PYTEST_", "COV_CORE_")):
            monkeypatch.delenv(name)
    hub = tmp_path / "hub"
    hub.mkdir()
    repo = tmp_path / "demo-api"
    repo.mkdir()
    (repo / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    for name, text in SUITE.items():
        (repo / name).parent.mkdir(exist_ok=True)
        (repo / name).write_text(text, encoding="utf-8")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "chore: start")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    config = {
        "default_branch": "main",
        "repos": [{"dir": "demo-api", "default_branch": "main", "check_fast": "true"}],
    }
    return Workspace(hub=hub, repo=repo, config=json.dumps(config))
