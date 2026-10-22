"""The spike pack's ``draft.py`` (AGH-492), in process: research.md and the ADR draft it writes
under brain/features/<slug>/, never over a file, and what marks them incomplete."""

import importlib.util
import re
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

SCRIPT = Path(str(files("agent_hub.core").joinpath("workflows/builtin/spike/scripts/draft.py")))

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.spike.scripts.draft"

QUESTION = "Should the session brief be cached between sessions?"
NOW = 1_000_000.0
FOLDER = Path("brain/features/brief-cache")


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


def a_state(**changes: Any) -> dict[str, Any]:
    state = {
        "slug": "brief-cache",
        "timebox_s": 7200,
        "spent_s": 3600,
        "at": NOW,
        "over": False,
        "left_m": 60,
        "round": 1,
        "picked": "a",
        "go": True,
        "done": True,
        "note": "Go with A, keep the cache small.",
        "approver": "Dana Owner",
        "option": OPTION_A,
    }
    return state | changes


OPTION_A = {
    "id": "a",
    "title": "A file cache keyed by the brain's commit",
    "summary": "Reuse the brief while the brain's commit is the same.",
    "pros": ["Fast starts"],
    "cons": ["A stale tracker part"],
}
OPTION_B = {
    "id": "b",
    "title": "A short time-to-live cache",
    "summary": "Reuse the brief for ten minutes.",
    "pros": ["Simple"],
    "cons": ["Stale for up to ten minutes"],
}
RECALL = {
    "summary": "No decision covers caching the brief.",
    "sources": [{"ref": "brain/decisions/index.md", "says": "Nothing on the brief cache."}],
}
RESEARCH = {
    "summary": "The brief is rebuilt on each start.",
    "repos": ["agent-hub"],
    "findings": [{"area": "brief", "fact": "Built on each call.", "where": "brief.py:40"}],
    "invariants": ["The brief never holds secrets."],
    "open_questions": ["How stale may a brief be?"],
}
OPTIONS = {
    "options": [OPTION_A, OPTION_B],
    "recommendation": "a",
    "reason": "The commit key never serves a stale brain.",
    "brief": "a) cache\nb) ttl",
}
CAUSES = [
    {
        "cause": f"Cause {n}.",
        "likelihood": "high",
        "impact": "moderate",
        "sign": f"Sign {n}.",
        "experiment": f"Experiment {n}.",
    }
    for n in (1, 2, 3)
]
PREMORTEM = {
    "causes": CAUSES,
    "others": ["Another cause."],
    "assumptions": [{"text": "The brief takes two seconds.", "checked": True}],
    "first": "Close an issue and start a session.",
}
ALL = {
    "state": a_state(),
    "recall": RECALL,
    "research": RESEARCH,
    "options": OPTIONS,
    "premortem": PREMORTEM,
}


def inputs(**changes: Any) -> dict[str, Any]:
    return ALL | changes


def adr_of(**changes: Any) -> str:
    given = inputs(**changes)
    reasons = load().reasons(**given)
    return str(load().render_adr(QUESTION, given, reasons, run="run-1", today="2026-10-22"))


def research_of(**changes: Any) -> str:
    given = inputs(**changes)
    reasons = load().reasons(**given)
    return str(
        load().render_research(
            QUESTION, given, reasons, run="run-1", today="2026-10-22", spent_m=60
        )
    )


def section(text: str, heading: str) -> str:
    start = text.index(f"\n{heading}\n")
    rest = text[start + len(heading) + 2 :]
    following = re.search(r"^## ", rest, re.MULTILINE)
    return rest if following is None else rest[: following.start()]


def body(text: str) -> str:
    return text.split("\n---\n", 1)[1].lstrip("\n")


def test_writes_unnumbered_draft_adr_in_feature_folder_when_every_step_ran() -> None:
    adr = adr_of()

    assert adr.startswith("---\ntype: adr-draft\nstatus: draft\ncomplete: true\n")
    assert "\nlast_verified: 2026-10-22\n" in adr
    (title,) = [line for line in adr.splitlines() if line.startswith("# ")]
    assert title == "# Draft: A file cache keyed by the brain's commit"
    assert re.search(r"^# \d{4}\.", adr, re.MULTILINE) is None
    assert "- Status: draft (record it with /adr)" in adr
    headings = [line for line in adr.splitlines() if line.startswith("##")]
    assert headings == [
        "## Context and Problem Statement",
        "## Considered Options",
        "## Decision Outcome",
        "### Consequences",
        "## Premortem",
        "### 1. Cause 1.",
        "### 2. Cause 2.",
        "### 3. Cause 3.",
    ]


def test_holds_exactly_three_causes_in_premortem_when_premortem_ran() -> None:
    premortem = section(adr_of(), "## Premortem")

    causes = re.split(r"^### ", premortem, flags=re.MULTILINE)[1:]
    assert len(causes) == 3
    for n, cause in enumerate(causes, start=1):
        assert cause.startswith(f"{n}. Cause {n}.\n")
        assert f"Early-warning sign: Sign {n}." in cause
        assert f"Cheapest experiment: Experiment {n}." in cause
        assert "Likelihood: high" in cause
    assert "Another cause." in causes[-1]
    assert "Run first: Close an issue and start a session." in causes[-1]


def test_marks_incomplete_when_timebox_reached() -> None:
    over = a_state(over=True, spent_s=7300, picked="", go=False, note="", option={})
    given = {"state": over, "options": OPTIONS, "premortem": None}

    adr = adr_of(**given)
    research = research_of(**given)

    for text in (adr, research):
        assert "\ncomplete: false\n" in text
        assert body(text).startswith("> Incomplete: timebox 2h reached after options")
    assert section(adr, "## Premortem").strip().startswith("Not run")
    assert load().reasons(**inputs(**given)) == ["timebox 2h reached after options"]


def test_lists_each_reason_when_steps_were_skipped_or_no_pick() -> None:
    two = {**PREMORTEM, "causes": CAUSES[:2]}
    unpicked = a_state(picked="", go=False, round=3, option={})

    found = load().reasons(**inputs(state=unpicked, research=None, premortem=two))
    early = load().reasons(**inputs(state=a_state(over=True, timebox_s=5400), research=None))

    assert found == [
        "research did not run",
        "no option picked after 3 rounds",
        "the premortem gave 2 causes, not 3",
    ]
    assert early == ["timebox 90m reached after recall"]
    assert load().reasons(**inputs(premortem=None)) == ["premortem did not run"]
    assert load().reasons(**inputs()) == []


def test_renders_options_and_pick_with_owner_note_when_picked() -> None:
    research = research_of()
    adr = adr_of()

    options = section(research, "## Options")
    assert "### a. A file cache keyed by the brain's commit" in options
    assert "### b. A short time-to-live cache" in options
    assert "Recommended: a. The commit key never serves a stale brain." in options
    pick = section(research, "## Pick")
    assert "Option a, picked by Dana Owner" in pick
    assert "Go with A, keep the cache small." in pick
    assert "- **brief**: Built on each call. (`brief.py:40`)" in section(
        research, "## Detailed findings"
    )
    assert 'Chosen option: "a. A file cache keyed by the brain\'s commit"' in adr
    assert "- Deciders: Dana Owner" in adr
    assert "Good: Fast starts" in section(adr, "## Decision Outcome")


def test_escapes_a_heading_when_agent_text_starts_with_one() -> None:
    sneaky = {**RESEARCH, "summary": "## Premortem"}

    research = research_of(research=sneaky)

    assert "\n## Premortem" not in research
    assert "\\## Premortem" in research
