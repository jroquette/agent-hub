"""A plan's version from its ``## Amendments`` entries (two-level-flows AC-1.4)."""

from agent_hub.core.features.feature_view import AmendmentView, PlanView
from agent_hub.core.features.plan_version import plan_version

PLAN = b"""---
type: plan
status: approved
---
# Plan: demo

## Overview

Text.
"""


def test_reads_v1_when_plan_has_no_amendments_section() -> None:
    assert plan_version(PLAN) == PlanView(version=1, amendments=())


def test_counts_entries_when_amendments_section_lists_them() -> None:
    text = PLAN + (
        b"\n## Amendments\n\n"
        b"Approved by the owner.\n\n"
        b"A1 (2026-10-20, Jos\xc3\xa9): Split the ticket in two.\n"
        b"- A2 (2026-10-21, Jos\xc3\xa9 Henrique Roquette): Drop the CSV export.\n"
    )

    assert plan_version(text) == PlanView(
        version=3,
        amendments=(
            AmendmentView(
                id="A1",
                date="2026-10-20",
                who="José",
                title="Split the ticket in two.",
                anchor="Amendments",
            ),
            AmendmentView(
                id="A2",
                date="2026-10-21",
                who="José Henrique Roquette",
                title="Drop the CSV export.",
                anchor="Amendments",
            ),
        ),
    )


def test_reads_entry_when_written_bold_or_as_dash_item() -> None:
    text = PLAN + (
        b"\n## Amendments (owner)\n\n"
        b"- **A1 (2026-10-20, Ana):** Rename the step.\n"
        b"**A2 (2026-10-22, Ana):** Keep the old route.\n"
        b"* A3 (2026-10-23, Ana): a star item is not an entry.\n"
        b"4. A4 (2026-10-24, Ana): a numbered item is not an entry.\n"
        b"__A5 (2026-10-25, Ana):__ underscore bold is not an entry.\n"
    )

    found = plan_version(text)

    assert found.version == 3
    assert [(a.id, a.title, a.anchor) for a in found.amendments] == [
        ("A1", "Rename the step.", "Amendments (owner)"),
        ("A2", "Keep the old route.", "Amendments (owner)"),
    ]


def test_ignores_entries_when_outside_the_section() -> None:
    text = (
        b"# Plan\n\nA1 (2026-10-01, Ana): before the section.\n"
        b"## Amendments\n\nA1 (2026-10-20, Ana): counted.\n"
        b"### Detail\n\nA2 (2026-10-21, Ana): a subsection still counts.\n"
        b"## Success criteria\n\nA3 (2026-10-22, Ana): after the section.\n"
        b"### Proposed spec amendments\n\nA4 (2026-10-23, Ana): not the section.\n"
    )

    assert [a.id for a in plan_version(text).amendments] == ["A1", "A2"]


def test_ignores_entries_when_inside_code_blocks() -> None:
    text = (
        b"## Amendments\n\n"
        b"```text\nA1 (2026-10-20, Ana): an example.\n## Not a heading\n```\n"
        b"~~~\nA2 (2026-10-20, Ana): another example.\n~~~\n"
        b"A3 (2026-10-21, Ana): the real one.\n"
    )

    assert plan_version(text) == PlanView(
        version=2,
        amendments=(
            AmendmentView(
                id="A3", date="2026-10-21", who="Ana", title="the real one.", anchor="Amendments"
            ),
        ),
    )


def test_counts_repeated_id_once_when_entry_repeats() -> None:
    text = (
        b"## Amendments\n\n"
        b"A1 (2026-10-20, Ana): first.\n"
        b"A1 (2026-10-25, Ana): written again.\n"
        b"A2 (2026-10-26, Ana): second.\n"
    )

    found = plan_version(text)

    assert found.version == 3
    assert [(a.id, a.title) for a in found.amendments] == [("A1", "first."), ("A2", "second.")]


def test_ignores_lines_when_not_an_entry() -> None:
    text = (
        b"## Amendments\n\n"
        b"A1 2026-10-20, Ana: no parentheses.\n"
        b"A2 (20-10-2026, Ana): not an ISO date.\n"
        b"See A3 (2026-10-20, Ana): not at the start.\n"
        b"\xff\xfe broken bytes\n"
    )

    assert plan_version(text) == PlanView(version=1, amendments=())


# Quality review B1, B2 (AGH-323): a long run of blanks is read in linear time. Sized so the old
# backtracking patterns took close to a minute; no timing assertion.
LONG_BLANKS = 50_000


def test_reads_heading_when_followed_by_long_blank_run() -> None:
    text = (
        b"## Amendments\n\n"
        + b"### a"
        + b" " * LONG_BLANKS
        + b"x\n"
        + b"A1 (2026-10-20, Ana): counted.\n"
    )

    assert [(a.id, a.anchor) for a in plan_version(text).amendments] == [("A1", "Amendments")]


def test_skips_entry_when_parenthesis_never_closes() -> None:
    text = (
        b"## Amendments\n\n"
        + b"A1 (2026-10-20, a"
        + b" " * LONG_BLANKS
        + b"x\n"
        + b"A2 (2026-10-21, Ana): the real one.\n"
    )

    found = plan_version(text)

    assert found.version == 2
    assert [(a.id, a.who) for a in found.amendments] == [("A2", "Ana")]
