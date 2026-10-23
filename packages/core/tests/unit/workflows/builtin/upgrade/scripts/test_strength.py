"""The upgrade pack's ``strength.py`` (AGH-484), in process in a temporary git repo: the files the
adapt commits touched, a lockfile edit, and test strength on their lines (a fake ``npx``)."""

import importlib.util
import json
import os
import subprocess
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(
    str(files("agent_hub.core").joinpath("workflows/builtin/upgrade/scripts/strength.py"))
)

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.upgrade.scripts.strength"
WEB_PACKAGE = {"name": "web", "devDependencies": {"@stryker-mutator/core": "8.7.1"}}
SOURCE = "export const a = 1;\nexport const b = 2;\nexport const c = 3;\n"


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


def git(root: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603 - git with fixed arguments, in a temporary repo
        ["git", *args],  # noqa: S607 - git from PATH
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def write(root: Path, written: dict[str, str]) -> None:
    for name, text in written.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")


def commit(root: Path, written: dict[str, str], message: str) -> str:
    write(root, written)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)
    return git(root, "rev-parse", "HEAD").strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repo whose last commit is the bump; the cwd. ``PATH`` starts with ``tmp_path/bin``."""
    root = tmp_path / "repo"
    root.mkdir()
    for key, value in {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Jo",
        "GIT_AUTHOR_EMAIL": "jo@example.com",
        "GIT_COMMITTER_NAME": "Jo",
        "GIT_COMMITTER_EMAIL": "jo@example.com",
        "RECORD": str(tmp_path / "record.txt"),
        "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
    }.items():
        monkeypatch.setenv(key, value)
    git(root, "init", "-q", "-b", "main")
    commit(
        root,
        {
            "pyproject.toml": '[project]\nname = "demo"\n',
            "uv.lock": "version = 1\n",
            "src/a.py": "A = 1\n",
            "web/package.json": json.dumps({"name": "web"}),
            "web/src/x.ts": SOURCE,
        },
        "chore(deps): bump httpx from 0.28.1 to 1.0.0 (DEM-1)",
    )
    monkeypatch.chdir(root)
    return root


def bump_commit(root: Path) -> str:
    return git(root, "rev-parse", "HEAD").strip()


def strength(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, object]:
    assert load().main(list(args)) == 0
    found: dict[str, object] = json.loads(capsys.readouterr().out)
    return found


def fake_npx(root: Path, body: str) -> None:
    bin_dir = root.parent / "bin"
    bin_dir.mkdir(exist_ok=True)
    tool = bin_dir / "npx"
    tool.write_text(f'#!/bin/sh\necho "$(pwd)|$*" >> "$RECORD"\n{body}\n', encoding="utf-8")
    tool.chmod(0o755)


def report(*mutants: tuple[int, str]) -> str:
    entries = [
        {
            "id": str(n),
            "mutatorName": "ArithmeticOperator",
            "replacement": "-",
            "status": status,
            "location": {"start": {"line": line, "column": 1}, "end": {"line": line, "column": 9}},
        }
        for n, (line, status) in enumerate(mutants)
    ]
    return json.dumps({"schemaVersion": "1", "files": {"src/x.ts": {"mutants": entries}}})


def test_counts_touched_files_when_adapt_commits_follow_the_bump(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = bump_commit(repo)
    commit(repo, {"src/a.py": "A = 2\n", "tests/test_a.py": "def test(): ...\n"}, "fix: a")
    commit(repo, {"web/src/x.ts": SOURCE.replace("2", "4")}, "fix: x")

    found = strength(capsys, "--base", base, "--budget", "600")

    assert found["touched"] == 3
    assert found["files"] == ["src/a.py", "tests/test_a.py", "web/src/x.ts"]
    assert found["lockfiles_edited"] == []


def test_reports_zero_touched_and_not_run_when_no_commits_follow_the_bump(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    found = strength(capsys, "--base", bump_commit(repo), "--budget", "600")

    assert found == {
        "touched": 0,
        "files": [],
        "lockfiles_edited": [],
        "lockfile_edit": False,
        "ran": False,
        "tool": "",
        "reason": "no commit after the bump",
        "mutants": 0,
        "killed": 0,
        "inconclusive": 0,
        "survived": [],
        "more_survived": 0,
    }


def test_lists_lockfile_edited_when_adapt_commits_touch_uv_lock(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = bump_commit(repo)
    commit(repo, {"uv.lock": "version = 2\n", "web/package.json": "{}", "src/a.py": "A = 3\n"}, "x")

    found = strength(capsys, "--base", base, "--budget", "600")

    assert found["lockfiles_edited"] == ["uv.lock", "web/package.json"]
    assert found["lockfile_edit"] is True
    assert found["touched"] == 3


def test_reports_not_run_when_no_mutation_tool(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = bump_commit(repo)
    commit(repo, {"src/a.py": "A = 2\n"}, "fix: a")

    found = strength(capsys, "--base", base, "--budget", "600")

    assert (found["ran"], found["tool"]) == (False, "")
    assert found["reason"] == "no mutation tool found in the repo"


def test_reports_not_run_when_only_tests_changed(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = bump_commit(repo)
    commit(repo, {"tests/test_a.py": "x\n", "web/src/x.test.ts": "x\n"}, "test: a")

    found = strength(capsys, "--base", base, "--budget", "600")

    assert (found["touched"], found["ran"]) == (2, False)
    assert found["reason"] == "no source line changed after the bump (tests only)"


@pytest.mark.parametrize("tool", ["mutmut", "cosmic-ray"])
def test_names_python_tool_as_not_run_when_repo_uses_mutmut(
    repo: Path, capsys: pytest.CaptureFixture[str], *, tool: str
) -> None:
    write(
        repo,
        {
            "pyproject.toml": (
                f'[project]\nname = "demo"\n\n[dependency-groups]\ndev = ["{tool}>=3"]\n'
            )
        },
    )
    git(repo, "commit", "-qam", "dev tool")
    base = bump_commit(repo)
    commit(repo, {"src/a.py": "A = 2\n"}, "fix: a")

    found = strength(capsys, "--base", base, "--budget", "600")

    assert (found["ran"], found["tool"]) == (False, tool)
    assert found["reason"] == (
        f"{tool} needs a per-repo setup this run does not make: run /test-strength on the PR"
    )


def test_lists_survivors_on_changed_lines_when_stryker_runs(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo, {"web/package.json": json.dumps(WEB_PACKAGE)})
    git(repo, "commit", "-qam", "stryker")
    base = bump_commit(repo)
    commit(repo, {"web/src/x.ts": SOURCE.replace("2", "4").replace("3", "5")}, "fix: x")
    mutants = report(
        (2, "Killed"),
        (3, "Survived"),
        (3, "NoCoverage"),
        (2, "Timeout"),
        (3, "RuntimeError"),
        (9, "Survived"),
    )
    fake_npx(
        repo,
        "mkdir -p reports/mutation"
        f" && cat > reports/mutation/mutation.json <<'EOF'\n{mutants}\nEOF",
    )

    found = strength(capsys, "--base", base, "--budget", "600")

    record = Path(os.environ["RECORD"]).read_text(encoding="utf-8").splitlines()
    assert record == [
        f"{repo / 'web'}|--no-install stryker run --mutate src/x.ts:2-3"
        " --coverageAnalysis perTest --reporters json"
    ]
    assert (found["ran"], found["tool"], found["reason"]) == (True, "stryker", "")
    assert (found["mutants"], found["killed"], found["inconclusive"]) == (5, 2, 1)
    assert found["survived"] == [
        {"path": "web/src/x.ts", "line": 3, "mutator": "ArithmeticOperator", "replacement": "-"},
        {"path": "web/src/x.ts", "line": 3, "mutator": "ArithmeticOperator", "replacement": "-"},
    ]
    assert found["more_survived"] == 0
    assert not (repo / "web/reports").exists()


def test_marks_inconclusive_when_tool_exceeds_budget(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo, {"web/package.json": json.dumps(WEB_PACKAGE)})
    git(repo, "commit", "-qam", "stryker")
    base = bump_commit(repo)
    commit(repo, {"web/src/x.ts": SOURCE.replace("2", "4")}, "fix: x")
    fake_npx(repo, "sleep 30 & wait")

    found = strength(capsys, "--base", base, "--budget", "1")

    assert (found["ran"], found["tool"]) == (False, "stryker")
    assert found["reason"] == "inconclusive: stryker ran past its 1 s budget in web"


def test_exits_one_when_tool_leaves_a_tracked_change(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo, {"web/package.json": json.dumps(WEB_PACKAGE)})
    git(repo, "commit", "-qam", "stryker")
    base = bump_commit(repo)
    commit(repo, {"web/src/x.ts": SOURCE.replace("2", "4")}, "fix: x")
    fake_npx(repo, "echo mutated >> src/x.ts")

    assert load().main(["--base", base, "--budget", "600"]) == 1

    assert capsys.readouterr().err == "strength.py: the tool left web/src/x.ts changed\n"


@pytest.mark.parametrize(
    "argv",
    [
        ["--base", "HEAD", "--budget", "600"],
        ["--base", "0a1b2c3d", "--budget", "0"],
        ["--base", "0a1b2c3d", "--budget", "x"],
        ["--base", "0a1b2c3d", "--budget", "3601"],
    ],
)
def test_exits_two_when_the_arguments_are_bad(
    capsys: pytest.CaptureFixture[str], *, argv: list[str]
) -> None:
    assert load().main(argv) == 2

    assert capsys.readouterr().out == ""


def test_runs_stryker_in_each_folder_and_names_what_it_did_not_measure_when_diff_spans_folders(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(
        repo,
        {
            "web/package.json": json.dumps(WEB_PACKAGE),
            "app/package.json": json.dumps(WEB_PACKAGE),
            "app/src/x.ts": SOURCE,
            "lib/package.json": json.dumps({"name": "lib"}),
            "lib/y.ts": SOURCE,
        },
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "folders")
    base = bump_commit(repo)
    changed_source = SOURCE.replace("3", "5")
    commit(
        repo,
        {
            "web/src/x.ts": changed_source,
            "app/src/x.ts": changed_source,
            "lib/y.ts": changed_source,
            "src/a.py": "A = 2\n",
        },
        "fix: all",
    )
    mutants = report((3, "Survived"), (3, "Killed"))
    fake_npx(
        repo,
        "mkdir -p reports/mutation"
        f" && cat > reports/mutation/mutation.json <<'EOF'\n{mutants}\nEOF",
    )

    found = strength(capsys, "--base", base, "--budget", "600")

    calls = Path(os.environ["RECORD"]).read_text(encoding="utf-8").splitlines()
    assert [line.split("|")[0] for line in calls] == [str(repo / "app"), str(repo / "web")]
    assert (found["ran"], found["mutants"], found["killed"]) == (True, 4, 2)
    assert [item["path"] for item in found["survived"]] == ["app/src/x.ts", "web/src/x.ts"]  # type: ignore[union-attr]
    assert found["reason"] == "not measured: lib/y.ts, src/a.py"


def test_reports_not_run_and_drops_the_old_report_when_stryker_fails(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo, {"web/package.json": json.dumps(WEB_PACKAGE)})
    git(repo, "commit", "-qam", "stryker")
    base = bump_commit(repo)
    commit(repo, {"web/src/x.ts": SOURCE.replace("2", "4")}, "fix: x")
    # A report from a run by hand, still in the kept worktree.
    write(repo, {"web/reports/mutation/mutation.json": report((2, "Survived"))})
    fake_npx(repo, "exit 1")

    found = strength(capsys, "--base", base, "--budget", "600")

    assert (found["ran"], found["tool"], found["survived"]) == (False, "stryker", [])
    assert found["reason"] == "stryker exited 1 in web without a report"
    assert not (repo / "web/reports/mutation/mutation.json").exists()
