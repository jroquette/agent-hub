"""The incident pack's ``check.py`` (AGH-483), in process: which agent-written checks it runs.

A check is an argv list a model wrote after reading untrusted text, so ``refusal`` allows only
read-only inspection programs, git's read subcommands without the options that run a program or
write a file, and paths inside the checkout; ``child_env`` passes nothing from the parent.
``main`` runs the allowed checks in a throwaway worktree at the evidence's head and leaves the
repo's checkout as it was.
"""

import importlib.util
import io
import json
import os
import subprocess
import sys
import time
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(str(files("agent_hub.core").joinpath("workflows/builtin/incident/scripts/check.py")))

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.incident.scripts.check"
CHILD_ENV_KEYS = {
    "PATH",
    "LANG",
    "HOME",
    "GIT_CONFIG_NOSYSTEM",
    "GIT_CONFIG_GLOBAL",
    "GIT_TERMINAL_PROMPT",
    "GIT_OPTIONAL_LOCKS",
    "PAGER",
}
GIT_PREFIX = [
    "git",
    "-c",
    "core.pager=cat",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "diff.external=",
    "--no-pager",
]


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


@pytest.mark.parametrize(
    "argv",
    [
        ["git", "grep", "-n", "timeout", "--", "src"],
        ["git", "log", "-S", "x", "--oneline"],
        ["git", "log", "--first-parent", "main..HEAD", "--", "app/payment.py"],
        ["git", "show", "HEAD~2:app/config.py"],
        ["test", "-f", "app/config.py"],
        ["grep", "-rn", "x", "src"],
        ["wc", "-l", "a.txt"],
        ["tail", "-n", "20", "log.txt"],
        ["cat", "app/x=y.txt"],
    ],
)
def test_allows_read_only_inspection_when_argv_is_on_the_list(argv: list[str]) -> None:
    assert load().refusal(argv) is None


@pytest.mark.parametrize(
    ("argv", "reason"),
    [
        (["sh", "-c", "true"], "program"),
        (["/bin/cat", "x"], "program"),
        (["rg", "--pre", "x", "y"], "program"),
        (["find", ".", "-exec", "rm", "{}", ";"], "program"),
        (["python3", "-c", "print(1)"], "program"),
        (["git", "-c", "core.pager=sh", "log"], "git subcommand"),
        (["git", "push"], "git subcommand"),
        (["git", "config", "x"], "git subcommand"),
        (["git"], "git subcommand"),
        (["git", "grep", "-O", "x"], "option"),
        (["git", "grep", "-nOsh", "x"], "option"),
        (["git", "grep", "--open-files-in-pager=sh", "x"], "option"),
        (["git", "grep", "--open", "x"], "option"),
        (["git", "log", "--output=/tmp/x"], "option"),
        (["git", "log", "--outp=x"], "option"),
        (["git", "log", "-p", "--output-indicator-new=x"], "option"),
        (["git", "diff", "--ext-diff"], "option"),
        (["git", "show", "--textconv", "HEAD"], "option"),
        (["git", "cat-file", "--filters", "HEAD:x"], "option"),
        (["git", "log", "--exec=x"], "option"),
        (["git", "log", "--upload-pack=x"], "option"),
        (["git", "log", "--git-dir=x"], "option"),
        (["git", "log", "--work-tree=x"], "option"),
        (["git", "diff", "--no-index", "a", "b"], "option"),
        (["cat", "/etc/passwd"], "path"),
        (["cat", "../../x"], "path"),
        (["cat", "a/../../x"], "path"),
        (["grep", "--file=/etc/x", "y"], "path"),
        (["grep", "-f/etc/x", "y"], "path"),
        (["cat", "~/.aws/credentials"], "path"),
        (["git", "log", "--", "../x"], "path"),
        (["tail", "-f", "log"], "follow"),
        (["tail", "-F", "log"], "follow"),
        (["tail", "-nf", "log"], "follow"),
        (["tail", "--follow=name", "log"], "follow"),
        (["tail", "--fo", "log"], "follow"),
        (["cat", "a\x00b"], "control"),
        (["cat", "a\nb"], "control"),
        (["cat", "a\x9bb"], "control"),
        (["cat", *(["x"] * 16)], "elements"),
        ([], "elements"),
        (["cat", "x" * 257], "256"),
    ],
    ids=lambda value: "-".join(value)[:60] if isinstance(value, list) else value,
)
def test_refuses_check_when_argv_escapes_the_allow_list(argv: list[str], reason: str) -> None:
    refused = load().refusal(argv)

    assert refused is not None
    assert reason in refused
    assert len(refused) <= 200


def test_refuses_check_when_argv_is_not_a_list_of_text() -> None:
    check = load()

    assert check.refusal("git log") is not None
    assert check.refusal(["git", 1]) is not None


