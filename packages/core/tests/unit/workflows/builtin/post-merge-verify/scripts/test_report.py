"""The post-merge-verify pack's ``report.py``, in process: a run's entries rendered and appended to
the hub's inbox, nothing written when every verification passed.
"""

import importlib.util
import io
import json
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(
    str(files("agent_hub.core").joinpath("workflows/builtin/post-merge-verify/scripts/report.py"))
)

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.post-merge-verify.scripts.report"
SHA = "0a1b2c3d4e5f60718293a4b5c6d7e8f901234567"
MERGE = "9f8e7d6c5b4a39281706f5e4d3c2b1a098765432"


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


def a_run(
    *failures: dict[str, Any], cannot_run: tuple[dict[str, Any], ...] = (), **counts: int
) -> dict[str, Any]:
    found = dict.fromkeys(
        ("selected", "passed", "failed", "timed_out", "errors", "cannot_run", "not_run"), 0
    )
    found |= {"failed": len(failures), "cannot_run": len(cannot_run)} | counts
    found["selected"] = sum(value for key, value in found.items() if key != "selected")
    return {
        "sha": SHA,
        "counts": found,
        "broken": len(failures),
        "failures": list(failures),
        "more_failed": [],
        "cannot_run": list(cannot_run),
        "more_cannot_run": 0,
    }


def a_failure(command: str = "test -f kept.txt", **given: Any) -> dict[str, Any]:
    found = {
        "feature": "grp/DEM-7",
        "ac": "AC-7.1",
        "command": command,
        "status": "failed",
        "exit_code": 1,
        "tail": "no kept.txt\n",
        "since": "2026-01-02",
    }
    return found | given


def a_suspect(kind: str = "regression") -> dict[str, Any]:
    return {
        "feature": "grp/DEM-7",
        "ac": "AC-7.1",
        "merge": MERGE,
        "subject": "Merge pull request #9 from acme/jdoe/dem-7-drop",
        "kind": kind,
        "evidence": "The merge deletes kept.txt, which the verification tests.",
    }


def report(
    hub: Path,
    run: dict[str, Any],
    *,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: tuple[str, ...] = (),
    explain: dict[str, Any] | None = None,
    run_id: str = "run-1",
) -> tuple[int, Any]:
    monkeypatch.chdir(hub)
    monkeypatch.setenv("AGENT_HUB_RUN_ID", run_id)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(run)))
    given = [
        "--mode",
        "merge",
        "--sha",
        SHA,
        "--repo",
        "demo-api",
        "--tickets",
        '["DEM-7"]',
        "--explain",
        json.dumps(explain) if explain is not None else "",
        "--today",
        "2026-01-09",
        *argv,
    ]
    code = load().main(given)
    out = capsys.readouterr().out
    return code, json.loads(out) if code == 0 else None


INBOX = "brain/_inbox/verify-2026-01-09.md"


def test_writes_no_file_when_every_verification_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, found = report(tmp_path, monkeypatch=monkeypatch, capsys=capsys, run=a_run(passed=3))

    assert code == 0
    assert found == {"verdict": "clean", "entries": 0, "path": ""}
    assert not (tmp_path / "brain").exists()


def test_names_ac_command_exit_code_and_suspect_when_a_verification_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = a_run(a_failure(), passed=1)

    code, found = report(
        tmp_path,
        monkeypatch=monkeypatch,
        capsys=capsys,
        run=run,
        explain={"suspects": [a_suspect()]},
    )

    assert code == 0
    assert found == {"verdict": "regressed", "entries": 1, "path": INBOX}
    text = (tmp_path / INBOX).read_text(encoding="utf-8")
    assert text.startswith("---\ntype: verify-report\n")
    assert "## Run run-1 at 0a1b2c3 (merge)" in text
    assert "#### grp/DEM-7 AC-7.1: failed, exit 1" in text
    assert "```text\ntest -f kept.txt\n```" in text
    assert "Last passed: 2026-01-02." in text
    assert "Suspect: 9f8e7d6 Merge pull request #9 from acme/jdoe/dem-7-drop (regression)." in text
    assert "Evidence: The merge deletes kept.txt, which the verification tests." in text
    assert "Draft: /fix (or /change) grp/DEM-7 AC-7.1:" in text
    assert "suspect 9f8e7d6" in text
    assert "Cannot run after merge" not in text


def test_lists_cannot_run_apart_from_failures_when_flagged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    flagged = {
        "feature": "grp/DEM-7",
        "ac": "AC-7.3",
        "reason": "absolute path",
        "command": "cd /home/user/x && true",
    }

    code, found = report(
        tmp_path, monkeypatch=monkeypatch, capsys=capsys, run=a_run(cannot_run=(flagged,), passed=1)
    )

    assert code == 0
    assert found == {"verdict": "attention", "entries": 1, "path": INBOX}
    text = (tmp_path / INBOX).read_text(encoding="utf-8")
    assert "### Cannot run after merge" in text
    assert "- grp/DEM-7 AC-7.3 (absolute path):" in text
    assert "```text\ncd /home/user/x && true\n```" in text
    assert "### Failed" not in text
    assert "0 failed" in text


