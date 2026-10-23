"""The release pack's ``bump.py`` (AGH-494), in process: the release commit's edits and commit."""

import importlib.util
import json
import subprocess
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(str(files("agent_hub.core").joinpath("workflows/builtin/release/scripts/bump.py")))

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.release.scripts.bump"
# The repo's own README: its version strings are what a release replaces.
REPO_ROOT = Path(__file__).resolve().parents[8]


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


URL = "https://github.com/acme/platform"
CHANGELOG = f"""# Changelog

Intro.

## [Unreleased]

### Added

- The release pack (AGH-494).

## [0.20.1] - 2026-10-22

### Fixed

- Something.

[Unreleased]: {URL}/compare/v0.20.1...HEAD
[0.20.1]: {URL}/compare/v0.20.0...v0.20.1
"""
LOCK = """[[package]]
name = "agent-hub"
version = "0.20.1"
source = { editable = "packages/agent-hub" }

[[package]]
name = "agent-hub-cli"
version = "0.20.1"
source = { editable = "packages/cli" }

[[package]]
name = "agent-hub-core"
version = "0.1.0"
source = { editable = "packages/core" }
"""
README = """<img alt="Version 0.20.1" src="https://img.shields.io/badge/version-0.20.1-blue">
uvx --from 'git+https://github.com/acme/platform@v0.20.1#subdirectory=packages/agent-hub' hub
You should see `0.20.1`. Not 0.20.10, 10.20.1 or 0.20.1.5.
"""
SPEC = """| 4 · Workflows | x | — |

Status (2026-10-22, latest release v0.20.1; per-release changes in CHANGELOG.md): Phase 0 done.
and v0.20.1 the third playground delivery.
"""


def pyproject(name: str) -> str:
    return f'[project]\nname = "{name}"\nversion = "0.20.1"\n\n[tool.x]\nversion = "0.20.1"\n'


def release_files() -> dict[str, str]:
    return {
        "CHANGELOG.md": CHANGELOG,
        "README.md": README,
        "docs/SPEC.md": SPEC,
        "packages/cli/pyproject.toml": pyproject("agent-hub-cli"),
        "packages/agent-hub/pyproject.toml": pyproject("agent-hub"),
        "uv.lock": LOCK,
    }


def edited(files: dict[str, str] | None = None) -> dict[str, str]:
    found: dict[str, str] = load().edits(
        release_files() if files is None else files,
        version="0.21.0",
        previous="0.20.1",
        last_tag="v0.20.1",
        today="2026-10-30",
    )
    return found


def git(folder: Path, *args: str) -> str:
    done = subprocess.run(  # noqa: S603 - git from PATH, fixed arguments
        ["git", "-c", "user.name=T", "-c", "user.email=t@example.com", *args],  # noqa: S607
        cwd=folder,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


CHECK_RELEASE = """import sys
from pathlib import Path
cli = Path("packages/cli/pyproject.toml").read_text()
meta = Path("packages/agent-hub/pyproject.toml").read_text()
same = cli.split("\\n")[2] == meta.split("\\n")[2]
print("version lockstep ok" if same else "version lockstep: differ")
sys.exit(0 if same else 1)
"""


def a_repo(tmp_path: Path, files: dict[str, str] | None = None) -> Path:
    repo = tmp_path / "repo"
    for name, text in (release_files() if files is None else files).items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding="utf-8")
    (repo / "scripts").mkdir(exist_ok=True)
    (repo / "scripts/check_release.py").write_text(CHECK_RELEASE)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "T")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "base")
    return repo


def args(regenerate: str = "true") -> list[str]:
    return [
        "--version",
        "0.21.0",
        "--previous",
        "0.20.1",
        "--last-tag",
        "v0.20.1",
        "--issue",
        "AGH-9",
        "--regenerate",
        regenerate,
        "--today",
        "2026-10-30",
    ]


def test_sets_both_versions_when_bumped() -> None:
    found = edited()

    for name in ("packages/cli/pyproject.toml", "packages/agent-hub/pyproject.toml"):
        assert found[name].startswith('[project]\nname = "agent-hub')
        assert '\nversion = "0.21.0"\n\n[tool.x]\nversion = "0.20.1"\n' in found[name]
    assert 'name = "agent-hub"\nversion = "0.21.0"' in found["uv.lock"]
    assert 'name = "agent-hub-cli"\nversion = "0.21.0"' in found["uv.lock"]
    assert 'name = "agent-hub-core"\nversion = "0.1.0"' in found["uv.lock"]


def test_opens_new_unreleased_when_changelog_bumped() -> None:
    module = load()
    found = edited()["CHANGELOG.md"]

    assert "## [Unreleased]\n\n## [0.21.0] - 2026-10-30\n\n### Added\n" in found
    assert f"[Unreleased]: {URL}/compare/v0.21.0...HEAD\n" in found
    assert f"[0.21.0]: {URL}/compare/v0.20.1...v0.21.0\n[0.20.1]:" in found
    assert module.section(found, "0.21.0") == "### Added\n\n- The release pack (AGH-494)."


def test_flags_empty_changelog_when_unreleased_has_no_entry() -> None:
    files = release_files()
    files["CHANGELOG.md"] = CHANGELOG.replace("### Added\n\n- The release pack (AGH-494).\n\n", "")
    found = edited(files)["CHANGELOG.md"]

    assert load().section(found, "0.21.0") == ""


def test_replaces_whole_version_tokens_when_readme_bumped() -> None:
    module = load()
    found, count = module.replace_tokens(README, "0.20.1", "0.21.0")

    assert count == 4
    assert "Not 0.20.10, 10.20.1 or 0.20.1.5." in found
    assert "@v0.21.0#" in found
    assert "version-0.21.0-blue" in found


