"""release.yml's dispatch job creates the release tag (ADR 0047): its check step and its tag step,
read from the workflow file, run in order with real git against a local bare remote. They create an
annotated tag whose message is the notes, on the given commit, push only that tag, and refuse a
malformed input, a commit off main, a version other than the one that commit declares, and a tag
that already exists (never moved)."""

import shutil
import subprocess
from pathlib import Path

import pytest

from tests.e2e.conftest import REPO_ROOT, isolated_git_env, workflow_step_script

# The dispatch job's steps, in the order the job runs them; only the last one holds the token.
STEP_NAMES = (
    "- name: Check the inputs, that the commit is on main, and its declared versions",
    "- name: Create and push the annotated tag, unless it exists",
)
VERSION = "0.2.0"
TAG = f"v{VERSION}"
NOTES = "Features\n\n- one\n\n# Migration steps\n\nnone"
BOT_NAME = "github-actions[bot]"
TIMEOUT_SECONDS = 120


def git(cwd: Path, *arguments: str) -> str:
    result = subprocess.run(
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
        text=True,
        env=isolated_git_env(),
        timeout=TIMEOUT_SECONDS,
    )
    return result.stdout.strip()


def commit_version(repo: Path, version: str) -> str:
    """Commit both lockstep files at ``version`` in ``repo``; the new commit's SHA."""
    for relative in ("packages/cli/pyproject.toml", "packages/agent-hub/pyproject.toml"):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'[project]\nname = "x"\nversion = "{version}"\n', encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", f"version {version}")
    return git(repo, "rev-parse", "HEAD")


def remote_and_checkout(tmp_path: Path) -> tuple[Path, Path, str]:
    """A bare ``origin`` whose main declares VERSION, and a clone of it; the main commit's SHA."""
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    checkout = tmp_path / "checkout"
    git(tmp_path, "init", "--bare", "-q", "-b", "main", str(origin))
    git(tmp_path, "init", "-q", "-b", "main", str(seed))
    (seed / "scripts").mkdir()
    shutil.copy(REPO_ROOT / "scripts" / "check_release.py", seed / "scripts")
    sha = commit_version(seed, VERSION)
    git(seed, "remote", "add", "origin", str(origin))
    git(seed, "push", "-q", "origin", "main")
    git(tmp_path, "clone", "-q", str(origin), str(checkout))
    return origin, checkout, sha


def run_step(
    checkout: Path, *, version: str = VERSION, sha: str, notes: str = NOTES
) -> subprocess.CompletedProcess[str]:
    """Run the job's steps in order, as Actions does (bash -eo pipefail); stop at a failure."""
    env = {**isolated_git_env(), "VERSION": version, "SHA": sha, "NOTES": notes}
    for name in STEP_NAMES:
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", workflow_step_script(name)],
            cwd=checkout,
            capture_output=True,
            text=True,
            env=env,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
        if result.returncode != 0:
            break
    return result


def files_outside_git(root: Path) -> list[Path]:
    """Every path under ``root`` but the repositories' own git data (the bare origin, ``.git``)."""
    skipped = {".git", "origin.git"}
    return sorted(
        path.relative_to(root) for path in root.rglob("*") if skipped.isdisjoint(path.parts)
    )


def remote_tags(origin: Path) -> str:
    return git(origin, "for-each-ref", "refs/tags", "--format=%(refname) %(objectname)")


def test_creates_annotated_tag_with_notes_when_inputs_valid(tmp_path: Path) -> None:
    origin, checkout, sha = remote_and_checkout(tmp_path)
    git(checkout, "tag", "local-only", sha)

    result = run_step(checkout, sha=sha)

    assert result.returncode == 0, result.stderr
    assert git(origin, "for-each-ref", "refs/tags", "--format=%(refname)") == f"refs/tags/{TAG}"
    assert git(origin, "cat-file", "-t", f"refs/tags/{TAG}") == "tag"
    assert git(origin, "rev-parse", f"refs/tags/{TAG}^{{commit}}") == sha
    assert git(origin, "for-each-ref", f"refs/tags/{TAG}", "--format=%(contents)") == NOTES
    assert git(origin, "for-each-ref", f"refs/tags/{TAG}", "--format=%(taggername)") == BOT_NAME


def test_tags_given_sha_when_main_moved_past_it(tmp_path: Path) -> None:
    origin, checkout, sha = remote_and_checkout(tmp_path)
    commit_version(checkout, "0.3.0")
    git(checkout, "push", "-q", "origin", "main")

    result = run_step(checkout, sha=sha)

    assert result.returncode == 0, result.stderr
    assert git(origin, "rev-parse", f"refs/tags/{TAG}^{{commit}}") == sha


