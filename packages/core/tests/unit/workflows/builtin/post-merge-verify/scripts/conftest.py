"""The post-merge-verify pack's script tests' workspace: a temporary hub with a sibling git repo,
built at test time.
"""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest


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
    """A hub (``hub``, holding ``hub.json`` and ``brain/features/``) and its repo ``demo-api``."""

    hub: Path
    repo: Path

    def git(self, *args: str) -> str:
        return git(self.repo, *args)

    def commit(self, subject: str, **content: str) -> str:
        for name, text in content.items():
            # ``src__a_py`` is the file ``src/a_py``.
            path = self.repo / name.replace("__", "/")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", subject)
        return git(self.repo, "rev-parse", "HEAD")

    def remove(self, subject: str, name: str) -> str:
        git(self.repo, "rm", "-q", name)
        git(self.repo, "commit", "-q", "-m", subject)
        return git(self.repo, "rev-parse", "HEAD")

    def merge(self, branch: str, subject: str) -> str:
        """Merge ``branch`` into main with a merge commit; return the merge's sha."""
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "merge", "-q", "--no-ff", "-m", subject, branch)
        return git(self.repo, "rev-parse", "HEAD")

    def record(self, key: str, record: dict[str, Any]) -> Path:
        folder = self.hub / "brain/features" / key
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "features.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        return path


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    hub = tmp_path / "hub"
    (hub / "brain/features").mkdir(parents=True)
    config = {"repos": [{"dir": "demo-api", "check_fast": "true", "check": "true"}]}
    (hub / "hub.json").write_text(json.dumps(config), encoding="utf-8")
    repo = tmp_path / "demo-api"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    found = Workspace(hub=hub, repo=repo)
    found.commit("chore: start", README="demo\n")
    return found