def test_marks_flaky_and_keeps_failure_when_explain_says_flaky(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    flaky = a_suspect("flaky") | {"merge": "", "subject": ""}

    code, found = report(
        tmp_path,
        monkeypatch=monkeypatch,
        capsys=capsys,
        run=a_run(a_failure()),
        explain={"suspects": [flaky]},
    )

    assert code == 0
    assert found["verdict"] == "regressed"
    text = (tmp_path / INBOX).read_text(encoding="utf-8")
    assert "#### grp/DEM-7 AC-7.1: failed, exit 1" in text
    assert "(flaky)" in text
    assert "Flaky: no merge since the last pass touches what it tests" in text


def test_reports_failure_without_suspect_when_explain_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    timed_out = a_failure(status="timeout", exit_code=None, since="")

    code, found = report(
        tmp_path,
        monkeypatch=monkeypatch,
        capsys=capsys,
        run=a_run(timed_out, failed=0, timed_out=1),
    )

    assert code == 0
    assert found["verdict"] == "regressed"
    text = (tmp_path / INBOX).read_text(encoding="utf-8")
    assert "#### grp/DEM-7 AC-7.1: timeout, timed out" in text
    assert "Suspect: none named (explain did not run)." in text
    assert "Last passed: unknown." in text


def test_lists_unreadable_truncated_and_not_run_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    unreadable = [{"path": "brain/features/x/features.json", "reason": "not JSON"}]
    run = a_run(passed=1, not_run=2)
    run["more_failed"] = []

    code, found = report(
        tmp_path,
        run,
        monkeypatch=monkeypatch,
        capsys=capsys,
        argv=("--unreadable", json.dumps(unreadable), "--truncated", "4"),
    )

    assert code == 0
    assert found == {"verdict": "attention", "entries": 7, "path": INBOX}
    text = (tmp_path / INBOX).read_text(encoding="utf-8")
    assert "2 not run: the run's budget was spent." in text
    assert "- brain/features/x/features.json: not JSON" in text
    assert "4 ACs not selected (cap)." in text


def test_lists_more_failed_when_failures_exceed_the_detail_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = a_run(a_failure(), failed=3)
    run["more_failed"] = ["grp/DEM-7 AC-7.2", "grp/DEM-7 AC-7.3"]
    run["more_cannot_run"] = 5
    run["counts"]["cannot_run"] = 5

    code, found = report(tmp_path, monkeypatch=monkeypatch, capsys=capsys, run=run)

    assert code == 0
    assert found["entries"] == 8
    text = (tmp_path / INBOX).read_text(encoding="utf-8")
    assert "And 2 more failed: grp/DEM-7 AC-7.2, grp/DEM-7 AC-7.3." in text
    assert "And 5 more." in text


def test_appends_second_section_when_report_exists_for_the_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    report(tmp_path, monkeypatch=monkeypatch, capsys=capsys, run=a_run(a_failure()), run_id="run-1")
    code, found = report(
        tmp_path, monkeypatch=monkeypatch, capsys=capsys, run=a_run(a_failure()), run_id="run-2"
    )

    assert code == 0
    assert found["path"] == INBOX
    text = (tmp_path / INBOX).read_text(encoding="utf-8")
    assert text.count("type: verify-report") == 1
    assert text.index("## Run run-1 ") < text.index("## Run run-2 ")


def test_fences_command_when_it_holds_backticks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    command = "echo ```` && printf '\x1b[31m' \x00"
    failure = a_failure(command, tail="red\x1b[0m\r\n## Not a heading\n", feature="grp/\nDEM-7")

    code, _ = report(tmp_path, monkeypatch=monkeypatch, capsys=capsys, run=a_run(failure))

    assert code == 0
    text = (tmp_path / INBOX).read_text(encoding="utf-8")
    assert "`````text\necho ```` && printf '[31m' \n`````" in text
    assert "```text\nred[0m\n## Not a heading\n```" in text
    assert "#### grp/DEM-7 AC-7.1" in text
    assert "\x1b" not in text
    assert "\x00" not in text


@pytest.mark.parametrize(
    "argv",
    [
        ["--mode", "merge"],
        ["--mode", "daily", "--sha", SHA, "--repo", "demo-api"],
        ["--mode", "merge", "--sha", SHA, "--repo", "demo-api", "--truncated", "x"],
        ["--mode", "merge", "--sha", SHA, "--repo", "demo-api", "--explain", "nope"],
        ["--mode", "merge", "--sha", SHA, "--repo", "demo-api", "--tickets", "{}"],
        ["--mode", "merge", "--sha", SHA, "--repo", "demo-api", "--today", "today"],
        ["--mode", "merge", "--sha", SHA, "--repo", "demo-api", "--other", "x"],
    ],
)
def test_exits_two_when_arguments_are_bad(
    argv: list[str],
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(a_run())))

    code = load().main(argv)

    assert code == 2
    assert capsys.readouterr().err.startswith("report.py: ")
    assert not (tmp_path / "brain").exists()


def test_exits_two_when_stdin_is_not_a_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO("[1]"))

    code = load().main(["--mode", "weekly", "--sha", SHA, "--repo", "demo-api"])

    assert code == 2
    assert "stdin" in capsys.readouterr().err


def test_says_no_suspect_found_when_explain_ran_without_naming_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    other = a_suspect() | {"ac": "AC-7.2"}

    code, _ = report(
        tmp_path,
        monkeypatch=monkeypatch,
        capsys=capsys,
        run=a_run(a_failure()),
        explain={"suspects": [other]},
    )

    assert code == 0
    text = (tmp_path / INBOX).read_text(encoding="utf-8")
    assert "Suspect: none found (explain named no merge for this AC)." in text
    assert "explain did not run" not in text


def test_appends_section_once_when_report_reruns_on_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    first = report(tmp_path, monkeypatch=monkeypatch, capsys=capsys, run=a_run(a_failure()))
    again = report(tmp_path, monkeypatch=monkeypatch, capsys=capsys, run=a_run(a_failure()))

    assert first == again
    text = (tmp_path / INBOX).read_text(encoding="utf-8")
    assert text.count("## Run run-1 at 0a1b2c3 (merge)") == 1