def test_passes_no_inherited_secret_when_child_env_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("GITHUB_TOKEN", "LINEAR_API_KEY", "AWS_PROFILE", "GIT_DIR", "GIT_CONFIG"):
        monkeypatch.setenv(name, "secret")

    env = load().child_env("/usr/bin:/bin", str(tmp_path))

    assert set(env) == CHILD_ENV_KEYS
    assert "secret" not in env.values()
    assert env["HOME"] == str(tmp_path)
    assert env["PATH"] == "/usr/bin:/bin"
    assert env["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["PAGER"] == "cat"


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["git", "grep", "-q", "x"], [*GIT_PREFIX, "grep", "-q", "x"]),
        (
            ["git", "log", "-p"],
            [*GIT_PREFIX, "log", "--no-ext-diff", "--no-textconv", "-p"],
        ),
        (["git", "blame", "a.py"], [*GIT_PREFIX, "blame", "--no-textconv", "a.py"]),
        (["cat", "a.py"], ["cat", "a.py"]),
    ],
)
def test_runs_git_with_its_safe_prefix_when_command_built(
    argv: list[str], expected: list[str]
) -> None:
    assert load().command(argv) == expected


def git(folder: Path, *args: str) -> str:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    done = subprocess.run(  # noqa: S603 - git from PATH, fixed arguments
        ["git", "-c", "user.name=T", "-c", "user.email=t@example.com", *args],  # noqa: S607
        cwd=folder,
        env=env,
        capture_output=True,
        check=True,
    )
    return done.stdout.decode().strip()


def a_repo(root: Path, content: dict[str, bytes]) -> tuple[Path, str]:
    """A repo ``api`` next to a hub, one commit holding ``content``; the repo and its head."""
    repo = root / "api"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    for name, data in {"README": b"readme\n", **content}.items():
        (repo / name).write_bytes(data)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "base")
    (root / "hub").mkdir()
    return repo, git(repo, "rev-parse", "HEAD")


def a_hypothesis(n: int, check: list[str], *, mitigation: bool = True) -> dict[str, Any]:
    return {
        "id": f"H{n}",
        "rank": n,
        "statement": f"Hypothesis {n}.",
        "repo": "api",
        "check": check,
        "confirms_when": "It exits 0.",
        "mitigation": {"summary": f"Revert {n}.", "undo": f"Re-apply {n}."} if mitigation else None,
    }


def run_checks(
    root: Path,
    head: str,
    hypotheses: list[dict[str, Any]],
    *extra: str,
    io_: tuple[pytest.MonkeyPatch, pytest.CaptureFixture[str]],
) -> tuple[int, Any]:
    monkeypatch, capsys = io_
    monkeypatch.chdir(root / "hub")
    stdin = json.dumps({"hypotheses": hypotheses}).encode()
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin)))
    repos = json.dumps([{"dir": "api", "head": head, "ref": "origin/main", "commits": []}])

    code = load().main(["--repos", repos, *extra])

    out = capsys.readouterr().out
    return code, json.loads(out) if code == 0 else out


