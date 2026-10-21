"""A scenario run's findings as texts for others (AC-350.27; docs/design/scenarios.md)."""

import re
from datetime import date
from typing import Any

import pytest

from agent_hub.core.brain.frontmatter import split_frontmatter
from agent_hub.core.scenarios.findings import (
    CUT_MARKER,
    MAX_DRAFT_DESCRIPTION_CHARS,
    MAX_DRAFT_TITLE_CHARS,
    FindingsError,
    finding_of,
    inbox_note,
    issue_draft,
)
from agent_hub.core.scenarios.investigation import MAX_TEXT_CHARS, MAX_TITLE_CHARS
from agent_hub.core.scenarios.run_record import fold_records

GATE = "order-held__investigation"
RECORD = ".agent-runs/workflows/walk-1/records.jsonl"
DAY = date(2026, 10, 21)
# A secret shape built at run time: a finding that kept one is redacted again.
KEY = "AKIA" + "SYNTHETIC0000000"


def a_record(**header: Any) -> list[dict[str, Any]]:
    """A scenario run paused at its first investigation, with two findings."""
    start = {"event": "start", "run": "walk-1", "scenario": "order-walk", "environment": "staging"}
    return [
        start | {"mode": "interactive", "kind": "scenario"} | header,
        {"event": "investigation", "step": "order-held", "gate": GATE, "number": 1}
        | {"step_attempt": 1, "failure_kind": "timeout"},
        {"event": "gate", "node": GATE, "attempt": 1, "form": "choice"},
        {
            "event": "proposal",
            "gate": GATE,
            "number": 1,
            "proposal": 1,
            "findings": [
                {
                    "finding_id": "f1",
                    "title": "Order stays\non hold",
                    "text": "The hold flag is set after the send.\nIt never clears.",
                    "evidence": f"status ON_HOLD after 5 polls; key {KEY}",
                },
                {"finding_id": "f2", "title": "Queue is slow", "text": "", "evidence": ""},
            ],
            "options": [],
        },
    ]


def test_writes_plain_draft_when_findings_issue_built() -> None:
    view = fold_records(a_record())
    finding = finding_of(view, "f1")
    assert finding is not None

    draft = issue_draft(view, finding, record=RECORD)

    assert draft.title == "Scenario order-walk: Order stays on hold"
    assert draft.description.splitlines() == [
        "The scenario order-walk found this in run walk-1, at step order-held, in environment"
        " staging.",
        "",
        "The hold flag is set after the send.",
        "It never clears.",
        "",
        "Evidence: status ON_HOLD after 5 polls; key [redacted: AWS access key]",
        "",
        "Record: /scenarios/order-walk/runs/walk-1 in hub web, or the file"
        f" {RECORD} in the hub (finding f1).",
    ]
    assert KEY not in draft.title + draft.description
    plain = issue_draft(view, view.findings[1], record=RECORD).description
    assert "Evidence: none recorded" in plain
    assert "(no description was recorded)" in plain


def test_writes_external_provenance_when_findings_inbox_built() -> None:
    view = fold_records(a_record())
    finding = finding_of(view, "f1")
    assert finding is not None

    note = inbox_note(view, finding, record=RECORD, day=DAY)

    assert note.name == "2026-10-21-scenario-order-walk-f1.md"
    front = split_frontmatter(note.text)
    assert front.fields == {
        "type": "scenario-finding",
        "repos": [],
        "status": "proposed",
        "last_verified": "2026-10-21",
        "sources": ["scenario run walk-1", "finding f1"],
        "provenance": "agent-from-external",
    }
    assert front.body.startswith("## Order stays on hold\n\n")
    assert "The hold flag is set after the send.\nIt never clears." in front.body
    assert "in environment staging" in front.body
    assert f"Record: /scenarios/order-walk/runs/walk-1 in hub web, or the file {RECORD}" in (
        front.body
    )
    assert KEY not in note.text


def test_finds_nothing_when_finding_id_unknown() -> None:
    view = fold_records(a_record())

    assert finding_of(view, "f9") is None
    assert finding_of(view, "f1") == view.findings[0]


@pytest.mark.parametrize(
    "header",
    [{"scenario": "../order-walk"}, {"run": "walk 1"}, {"scenario": None}],
    ids=["scenario-path", "run-space", "scenario-missing"],
)
def test_refuses_when_findings_record_names_unsafe_header(header: dict[str, Any]) -> None:
    view = fold_records(a_record(**header))

    with pytest.raises(FindingsError):
        inbox_note(view, view.findings[0], record=RECORD, day=DAY)
    with pytest.raises(FindingsError):
        issue_draft(view, view.findings[0], record=RECORD)


# Agent-written text with terminal controls: hidden text (ESC[8m), a bare carriage return that
# rewrites the line, a C1 CSI and a bidi override. None may reach the draft or the note raw.
CONTROLS = "Order\x1b[8m hidden\x1b[0m held\rFAKE\x9b2J‮flip"


