import pytest

from agent_hub.core.brain.frontmatter import (
    first_paragraph,
    split_frontmatter,
    with_frontmatter,
)

NOTE = """---
type: learning
provenance: agent
tags: [testing, ci]
target: "learnings/gotchas/"
---
# Run the migrations check

Run `make migrations` before
the PR.

Second paragraph.
"""


def test_splits_fields_when_note_has_frontmatter() -> None:
    front = split_frontmatter(NOTE)

    assert front.fields == {
        "type": "learning",
        "provenance": "agent",
        "tags": ["testing", "ci"],
        "target": "learnings/gotchas/",
    }
    assert front.body.startswith("# Run the migrations check\n")
    assert front.problem is None


def test_reads_block_list_when_values_indented() -> None:
    front = split_frontmatter("---\nsources:\n  - a.md\n  - b.md\nkind: x\n---\nbody\n")

    assert front.fields == {"sources": ["a.md", "b.md"], "kind": "x"}
    assert front.body == "body\n"


def test_returns_whole_text_when_note_has_no_frontmatter() -> None:
    front = split_frontmatter("# Title\n\ntext\n")

    assert (front.fields, front.body, front.problem) == ({}, "# Title\n\ntext\n", None)


@pytest.mark.parametrize(
    "text",
    [
        "---\ntype: learning\n# no closing fence\n",
        "---\nnot a field\n---\nbody\n",
        "---\n" + "k: v\n" * 70 + "---\nbody\n",
        "---\nk: " + "v" * 9000 + "\n---\nbody\n",
    ],
    ids=["unclosed", "no-colon", "too-many-lines", "too-large"],
)
def test_reports_problem_when_frontmatter_malformed(text: str) -> None:
    front = split_frontmatter(text)

    assert front.fields == {}
    assert front.body == text
    assert front.problem


def test_rewrites_status_when_fields_updated() -> None:
    updated = with_frontmatter(
        "---\ntype: learning\nstatus: proposed\nsources:\n  - a.md\n# kept comment\n---\nbody\n",
        {"status": "accepted", "last_verified": "2026-10-12", "sources": "b.md"},
    )

    assert updated == (
        "---\ntype: learning\nstatus: accepted\nsources: b.md\n# kept comment\n"
        "last_verified: 2026-10-12\n---\nbody\n"
    )


def test_adds_frontmatter_when_note_has_none() -> None:
    assert with_frontmatter("# T\n", {"status": "rejected"}) == "---\nstatus: rejected\n---\n# T\n"


def test_quotes_value_when_reason_has_special_characters() -> None:
    reason = 'Duplicate of "x": see #12\nand more'

    updated = with_frontmatter(NOTE, {"rejected_reason": reason})

    assert 'rejected_reason: "Duplicate of \\"x\\": see #12 and more"\n' in updated
    assert split_frontmatter(updated).fields["rejected_reason"] == (
        'Duplicate of "x": see #12 and more'
    )


def test_clips_first_paragraph_when_paragraph_is_long() -> None:
    body = "# Title\n\n" + "word " * 100 + "\n\nnext"

    paragraph = first_paragraph(body, limit=200)

    assert len(paragraph) == 200
    assert paragraph.endswith("…")


def test_joins_lines_when_first_paragraph_wraps() -> None:
    assert first_paragraph(split_frontmatter(NOTE).body) == "Run `make migrations` before the PR."


def test_returns_empty_when_body_has_only_headings() -> None:
    assert first_paragraph("# Title\n\n## Sub\n") == ""