def by_id(output: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {result["id"]: result for result in output["results"]}


def test_marks_confirmed_when_check_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, head = a_repo(tmp_path, {"app.py": b"BUG = 1\n"})
    check = ["git", "grep", "-q", "BUG", "--", "app.py"]

    code, output = run_checks(tmp_path, head, [a_hypothesis(1, check)], io_=(monkeypatch, capsys))

    assert code == 0
    assert by_id(output)["H1"] | {"tail": ""} == {
        "id": "H1",
        "rank": 1,
        "repo": "api",
        "status": "confirmed",
        "exit_code": 0,
        "reason": "",
        "tail": "",
    }
    assert (output["confirmed"], output["mitigations"]) == (1, 1)


def test_marks_failed_when_check_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, head = a_repo(tmp_path, {"app.py": b"fine = 1\n"})
    check = ["git", "grep", "-q", "BUG", "--", "app.py"]

    code, output = run_checks(tmp_path, head, [a_hypothesis(1, check)], io_=(monkeypatch, capsys))

    assert code == 0
    assert by_id(output)["H1"]["status"] == "failed"
    assert by_id(output)["H1"]["exit_code"] == 1
    assert (output["confirmed"], output["mitigations"]) == (0, 0)


@pytest.mark.parametrize(
    "check",
    [
        ["sh", "-c", "touch {marker}"],
        ["git", "log", "--output={marker}"],
        ["git", "grep", "--open-files-in-pager=touch {marker}", "x"],
    ],
    ids=["shell", "git-output", "git-pager"],
)
def test_records_refusal_without_running_when_argv_is_refused(
    check: list[str],
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, head = a_repo(tmp_path, {"x": b"x\n"})
    marker = tmp_path / "marker"
    argv = [part.replace("{marker}", str(marker)) for part in check]

    code, output = run_checks(tmp_path, head, [a_hypothesis(1, argv)], io_=(monkeypatch, capsys))

    assert code == 0
    result = by_id(output)["H1"]
    assert result["status"] == "refused"
    assert result["exit_code"] is None
    assert result["reason"].startswith("refused: ")
    assert not marker.exists()


def test_reports_timeout_when_check_exceeds_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, head = a_repo(tmp_path, {"x": b"x\n"})
    check = load()
    pid_file = tmp_path / "background.pid"
    # A check that outlives its limit and leaves a background child in its process group: the
    # allowed argv is run as this one, so the limit and the group's kill are what is tested.
    slow = ["sh", "-c", f"sleep 30 & echo $! > {pid_file}; wait"]
    monkeypatch.setattr(check, "command", lambda _: slow)
    monkeypatch.chdir(tmp_path / "hub")
    stdin = json.dumps({"hypotheses": [a_hypothesis(1, ["git", "log"])]}).encode()
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin)))

    code = check.main(["--repos", json.dumps([{"dir": "api", "head": head}]), "--timeout", "1"])

    output = json.loads(capsys.readouterr().out)
    assert code == 0
    result = by_id(output)["H1"]
    assert result["status"] == "timeout"
    assert result["exit_code"] is None
    assert output["confirmed"] == 0
    background = int(pid_file.read_text(encoding="utf-8"))
    # The whole group was killed: the background sleep is gone, not left running.
    for _ in range(50):
        try:
            os.kill(background, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail(f"the check's background process {background} outlived its timeout")


def test_prunes_the_repo_when_making_its_worktree_is_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, head = a_repo(tmp_path, {"x": b"x\n"})
    check = load()
    # Making the worktree gets no time: git is stopped, maybe after it registered the worktree.
    monkeypatch.setattr(check, "WORKTREE_TIMEOUT", 0.000001)
    before = repo_state(repo)
    monkeypatch.chdir(tmp_path / "hub")
    stdin = json.dumps({"hypotheses": [a_hypothesis(1, ["test", "-f", "x"])]}).encode()
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin)))

    code = check.main(["--repos", json.dumps([{"dir": "api", "head": head}])])

    output = json.loads(capsys.readouterr().out)
    assert code == 0
    assert output["results"][0]["status"] == "error"
    assert repo_state(repo) == before
    assert git(repo, "worktree", "prune", "--dry-run", "-v") == ""


def test_refuses_remaining_checks_when_budget_is_spent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, head = a_repo(tmp_path, {"x": b"x\n"})
    checks = [a_hypothesis(n, ["test", "-f", "x"]) for n in (1, 2)]

    code, output = run_checks(tmp_path, head, checks, "--budget", "0", io_=(monkeypatch, capsys))

    assert code == 0
    for result in output["results"]:
        assert result["status"] == "refused"
        assert "budget" in result["reason"]
    assert output["confirmed"] == 0


