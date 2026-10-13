"""Review records, ``reviews/<ticket>.md`` (AGH-136 S5, D4)."""

import pytest

from agent_hub.core.features.feature_reviews import (
    ReviewRecord,
    approved_tickets,
    review_records,
)
from agent_hub.core.features.feature_status import RecordHead

SLUG = "demo-feature"


def a_review(name: str, text: str) -> RecordHead:
    return RecordHead(name=name, head=text.encode(), problem=None)


def test_counts_approved_when_outcome_approved() -> None:
    heads = (
        a_review(
            "demo-1520.md",
            "---\ntype: review\nticket: DEMO-1520\noutcome: approved\npr: demo-api#12\n"
            "reviewed_at: 2026-10-12\n---\n# Review\n",
        ),
        a_review("demo-1521.md", "---\nticket: DEMO-1521\noutcome: changes-requested\n---\n"),
        a_review("t3.md", "---\noutcome: approved\n---\n"),
    )

    records = review_records(heads, slug=SLUG)

    assert records[0] == ReviewRecord(
        ticket="DEMO-1520",
        path="features/demo-feature/reviews/demo-1520.md",
        outcome="approved",
        pr="demo-api#12",
        reviewed_at="2026-10-12",
        problem=None,
    )
    assert approved_tickets(records) == frozenset({"DEMO-1520", "T3"})


@pytest.mark.parametrize(
    ("head", "problem"),
    [
        ("# Review\n\nLooks good.\n", "no frontmatter"),
        ("---\noutcome: approved\n", "not closed"),
        ("---\noutcome: lgtm\n---\n", "outcome"),
        ("---\noutcome: approved\ntype: eval\n---\n", "type"),
        ("---\noutcome: approved\nticket: [A, B]\n---\n", "ticket"),
        ("---\noutcome: approved\nreviewed_at: soon\n---\n", "reviewed_at"),
    ],
    ids=["absent", "unclosed", "outcome", "type", "list-ticket", "date"],
)
def test_reports_problem_when_review_malformed(head: str, problem: str) -> None:
    [record] = review_records((a_review("demo-1520.md", head),), slug=SLUG)

    assert record.problem is not None
    assert problem in record.problem
    assert record.outcome is None
    assert approved_tickets((record,)) == frozenset()


def test_reports_problem_when_head_unreadable() -> None:
    head = RecordHead(name="demo-1520.md", head=None, problem="not a regular file")

    [record] = review_records((head,), slug=SLUG)

    assert (record.ticket, record.problem, record.outcome) == (
        "demo-1520",
        "not a regular file",
        None,
    )


def test_reports_problem_when_name_not_a_ticket() -> None:
    [record] = review_records(
        (a_review("not a ticket.md", "---\noutcome: approved\n---\n"),), slug=SLUG
    )

    assert record.problem is not None
    assert "ticket" in record.problem
