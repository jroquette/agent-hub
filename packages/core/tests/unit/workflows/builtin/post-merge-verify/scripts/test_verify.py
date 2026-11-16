"""The post-merge-verify pack's ``verify.py``, in process: which verifications cannot run after a
merge, and each other one run once at the commit in a throwaway worktree, the checkout untouched.
"""

import importlib.util
import io
import json
import shutil
import sys
import time
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(
    str(files("agent_hub.core").joinpath("workflows/builtin/post-merge-verify/scripts/verify.py"))
)

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.post-merge-verify.scripts.verify"

# The conftest's ``workspace``: a hub and its git repo ``demo-api``.
type Workspace = Any


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


def an_ac(ac_id: str, verification: str) -> dict[str, Any]:
    return {
        "id": ac_id,
        "description": "A synthetic acceptance criterion.",
        "repo": "demo-api",
        "verification": verification,
        "passes": True,
        "evidence": "2026-01-02: passed on the branch; 2026-01-05: again.",
    }


def verify(
    workspace: Workspace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *verifications: str,
    sha: str = "",
    argv: tuple[str, ...] = (),
) -> tuple[int, Any, str]:
    """``verify.py`` on one record ``grp/DEM-7`` whose ACs ``AC-7.<n>`` hold ``verifications``."""
    acs = [an_ac(f"AC-7.{n}", text) for n, text in enumerate(verifications, start=1)]
    workspace.record("grp/DEM-7", {"feature": "grp/DEM-7", "acs": acs})
    selection = {
        "mode": "merge",
        "sha": sha or workspace.git("rev-parse", "HEAD"),
        "repo_path": str(workspace.repo),
        "selected": [{"feature": "grp/DEM-7", "ac": ac["id"], "why": "ticket"} for ac in acs],
    }
    monkeypatch.chdir(workspace.hub)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(selection)))
    code = load().main(list(argv))
    captured = capsys.readouterr()
    return code, json.loads(captured.out) if code == 0 else None, captured.err


@pytest.mark.parametrize(
    ("command", "reason"),
    [
        ("cd /home/user/agent-hub && make check", "absolute path"),
        ("PATH=/root/.local/bin:$PATH uv run pytest -q", "absolute path"),
        ('cd "${WT:-/home/user/x}" && cat /home/user/y', "absolute path"),
        ("cd '/srv/app' && true", "absolute path"),
        ("cd .claude/worktrees/dem-1 && true", "worktree path"),
        ("git diff --name-only origin/main...HEAD", "origin diff range"),
        ("x" * 8193, "too long"),
    ],
)
def test_flags_cannot_run_when_verification_is_not_portable(command: str, reason: str) -> None:
    assert load().cannot_run(command) == reason


@pytest.mark.parametrize(
    "command",
    [
        "make check > /dev/null 2>&1",
        "pytest -q > /tmp/x.log; grep -q passed /tmp/x.log",
        "curl -sf https://example.com/a",
        "uv run pytest packages/x -q",
        'cd "${WT:-/home/user/x}" && make check',
        "cd ${WT:-/home/user/agent-hub/.claude/worktrees/dem-1} && uv run pytest -q",
    ],
)
def test_runs_when_paths_are_relative_or_dev_or_tmp(command: str) -> None:
    assert load().cannot_run(command) is None


@pytest.mark.parametrize(
    ("returncode", "timed_out", "status"),
    [(0, False, "passed"), (1, False, "failed"), (None, True, "timeout")],
)
def test_classifies_run_when_it_ends(
    returncode: int | None,
    *,
    timed_out: bool,
    status: str,
) -> None:
    assert load().classify(returncode, timed_out=timed_out) == status


