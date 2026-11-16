"""The sdlc pack's ``feedback.py`` (AGH-229), in process: the check and the findings, blocking
first, within 32768 bytes."""

import importlib.util
import io
import json
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(str(files("agent_hub.core").joinpath("workflows/builtin/sdlc/scripts/feedback.py")))

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.sdlc.scripts.feedback"


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


def compact(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def a_finding(finding_id: str, severity: str, what: str = "Wrong.") -> dict[str, Any]:
    return {"id": finding_id, "severity": severity, "what": what}


def run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *argv: str,
    stdin: str = "",
) -> tuple[int, str]:
    module = load()
    monkeypatch.setattr(module.sys, "stdin", io.StringIO(stdin))
    code = module.main(list(argv))
    return code, capsys.readouterr().out.removesuffix("\n")


@pytest.mark.parametrize(("over", "kept"), [(0, 2), (1, 1)])
def test_keeps_at_most_32768_bytes_when_the_findings_reach_the_budget(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *, over: int, kept: int
) -> None:
    first = a_finding("F1", "blocking")

    def expected(findings: list[dict[str, Any]], omitted: int) -> str:
        parts = ",".join(compact({"reviewer": "spec", **f}) for f in findings)
        return '{"check":null,"findings":[' + parts + '],"omitted":' + str(omitted) + "}"

    unfilled = len(expected([first, a_finding("F2", "minor", "")], 0).encode())
    second = a_finding("F2", "minor", "w" * (32768 - unfilled + over))
    review = {"reviewer": "spec", "findings": [first, second]}

    code, output = run(monkeypatch, capsys, stdin=json.dumps(review))

    assert code == 0
    assert output == expected([first, second][:kept], 2 - kept)
    assert len(output.encode()) <= 32768


def test_folds_the_notes_blocking_first_when_a_second_lens_is_given(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    check = {"passed": False, "exit_code": 2, "round": 1, "tail": "FAILED\n"}
    spec = {"reviewer": "spec", "findings": [a_finding("S1", "minor"), a_finding("S2", "blocking")]}
    quality = {"reviewer": "quality", "findings": [a_finding("Q1", "blocking"), "not a finding"]}

    _, notes = run(monkeypatch, capsys, "--check", json.dumps(check), stdin=json.dumps(spec))
    code, folded = run(monkeypatch, capsys, "--notes", notes, stdin=json.dumps(quality))

    assert code == 0
    output = json.loads(folded)
    assert output["check"] == {"passed": False, "exit_code": 2, "tail": "FAILED\n"}
    assert [(f["reviewer"], f["id"]) for f in output["findings"]] == [
        ("spec", "S2"),
        ("quality", "Q1"),
        ("spec", "S1"),
    ]
    assert output["omitted"] == 0


def test_keeps_the_earlier_count_when_the_notes_omitted_findings(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    notes = {"check": None, "findings": [], "omitted": 3}

    _, output = run(monkeypatch, capsys, "--notes", json.dumps(notes))

    assert json.loads(output) == {"check": None, "findings": [], "omitted": 3}


@pytest.mark.parametrize("notes", ['{"omitted": "x", "findings": {}}', ""])
def test_reads_nothing_when_no_lens_ran_and_the_notes_are_odd(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], notes: str
) -> None:
    _, output = run(monkeypatch, capsys, "--check", "", "--notes", notes, stdin=" \n")

    assert json.loads(output) == {"check": None, "findings": [], "omitted": 0}


@pytest.mark.parametrize(
    ("argv", "stdin"),
    [(("--check", "[1]"), ""), (("--notes", "{"), ""), ((), "not json")],
)
def test_exits_two_when_a_value_is_not_a_json_object(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    argv: tuple[str, ...],
    stdin: str,
) -> None:
    code, output = run(monkeypatch, capsys, *argv, stdin=stdin)

    assert (code, output) == (2, "")
