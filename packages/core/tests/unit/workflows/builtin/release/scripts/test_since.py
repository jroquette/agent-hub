"""The release pack's ``since.py`` (AGH-494), in process: the PRs since the last tag, the bump."""

import importlib.util
import json
import subprocess
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(str(files("agent_hub.core").joinpath("workflows/builtin/release/scripts/since.py")))

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.release.scripts.since"


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


def git(folder: Path, *args: str) -> str:
    done = subprocess.run(  # noqa: S603 - git from PATH, fixed arguments
        ["git", "-c", "user.name=T", "-c", "user.email=t@example.com", *args],  # noqa: S607
        cwd=folder,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def a_repo(tmp_path: Path, tag: str = "v0.20.1") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "commit", "-q", "--allow-empty", "-m", "chore(repo): release 0.20.1 (AGH-1)")
    if tag:
        git(repo, "tag", "-a", tag, "-m", tag)
    return repo


def merge_pr(repo: Path, number: int, title: str, *, body: str | None = None) -> str:
    """A PR merged as GitHub does: a merge commit whose body is the PR title (or empty)."""
    branch = f"pr-{number}"
    git(repo, "checkout", "-q", "-b", branch)
    git(repo, "commit", "-q", "--allow-empty", "-m", title)
    git(repo, "checkout", "-q", "main")
    message = f"Merge pull request #{number} from acme/{branch}"
    shown = title if body is None else body
    if shown:
        message += f"\n\n{shown}"
    git(repo, "merge", "-q", "--no-ff", "-m", message, branch)
    return git(repo, "rev-parse", "HEAD")


def run(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    version: str = "",
) -> dict[str, Any]:
    monkeypatch.chdir(repo)
    assert load().main(["--version", version]) == 0
    found: dict[str, Any] = json.loads(capsys.readouterr().out)
    return found


def test_proposes_minor_when_a_feat_merged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = a_repo(tmp_path)
    feat = merge_pr(repo, 10, "feat(core): release pack (AGH-494)")
    merge_pr(repo, 11, "fix(cli): exit code (AGH-495)")

    found = run(repo, monkeypatch, capsys)

    assert found["last_tag"] == "v0.20.1"
    assert found["previous"] == "0.20.1"
    assert found["version"] == "0.21.0"
    assert found["bump"] == "minor"
    assert "#10" in found["reason"]
    assert found["count"] == 2
    assert found["prs"][0] == {
        "number": 10,
        "title": "feat(core): release pack (AGH-494)",
        "type": "feat",
        "breaking": False,
        "sha": feat,
    }
    assert [pr["type"] for pr in found["prs"]] == ["feat", "fix"]
    assert "#11 fix(cli): exit code (AGH-495)" in found["text"]
    assert found["omitted"] == 0


@pytest.mark.parametrize(
    "title", ["feat(core)!: drop the old flag (AGH-7)", "fix(cli): BREAKING CHANGE flags (AGH-7)"]
)
def test_proposes_major_when_title_has_bang_or_breaking_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    title: str,
) -> None:
    repo = a_repo(tmp_path)
    merge_pr(repo, 10, "feat(core): something (AGH-6)")
    merge_pr(repo, 11, title)

    found = run(repo, monkeypatch, capsys)

    assert (found["bump"], found["version"]) == ("major", "1.0.0")
    assert "#11" in found["reason"]
    assert found["prs"][1]["breaking"] is True


@pytest.mark.parametrize(
    "titles", [["fix(cli): one (AGH-2)", "chore(repo): two (AGH-3)"], ["docs(repo): three (AGH-4)"]]
)
def test_proposes_patch_when_only_fixes_or_chores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    titles: list[str],
) -> None:
    repo = a_repo(tmp_path)
    for number, title in enumerate(titles, start=20):
        merge_pr(repo, number, title)

    found = run(repo, monkeypatch, capsys)

    assert (found["bump"], found["version"]) == ("patch", "0.20.2")


