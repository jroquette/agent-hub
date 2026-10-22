"""The incident pack's ``mitigation.py`` (AGH-483), in process: the mitigation the owner chose at
the gate, recorded (never applied): a confirmed hypothesis named in the text, else the owner's own
text, else, when the text is blank, the top-ranked confirmed mitigation.
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
    str(files("agent_hub.core").joinpath("workflows/builtin/incident/scripts/mitigation.py"))
)

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.incident.scripts.mitigation"


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


def a_hypothesis(n: int, *, mitigation: bool = True) -> dict[str, Any]:
    return {
        "id": f"H{n}",
        "rank": n,
        "statement": f"Hypothesis {n}.",
        "repo": "api",
        "check": ["test", "-f", "x"],
        "confirms_when": "It exits 0.",
        "mitigation": {"summary": f"Revert {n}.", "undo": f"Re-apply {n}."} if mitigation else None,
    }


HYPOTHESES = {"hypotheses": [a_hypothesis(1), a_hypothesis(2), a_hypothesis(3)]}
CHECK = {
    "results": [
        {"id": "H1", "rank": 1, "status": "failed"},
        {"id": "H2", "rank": 2, "status": "confirmed"},
        {"id": "H3", "rank": 3, "status": "confirmed"},
    ],
    "confirmed": 2,
    "mitigations": 2,
    "menu": "",
}


def run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    text: str,
    *,
    stdin: str = json.dumps(HYPOTHESES),
    check: str = json.dumps(CHECK),
) -> tuple[int, Any, str]:
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin.encode())))
    code = load().main(["--check", check, "--text", text, "--approver", "Jo"])
    captured = capsys.readouterr()
    return code, json.loads(captured.out) if code == 0 else captured.out, captured.err


def test_picks_named_confirmed_hypothesis_when_text_names_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, output, _ = run(monkeypatch, capsys, "Go with H3 please")

    assert code == 0
    assert output == {
        "id": "H3",
        "summary": "Revert 3.",
        "undo": "Re-apply 3.",
        "source": "hypothesis",
        "approver": "Jo",
    }


def test_records_owner_text_when_it_names_no_confirmed_hypothesis(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # H1's check failed: naming it is the owner's own text, not a pick.
    code, output, _ = run(monkeypatch, capsys, "H1: turn the retry flag off\x07")

    assert code == 0
    assert output == {
        "id": "",
        "summary": "H1: turn the retry flag off",
        "undo": "",
        "source": "owner",
        "approver": "Jo",
    }


def test_picks_top_ranked_confirmed_mitigation_when_text_is_blank(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, output, _ = run(monkeypatch, capsys, "  ")

    assert code == 0
    assert (output["id"], output["source"], output["summary"]) == ("H2", "hypothesis", "Revert 2.")


def test_skips_confirmed_hypothesis_without_mitigation_when_text_is_blank(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hypotheses = {
        "hypotheses": [a_hypothesis(1), a_hypothesis(2, mitigation=False), a_hypothesis(3)]
    }

    code, output, _ = run(monkeypatch, capsys, "", stdin=json.dumps(hypotheses))

    assert code == 0
    assert output["id"] == "H3"


def test_cuts_owner_text_when_it_is_long(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, output, _ = run(monkeypatch, capsys, "x" * 5000)

    assert code == 0
    assert len(output["summary"]) == 2000


@pytest.mark.parametrize(
    ("stdin", "check"),
    [
        ("not json", json.dumps(CHECK)),
        ('{"hypotheses": {}}', json.dumps(CHECK)),
        (json.dumps(HYPOTHESES), "not json"),
        (json.dumps(HYPOTHESES), '{"results": {}}'),
        (json.dumps(HYPOTHESES), ""),
    ],
    ids=[
        "hypotheses-not-json",
        "hypotheses-not-list",
        "check-not-json",
        "results-not-list",
        "check-blank",
    ],
)
def test_exits_two_when_hypotheses_json_is_malformed(
    stdin: str,
    check: str,
    *,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, err = run(monkeypatch, capsys, "H2", stdin=stdin, check=check)

    assert code == 2
    assert out == ""
    assert err.startswith("mitigation.py: ")


def test_exits_two_when_nothing_can_be_recorded(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    check = {**CHECK, "results": [{"id": "H1", "rank": 1, "status": "failed"}]}

    code, _, err = run(monkeypatch, capsys, "", check=json.dumps(check))

    assert code == 2
    assert "no confirmed mitigation" in err
