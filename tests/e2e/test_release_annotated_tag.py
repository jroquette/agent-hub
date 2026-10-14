"""release.yml refuses a lightweight tag (ADR 0013): its annotation step, read from the workflow
file, runs with real git against a local bare remote. The remote decides, whatever kind of tag the
checkout holds, since actions/checkout may fetch an annotated tag as lightweight."""

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from tests.e2e.conftest import REPO_ROOT

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
STEP_NAME = "- name: Check the tag form, that it is annotated, and the cli and meta versions"
TAG = "v0.2.0"
TIMEOUT_SECONDS = 120


def step_script() -> str:
    """The ``run: |`` block of the annotation step in release.yml, dedented."""
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    start = next(index for index, line in enumerate(lines) if line.strip() == STEP_NAME)
    run_index = next(
        index for index in range(start, len(lines)) if lines[index].strip() == "run: |"
    )
    run_indent = len(lines[run_index]) - len(lines[run_index].lstrip())
    block: list[str] = []
    for line in lines[run_index + 1 :]:
        if line.strip() and len(line) - len(line.lstrip()) <= run_indent:
            break
        block.append(line)
    return textwrap.dedent("\n".join(block))


def git(cwd: Path, *arguments: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Release Test",
            "-c",
            "user.email=release@example.invalid",
            *arguments,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
        env=isolated_git_env(),
        timeout=TIMEOUT_SECONDS,
    )


def isolated_git_env() -> dict[str, str]:
    """The environment without the user's git config (tag signing, url rewrites)."""
    return {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def make_tag(cwd: Path, kind: str) -> None:
    if kind == "annotated":
        git(cwd, "tag", "-a", TAG, "-m", TAG)
    else:
        git(cwd, "tag", TAG)


def checkout_with_remote_tag(tmp_path: Path, *, remote: str, local: str) -> Path:
    """A checkout whose bare ``origin`` holds TAG as ``remote``; the checkout holds ``local``."""
    origin = tmp_path / "origin.git"
    checkout = tmp_path / "checkout"
    git(tmp_path, "init", "--bare", "-q", str(origin))
    git(tmp_path, "init", "-q", "-b", "main", str(checkout))
    for relative in ("packages/cli/pyproject.toml", "packages/agent-hub/pyproject.toml"):
        path = checkout / relative
        path.parent.mkdir(parents=True)
        path.write_text(f'[project]\nname = "x"\nversion = "{TAG[1:]}"\n', encoding="utf-8")
    (checkout / "scripts").mkdir()
    shutil.copy(REPO_ROOT / "scripts" / "check_release.py", checkout / "scripts")
    git(checkout, "add", ".")
    git(checkout, "commit", "-q", "-m", "release")
    git(checkout, "remote", "add", "origin", str(origin))
    make_tag(checkout, remote)
    git(checkout, "push", "-q", "origin", "main", f"refs/tags/{TAG}")
    git(checkout, "tag", "-d", TAG)
    make_tag(checkout, local)
    return checkout


@pytest.mark.parametrize("local", ["annotated", "lightweight"])
def test_refuses_tag_when_remote_tag_lightweight(tmp_path: Path, local: str) -> None:
    checkout = checkout_with_remote_tag(tmp_path, remote="lightweight", local=local)

    result = run_step(checkout)

    assert result.returncode == 1
    assert f'tag "{TAG}": is a lightweight tag' in result.stderr


@pytest.mark.parametrize("local", ["annotated", "lightweight"])
def test_accepts_tag_when_remote_tag_annotated(tmp_path: Path, local: str) -> None:
    checkout = checkout_with_remote_tag(tmp_path, remote="annotated", local=local)

    result = run_step(checkout)

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(f'tag "{TAG}" ok: annotated, ')


def run_step(checkout: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-e", "-c", step_script()],
        cwd=checkout,
        capture_output=True,
        text=True,
        env={**isolated_git_env(), "TAG": TAG},
        timeout=TIMEOUT_SECONDS,
        check=False,
    )
