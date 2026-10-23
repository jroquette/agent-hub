"""The spike pack's ``draft.py`` (AGH-492), in process: research.md and the ADR draft it writes
under brain/features/<slug>/, never over a file, and what marks them incomplete."""

import importlib.util
import io
import json
import re
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

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


def run_main(
    hub: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    slug: str = "brief-cache",
    stdin: str | None = None,
    **changes: Any,
) -> tuple[int, Any, str]:
    given = inputs(**changes)
    argv = ["--slug", slug, "--question", QUESTION, "--now", str(NOW)]
    for name in ("state", "recall", "options", "premortem"):
        value = given[name]
        argv += [
            f"--{name}",
            value if isinstance(value, str) else json.dumps(value) if value else "",
        ]
    research = given["research"]
    text = stdin if stdin is not None else json.dumps(research) if research else ""
    monkeypatch.chdir(hub)
    monkeypatch.setenv("AGENT_HUB_RUN_ID", "run-7")
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))
    code = load().main(argv)
    out, err = capsys.readouterr()
    return code, json.loads(out) if code == 0 else out, err


def test_writes_research_and_adr_draft_with_three_causes_when_every_step_ran(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = run_main(tmp_path, monkeypatch, capsys)

    folder = tmp_path.resolve() / FOLDER
    assert code == 0
    assert out == {
        "result": "complete",
        "research": str(folder / "research.md"),
        "adr": str(folder / "adr-draft-brief-cache.md"),
        "reasons": [],
        "spent_m": 60,
    }
    research = Path(out["research"]).read_text(encoding="utf-8")
    adr = Path(out["adr"]).read_text(encoding="utf-8")
    assert research.startswith("---\ntype: research\n")
    assert "\nrun: run-7\n" in research
    assert len(re.findall(r"^### ", section(adr, "## Premortem"), re.MULTILINE)) == 3


def test_writes_only_research_when_timebox_reached_before_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    over = a_state(over=True, spent_s=7300, picked="", go=False, note="", approver="", option={})

    code, out, _ = run_main(tmp_path, monkeypatch, capsys, state=over, options=None, premortem=None)

    assert code == 0
    assert (out["result"], out["adr"]) == ("incomplete", "")
    assert out["reasons"] == ["timebox 2h reached after research"]
    assert sorted(p.name for p in (tmp_path / FOLDER).iterdir()) == ["research.md"]
    research = Path(out["research"]).read_text(encoding="utf-8")
    assert body(research).startswith("> Incomplete: timebox 2h reached after research.")


def test_keeps_existing_files_when_research_or_draft_already_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / FOLDER
    folder.mkdir(parents=True)
    (folder / "research.md").write_text("mine\n", encoding="utf-8")
    (folder / "adr-draft-brief-cache.md").write_text("mine too\n", encoding="utf-8")

    _, first, _ = run_main(tmp_path, monkeypatch, capsys)
    _, second, _ = run_main(tmp_path, monkeypatch, capsys)

    assert (folder / "research.md").read_text(encoding="utf-8") == "mine\n"
    assert (folder / "adr-draft-brief-cache.md").read_text(encoding="utf-8") == "mine too\n"
    real = tmp_path.resolve() / FOLDER
    assert first["research"] == str(real / "research-run-7.md")
    assert first["adr"] == str(real / "adr-draft-brief-cache-run-7.md")
    assert second["research"] == str(real / "research-run-7-2.md")


def test_writes_only_under_the_feature_folder_when_slug_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, _ = run_main(tmp_path, monkeypatch, capsys)
    refused, out, err = run_main(tmp_path, monkeypatch, capsys, slug="../../docs/adr")
    (tmp_path / "brain/features/linked").symlink_to(tmp_path)
    linked, _, outside = run_main(tmp_path, monkeypatch, capsys, slug="linked")

    assert code == 0
    written = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if p.is_file())
    assert written == [
        "brain/features/brief-cache/adr-draft-brief-cache.md",
        "brain/features/brief-cache/research.md",
    ]
    assert (refused, out) == (2, "")
    assert err.startswith("draft.py: slug")
    assert linked == 2
    assert outside.startswith("draft.py: slug")
    assert not (tmp_path / "docs").exists()


@pytest.mark.parametrize("name", ["state", "recall", "options", "premortem", "research"])
def test_exits_two_when_an_input_is_not_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    name: str,
) -> None:
    changes: dict[str, Any] = {"stdin": "not json"} if name == "research" else {name: "not json"}

    code, out, err = run_main(tmp_path, monkeypatch, capsys, **changes)

    assert (code, out) == (2, "")
    assert err.startswith(f"draft.py: {'stdin' if name == 'research' else '--' + name} is not")
    assert not (tmp_path / "brain").exists()


def test_exits_one_when_feature_folder_cannot_be_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "brain/features").mkdir(parents=True)
    (tmp_path / FOLDER).write_text("a file where the folder goes\n", encoding="utf-8")

    code, out, err = run_main(tmp_path, monkeypatch, capsys)

    assert (code, out) == (1, "")
    assert err.startswith("draft.py: cannot write brain/features/brief-cache")


def test_reads_values_that_start_with_a_dash_when_owner_text_is_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    state = json.dumps(a_state(note="--keep it small", approver="-Dana"))
    argv = ["--slug", "brief-cache", "--question", "-x: cache the brief?", "--state", state]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    code = load().main([*argv, "--options", json.dumps(OPTIONS), "--now", str(NOW)])

    out = json.loads(capsys.readouterr().out)
    assert code == 0
    research = Path(out["research"]).read_text(encoding="utf-8")
    assert "```text\n-x: cache the brief?\n```" in research
    assert "Owner's note: --keep it small" in research