def a_controlled_record() -> list[dict[str, Any]]:
    record = a_record()
    finding = record[-1]["findings"][0]
    finding.update(title=CONTROLS, text=f"Line one {CONTROLS}\nLine two\r\n", evidence=CONTROLS)
    return record


def raw_controls(text: str) -> list[str]:
    """The control characters (C0 but newline, DEL, C1) and bidi controls left in ``text``."""
    return [
        character
        for character in text
        if (ord(character) < 0x20 and character != "\n")
        or 0x7F <= ord(character) <= 0x9F
        or character in "‪‫‬‭‮⁦⁧⁨⁩"
    ]


def test_escapes_controls_when_findings_issue_built() -> None:
    view = fold_records(a_controlled_record())

    draft = issue_draft(view, view.findings[0], record=RECORD)

    assert raw_controls(draft.title + draft.description) == []
    assert (
        draft.title
        == "Scenario order-walk: Order\\x1b[8m hidden\\x1b[0m held\\rFAKE\\x9b2J\\u202eflip"
    )
    lines = draft.description.splitlines()
    assert lines[2] == "Line one Order\\x1b[8m hidden\\x1b[0m held\\rFAKE\\x9b2J\\u202eflip"
    # A CRLF line end is a line end, not an escaped carriage return.
    assert lines[3] == "Line two"


def test_escapes_controls_when_findings_inbox_built() -> None:
    view = fold_records(a_controlled_record())

    note = inbox_note(view, view.findings[0], record=RECORD, day=DAY)

    assert raw_controls(note.text) == []
    assert "## Order\\x1b[8m hidden\\x1b[0m held\\rFAKE\\x9b2J\\u202eflip" in note.text


# Review Q4, Q5 (AGH-362): escapes grow text up to six times; the draft stays under the tracker's
# caps (the MCP adapter's 255-character title and 10,000-character description), cut at an escape
# boundary with a marker. Every format character (Cf) and line or paragraph separator is escaped.
TRACKER_TITLE_CAP = 255
TRACKER_DESCRIPTION_CAP = 10_000
# An escape, or one plain character: a cut never ends inside an escape.
ESCAPE_OR_CHARACTER = r"\\x[0-9a-f]{2}|\\u[0-9a-f]{4}|\\U[0-9a-f]{8}|\\[rt]|."


def an_all_controls_record() -> list[dict[str, Any]]:
    record = a_record()
    record[-1]["findings"][0].update(
        title="‮" * MAX_TITLE_CHARS,
        text="‮" * MAX_TEXT_CHARS,
        evidence="‮" * MAX_TEXT_CHARS,
    )
    return record


def test_fits_tracker_caps_when_findings_text_all_controls() -> None:
    view = fold_records(an_all_controls_record())

    draft = issue_draft(view, view.findings[0], record=RECORD)
    note = inbox_note(view, view.findings[0], record=RECORD, day=DAY)

    assert len(draft.title) <= MAX_DRAFT_TITLE_CHARS <= TRACKER_TITLE_CAP
    assert len(draft.description) <= MAX_DRAFT_DESCRIPTION_CHARS <= TRACKER_DESCRIPTION_CAP
    assert draft.title.endswith(CUT_MARKER)
    escapes = draft.title.removesuffix(CUT_MARKER).removeprefix("Scenario order-walk: ")
    assert re.fullmatch(r"(\\u202e)+", escapes), escapes
    assert draft.description.count(CUT_MARKER) == 2
    for line in draft.description.splitlines():
        cut = line.removesuffix(CUT_MARKER)
        assert "".join(re.findall(ESCAPE_OR_CHARACTER, cut)) == cut
        assert not re.search(r"\\(u[0-9a-f]{0,3}|x[0-9a-f]?)$", cut), line[-12:]
    assert raw_controls(draft.title + draft.description + note.text) == []


@pytest.mark.parametrize(
    ("character", "escape"),
    [
        ("‎", "\\u200e"),
        ("‏", "\\u200f"),
        ("؜", "\\u061c"),
        ("​", "\\u200b"),
        ("⁠", "\\u2060"),
        ("﻿", "\\ufeff"),
        (" ", "\\u2028"),
        (" ", "\\u2029"),
        ("\U000e0041", "\\U000e0041"),
    ],
    ids=["lrm", "rlm", "alm", "zwsp", "word-joiner", "bom", "line-sep", "para-sep", "tag"],
)
def test_escapes_format_character_when_findings_texts_built(character: str, escape: str) -> None:
    record = a_record()
    record[-1]["findings"][0].update(
        title=f"a{character}b", text=f"c{character}d", evidence=f"e{character}f"
    )
    view = fold_records(record)

    draft = issue_draft(view, view.findings[0], record=RECORD)
    note = inbox_note(view, view.findings[0], record=RECORD, day=DAY)

    for text in (draft.title, draft.description, note.text):
        assert character not in text
    assert draft.title.endswith(f"a{escape}b")
    assert f"c{escape}d" in draft.description
    assert f"Evidence: e{escape}f" in note.text
