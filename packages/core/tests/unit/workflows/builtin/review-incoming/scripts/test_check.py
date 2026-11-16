"""The review-incoming pack's ``check.py`` (AGH-493), in process: the repo's check at the PR's
head in a throwaway detached worktree, never for a fork, with no inherited secret, the clone left
as it was."""

import json
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

# The conftest's ``Clone``: a hub, its repo's clone, ``base`` and ``head``.
type Clone = Any

ONLY_AT_HEAD = "test -f app/run.py"


@pytest.fixture
def check(script: Any) -> ModuleType:
    module: ModuleType = script("check")
    return module


@pytest.fixture
def run(check: ModuleType, clone: Clone, capsys: pytest.CaptureFixture[str]) -> Any:
    def running(command: str, *extra: str, fork: str = "false") -> tuple[int, Any, str]:
        argv = ["--path", str(clone.repo), "--head", clone.head, "--command", command]
        code = check.main([*argv, "--fork", fork, *extra])
        captured = capsys.readouterr()
        return code, json.loads(captured.out) if code == 0 else None, captured.err

    return running


def test_passes_no_inherited_secret_when_child_env_built(check: ModuleType, tmp_path: Path) -> None:
    environ = {
        "PATH": "/usr/bin",
        "HOME": "/home/owner",
        "GH_TOKEN": "x",
        "GITHUB_TOKEN": "x",
        "LINEAR_API_KEY": "x",
        "AWS_PROFILE": "prod",
        "HTTPS_PROXY": "http://proxy:3128",
        "SSL_CERT_FILE": "/etc/ca.pem",
    }

    env = check.child_env(environ, tmp_path)

    for name in ("GH_TOKEN", "GITHUB_TOKEN", "LINEAR_API_KEY", "AWS_PROFILE"):
        assert name not in env, name
    assert env["PATH"] == "/usr/bin"
    assert Path(env["HOME"]).is_relative_to(tmp_path)
    assert Path(env["TMPDIR"]).is_relative_to(tmp_path)
    assert env["HTTPS_PROXY"] == "http://proxy:3128"
    assert env["SSL_CERT_FILE"] == "/etc/ca.pem"


def test_skips_the_check_when_head_is_a_fork(clone: Clone, run: Any) -> None:
    before = clone.state()

    code, result, _ = run(f"touch {clone.repo}/ran", fork="true")

    assert code == 0
    assert result["status"] == "not_run"
    assert result["exit_code"] is None
    assert "fork" in result["reason"]
    assert not (clone.repo / "ran").exists()
    assert clone.state() == before


def test_marks_passed_when_check_exits_zero_at_head(run: Any) -> None:
    code, result, _ = run(ONLY_AT_HEAD)

    assert code == 0
    assert result == {
        "status": "passed",
        "exit_code": 0,
        "tail": "",
        "reason": "",
        "command": ONLY_AT_HEAD,
    }


def test_marks_failed_when_check_exits_nonzero(run: Any) -> None:
    code, result, _ = run("echo '```red'; exit 3")

    assert code == 0
    assert result["status"] == "failed"
    assert result["exit_code"] == 3
    assert result["tail"] == "`red\n"


def test_reports_timeout_when_check_exceeds_limit(run: Any, tmp_path: Path) -> None:
    marker = tmp_path / "survived"

    code, result, _ = run(f"(sleep 1; touch {marker}) & sleep 5", "--timeout", "0.2")

    assert code == 0
    assert result["status"] == "timeout"
    assert result["exit_code"] is None
    # The whole process group was killed: the background child never wrote its marker.
    time.sleep(1.5)
    assert not marker.exists()


@pytest.mark.parametrize("command", [ONLY_AT_HEAD, "exit 1", "sleep 5"])
def test_leaves_repo_checkout_unchanged_when_check_ran(
    clone: Clone, run: Any, command: str
) -> None:
    before = clone.state()

    code, _, _ = run(command, "--timeout", "0.5")

    assert code == 0
    assert clone.state() == before


def test_marks_error_when_head_is_missing_from_clone(
    check: ModuleType, clone: Clone, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["--path", str(clone.repo), "--head", "e" * 40, "--command", "true", "--fork", "false"]

    code = check.main(argv)

    result = json.loads(capsys.readouterr().out)
    assert code == 0
    assert result["status"] == "error"
    assert "fetch again" in result["reason"]


@pytest.mark.parametrize("head", ["abc123", "E" * 40, "g" * 40])
def test_exits_two_when_head_is_not_a_full_sha(
    check: ModuleType, capsys: pytest.CaptureFixture[str], head: str
) -> None:
    argv = ["--path", "/nonexistent", "--head", head, "--command", "true", "--fork", "false"]

    code = check.main(argv)

    assert code == 2
    assert "head must be a full commit sha" in capsys.readouterr().err


def test_exits_two_when_fork_is_not_a_boolean(
    check: ModuleType, clone: Clone, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["--path", str(clone.repo), "--head", clone.head, "--command", "true", "--fork", ""]

    code = check.main(argv)

    assert code == 2
    assert "fork must be true or false" in capsys.readouterr().err


def test_stays_under_output_cap_when_check_prints_megabytes(run: Any) -> None:
    code, result, _ = run(
        "head -c 3000000 /dev/zero | tr '\\0' 'x'; printf '\\360\\235\\204\\236%.0s' $(seq 5000)"
    )

    assert code == 0
    assert result["status"] == "passed"
    assert len(result["tail"]) <= 4000
    assert result["tail"].endswith("\U0001d11e")
    assert len(json.dumps(result).encode()) < 65536


def test_kills_a_background_process_when_a_passing_check_leaves_one(
    run: Any, tmp_path: Path
) -> None:
    marker = tmp_path / "survived"

    code, result, _ = run(f"(sleep 1; touch {marker}) & exit 0")

    assert code == 0
    assert result["status"] == "passed"
    time.sleep(1.5)
    assert not marker.exists()