def test_refuses_and_keeps_tag_when_tag_exists_on_remote(tmp_path: Path) -> None:
    origin, checkout, sha = remote_and_checkout(tmp_path)
    git(checkout, "tag", "-a", TAG, "-m", "first", sha)
    git(checkout, "push", "-q", "origin", f"refs/tags/{TAG}")
    git(checkout, "tag", "-d", TAG)
    before = remote_tags(origin)

    result = run_step(checkout, sha=sha)

    assert result.returncode == 1
    assert f"tag {TAG} already exists" in result.stderr
    assert remote_tags(origin) == before


def test_refuses_tag_when_sha_not_on_main(tmp_path: Path) -> None:
    origin, checkout, _ = remote_and_checkout(tmp_path)
    git(checkout, "switch", "-q", "-c", "side")
    (checkout / "side.txt").write_text("side\n", encoding="utf-8")
    side = commit_version(checkout, VERSION)
    git(checkout, "push", "-q", "origin", "side")
    git(checkout, "fetch", "-q", "origin")

    result = run_step(checkout, sha=side)

    assert result.returncode == 1
    assert "is not on main" in result.stderr
    assert remote_tags(origin) == ""


def test_refuses_tag_when_sha_unknown(tmp_path: Path) -> None:
    origin, checkout, _ = remote_and_checkout(tmp_path)

    result = run_step(checkout, sha="0" * 40)

    assert result.returncode == 1
    assert "not found" in result.stderr
    assert remote_tags(origin) == ""


def test_refuses_tag_when_version_differs_from_declared(tmp_path: Path) -> None:
    origin, checkout, sha = remote_and_checkout(tmp_path)

    result = run_step(checkout, version="0.3.0", sha=sha)

    assert result.returncode == 1
    assert "must be v + the version" in result.stderr
    assert remote_tags(origin) == ""


def test_refuses_tag_when_version_malformed(tmp_path: Path) -> None:
    """The form is check_release.py's (unit-tested there); this proves the step applies it."""
    origin, checkout, sha = remote_and_checkout(tmp_path)

    result = run_step(checkout, version="0-2-0", sha=sha)

    assert result.returncode == 1
    assert "must be v<major>.<minor>.<patch>" in result.stderr
    assert remote_tags(origin) == ""


@pytest.mark.parametrize("cut", ["short", "upper", "long", "ref", "newline"])
def test_refuses_tag_when_sha_malformed(tmp_path: Path, cut: str) -> None:
    origin, checkout, sha = remote_and_checkout(tmp_path)
    malformed = {
        "short": sha[:12],
        "upper": sha.upper(),
        "long": sha + "0",
        "ref": "main",
        "newline": sha + "\n",
    }[cut]

    result = run_step(checkout, sha=malformed)

    assert result.returncode == 1
    assert "sha must be a full 40-character commit SHA" in result.stderr
    assert remote_tags(origin) == ""


def test_refuses_tag_when_notes_empty(tmp_path: Path) -> None:
    origin, checkout, sha = remote_and_checkout(tmp_path)

    result = run_step(checkout, sha=sha, notes="")

    assert result.returncode == 1
    assert "notes are empty" in result.stderr
    assert remote_tags(origin) == ""


HOSTILE_NOTES = {
    "command-substitution": 'Fixes: $(touch pwned) and $(touch "$PWD/also")',
    "backticks": "Fixes: `touch pwned` and `id`",
    "file-option": "-F /etc/passwd",
    "cleanup-option": "--cleanup=strip",
    "expression-and-variable": "${{ github.token }} $HOME ${PATH}",
    "quotes": "it's \"quoted\" and 'single' \\ backslash",
    "comment-lines": "# Features\n\n# none\n#",
    "many-lines": "\n".join(f"- line {number}" for number in range(500)),
}


@pytest.mark.parametrize("kind", sorted(HOSTILE_NOTES))
def test_keeps_notes_verbatim_when_notes_hostile(tmp_path: Path, kind: str) -> None:
    notes = HOSTILE_NOTES[kind]
    origin, checkout, sha = remote_and_checkout(tmp_path)
    before = files_outside_git(tmp_path)

    result = run_step(checkout, sha=sha, notes=notes)

    assert result.returncode == 0, result.stderr
    message = subprocess.run(
        ["git", "cat-file", "tag", f"refs/tags/{TAG}"],
        cwd=origin,
        capture_output=True,
        text=True,
        env=isolated_git_env(),
        check=True,
        timeout=TIMEOUT_SECONDS,
    ).stdout.split("\n\n", 1)[1]
    assert message == notes + "\n"
    after = files_outside_git(tmp_path)
    assert after == before