def test_counts_pass_without_entry_when_command_exits_zero(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, found, _ = verify(workspace, monkeypatch, capsys, "test -f README")

    assert code == 0
    assert found["counts"] == {
        "selected": 1,
        "passed": 1,
        "failed": 0,
        "timed_out": 0,
        "errors": 0,
        "cannot_run": 0,
        "not_run": 0,
    }
    assert (found["broken"], found["failures"], found["cannot_run"]) == (0, [], [])


def test_reports_exit_code_when_command_fails(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, found, _ = verify(workspace, monkeypatch, capsys, "echo broken; exit 3")

    assert code == 0
    assert found["broken"] == 1
    assert found["failures"] == [
        {
            "feature": "grp/DEM-7",
            "ac": "AC-7.1",
            "command": "echo broken; exit 3",
            "status": "failed",
            "exit_code": 3,
            "tail": "broken\n",
            "since": "2026-01-02",
        }
    ]


def test_runs_each_command_once_when_it_fails(
    *,
    workspace: Workspace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    counter = tmp_path / "runs"
    monkeypatch.setenv("COUNTER", str(counter))

    code, found, _ = verify(workspace, monkeypatch, capsys, 'echo x >> "$COUNTER"; exit 1')

    assert code == 0
    assert found["counts"]["failed"] == 1
    assert counter.read_text(encoding="utf-8") == "x\n"


def test_sets_wt_to_the_throwaway_worktree_when_a_command_runs(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    command = 'cd "${WT:-/home/user/nowhere}" && test "$PWD" = "$WT" && test -f README'

    code, found, _ = verify(workspace, monkeypatch, capsys, command)

    assert code == 0
    assert found["counts"]["passed"] == 1
    assert found["cannot_run"] == []


def test_reports_timeout_when_command_exceeds_limit(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    started = time.monotonic()

    code, found, _ = verify(
        workspace, monkeypatch, capsys, "sleep 30 & sleep 30", argv=("--timeout", "1")
    )

    assert code == 0
    assert time.monotonic() - started < 20
    assert found["counts"]["timed_out"] == 1
    assert found["failures"][0]["status"] == "timeout"
    assert found["failures"][0]["exit_code"] is None


def test_counts_not_run_when_budget_is_spent(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, found, _ = verify(workspace, monkeypatch, capsys, "true", "false", argv=("--budget", "0"))

    assert code == 0
    assert found["counts"]["not_run"] == 2
    assert found["counts"]["passed"] == 0
    assert found["broken"] == 0


def test_runs_at_the_merge_commit_when_checkout_is_elsewhere(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace.git("checkout", "-q", "-b", "dem-7-add")
    sha = workspace.commit("feat(api): add only (DEM-7)", only_txt="here\n")
    workspace.git("checkout", "-q", "main")

    code, found, _ = verify(workspace, monkeypatch, capsys, "test -f only_txt", sha=sha)

    assert code == 0
    assert found["sha"] == sha
    assert found["counts"]["passed"] == 1
    assert not (workspace.repo / "only_txt").exists()


def test_leaves_repo_checkout_unchanged_when_verifications_run(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (workspace.repo / "draft.txt").write_text("not committed\n", encoding="utf-8")
    (workspace.repo / "README").write_text("edited\n", encoding="utf-8")
    before = [
        workspace.git("rev-parse", "HEAD"),
        workspace.git("branch", "--show-current"),
        workspace.git("status", "--porcelain"),
    ]

    code, found, _ = verify(
        workspace, monkeypatch, capsys, "echo x > made.txt && git add made.txt", "rm README"
    )

    assert code == 0
    assert found["counts"]["passed"] == 2
    after = [
        workspace.git("rev-parse", "HEAD"),
        workspace.git("branch", "--show-current"),
        workspace.git("status", "--porcelain"),
    ]
    assert after == before


def test_removes_temp_worktree_when_a_command_fails(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, found, _ = verify(workspace, monkeypatch, capsys, "exit 1")

    assert code == 0
    assert found["broken"] == 1
    assert len(workspace.git("worktree", "list").splitlines()) == 1


def test_exits_one_when_worktree_cannot_be_created(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, err = verify(workspace, monkeypatch, capsys, "true", sha="f" * 40)

    assert code == 1
    assert err.startswith("verify.py: cannot check out ffffffffffff")
    assert len(workspace.git("worktree", "list").splitlines()) == 1


def test_keeps_bounded_tail_when_output_is_large_and_not_utf8(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    command = "yes a | head -c 100000; printf '\\377\\376end'; exit 1"

    code, found, _ = verify(workspace, monkeypatch, capsys, command)

    assert code == 0
    tail = found["failures"][0]["tail"]
    assert len(tail) == 500
    assert tail.endswith("��end")


def test_reports_error_when_ac_cannot_be_read_again(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace.record("grp/DEM-7", {"feature": "grp/DEM-7", "acs": [an_ac("AC-7.1", "true")]})
    selection = {
        "sha": workspace.git("rev-parse", "HEAD"),
        "repo_path": str(workspace.repo),
        "selected": [
            {"feature": "grp/DEM-7", "ac": "AC-7.9", "why": "ticket"},
            {"feature": "../../outside", "ac": "AC-1", "why": "ticket"},
        ],
    }
    monkeypatch.chdir(workspace.hub)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(selection)))

    code = load().main([])

    found = json.loads(capsys.readouterr().out)
    assert code == 0
    assert found["counts"]["errors"] == 2
    assert [item["status"] for item in found["failures"]] == ["error", "error"]
    assert found["failures"][0]["tail"] == "no AC-7.9 with a verification in the record"
    assert found["failures"][1]["tail"] == "the feature leaves brain/features"


@pytest.mark.parametrize(
    ("stdin", "argv"),
    [("not json", []), ('{"sha": "x"}', []), ("{}", ["--timeout", "soon"]), ("{}", ["-x"])],
)
def test_exits_two_when_input_is_not_a_selection(
    stdin: str,
    argv: list[str],
    *,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))

    code = load().main(argv)

    assert code == 2
    assert capsys.readouterr().err.startswith("verify.py: ")


@pytest.mark.parametrize("wide", ["a", "\U0001f600"])
def test_stays_under_output_cap_when_every_selected_ac_fails(wide: str) -> None:
    module = load()
    results = module.Results(sha="0" * 40)
    for n in range(2000):
        results.failed(
            module.entry(
                f"grp/{'f' * 190}-{n}",
                f"AC-{n}",
                command=wide * 8192,
                status="failed",
                exit_code=1,
                tail=wide * 8192,
                since="",
            )
        )
        results.cannot_run.append(
            {
                "feature": f"grp/{'f' * 190}",
                "ac": f"AC-{n}",
                "reason": "absolute path",
                "command": wide * module.COMMAND_CHARS,
            }
        )
    results.counts["cannot_run"] = 2000

    found = results.output()

    text = json.dumps(found, ensure_ascii=False).encode()
    assert len(text) <= 524288
    assert found["broken"] == 2000
    failures = json.dumps(found["failures"], ensure_ascii=False, separators=(",", ":"))
    assert len(failures.encode()) <= module.FAILURES_BYTES
    assert found["counts"]["failed"] == 2000
    # Every failure is detailed or named while they fit; past the cap only the count says so.
    assert len(found["failures"]) + len(found["more_failed"]) <= 2000
    assert len(found["cannot_run"]) + found["more_cannot_run"] == 2000
    if wide == "a":
        assert len(found["failures"]) + len(found["more_failed"]) == 2000
        assert len(found["failures"]) == 50
        assert found["more_failed"][0] == f"grp/{'f' * 190}-50 AC-50"


def test_runs_again_with_one_worktree_when_resumed_after_a_lost_worktree(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A run killed before its cleanup leaves a worktree entry whose folder is gone.
    lost = workspace.repo.parent / "lost"
    workspace.git("worktree", "add", "--detach", "--quiet", str(lost), "HEAD")
    shutil.rmtree(lost)

    first = verify(workspace, monkeypatch, capsys, "test -f README", "exit 1")
    again = verify(workspace, monkeypatch, capsys, "test -f README", "exit 1")

    assert first == again
    assert first[1]["counts"]["passed"] == 1
    assert len(workspace.git("worktree", "list").splitlines()) == 1
