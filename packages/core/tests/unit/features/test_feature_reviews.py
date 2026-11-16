"""Review records, ``reviews/<ticket>.md`` (AGH-136 S5, D4)."""

import pytest

from agent_hub.core.features.feature_reviews import (
    ReviewPullRequest,
    ReviewRecord,
    approved_tickets,
    review_pull_requests,
    review_records,
)
from agent_hub.core.features.feature_status import RecordHead

SLUG = "demo-feature"


def a_review(name: str, text: str) -> RecordHead:
    return RecordHead(name=name, head=text.encode(), problem=None)


def test_counts_approved_when_outcome_approved() -> None:
    heads = (
        a_review(
            "acme-1520.md",
            "---\ntype: review\nticket: ACME-1520\noutcome: approved\npr: demo-api#12\n"
            "reviewed_at: 2026-10-12\n---\n# Review\n",
        ),
        a_review("acme-1521.md", "---\nticket: ACME-1521\noutcome: changes-requested\n---\n"),
        a_review("t3.md", "---\noutcome: approved\n---\n"),
    )

    records = review_records(heads, slug=SLUG)

    assert records[0] == ReviewRecord(
        ticket="ACME-1520",
        path="features/demo-feature/reviews/acme-1520.md",
        outcome="approved",
        pr="demo-api#12",
        reviewed_at="2026-10-12",
        problem=None,
        prs=("demo-api#12",),
    )
    assert approved_tickets(records) == frozenset({"ACME-1520", "T3"})


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
    [record] = review_records((a_review("acme-1520.md", head),), slug=SLUG)

    assert record.problem is not None
    assert problem in record.problem
    assert record.outcome is None
    assert approved_tickets((record,)) == frozenset()


def test_reports_problem_when_head_unreadable() -> None:
    head = RecordHead(name="acme-1520.md", head=None, problem="not a regular file")

    [record] = review_records((head,), slug=SLUG)

    assert (record.ticket, record.problem, record.outcome) == (
        "acme-1520",
        "not a regular file",
        None,
    )


def test_reports_problem_when_name_not_a_ticket() -> None:
    [record] = review_records(
        (a_review("not a ticket.md", "---\noutcome: approved\n---\n"),), slug=SLUG
    )

    assert record.problem is not None
    assert "ticket" in record.problem


def _pr_review(ticket: str, pr: str) -> RecordHead:
    return a_review(
        f"{ticket}.md", f"---\ntype: review\nticket: {ticket}\noutcome: approved\npr: {pr}\n---\n"
    )


def test_links_pull_request_when_review_names_hub_repo() -> None:
    heads = (
        _pr_review("ACME-1", "demo-api#12"),
        _pr_review("ACME-2", "Demo-Web#7"),
        _pr_review("ACME-3", "https://github.com/acme/other/pull/3"),
        _pr_review("ACME-4", "demo-api#pending"),
        _pr_review("ACME-5", "unknown-repo#9"),
    )
    repos = {"demo-api": "acme/demo-api", "web": "acme/demo-web"}

    urls = review_pull_requests(review_records(heads, slug=SLUG), repos)

    assert urls == {
        "ACME-1": (ReviewPullRequest("demo-api", "https://github.com/acme/demo-api/pull/12"),),
        "ACME-2": (ReviewPullRequest("web", "https://github.com/acme/demo-web/pull/7"),),
        "ACME-3": (ReviewPullRequest(None, "https://github.com/acme/other/pull/3"),),
    }


def test_takes_later_record_when_ticket_reviewed_twice() -> None:
    heads = (
        _pr_review("ACME-1", "demo-api#12"),
        a_review(
            "acme-1-r2.md",
            "---\ntype: review\nticket: ACME-1\noutcome: approved\npr: demo-api#13\n---\n",
        ),
    )

    urls = review_pull_requests(review_records(heads, slug=SLUG), {"demo-api": "acme/demo-api"})

    assert urls == {
        "ACME-1": (ReviewPullRequest("demo-api", "https://github.com/acme/demo-api/pull/13"),)
    }


def test_links_no_pull_request_when_review_malformed() -> None:
    heads = (
        a_review(
            "acme-1.md",
            "---\nticket: ACME-1\noutcome: approved\npr: demo-api#12\nreviewed_at: soon\n---\n",
        ),
    )

    records = review_records(heads, slug=SLUG)

    assert records[0].problem is not None
    assert review_pull_requests(records, {"demo-api": "acme/demo-api"}) == {}


# AGH-592: a ticket that owns several repos lists one pull request per repo, in merge order.
def test_links_every_pull_request_in_order_when_review_lists_prs() -> None:
    heads = (
        a_review(
            "ACME-1.md",
            "---\ntype: review\nticket: ACME-1\noutcome: approved\n"
            "prs: [demo-api#101, https://github.com/acme/demo-web/pull/55]\n---\n",
        ),
        _pr_review("ACME-2", "demo-api#12"),
    )
    repos = {"demo-api": "acme/demo-api", "web": "acme/demo-web"}

    records = review_records(heads, slug=SLUG)
    urls = review_pull_requests(records, repos)

    assert records[0].prs == ("demo-api#101", "https://github.com/acme/demo-web/pull/55")
    assert records[0].pr == "demo-api#101"
    assert records[1].prs == ("demo-api#12",)
    assert urls == {
        "ACME-1": (
            ReviewPullRequest(repo="demo-api", url="https://github.com/acme/demo-api/pull/101"),
            ReviewPullRequest(repo="web", url="https://github.com/acme/demo-web/pull/55"),
        ),
        "ACME-2": (
            ReviewPullRequest(repo="demo-api", url="https://github.com/acme/demo-api/pull/12"),
        ),
    }


def test_reports_problem_when_review_gives_pr_and_prs() -> None:
    head = a_review(
        "ACME-1.md",
        "---\ntype: review\nticket: ACME-1\noutcome: approved\npr: demo-api#1\n"
        "prs: [demo-api#1]\n---\n",
    )

    (record,) = review_records((head,), slug=SLUG)

    assert record.problem == "give pr or prs, not both"
