"""The release pack's ``tagged.py`` (AGH-494), in process: is the release tag on the commit."""

import importlib.util
import json
import subprocess
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(str(files("agent_hub.core").joinpath("workflows/builtin/release/scripts/tagged.py")))

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.release.scripts.tagged"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(MODULE, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # No __pycache__ beside the pack's files: the pack is seeded into hubs file by file.
    writes, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = writes
    return module


SHA = "a" * 40
OTHER = "b" * 40
TAG_OBJECT = "c" * 40


def listed(*lines: tuple[str, str]) -> str:
    return "".join(f"{sha}\t{ref}\n" for sha, ref in lines)


def git(folder: Path, *args: str) -> str:
    done = subprocess.run(  # noqa: S603 - git from PATH, fixed arguments
        ["git", "-c", "user.name=T", "-c", "user.email=t@example.com", *args],  # noqa: S607
        cwd=folder,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def a_repo_with_origin(tmp_path: Path) -> tuple[Path, str]:
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", str(origin))
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "commit", "-q", "--allow-empty", "-m", "chore(repo): release 0.21.0 (AGH-9)")
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "push", "-q", "origin", "main")
    return repo, git(repo, "rev-parse", "HEAD")


def run(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *, sha: str
) -> dict[str, Any]:
    monkeypatch.chdir(repo)
    assert load().main(["--version", "0.21.0", "--sha", sha]) == 0
    found: dict[str, Any] = json.loads(capsys.readouterr().out)
    return found


def test_accepts_tag_when_peeled_entry_equals_release_commit() -> None:
    text = listed((TAG_OBJECT, "refs/tags/v0.21.0"), (SHA, "refs/tags/v0.21.0^{}"))

    found = load().verdict(text, "0.21.0", SHA)

    assert found == {
        "ok": True,
        "found": True,
        "annotated": True,
        "peeled": SHA,
        "reason": f"v0.21.0 is an annotated tag on {SHA}",
    }


def test_rejects_lightweight_tag_when_no_peeled_entry() -> None:
    found = load().verdict(listed((SHA, "refs/tags/v0.21.0")), "0.21.0", SHA)

    assert (found["ok"], found["found"], found["annotated"]) == (False, True, False)
    assert "lightweight" in found["reason"]
    assert "never moved" in found["reason"]


def test_rejects_tag_when_peeled_commit_differs() -> None:
    text = listed((TAG_OBJECT, "refs/tags/v0.21.0"), (OTHER, "refs/tags/v0.21.0^{}"))

    found = load().verdict(text, "0.21.0", SHA)

    assert (found["ok"], found["annotated"], found["peeled"]) == (False, True, OTHER)
    assert "squash" in found["reason"]
    assert SHA in found["reason"]


def test_reports_missing_when_tag_absent() -> None:
    found = load().verdict(listed((SHA, "refs/tags/v0.21.1^{}")), "0.21.0", SHA)

    assert (found["ok"], found["found"], found["peeled"]) == (False, False, "")
    assert "no tag v0.21.0" in found["reason"]


def test_accepts_annotated_tag_when_origin_holds_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, sha = a_repo_with_origin(tmp_path)
    git(repo, "tag", "-a", "v0.21.0", "-m", "notes")
    git(repo, "push", "-q", "origin", "v0.21.0")

    found = run(repo, monkeypatch, capsys, sha=sha)

    assert (found["ok"], found["peeled"]) == (True, sha)


def test_rejects_lightweight_tag_when_origin_holds_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, sha = a_repo_with_origin(tmp_path)
    git(repo, "tag", "v0.21.0")
    git(repo, "push", "-q", "origin", "v0.21.0")

    found = run(repo, monkeypatch, capsys, sha=sha)

    assert (found["ok"], found["found"], found["annotated"]) == (False, True, False)


def test_reports_unreachable_when_ls_remote_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, sha = a_repo_with_origin(tmp_path)
    git(repo, "remote", "set-url", "origin", str(tmp_path / "missing.git"))

    found = run(repo, monkeypatch, capsys, sha=sha)

    assert (found["ok"], found["found"]) == (False, False)
    assert found["reason"].startswith("git ls-remote failed: ")


@pytest.mark.parametrize(
    ("version", "sha"), [("0.21", SHA), ("v0.21.0", SHA), ("0.21.0", "abc"), ("0.21.0", "G" * 40)]
)
def test_exits_two_when_version_or_sha_malformed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, version: str, sha: str
) -> None:
    monkeypatch.chdir(tmp_path)

    assert load().main(["--version", version, "--sha", sha]) == 2
