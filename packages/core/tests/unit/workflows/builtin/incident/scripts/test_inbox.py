"""The incident pack's ``inbox.py`` (AGH-483), in process: the drafts a run leaves in
``brain/_inbox/`` for the owner - the hand-off for /fix (or /change) - with the untrusted text
fenced, and never over an existing file.
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

SCRIPT = Path(str(files("agent_hub.core").joinpath("workflows/builtin/incident/scripts/inbox.py")))

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.incident.scripts.inbox"
OWNER_APPLIES = (
    "The pack records the chosen mitigation; applying it is the owner's step through /fix"
    " (or /change)."
)
REPORT = "Checkout fails since Tuesday."
TODAY = "2026-10-22"


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


def a_hypothesis(n: int) -> dict[str, Any]:
    return {
        "id": f"H{n}",
        "rank": n,
        "statement": f"Hypothesis {n}.",
        "repo": "api",
        "check": ["git", "grep", "-q", f"BUG{n}", "--", "app.py"],
        "confirms_when": "The pattern is found.",
        "mitigation": {"summary": f"Revert {n}.", "undo": f"Re-apply {n}."},
    }


HYPOTHESES = {"hypotheses": [a_hypothesis(1), a_hypothesis(2)]}


def a_check(*statuses: str) -> dict[str, Any]:
    results = [
        {
            "id": f"H{n}",
            "rank": n,
            "repo": "api",
            "status": status,
            "exit_code": 0 if status == "confirmed" else 1,
            "reason": "",
            "tail": f"app.py:1:BUG{n} = 1" if status == "confirmed" else "",
        }
        for n, status in enumerate(statuses, start=1)
    ]
    confirmed = statuses.count("confirmed")
    return {"results": results, "confirmed": confirmed, "mitigations": confirmed, "menu": ""}


MITIGATION = {
    "id": "H1",
    "summary": "Revert 1.",
    "undo": "Re-apply 1.",
    "source": "hypothesis",
    "approver": "Jo",
}


def handoff(**given: Any) -> str:
    values: dict[str, Any] = {
        "hypotheses": HYPOTHESES,
        "check": a_check("confirmed", "failed"),
        "mitigation": MITIGATION,
        "decision": "record",
        "run": "run00001",
        "today": TODAY,
    }
    rendered: str = load().render_handoff(given.pop("report", REPORT), **(values | given))
    return rendered


def section(text: str, title: str) -> str:
    start = text.index(f"## {title}\n")
    end = text.find("\n## ", start + 1)
    return text[start : end if end != -1 else len(text)]


def test_says_the_owner_applies_the_mitigation_when_handoff_rendered() -> None:
    text = handoff()

    assert OWNER_APPLIES in text
    assert text.startswith("---\ntype: incident-handoff\nstatus: draft\nprovenance: agent\n")
    for title in (
        "Symptom",
        "Reproduction",
        "Hypotheses",
        "Chosen mitigation",
        "Draft for /fix (or /change)",
    ):
        assert f"\n## {title}\n" in text, title


def test_writes_reproduction_from_confirmed_check_when_one_is_confirmed() -> None:
    reproduction = section(handoff(), "Reproduction")

    assert '["git", "grep", "-q", "BUG1", "--", "app.py"]' in reproduction
    assert "app.py:1:BUG1 = 1" in reproduction
    assert "BUG2" not in reproduction


def test_says_no_reproduction_when_nothing_is_confirmed() -> None:
    text = handoff(check=a_check("failed", "refused"), mitigation="", decision="")

    assert "No hypothesis was confirmed" in section(text, "Reproduction")
    assert "none chosen" in section(text, "Chosen mitigation")


def test_lists_every_hypothesis_with_its_status_when_rendered() -> None:
    hypotheses = section(handoff(check=a_check("confirmed", "refused")), "Hypotheses")

    assert "H1" in hypotheses
    assert "confirmed" in hypotheses
    assert "H2" in hypotheses
    assert "refused" in hypotheses


def test_names_the_mitigation_and_its_approver_when_one_is_recorded() -> None:
    chosen = section(handoff(), "Chosen mitigation")

    assert "H1" in chosen
    assert "Revert 1." in chosen
    assert "Re-apply 1." in chosen
    assert "Jo" in chosen


def test_names_the_owner_text_when_the_owner_wrote_the_mitigation() -> None:
    owner = MITIGATION | {"id": "", "summary": "Turn the flag off.", "source": "owner"}

    chosen = section(handoff(mitigation=owner), "Chosen mitigation")

    assert "The owner's own mitigation, recorded by Jo (owner)" in chosen
    assert "Turn the flag off." in chosen


def test_says_none_chosen_when_mitigation_declined() -> None:
    chosen = section(handoff(mitigation="", decision="none"), "Chosen mitigation")

    assert "none chosen" in chosen
    assert "Revert 1." not in chosen


def test_fences_report_when_it_holds_backticks_and_control_chars() -> None:
    report = "Error ````` here\x07\x1b[31m\nsecond\tline\n``` end"

    symptom = section(handoff(report=report), "Symptom")

    fence = "``````"  # one longer than the longest backtick run in the report
    assert f"{fence}text\nError ````` here[31m\nsecond\tline\n``` end\n{fence}" in symptom
    assert "\x07" not in symptom
    assert "\x1b" not in symptom


def test_fences_with_three_backticks_when_text_holds_none() -> None:
    assert load().fence("plain") == "```text\nplain\n```"


def run_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *argv: str,
    stdin: str = REPORT,
) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin.encode())))
    code = load().main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


HANDOFF_ARGS = (
    "handoff",
    "--hypotheses",
    json.dumps(HYPOTHESES),
    "--check",
    json.dumps(a_check("confirmed", "failed")),
    "--mitigation",
    json.dumps(MITIGATION),
    "--decision",
    "record",
    "--today",
    TODAY,
)


def test_writes_the_handoff_in_the_inbox_when_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENT_HUB_RUN_ID", "0123456789abcdef")

    code, out, _ = run_main(monkeypatch, capsys, *HANDOFF_ARGS)

    assert code == 0
    path = f"brain/_inbox/incident-{TODAY}-01234567-handoff.md"
    assert json.loads(out) == {"path": path, "confirmed": 1, "mitigation": "H1"}
    assert OWNER_APPLIES in (tmp_path / path).read_text(encoding="utf-8")


def test_names_the_run_local_when_no_run_id_is_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENT_HUB_RUN_ID", raising=False)

    code, out, _ = run_main(monkeypatch, capsys, *HANDOFF_ARGS)

    assert code == 0
    assert json.loads(out)["path"] == f"brain/_inbox/incident-{TODAY}-local-handoff.md"


def test_refuses_to_overwrite_when_handoff_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENT_HUB_RUN_ID", "run00001")
    existing = tmp_path / f"brain/_inbox/incident-{TODAY}-run00001-handoff.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("the owner's notes\n", encoding="utf-8")

    code, out, err = run_main(monkeypatch, capsys, *HANDOFF_ARGS)

    assert code == 1
    assert out == ""
    assert f"brain/_inbox/incident-{TODAY}-run00001-handoff.md" in err
    assert existing.read_text(encoding="utf-8") == "the owner's notes\n"


@pytest.mark.parametrize(
    "argv",
    [
        ("handoff", "--hypotheses", "not json", "--check", "{}", "--today", TODAY),
        ("handoff", "--hypotheses", "{}", "--check", "[]", "--today", TODAY),
        ("handoff", "--hypotheses", json.dumps(HYPOTHESES), "--check", "{}", "--today", "today"),
        (
            "handoff",
            "--hypotheses",
            json.dumps(HYPOTHESES),
            "--check",
            json.dumps(a_check("confirmed")),
            "--mitigation",
            "{not json",
            "--today",
            TODAY,
        ),
    ],
    ids=["hypotheses-not-json", "check-not-object", "bad-today", "mitigation-not-json"],
)
def test_exits_two_when_handoff_input_is_malformed(
    argv: tuple[str, ...],
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    code, out, err = run_main(monkeypatch, capsys, *argv)

    assert code == 2
    assert out == ""
    assert err.startswith("inbox.py: ")
    assert not (tmp_path / "brain").exists()