def test_reads_the_evidence_head_when_checkout_is_on_another_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, base = a_repo(tmp_path, {"x": b"x\n"})
    (repo / "only_at_head.txt").write_text("new\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "head")
    head = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-qb", "old", base)
    assert not (repo / "only_at_head.txt").exists()

    code, output = run_checks(
        tmp_path,
        head,
        [a_hypothesis(1, ["test", "-f", "only_at_head.txt"])],
        io_=(monkeypatch, capsys),
    )

    assert code == 0
    assert by_id(output)["H1"]["status"] == "confirmed"


def repo_state(repo: Path) -> tuple[str, ...]:
    return (
        git(repo, "rev-parse", "HEAD"),
        git(repo, "branch", "--show-current"),
        git(repo, "status", "--porcelain"),
        git(repo, "worktree", "list", "--porcelain"),
    )


def test_leaves_repo_checkout_unchanged_when_checks_ran(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, head = a_repo(tmp_path, {"app.py": b"BUG = 1\n"})
    (repo / "untracked.txt").write_text("mine\n", encoding="utf-8")
    (repo / "app.py").write_text("edited\n", encoding="utf-8")
    before = repo_state(repo)
    checks = [
        a_hypothesis(1, ["git", "grep", "-q", "BUG", "--", "app.py"]),
        a_hypothesis(2, ["test", "-f", "missing.txt"]),
        a_hypothesis(3, ["cat", "missing.txt"]),
    ]

    code, output = run_checks(tmp_path, head, checks, io_=(monkeypatch, capsys))

    assert code == 0
    assert [r["status"] for r in output["results"]] == ["confirmed", "failed", "failed"]
    assert repo_state(repo) == before
    assert len(before[3].split("\n\n")) == 1
    assert (repo / "app.py").read_text(encoding="utf-8") == "edited\n"
    assert not list(tmp_path.glob("hub/*"))


@pytest.mark.parametrize(
    ("repo", "repos"),
    [("web", None), ("api", "[]"), ("api", '[{"dir": "api", "head": ""}]')],
    ids=["unknown-repo", "no-evidence", "no-head"],
)
def test_marks_error_when_repo_is_unknown(
    repo: str,
    repos: str | None,
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, head = a_repo(tmp_path, {"x": b"x\n"})
    hypotheses = [a_hypothesis(1, ["test", "-f", "x"]) | {"repo": repo}]
    monkeypatch.chdir(tmp_path / "hub")
    monkeypatch.setattr(
        sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps({"hypotheses": hypotheses}).encode()))
    )
    given = repos if repos is not None else json.dumps([{"dir": "api", "head": head}])

    code = load().main(["--repos", given])

    output = json.loads(capsys.readouterr().out)
    assert code == 0
    assert output["results"][0]["status"] == "error"
    assert output["results"][0]["exit_code"] is None
    assert output["confirmed"] == 0


def test_marks_error_when_two_hypotheses_share_an_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, head = a_repo(tmp_path, {"x": b"x\n"})
    checks = [a_hypothesis(1, ["test", "-f", "x"]), a_hypothesis(1, ["test", "-f", "x"])]

    code, output = run_checks(tmp_path, head, checks, io_=(monkeypatch, capsys))

    assert code == 0
    assert [r["status"] for r in output["results"]] == ["confirmed", "error"]
    assert "duplicate" in output["results"][1]["reason"]


def test_marks_error_when_the_head_cannot_be_checked_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    a_repo(tmp_path, {"x": b"x\n"})

    code, output = run_checks(
        tmp_path, "f" * 40, [a_hypothesis(1, ["test", "-f", "x"])], io_=(monkeypatch, capsys)
    )

    assert code == 0
    assert output["results"][0]["status"] == "error"
    assert output["results"][0]["reason"] == "error: cannot check out fffffff"


def test_counts_mitigations_of_confirmed_hypotheses_only_when_menu_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, head = a_repo(tmp_path, {"x": b"x\n"})
    monkeypatch.setenv("AGENT_HUB_RUN_ID", "run-0123456789")
    checks = [
        a_hypothesis(3, ["test", "-f", "missing"]),
        a_hypothesis(1, ["test", "-f", "x"]),
        a_hypothesis(2, ["test", "-f", "x"], mitigation=False),
    ]

    code, output = run_checks(tmp_path, head, checks, io_=(monkeypatch, capsys))

    assert code == 0
    # Ranked: the checks run and print in rank order.
    assert [r["id"] for r in output["results"]] == ["H1", "H2", "H3"]
    assert (output["confirmed"], output["mitigations"]) == (2, 1)
    menu = output["menu"]
    assert "H1: Revert 1. (undo: Re-apply 1.)" in menu
    assert "Revert 3." not in menu
    assert "H3 failed" in menu
    assert "hub workflow respond run-0123456789 --choice record --text" in menu
    assert "hub workflow respond run-0123456789 --choice none" in menu
    assert len(menu) <= 4096


def test_stays_under_output_cap_when_every_tail_is_full(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, head = a_repo(tmp_path, {"big.bin": b"\xff" * (1024 * 1024)})
    checks = [a_hypothesis(n, ["cat", "big.bin"]) for n in range(1, 6)]
    monkeypatch.chdir(tmp_path / "hub")
    stdin = json.dumps({"hypotheses": checks}).encode()
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin)))

    code = load().main(["--repos", json.dumps([{"dir": "api", "head": head}])])

    out = capsys.readouterr().out
    assert code == 0
    assert len(out.encode()) <= 16384
    output = json.loads(out)
    assert all(len(result["tail"]) <= 1000 for result in output["results"])
    assert all(result["tail"] for result in output["results"])


@pytest.mark.parametrize(
    ("stdin", "repos"),
    [
        ("not json", "[]"),
        ('{"hypotheses": {}}', "[]"),
        ("[]", "[]"),
        ('{"hypotheses": []}', "{not json"),
        ('{"hypotheses": []}', "{}"),
    ],
    ids=[
        "stdin-not-json",
        "hypotheses-not-list",
        "stdin-not-object",
        "repos-not-json",
        "repos-not-list",
    ],
)
def test_exits_two_when_input_is_malformed(
    stdin: str,
    repos: str,
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin.encode())))

    code = load().main(["--repos", repos])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert captured.err.startswith("check.py: ")
