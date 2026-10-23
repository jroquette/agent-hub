"""The flaky pack's ``report.py``, in process: the inbox note it writes per test, one section per
run, safe to run again, and the outcome it prints.
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

SCRIPT = Path(str(files("agent_hub.core").joinpath("workflows/builtin/flaky/scripts/report.py")))

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.flaky.scripts.report"

TEST = "tests/test_x.py::test_y[a b]"
SHA = "0a1b2c3d4e5f60718293a4b5c6d7e8f901234567"


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


def a_mode(name: str, status: str = "ran", **counts: Any) -> dict[str, Any]:
    keys = ("passed", "failed", "errors", "timed_out", "missing", "not_run")
    found = {key: counts.get(key, 0) for key in keys}
    note = counts.get("note", f"how {name} ran")
    return {"mode": name, "status": status, "note": note, **found, "tails": counts.get("tails", [])}


def a_run(**changes: Any) -> dict[str, Any]:
    run = {
        "test": TEST,
        "repo": "demo-api",
        "repo_path": "/ws/demo-api",
        "sha": SHA,
        "runner": ["uv", "run", "--locked", "python"],
        "runs": 20,
        "budget_spent": False,
        "reproduced": True,
        "modes": [
            a_mode("alone", passed=20),
            a_mode("suite", passed=14, failed=6, tails=["run 2: E   assert not [1]"]),
            a_mode("shuffled", "unavailable", note="skipped: neither plugin is installed"),
            a_mode("parallel", passed=20),
        ],
    }
    return run | changes


CLASSIFIED = {
    "cause": "order_dependence",
    "shared": "process",
    "confidence": "high",
    "evidence": "Alone passes 20 of 20; in its file it fails 6 of 20 after test_a fills STATE.",
    "next_step": "Clear STATE in a fixture.",
}


class Report:
    """``report.py`` run in a temporary hub."""

    def __init__(
        self, hub: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self.hub, self.monkeypatch, self.capsys = hub, monkeypatch, capsys
        monkeypatch.chdir(hub)

    def __call__(
        self, run: Any, classification: Any = "", *, run_id: str = "run-1", stdin: str = ""
    ) -> tuple[int, Any, str]:
        self.monkeypatch.setenv("AGENT_HUB_RUN_ID", run_id)
        given = stdin or json.dumps(run)
        self.monkeypatch.setattr(sys, "stdin", io.StringIO(given))
        text = classification if isinstance(classification, str) else json.dumps(classification)
        code = load().main(["--classification", text, "--today", "2026-01-09"])
        captured = self.capsys.readouterr()
        return code, json.loads(captured.out) if code == 0 else None, captured.err

    def note(self, found: Any) -> str:
        return (self.hub / found["path"]).read_text(encoding="utf-8")


@pytest.fixture
def report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> Report:
    hub = tmp_path / "hub"
    hub.mkdir()
    return Report(hub, monkeypatch, capsys)


def test_writes_note_when_reproduced(report: Report) -> None:
    code, found, err = report(a_run(), CLASSIFIED)

    assert code == 0, err
    assert found["outcome"] == "reproduced"
    slug = load().slug(TEST)
    assert found["path"] == f"brain/_inbox/flaky-{slug}.md"
    text = report.note(found)
    front, rest = text.split("\n---\n", 1)
    assert front.splitlines() == [
        "---",
        "type: flaky",
        "status: proposed",
        "last_verified: 2026-01-09",
        "provenance: agent",
    ]
    assert "## Run run-1 at 0a1b2c3" in rest
    assert f"Test: `{TEST}`" in rest
    assert "Repo: `demo-api`" in rest
    assert f"Commit: `{SHA}`" in rest
    assert "Runner: `uv run --locked python`" in rest
    assert "Runs per mode: 20." in rest
    assert "| Mode | Status | Passed | Failed | Errors | Timed out | Missing | Not run |" in rest
    assert "| alone | ran | 20 | 0 | 0 | 0 | 0 | 0 |" in rest
    assert "| suite | ran | 14 | 6 | 0 | 0 | 0 | 0 |" in rest
    assert "| shuffled | skipped | 0 | 0 | 0 | 0 | 0 | 0 |" in rest
    assert "Outcome: reproduced." in rest
    assert "Cause: order_dependence (confidence high)." in rest
    assert "Shared state: process." in rest
    assert f"Evidence: {CLASSIFIED['evidence']}" in rest
    assert "Next step: Clear STATE in a fixture." in rest
    assert "#### suite" in rest
    assert "```text\nrun 2: E   assert not [1]\n```" in rest


def test_keeps_note_when_rerun_with_same_run(report: Report) -> None:
    _, found, _ = report(a_run(), CLASSIFIED)
    first = (report.hub / found["path"]).read_bytes()

    code, again, err = report(a_run(), CLASSIFIED)

    assert code == 0, err
    assert again == found
    assert (report.hub / found["path"]).read_bytes() == first


def test_appends_section_when_new_run(report: Report) -> None:
    report(a_run(), CLASSIFIED)

    code, found, err = report(
        a_run(reproduced=False, modes=[a_mode("alone", passed=20)]), "", run_id="run-2"
    )

    assert code == 0, err
    text = report.note(found)
    assert text.count("type: flaky") == 1
    assert text.index("## Run run-1 at 0a1b2c3") < text.index("## Run run-2 at 0a1b2c3")
    assert found["outcome"] == "not_reproduced"


def test_fences_tail_when_it_holds_backticks(report: Report) -> None:
    tails = ["run 1: ````\nE  boom\x1b[31m\x00"]
    run = a_run(modes=[a_mode("alone", failed=1, tails=tails)])

    code, found, err = report(run, CLASSIFIED)

    assert code == 0, err
    text = report.note(found)
    assert "`````text\nrun 1: ````\nE  boom[31m\n`````" in text
    assert "\x1b" not in text
    assert "\x00" not in text


def test_writes_note_without_cause_when_classification_empty(report: Report) -> None:
    code, found, err = report(a_run(), "")

    assert code == 0, err
    assert found["outcome"] == "reproduced"
    text = report.note(found)
    assert "Cause: not classified (the classify step did not run or gave nothing)." in text
    assert "Shared state:" not in text
    # The fixed next step for a reproduced flake without a cause.
    assert "Next step: Raise runs, or run it under the check gate's load" in text


def test_names_fixed_next_step_when_agent_gives_none(report: Report) -> None:
    code, found, err = report(a_run(), CLASSIFIED | {"cause": "timing", "next_step": ""})

    assert code == 0, err
    assert "Next step: Wait on the condition the test needs" in report.note(found)


def test_writes_not_reproduced_when_no_failure(report: Report) -> None:
    modes = [a_mode("alone", passed=20), a_mode("suite", passed=20)]

    code, found, err = report(a_run(reproduced=False, modes=modes), "")

    assert code == 0, err
    assert found["outcome"] == "not_reproduced"
    text = report.note(found)
    assert "Outcome: not reproduced: every run passed (alone 20 of 20, suite 20 of 20)." in text
    assert "| suite | ran | 20 | 0 | 0 | 0 | 0 | 0 |" in text
    assert "Next step: Raise runs, or run it under the check gate's load" in text
    assert "Cause:" not in text


def test_lists_skipped_mode_when_unavailable(report: Report) -> None:
    code, found, err = report(a_run(), CLASSIFIED)

    assert code == 0, err
    text = report.note(found)
    assert "Skipped: shuffled (skipped: neither plugin is installed)." in text


def test_notes_budget_when_spent(report: Report) -> None:
    run = a_run(budget_spent=True, modes=[a_mode("alone", passed=3, not_run=17)])

    code, found, err = report(run, CLASSIFIED)

    assert code == 0, err
    assert "The run's budget was spent: 17 runs not run." in report.note(found)


@pytest.mark.parametrize(
    ("test", "start"),
    [
        ("tests/test_x.py::test_y", "tests-test-x-py-test-y-"),
        ("../../etc/passwd.py::T::t[/../x]", "etc-passwd-py-t-t-x-"),
        ("A/B.py::Test_Y[ ]", "a-b-py-test-y-"),
        ("x" * 200 + ".py::t", "x" * 80 + "-"),
    ],
)
def test_slugs_test_id_when_it_holds_path_chars(test: str, start: str) -> None:
    module = load()

    found = module.slug(test)

    assert found.startswith(start)
    assert len(found) == len(start) + 8
    assert set(found) <= set("abcdefghijklmnopqrstuvwxyz0123456789-")
    assert module.slug(test + "x") != found


def test_refuses_note_when_path_is_a_link(report: Report) -> None:
    inbox = report.hub / "brain/_inbox"
    inbox.mkdir(parents=True)
    target = report.hub / "elsewhere.md"
    target.write_text("kept\n", encoding="utf-8")
    (inbox / f"flaky-{load().slug(TEST)}.md").symlink_to(target)

    code, _, err = report(a_run(), CLASSIFIED)

    assert code == 1
    assert "report.py: " in err
    assert "is a link" in err
    assert target.read_text(encoding="utf-8") == "kept\n"


def test_refuses_note_when_inbox_is_a_link(report: Report, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (report.hub / "brain").mkdir()
    (report.hub / "brain/_inbox").symlink_to(elsewhere)

    code, _, err = report(a_run(), CLASSIFIED)

    assert code == 1
    assert "is a link" in err
    assert list(elsewhere.iterdir()) == []


def test_refuses_note_when_it_is_too_large(report: Report) -> None:
    path = report.hub / "brain/_inbox" / f"flaky-{load().slug(TEST)}.md"
    path.parent.mkdir(parents=True)
    path.write_text("x" * (256 * 1024 + 1), encoding="utf-8")

    code, _, err = report(a_run(), CLASSIFIED)

    assert code == 1
    assert "over 256 KiB" in err


@pytest.mark.parametrize(
    ("stdin", "reason"),
    [
        ("{not json", "stdin is not JSON"),
        ("[]", "stdin is not a repeat run"),
        (json.dumps({"test": TEST}), "stdin is not a repeat run"),
        (json.dumps(a_run(test=7)), "stdin is not a repeat run"),
        (json.dumps(a_run(sha="x" * 41)), "stdin is not a repeat run"),
        (json.dumps(a_run(runner=[" " * 70_000])), "stdin is over 64 KiB"),
    ],
)
def test_rejects_run_when_stdin_is_not_json(report: Report, stdin: str, reason: str) -> None:
    code, _, err = report(None, CLASSIFIED, stdin=stdin)

    assert code == 2
    assert reason in err
    assert not (report.hub / "brain").exists()


@pytest.mark.parametrize(
    ("argv", "reason"),
    [
        (["--classification", "{x"], "--classification is not JSON"),
        (["--classification", "[]"], "--classification is not a JSON object"),
        (["--classification", "", "--today", "today"], "--today is not a date"),
        (["--other", "x"], "usage: report.py"),
        (["--classification"], "usage: report.py"),
    ],
)
def test_rejects_options_when_wrong(
    report: Report, monkeypatch: pytest.MonkeyPatch, *, argv: list[str], reason: str
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(a_run())))

    code = load().main(argv)

    assert code == 2
    assert reason in report.capsys.readouterr().err