def test_reads_title_from_branch_tip_when_merge_body_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = a_repo(tmp_path)
    merge_pr(repo, 244, "feat(web): a page (AGH-9)", body="")

    found = run(repo, monkeypatch, capsys)

    assert found["prs"][0]["title"] == "feat(web): a page (AGH-9)"
    assert found["prs"][0]["number"] == 244
    assert found["bump"] == "minor"


def test_reads_number_from_subject_when_commit_squashed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = a_repo(tmp_path)
    git(repo, "commit", "-q", "--allow-empty", "-m", "fix(cli): squashed (AGH-5) (#30)")

    found = run(repo, monkeypatch, capsys)

    assert found["prs"][0]["number"] == 30
    assert found["prs"][0]["type"] == "fix"


def test_keeps_given_version_when_greater_than_last_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = a_repo(tmp_path)
    merge_pr(repo, 10, "fix(cli): one (AGH-2)")

    found = run(repo, monkeypatch, capsys, version="0.22.0")

    assert found["version"] == "0.22.0"
    assert found["bump"] == "minor"
    assert "0.22.0" in found["reason"]


@pytest.mark.parametrize("version", ["0.20.1", "0.20.0", "v0.21.0", "0.21", "０.21.0"])
def test_exits_two_when_version_not_greater_than_last_tag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    version: str,
) -> None:
    repo = a_repo(tmp_path)
    merge_pr(repo, 10, "fix(cli): one (AGH-2)")
    monkeypatch.chdir(repo)

    assert load().main(["--version", version]) == 2
    assert capsys.readouterr().err.startswith("since.py: ")


def test_reports_none_when_no_merge_since_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = a_repo(tmp_path)

    found = run(repo, monkeypatch, capsys)

    assert (found["bump"], found["count"], found["prs"]) == ("none", 0, [])
    assert found["version"] == "0.20.1"


def test_takes_highest_tag_when_several_reachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = a_repo(tmp_path, tag="v0.9.0")
    merge_pr(repo, 10, "fix(cli): one (AGH-2)")
    git(repo, "tag", "-a", "v0.10.0", "-m", "v0.10.0")
    git(repo, "tag", "-a", "not-a-release", "-m", "x")
    merge_pr(repo, 11, "fix(cli): two (AGH-3)")

    found = run(repo, monkeypatch, capsys)

    assert (found["last_tag"], found["version"], found["count"]) == ("v0.10.0", "0.10.1", 1)


def test_exits_two_when_no_release_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(a_repo(tmp_path, tag=""))

    assert load().main(["--version", ""]) == 2
    assert "no v" in capsys.readouterr().err


def test_exits_two_when_more_than_five_hundred_merges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = load()
    assert module.MAX_COMMITS == 500
    repo = a_repo(tmp_path)
    for number in range(4):
        merge_pr(repo, number + 1, f"fix(cli): {number} (AGH-2)")
    monkeypatch.setattr(module, "MAX_COMMITS", 3)
    monkeypatch.chdir(repo)

    assert module.main(["--version", ""]) == 2
    assert "cut a release sooner or pass version" in capsys.readouterr().err


def test_cuts_titles_when_text_over_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = load()
    assert module.TEXT_BUDGET == 32 * 1024
    repo = a_repo(tmp_path)
    merge_pr(repo, 1, "fix(cli): " + "x" * 300 + "\x1b[31m")
    for number in range(2, 6):
        merge_pr(repo, number, f"fix(cli): short {number} (AGH-2)")
    monkeypatch.setattr(module, "TEXT_BUDGET", 300)
    monkeypatch.chdir(repo)

    assert module.main(["--version", ""]) == 0
    found = json.loads(capsys.readouterr().out)

    assert len(found["prs"][0]["title"]) == module.MAX_TITLE == 200
    assert "\x1b" not in found["prs"][0]["title"]
    assert len(found["text"].encode()) <= 300
    assert found["omitted"] > 0
    assert found["text"].count("\n") + 1 + found["omitted"] == found["count"] == 5


def test_exits_one_when_git_log_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))

    assert load().main(["--version", ""]) == 1
    assert "failed" in capsys.readouterr().err
