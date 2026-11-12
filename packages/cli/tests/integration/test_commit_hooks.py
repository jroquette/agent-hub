"""AGH-835 (ADR 0061): a rendered hub's git hooks, run by real ``git commit``.

Each case renders the ``DEMO`` hub (``hub init``), makes it a git repository whose
``core.hooksPath`` is ``.githooks`` (as ``hub sync`` sets it), and commits with real git. The
rendered ``./hub`` reaches the workspace's ``hub`` through a fake ``uvx`` (``fake_uvx_bin``), so
nothing is downloaded. ``HOME`` is an empty folder that must stay empty, no ``pre-commit`` is on
``PATH`` and uv's folders sit under ``TMPDIR``: the hooks write nothing outside the hub and
``TMPDIR`` (AC-5).

AC-1: an unstaged edit that breaks feature A never blocks a commit of feature B. AC-2: a staged
``spec.md`` of feature A naming an AC its ``features.json`` lacks blocks the commit with that
finding. AC-3: the index is checked, not the working tree.
"""

import json
import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

TIMEOUT = 120
SYSTEM_PATH = ("/usr/bin", "/bin", "/usr/sbin", "/sbin")
ALPHA = "brain/features/alpha"
BETA = "brain/features/beta"
MISSING_LINE = (
    f"error features.tracker {ALPHA}/features.json: AC-2: in spec.md but not in features.json"
)


def real_git() -> str:
    found = shutil.which("git")
    assert found is not None, "the commit hook tests run git: install it"
    return os.path.realpath(found)


def a_record(feature: str, repo: str) -> dict[str, Any]:
    return {
        "feature": feature,
        "linear": [],
        "acs": [
            {
                "id": "AC-1",
                "description": "Given x When y Then z",
                "repo": repo,
                "verification": "pytest tests/unit/test_x.py::test_1",
                "passes": False,
                "evidence": None,
            }
        ],
    }