def test_counts_seven_tokens_when_repo_readme_bumped() -> None:
    """Six lines, the badge's line holding two (its alt text and its URL), as the 0.20.1 PR."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    pyproject_text = (REPO_ROOT / "packages/cli/pyproject.toml").read_text(encoding="utf-8")
    current = pyproject_text.split('version = "', 1)[1].split('"', 1)[0]

    found, count = load().replace_tokens(readme, current, "99.0.0")

    assert count == 7
    assert len([line for line in found.splitlines() if "99.0.0" in line]) == 6


def test_updates_status_line_when_spec_bumped() -> None:
    found = edited()["docs/SPEC.md"]

    assert "Status (2026-10-30, latest release v0.21.0; per-release" in found
    # The prose phrase is the owner's, in the PR.
    assert "and v0.20.1 the third playground delivery." in found


def test_commits_one_release_commit_when_run_in_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = a_repo(tmp_path)
    before = git(repo, "rev-parse", "HEAD")
    monkeypatch.chdir(repo)

    assert load().main(args()) == 0
    found: dict[str, Any] = json.loads(capsys.readouterr().out)

    assert git(repo, "log", "-1", "--format=%s") == "chore(repo): release 0.21.0 (AGH-9)"
    assert found["sha"] == git(repo, "rev-parse", "HEAD")
    assert len(found["sha"]) == 40
    assert git(repo, "rev-parse", "HEAD^") == before
    assert git(repo, "status", "--porcelain", "--untracked-files=all") == ""
    assert found["files"] == sorted(release_files())
    assert (found["version"], found["previous"]) == ("0.21.0", "0.20.1")
    assert found["changelog"] == "### Added\n\n- The release pack (AGH-494)."
    assert found["changelog_empty"] is False
    assert found["readme_replaced"] == 4
    assert found["lockstep"] == "version lockstep ok"


def test_exits_one_when_regenerate_changes_other_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = a_repo(tmp_path)
    before = git(repo, "rev-parse", "HEAD")
    monkeypatch.chdir(repo)

    assert load().main(args("touch other.txt")) == 1
    assert "other.txt" in capsys.readouterr().err
    assert git(repo, "rev-parse", "HEAD") == before


def test_exits_one_when_regenerate_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(a_repo(tmp_path))

    assert load().main(args("false")) == 1
    assert "false" in capsys.readouterr().err


def test_exits_one_when_worktree_dirty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = a_repo(tmp_path)
    (repo / "stray.txt").write_text("x")
    monkeypatch.chdir(repo)

    assert load().main(args()) == 1
    assert "not clean" in capsys.readouterr().err


def test_exits_two_when_unreleased_heading_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    files = release_files()
    files["CHANGELOG.md"] = CHANGELOG.replace("## [Unreleased]\n", "")
    monkeypatch.chdir(a_repo(tmp_path, files))

    assert load().main(args()) == 2
    assert capsys.readouterr().err.startswith("bump.py: CHANGELOG.md: ")


def test_exits_two_when_lock_entry_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    files = release_files()
    files["uv.lock"] = LOCK.replace('name = "agent-hub-cli"\nversion = "0.20.1"', "")
    monkeypatch.chdir(a_repo(tmp_path, files))

    assert load().main(args()) == 2
    assert capsys.readouterr().err.startswith("bump.py: uv.lock: ")


def test_exits_two_when_file_not_utf8(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = a_repo(tmp_path)
    (repo / "README.md").write_bytes(b"\xff\xfe version 0.20.1")
    git(repo, "commit", "-qam", "binary readme")
    monkeypatch.chdir(repo)

    assert load().main(args()) == 2
    assert capsys.readouterr().err.startswith("bump.py: README.md: ")


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--version", "0.21"),
        ("--previous", "v0.20.1"),
        ("--last-tag", "v0.20.0"),
        ("--issue", "AGH 9"),
        ("--today", "30/10/2026"),
    ],
)
def test_exits_two_when_argument_malformed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, option: str, value: str
) -> None:
    given = args()
    given[given.index(option) + 1] = value
    monkeypatch.chdir(a_repo(tmp_path))

    assert load().main(given) == 2


def test_restores_checkout_when_regenerate_fails_then_reruns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = a_repo(tmp_path)
    before = git(repo, "rev-parse", "HEAD")
    monkeypatch.chdir(repo)

    assert load().main(args("sh -c 'touch stray.txt; exit 3'")) == 1
    capsys.readouterr()
    assert git(repo, "rev-parse", "HEAD") == before
    assert git(repo, "status", "--porcelain", "--untracked-files=all") == ""
    assert (repo / "README.md").read_text() == README
    # The next run of the issue starts from the same clean checkout.
    assert load().main(args()) == 0
    assert json.loads(capsys.readouterr().out)["version"] == "0.21.0"


def test_restores_checkout_when_release_check_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = a_repo(tmp_path)
    (repo / "scripts/check_release.py").write_text("import sys\nsys.exit('lockstep: differ')\n")
    git(repo, "commit", "-qam", "a failing release check")
    before = git(repo, "rev-parse", "HEAD")
    monkeypatch.chdir(repo)

    assert load().main(args()) == 1
    assert "lockstep: differ" in capsys.readouterr().err
    assert git(repo, "rev-parse", "HEAD") == before
    assert git(repo, "status", "--porcelain", "--untracked-files=all") == ""


def test_reuses_release_commit_when_run_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = a_repo(tmp_path)
    monkeypatch.chdir(repo)
    assert load().main(args()) == 0
    first = json.loads(capsys.readouterr().out)

    assert load().main(args()) == 0
    again = json.loads(capsys.readouterr().out)

    assert again == first
    assert git(repo, "rev-list", "--count", "HEAD") == "2"
