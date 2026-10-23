"""The flaky pack's ``repeat.py``, in process: the inputs it refuses, the throwaway worktree it
always removes, and the test run alone, in its file's order, shuffled and in parallel, counted.
"""

import importlib.util
import json
import shutil
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(str(files("agent_hub.core").joinpath("workflows/builtin/flaky/scripts/repeat.py")))

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.flaky.scripts.repeat"

# The conftest's ``workspace``: a hub and its git repo ``demo-api``.
type Workspace = Any

NO_PLUGINS = {"xdist": False, "pytest_randomly": False, "random_order": False}


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(MODULE, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before it runs: its dataclasses look their module up (string annotations).
    sys.modules[MODULE] = module
    # No __pycache__ beside the pack's files: the pack is seeded into hubs file by file.
    writes, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = writes
    return module


class Repeat:
    """``repeat.py`` run in the workspace's hub, its runner this interpreter (which has pytest
    and pytest-xdist); ``calls`` holds each pytest run's argv, after the runner."""

    def __init__(
        self,
        workspace: Workspace,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        self.workspace, self.capsys = workspace, capsys
        self.module = load()
        self.calls: list[list[str]] = []
        monkeypatch.chdir(workspace.hub)
        monkeypatch.setattr(self.module, "runner", lambda path: [sys.executable])
        original = self.module.run_once

        def recorded(argv: list[str], **kwargs: Any) -> Any:
            self.calls.append(argv[1:])
            return original(argv, **kwargs)

        monkeypatch.setattr(self.module, "run_once", recorded)
        self.monkeypatch = monkeypatch

    def plugins(self, found: dict[str, bool]) -> None:
        self.monkeypatch.setattr(self.module, "detect", lambda python, path: dict(found))

    def __call__(self, test: str, *args: str, runs: str = "1", config: str = "") -> Any:
        argv = ["--repo", "demo-api", "--test", test, "--runs", runs]
        argv += ["--config", config or self.workspace.config, *args]
        code = self.module.main(argv)
        captured = self.capsys.readouterr()
        return code, json.loads(captured.out) if code == 0 else None, captured.err


@pytest.fixture
def repeat(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> Repeat:
    return Repeat(workspace, monkeypatch, capsys)


def mode(found: Any, name: str) -> Any:
    (only,) = [item for item in found["modes"] if item["mode"] == name]
    return only


def counts(found: Any, name: str) -> dict[str, int]:
    keys = ("passed", "failed", "errors", "timed_out", "missing", "not_run")
    return {key: mode(found, name)[key] for key in keys}


def ran(passed: int = 0, **others: int) -> dict[str, int]:
    keys = ("failed", "errors", "timed_out", "missing", "not_run")
    return {"passed": passed} | {key: others.get(key, 0) for key in keys}


@pytest.mark.parametrize(
    ("test", "reason"),
    [
        ("-p.py::test_y", "starts with - or @"),
        ("@args.py::test_y", "starts with - or @"),
        ("tests/../tests/test_x.py::test_y", "holds a .. segment"),
        ("/etc/test_x.py::test_y", "is absolute"),
        ("tests/test_x.py::test_y\n", "holds a control character"),
        ("tests/test_x.py::test_\x1by", "holds a control character"),
        ("tests/" + "a" * 520 + ".py::test_y", "is over 512 characters"),
        ("tests/test_x.py", "has no ::"),
        ("tests/test_x.txt::test_y", "is not a pytest node id"),
        ("tests/test_x.py::test y", "is not a pytest node id"),
        ("tests/test_none.py::test_y", "names no file of the repo"),
        ("tests/link_test.py::test_y", "names no file of the repo"),
    ],
)
def test_rejects_test_id_when_unsafe(
    repeat: Repeat, workspace: Workspace, *, test: str, reason: str
) -> None:
    # A link that leaves the worktree, committed as such: the file check resolves it.
    outside = workspace.repo.parent / "outside.py"
    outside.write_text("def test_y():\n    pass\n", encoding="utf-8")
    (workspace.repo / "tests/link_test.py").symlink_to("../../outside.py")
    workspace.git("add", "-A")
    workspace.git("commit", "-q", "-m", "test: a link")
    workspace.git("update-ref", "refs/remotes/origin/main", "HEAD")
    before = workspace.state()

    code, _, err = repeat(test)

    assert code == 2
    assert err.startswith("repeat.py: ")
    assert reason in err
    assert repeat.calls == []
    assert workspace.state() == before


def test_rejects_test_when_it_collects_nothing(repeat: Repeat, workspace: Workspace) -> None:
    before = workspace.state()

    code, _, err = repeat("tests/test_x.py::test_none")

    assert code == 2
    assert "repeat.py: " in err
    assert "collects 0 tests, not 1" in err
    assert repeat.calls == []
    assert workspace.state() == before


@pytest.mark.parametrize("runs", ["0", "201", "-1", "two", "1.5", ""])
def test_rejects_runs_when_out_of_range(repeat: Repeat, runs: str) -> None:
    code, _, err = repeat("tests/test_x.py::test_ok", runs=runs)

    assert code == 2
    assert "--runs is not a count from 1 to 200" in err
    assert repeat.calls == []


def test_rejects_repo_when_not_in_config(repeat: Repeat) -> None:
    config = json.dumps({"repos": [{"dir": "other", "default_branch": "main"}]})

    code, _, err = repeat("tests/test_x.py::test_ok", config=config)

    assert code == 2
    assert "'demo-api' is not a repo of the config" in err


@pytest.mark.parametrize(
    ("config", "reason"),
    [
        ("{not json", "--config is not JSON"),
        ("[]", "--config has no repos list"),
        ('{"repos": {}}', "--config has no repos list"),
        (json.dumps({"repos": [], "pad": "x" * 70_000}), "--config is over 64 KiB"),
    ],
)
def test_rejects_config_when_not_json(repeat: Repeat, config: str, reason: str) -> None:
    code, _, err = repeat("tests/test_x.py::test_ok", config=config)

    assert code == 2
    assert reason in err


@pytest.mark.parametrize(
    "argv",
    [
        ["--repo", "demo-api"],
        ["--repo", "demo-api", "--test", "t.py::t", "--runs", "1", "--config", "{}", "--x", "1"],
        ["--repo", "demo-api", "--test", "t.py::t", "--runs", "1", "--config"],
    ],
)
def test_prints_usage_when_options_are_wrong(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert load().main(argv) == 2
    assert "usage: repeat.py" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("option", "value"),
    [("--run-timeout", "0"), ("--run-timeout", "nan"), ("--budget", "-1"), ("--budget", "x")],
)
def test_rejects_limits_when_not_positive_seconds(repeat: Repeat, option: str, value: str) -> None:
    code, _, err = repeat("tests/test_x.py::test_ok", option, value)

    assert code == 2
    assert f"{option} is not" in err


def test_rejects_repo_when_not_a_git_checkout(repeat: Repeat, workspace: Workspace) -> None:
    shutil.rmtree(workspace.repo / ".git")

    code, _, err = repeat("tests/test_x.py::test_ok")

    assert code == 2
    assert "is not a git checkout" in err


def test_exits_one_when_base_cannot_be_checked_out(repeat: Repeat, workspace: Workspace) -> None:
    workspace.git("update-ref", "-d", "refs/remotes/origin/main")
    before = workspace.state()

    code, _, err = repeat("tests/test_x.py::test_ok")

    assert code == 1
    assert "repeat.py: cannot check out origin/main" in err
    assert repeat.calls == []
    assert workspace.state() == before


def test_exits_one_when_runner_cannot_start(
    repeat: Repeat, workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(repeat.module, "runner", lambda path: [str(workspace.hub / "no-python")])
    before = workspace.state()

    code, _, err = repeat("tests/test_x.py::test_ok")

    assert code == 1
    assert "repeat.py: cannot run" in err
    assert workspace.state() == before


def worktree_folders(tmp: Path) -> list[Path]:
    return sorted(tmp.glob("flaky-*"))


def boom(*args: Any, **kwargs: Any) -> Any:
    raise RuntimeError("mid-run")


@pytest.mark.parametrize(
    ("case", "test", "args"),
    [
        ("pass", "tests/test_x.py::test_ok", ()),
        ("fail", "tests/test_x.py::test_y", ()),
        ("run timeout", "slow/test_slow.py::test_slow", ("--run-timeout", "1")),
        ("budget spent", "tests/test_x.py::test_ok", ("--budget", "0")),
        ("exception", "tests/test_x.py::test_ok", ()),
    ],
)
def test_removes_worktree_when_run_ends(
    repeat: Repeat,
    workspace: Workspace,
    monkeypatch: pytest.MonkeyPatch,
    *,
    tmp_path: Path,
    case: str,
    test: str,
    args: tuple[str, ...],
) -> None:
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(repeat.module.tempfile, "tempdir", str(temp))
    repeat.plugins(NO_PLUGINS)
    if case == "exception":
        monkeypatch.setattr(repeat.module, "run_once", boom)
    before = workspace.state()

    if case == "exception":
        with pytest.raises(RuntimeError, match="mid-run"):
            repeat(test, *args)
    else:
        code, found, err = repeat(test, *args)
        assert code == 0, err
        expected = {
            "pass": ran(passed=1),
            "fail": ran(failed=1),
            "run timeout": ran(timed_out=1),
            "budget spent": ran(not_run=1),
        }[case]
        assert counts(found, "alone" if case != "fail" else "suite") == expected
        assert found["budget_spent"] is (case == "budget spent")

    assert workspace.state() == before
    assert worktree_folders(temp) == []


def test_prunes_stale_entry_when_starting(repeat: Repeat, workspace: Workspace) -> None:
    before = workspace.state()
    # A run killed before its cleanup leaves a worktree entry whose folder is gone.
    lost = workspace.repo.parent / "flaky-lost"
    workspace.git("worktree", "add", "--detach", "--quiet", str(lost), "HEAD")
    shutil.rmtree(lost)
    repeat.plugins(NO_PLUGINS)

    code, _, err = repeat("tests/test_x.py::test_ok")

    assert code == 0, err
    assert workspace.state() == before


def test_skips_mode_when_plugin_missing(repeat: Repeat) -> None:
    repeat.plugins(NO_PLUGINS)

    code, found, err = repeat("tests/test_x.py::test_ok", runs="2")

    assert code == 0, err
    assert [item["mode"] for item in found["modes"]] == ["alone", "suite", "shuffled", "parallel"]
    assert mode(found, "shuffled")["status"] == "unavailable"
    assert "pytest-randomly" in mode(found, "shuffled")["note"]
    assert "pytest-random-order" in mode(found, "shuffled")["note"]
    assert mode(found, "parallel")["status"] == "unavailable"
    assert "pytest-xdist" in mode(found, "parallel")["note"]
    assert counts(found, "shuffled") == ran() == counts(found, "parallel")
    assert counts(found, "alone") == ran(passed=2) == counts(found, "suite")
    # No pytest call for a mode whose plugin is missing.
    assert len(repeat.calls) == 4
    assert not any("-n" in call or "--randomly-seed=1001" in call for call in repeat.calls)
    assert found["reproduced"] is False


def test_reproduces_order_dependence_when_suite_fails(repeat: Repeat, workspace: Workspace) -> None:
    repeat.plugins(NO_PLUGINS)
    sha = workspace.git("rev-parse", "HEAD")

    code, found, err = repeat("tests/test_x.py::test_y", runs="2")

    assert code == 0, err
    assert counts(found, "alone") == ran(passed=2)
    assert counts(found, "suite") == ran(failed=2)
    assert found["reproduced"] is True
    assert (found["test"], found["repo"], found["sha"]) == (
        "tests/test_x.py::test_y",
        "demo-api",
        sha,
    )
    assert found["repo_path"] == str(workspace.repo.resolve())
    assert found["runner"] == [sys.executable]
    assert found["runs"] == 2
    assert found["budget_spent"] is False
    tails = mode(found, "suite")["tails"]
    assert len(tails) == 2
    assert tails[0].startswith("run 1: ")
    assert "assert not [1]" in tails[0]
    assert mode(found, "alone")["tails"] == []
    assert repeat.calls[0][-1] == "tests/test_x.py::test_y"
    assert repeat.calls[1][-1] == "tests/test_x.py"


def test_runs_folder_under_xdist_when_parallel(repeat: Repeat) -> None:
    code, found, err = repeat("tests/test_x.py::test_ok")

    assert code == 0, err
    assert mode(found, "parallel")["status"] == "ran"
    assert "tests" in mode(found, "parallel")["note"]
    (parallel,) = [call for call in repeat.calls if "-n" in call]
    assert parallel[parallel.index("-n") :] == ["-n", "auto", "tests"]
    assert counts(found, "parallel") == ran(passed=1)
    # This interpreter has no shuffle plugin: shuffled is skipped, the other three run.
    assert mode(found, "shuffled")["status"] == "unavailable"
    assert len(repeat.calls) == 3


def test_counts_parallel_failures_when_only_parallel_fails(repeat: Repeat) -> None:
    repeat.plugins({"xdist": True, "pytest_randomly": False, "random_order": False})

    code, found, err = repeat("tests/test_x.py::test_p")

    assert code == 0, err
    assert counts(found, "alone") == ran(passed=1) == counts(found, "suite")
    assert counts(found, "parallel") == ran(failed=1)
    assert found["reproduced"] is True


def test_reports_not_reproduced_when_every_mode_passes(repeat: Repeat) -> None:
    repeat.plugins({"xdist": True, "pytest_randomly": False, "random_order": False})

    code, found, err = repeat("tests/test_x.py::test_ok", runs="2")

    assert code == 0, err
    for name in ("alone", "suite", "parallel"):
        assert counts(found, name) == ran(passed=2), name
        assert mode(found, name)["tails"] == []
    assert found["reproduced"] is False


def test_counts_missing_when_summary_has_no_line(repeat: Repeat) -> None:
    repeat.plugins(NO_PLUGINS)

    code, found, err = repeat("gone/test_gone.py::test_ok")

    assert code == 0, err
    assert counts(found, "alone") == ran(passed=1)
    assert counts(found, "suite") == ran(missing=1)
    assert found["reproduced"] is True


def test_caps_tails_when_output_is_large(repeat: Repeat) -> None:
    repeat.plugins(NO_PLUGINS)

    code, found, err = repeat("loud/test_loud.py::test_loud", runs="4")

    assert code == 0, err
    for name in ("alone", "suite"):
        assert mode(found, name)["failed"] == 4
        tails = mode(found, name)["tails"]
        assert len(tails) == 3
        assert all(len(tail) <= 500 for tail in tails)
    assert len(json.dumps(found).encode()) <= 64 * 1024


@pytest.mark.parametrize(
    ("plugins", "expected"),
    [
        (
            {"xdist": True, "pytest_randomly": True, "random_order": True},
            {
                "alone": ["-p", "no:randomly", "a/b/test_x.py::test_y"],
                "suite": ["-p", "no:randomly", "a/b/test_x.py"],
                "shuffled": ["-p", "randomly", "--randomly-seed=1003", "a/b/test_x.py"],
                "parallel": ["-p", "no:randomly", "-n", "auto", "a/b"],
            },
        ),
        (
            {"xdist": True, "pytest_randomly": False, "random_order": True},
            {
                "alone": ["a/b/test_x.py::test_y"],
                "suite": ["a/b/test_x.py"],
                "shuffled": ["--random-order-seed=1003", "a/b/test_x.py"],
                "parallel": ["-n", "auto", "a/b"],
            },
        ),
    ],
)
def test_builds_argv_when_plugins_installed(
    plugins: dict[str, bool], expected: dict[str, list[str]]
) -> None:
    module = load()

    for name, argv in expected.items():
        assert module.mode_argv(name, plugins, test="a/b/test_x.py::test_y", seed=1003) == argv


def test_runs_whole_repo_when_test_file_is_at_root() -> None:
    plugins = {"xdist": True, "pytest_randomly": False, "random_order": False}

    argv = load().mode_argv("parallel", plugins, test="test_x.py::test_y", seed=1)

    assert argv == ["-n", "auto", "."]


def test_seeds_each_shuffled_tail_when_shuffled_run_fails(repeat: Repeat) -> None:
    repeat.plugins({"xdist": False, "pytest_randomly": True, "random_order": False})

    code, found, err = repeat("tests/test_x.py::test_ok", runs="2")

    # This interpreter has no pytest-randomly: each shuffled run stops before any summary line.
    assert code == 0, err
    assert counts(found, "shuffled") == ran(missing=2)
    tails = mode(found, "shuffled")["tails"]
    assert [tail.split(":", 1)[0] for tail in tails] == ["run 1, seed 1001", "run 2, seed 1002"]
    assert "seeds 1001-1002" in mode(found, "shuffled")["note"]


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        (
            {"uv.lock": "", "pyproject.toml": "[project]\n\n[tool.uv.workspace]\n"},
            ["uv", "run", "--locked", "--all-packages", "python"],
        ),
        ({"uv.lock": "", "pyproject.toml": "[project]\n"}, ["uv", "run", "--locked", "python"]),
        ({"uv.lock": ""}, ["uv", "run", "--locked", "python"]),
        ({".venv/bin/python": ""}, ["<venv>"]),
        ({}, ["python3"]),
    ],
)
def test_derives_runner_when_worktree_holds_its_files(
    tmp_path: Path, files: dict[str, str], expected: list[str]
) -> None:
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8")
    venv = str(tmp_path / ".venv/bin/python")

    assert load().runner(tmp_path) == [venv if item == "<venv>" else item for item in expected]


def test_detects_plugins_when_runner_is_this_interpreter(tmp_path: Path) -> None:
    found = load().detect([sys.executable], tmp_path)

    assert set(found) == {"xdist", "pytest_randomly", "random_order"}
    assert found["xdist"] is True


def test_drops_script_venv_when_running(monkeypatch: pytest.MonkeyPatch) -> None:
    script_bin = str(Path("/venvs/script/bin"))
    monkeypatch.setenv("VIRTUAL_ENV", "/venvs/script")
    monkeypatch.setenv("PATH", f"{script_bin}:/usr/bin")

    env = load().clean_env()

    assert "VIRTUAL_ENV" not in env
    assert env["PATH"] == "/usr/bin"