class HookedHub:
    """The rendered hub as a git repository with its ``.githooks`` on."""

    def __init__(self, root: Path, env: dict[str, str]) -> None:
        self.root = root
        self.env = env
        document = json.loads((root / "hub.json").read_text(encoding="utf-8"))
        self.repo = document["repos"][0]["dir"]

    def git(
        self, *arguments: str, env: Mapping[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 - absolute git, fixed arguments, no shell
            [real_git(), *arguments],
            capture_output=True,
            text=True,
            check=False,
            cwd=self.root,
            env=self.env | dict(env or {}),
            timeout=TIMEOUT,
        )

    def write_feature(self, folder: str, *, spec_ids: str = "AC-1") -> None:
        path = self.root / folder
        path.mkdir(parents=True, exist_ok=True)
        name = folder.rsplit("/", 1)[-1]
        (path / "spec.md").write_text(f"# {name}\n\n- {spec_ids}: the thing works.\n", "utf-8")
        record = json.dumps(a_record(name, self.repo), indent=2) + "\n"
        (path / "features.json").write_text(record, encoding="utf-8")

    def break_spec(self, folder: str) -> None:
        """Name ``AC-2`` in the spec, which ``features.json`` lacks (a tracker error)."""
        self.write_feature(folder, spec_ids="AC-1, AC-2")
        record = json.dumps(a_record(folder.rsplit("/", 1)[-1], self.repo), indent=2) + "\n"
        assert (self.root / folder / "features.json").read_text("utf-8") == record

    def commit(self, message: str) -> subprocess.CompletedProcess[str]:
        return self.git("commit", "-q", "-m", message)


@pytest.fixture
def hooked_hub(demo_hub: Path, fake_uvx_bin: Path, tmp_path: Path) -> HookedHub:
    home = tmp_path / "home"
    home.mkdir()
    temporary = tmp_path / "tmp"
    temporary.mkdir()
    document = json.loads((demo_hub / "hub.json").read_text(encoding="utf-8"))
    email = document["project"].get("author_email") or "jane@example.com"
    env = {
        "HOME": str(home),
        "TMPDIR": str(temporary),
        "PATH": os.pathsep.join((str(fake_uvx_bin), *SYSTEM_PATH)),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_AUTHOR_NAME": "Jane Doe",
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": "Jane Doe",
        "GIT_COMMITTER_EMAIL": email,
        "UV_CACHE_DIR": str(temporary / "uv-cache"),
        "UV_TOOL_DIR": str(temporary / "uv-tools"),
    }
    hub = HookedHub(demo_hub, env)
    for arguments in (
        ("init", "-q", "-b", "main"),
        ("config", "commit.gpgsign", "false"),
        ("config", "core.hooksPath", ".githooks"),
    ):
        assert hub.git(*arguments).returncode == 0
    assert shutil.which("pre-commit", path=env["PATH"]) is None
    hub.write_feature(ALPHA)
    hub.write_feature(BETA)
    assert hub.git("add", "-A").returncode == 0
    done = hub.commit("chore(hub): first commit")
    assert done.returncode == 0, done.stdout + done.stderr
    return hub


def test_passes_when_unstaged_edit_breaks_other_feature(hooked_hub: HookedHub) -> None:
    hooked_hub.break_spec(ALPHA)
    (hooked_hub.root / BETA / "notes.md").write_text("# notes\n", encoding="utf-8")
    assert hooked_hub.git("add", f"{BETA}/notes.md").returncode == 0

    done = hooked_hub.commit("docs(beta): add notes")

    assert done.returncode == 0, done.stdout + done.stderr
    assert hooked_hub.git("diff", "--quiet", "--", f"{ALPHA}/spec.md").returncode == 1


def test_passes_when_untracked_feature_is_broken(hooked_hub: HookedHub) -> None:
    hooked_hub.write_feature("brain/features/gamma", spec_ids="AC-1, AC-9")
    (hooked_hub.root / BETA / "notes.md").write_text("# notes\n", encoding="utf-8")
    assert hooked_hub.git("add", f"{BETA}/notes.md").returncode == 0

    done = hooked_hub.commit("docs(beta): add notes")

    assert done.returncode == 0, done.stdout + done.stderr


def test_blocks_when_staged_spec_names_missing_ac(hooked_hub: HookedHub) -> None:
    hooked_hub.break_spec(ALPHA)
    assert hooked_hub.git("add", f"{ALPHA}/spec.md").returncode == 0

    done = hooked_hub.commit("docs(alpha): name AC-2")

    assert done.returncode == 1
    # Git hands a hook's output to its own stderr.
    assert any(line.startswith(MISSING_LINE) for line in done.stderr.splitlines())
    assert hooked_hub.git("rev-list", "--count", "HEAD").stdout.strip() == "1"


def test_passes_when_staged_feature_valid_and_unstaged_edit_breaks_it(
    hooked_hub: HookedHub,
) -> None:
    spec = hooked_hub.root / ALPHA / "spec.md"
    spec.write_text("# alpha\n\n- AC-1: the thing works, said better.\n", encoding="utf-8")
    assert hooked_hub.git("add", f"{ALPHA}/spec.md").returncode == 0
    hooked_hub.break_spec(ALPHA)

    done = hooked_hub.commit("docs(alpha): reword AC-1")

    assert done.returncode == 0, done.stdout + done.stderr


def test_blocks_when_staged_file_has_trailing_whitespace(hooked_hub: HookedHub) -> None:
    (hooked_hub.root / BETA / "notes.md").write_text("# notes  \n", encoding="utf-8")
    assert hooked_hub.git("add", f"{BETA}/notes.md").returncode == 0

    done = hooked_hub.commit("docs(beta): add notes")

    assert done.returncode == 1
    assert any(
        line.startswith(f"error files.hygiene {BETA}/notes.md:1:")
        for line in done.stderr.splitlines()
    )


def test_blocks_when_message_carries_attribution(hooked_hub: HookedHub) -> None:
    (hooked_hub.root / BETA / "notes.md").write_text("# notes\n", encoding="utf-8")
    assert hooked_hub.git("add", f"{BETA}/notes.md").returncode == 0
    trailer = "Co-Authored-" + "By: Claude <noreply@anthropic.com>"

    done = hooked_hub.commit(f"docs(beta): add notes\n\n{trailer}\n")

    assert done.returncode == 1
    assert "commit-msg: the message carries AI attribution" in done.stderr


def test_writes_nothing_outside_hub_when_commit_runs_hooks(hooked_hub: HookedHub) -> None:
    (hooked_hub.root / BETA / "notes.md").write_text("# notes\n", encoding="utf-8")
    assert hooked_hub.git("add", f"{BETA}/notes.md").returncode == 0

    done = hooked_hub.commit("docs(beta): add notes")

    assert done.returncode == 0, done.stdout + done.stderr
    assert list(Path(hooked_hub.env["HOME"]).iterdir()) == []
    hooks = hooked_hub.root / ".githooks"
    for hook in ("pre-commit", "commit-msg"):
        text = (hooks / hook).read_text(encoding="utf-8")
        assert "://" not in text
        assert "pre-commit run" not in text


def test_passes_when_commit_names_paths_and_other_staged_feature_broken(
    hooked_hub: HookedHub,
) -> None:
    # `git commit <paths>` commits a temporary index (GIT_INDEX_FILE): HEAD plus those paths.
    hooked_hub.break_spec(ALPHA)
    assert hooked_hub.git("add", f"{ALPHA}/spec.md").returncode == 0
    (hooked_hub.root / BETA / "notes.md").write_text("# notes\n", encoding="utf-8")
    assert hooked_hub.git("add", f"{BETA}/notes.md").returncode == 0

    done = hooked_hub.git("commit", "-q", "-m", "docs(beta): add notes", "--", f"{BETA}/notes.md")

    assert done.returncode == 0, done.stdout + done.stderr
