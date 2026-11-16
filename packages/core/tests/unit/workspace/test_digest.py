from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from agent_hub.core.claims.claim import MAX_QUESTION, Claim
from agent_hub.core.workspace.digest import (
    ITEM_CAP,
    MAX_ITEMS,
    Digest,
    DigestInput,
    build_digest,
    digest_lines,
)

NOW = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)
HUB = "/work/acme-hub"
# A limit no test reaches, so every item shows.
ALL = 50


def _at(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()


def ticket(
    ticket_id: str = "DEM-1",
    *,
    title: str = "Login form",
    state: str = "In Progress",
    claim: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": ticket_id,
        "title": title,
        "state": state,
        "url": f"https://linear.example/DEM/issue/{ticket_id}",
        "claim": claim,
    }


def input_claim(
    *,
    session: str = "s-cloud",
    live: bool = True,
    question: str | None = None,
    asked_hours_ago: float | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    return {
        "session": session,
        "link": f"https://claude.example/code/{session}",
        "live": live,
        "question": question,
        "asked_at": None if asked_hours_ago is None else _at(asked_hours_ago),
        "title": title,
    }


def pr(
    number: int = 41,
    *,
    repo: str = "acme/api",
    title: str = "Add login form",
    branch: str = "feature/login",
    draft: bool = False,
    updated_hours_ago: float = 48,
    mergeable_state: str = "clean",
    checks: dict[str, int] | None = None,
    unresolved_threads: int = 0,
) -> dict[str, Any]:
    return {
        "repo": repo,
        "number": number,
        "title": title,
        "url": f"https://github.example/{repo}/pull/{number}",
        "branch": branch,
        "draft": draft,
        "updated_at": _at(updated_hours_ago),
        "mergeable_state": mergeable_state,
        "checks": {"success": 3, "skipped": 1} if checks is None else checks,
        "unresolved_threads": unresolved_threads,
    }


def source(
    tickets: list[dict[str, Any]] | None = None, prs: list[dict[str, Any]] | None = None
) -> DigestInput:
    return DigestInput.model_validate(
        {"version": 1, "read_at": _at(0.1), "tickets": tickets or [], "prs": prs or []}
    )


def local_claim(
    ticket_id: str = "DEM-1",
    *,
    session: str = "s-local",
    pid: int | None = 4242,
    activity_hours_ago: float = 1,
    question: str | None = None,
    asked_hours_ago: float | None = None,
    title: str | None = None,
) -> Claim:
    return Claim(
        ticket=ticket_id,
        session=session,
        pid=pid,
        started=None if pid is None else "Mon Nov 16 07:00:00 2026",
        hub=HUB,
        claimed_at=NOW - timedelta(hours=30),
        last_activity=NOW - timedelta(hours=activity_hours_ago),
        question=question,
        asked_at=None if asked_hours_ago is None else NOW - timedelta(hours=asked_hours_ago),
        title=title,
    )


def lines(
    digest_source: DigestInput, claims: tuple[Claim, ...] = (), *, limit: int = ALL
) -> tuple[str, ...]:
    return digest_lines(build_digest(digest_source, claims, NOW), limit=limit)


def section(all_lines: tuple[str, ...], name: str) -> list[str]:
    """The item lines under the ``<name>:`` line, up to the next section line."""
    if f"{name}:" not in all_lines:
        return []
    start = all_lines.index(f"{name}:") + 1
    items: list[str] = []
    for line in all_lines[start:]:
        if not line.startswith("- "):
            break
        items.append(line)
    return items


def idle_tickets(digest: Digest) -> list[str]:
    return [item.ticket for item in digest.idle]


# AC-25: sessions waiting on the owner.


def test_lists_waiting_sessions_oldest_first_when_questions_recorded() -> None:
    claims = (
        local_claim(
            "DEM-1", question="Merge #41?", asked_hours_ago=2, title="DEM-1 login", pid=4242
        ),
    )
    digest_source = source(
        tickets=[
            ticket("DEM-1"),
            ticket(
                "DEM-2",
                title="Signup",
                claim=input_claim(
                    session="s-cloud",
                    question="Which plan tier?",
                    asked_hours_ago=5,
                    title="DEM-2 signup",
                ),
            ),
        ]
    )

    waiting = section(lines(digest_source, claims), "Sessions waiting on you")

    assert waiting == [
        "- DEM-2 signup (DEM-2): Which plan tier? https://claude.example/code/s-cloud",
        f"- DEM-1 login (DEM-1): Merge #41? local, {HUB}, pid 4242",
    ]


def test_prefers_local_claim_when_both_name_the_ticket() -> None:
    claims = (local_claim(question="Local question?", asked_hours_ago=1, title="Local title"),)
    digest_source = source(
        tickets=[
            ticket(
                "DEM-1",
                claim=input_claim(
                    question="Cloud question?", asked_hours_ago=3, title="Cloud title"
                ),
            )
        ]
    )

    digest = build_digest(digest_source, claims, NOW)

    assert [(item.ticket, item.question) for item in digest.waiting] == [
        ("DEM-1", "Local question?")
    ]
    assert section(digest_lines(digest, limit=ALL), "Sessions waiting on you") == [
        f"- Local title (DEM-1): Local question? local, {HUB}, pid 4242"
    ]


def test_names_session_id_when_claim_has_no_title() -> None:
    digest_source = source(
        tickets=[
            ticket(
                "DEM-3",
                claim=input_claim(session="s-9", question="Ship it?", asked_hours_ago=1),
            )
        ]
    )

    assert section(lines(digest_source), "Sessions waiting on you") == [
        "- session s-9 (DEM-3): Ship it? https://claude.example/code/s-9"
    ]


def test_links_local_hub_and_pid_when_claim_is_local() -> None:
    with_pid = local_claim("DEM-1", question="One?", asked_hours_ago=2, title="A", pid=77)
    without_pid = local_claim(
        "DEM-2", session="s-2", question="Two?", asked_hours_ago=1, title="B", pid=None
    )

    digest_source = source(tickets=[ticket("DEM-1"), ticket("DEM-2")])

    waiting = section(lines(digest_source, (with_pid, without_pid)), "Sessions waiting on you")

    assert waiting == [
        f"- A (DEM-1): One? local, {HUB}, pid 77",
        f"- B (DEM-2): Two? local, {HUB}",
    ]


def test_omits_local_waiting_claim_when_ticket_not_in_input() -> None:
    # DEM-9 is Done, so the session's input no longer lists it; its claim was never released.
    claims = (local_claim("DEM-9", question="Merge #41?", asked_hours_ago=50, title="Old"),)
    digest_source = source(tickets=[ticket("DEM-1")])

    digest = build_digest(digest_source, claims, NOW)

    assert digest.waiting == ()
    assert idle_tickets(digest) == ["DEM-1"]


def test_builds_digest_when_local_waiting_claims_outnumber_max_items_off_input() -> None:
    claims = tuple(
        local_claim(f"DEM-{n}", session=f"s-{n}", question="Go?", asked_hours_ago=1)
        for n in range(1, 2 * MAX_ITEMS + 2)
    )

    digest = build_digest(source(), claims, NOW)

    assert digest.waiting == ()


# AC-26: tickets no one is on.


def test_lists_ticket_when_unclaimed_and_no_pr_moved_in_a_day() -> None:
    digest_source = source(
        tickets=[
            ticket("DEM-10", title="Audit log", state="In Review"),
            ticket("DEM-2", title="Signup", state="In Progress"),
        ],
        prs=[pr(updated_hours_ago=1, title="Unrelated", branch="chore/deps")],
    )

    digest = build_digest(digest_source, (), NOW)

    assert idle_tickets(digest) == ["DEM-2", "DEM-10"]
    assert section(digest_lines(digest, limit=ALL), "Tickets no one is on") == [
        "- DEM-2 Signup (In Progress) https://linear.example/DEM/issue/DEM-2",
        "- DEM-10 Audit log (In Review) https://linear.example/DEM/issue/DEM-10",
    ]


@pytest.mark.parametrize(
    ("claim", "claims"),
    [
        (input_claim(live=True), ()),
        (None, (local_claim(pid=4242, activity_hours_ago=2),)),
        (None, (local_claim(pid=None, activity_hours_ago=2),)),
    ],
    ids=["input_live", "local_pid", "local_recent"],
)
def test_omits_ticket_when_claim_live(
    claim: dict[str, Any] | None, claims: tuple[Claim, ...]
) -> None:
    digest_source = source(tickets=[ticket("DEM-1", claim=claim)])

    assert idle_tickets(build_digest(digest_source, claims, NOW)) == []


@pytest.mark.parametrize(
    ("claim", "claims"),
    [
        (input_claim(live=False), ()),
        (None, (local_claim(pid=None, activity_hours_ago=25),)),
        (None, (local_claim(pid=4242, activity_hours_ago=25),)),
    ],
    ids=["input_not_live", "local_no_pid_25h", "local_pid_25h"],
)
def test_lists_ticket_when_claim_stale(
    claim: dict[str, Any] | None, claims: tuple[Claim, ...]
) -> None:
    digest_source = source(tickets=[ticket("DEM-1", claim=claim)])

    assert idle_tickets(build_digest(digest_source, claims, NOW)) == ["DEM-1"]


@pytest.mark.parametrize(
    ("title", "branch"),
    [("DEM-1: login form", "feature/login"), ("Login form", "roquette/dem-1-login")],
    ids=["title", "branch_lowercase"],
)
def test_omits_ticket_when_pr_naming_it_moved_within_a_day(title: str, branch: str) -> None:
    digest_source = source(
        tickets=[ticket("DEM-1")],
        prs=[pr(title=title, branch=branch, updated_hours_ago=23, draft=True)],
    )

    assert idle_tickets(build_digest(digest_source, (), NOW)) == []


def test_lists_ticket_when_pr_naming_it_moved_25h_ago() -> None:
    digest_source = source(
        tickets=[ticket("DEM-1")],
        prs=[pr(title="DEM-1: login form", updated_hours_ago=25, draft=True)],
    )

    assert idle_tickets(build_digest(digest_source, (), NOW)) == ["DEM-1"]


@pytest.mark.parametrize(
    ("claim", "claims"),
    [
        (input_claim(live=False, question="Ship it?", asked_hours_ago=30), ()),
        (
            None,
            (
                local_claim(
                    pid=4242, activity_hours_ago=30, question="Ship it?", asked_hours_ago=30
                ),
            ),
        ),
    ],
    ids=["input_not_live", "local_stale"],
)
def test_omits_ticket_from_idle_when_listed_as_waiting(
    claim: dict[str, Any] | None, claims: tuple[Claim, ...]
) -> None:
    digest_source = source(tickets=[ticket("DEM-1", claim=claim)])

    digest = build_digest(digest_source, claims, NOW)

    assert [item.ticket for item in digest.waiting] == ["DEM-1"]
    assert idle_tickets(digest) == []


# AC-27: pull requests ready to merge.


def test_lists_ready_prs_in_one_section_when_clean_green_and_no_thread() -> None:
    digest_source = source(
        prs=[
            pr(12, repo="acme/web", title="Fix header"),
            pr(41, repo="acme/api", title="Add login form"),
            pr(7, repo="acme/api", title="Bump deps", checks={"success": 2, "neutral": 1}),
        ]
    )

    all_lines = lines(digest_source)

    assert section(all_lines, "Ready to merge") == [
        "- acme/api#7 Bump deps https://github.example/acme/api/pull/7",
        "- acme/api#41 Add login form https://github.example/acme/api/pull/41",
        "- acme/web#12 Fix header https://github.example/acme/web/pull/12",
    ]
    assert all_lines.count("Ready to merge:") == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"draft": True},
        {"mergeable_state": "blocked"},
        {"mergeable_state": "dirty"},
        {"checks": {"success": 3, "failure": 1}},
        {"checks": {"success": 3, "pending": 1}},
        {"unresolved_threads": 1},
    ],
    ids=["draft", "blocked", "dirty", "failing_check", "pending_check", "unresolved_thread"],
)
def test_omits_pr_when_not_ready(changes: dict[str, Any]) -> None:
    digest = build_digest(source(prs=[pr(**changes)]), (), NOW)

    assert digest.ready == ()


# AC-28: nothing waits.


def test_prints_one_line_when_nothing_waits() -> None:
    assert lines(source()) == ("Owner digest 2026-11-16: nothing waits on you.",)


# The digest's shape.


def test_orders_sections_waiting_idle_ready_when_all_present() -> None:
    digest_source = source(
        tickets=[
            ticket("DEM-1"),
            ticket("DEM-2", claim=input_claim(question="Go?", asked_hours_ago=1, title="T")),
        ],
        prs=[pr(41)],
    )

    all_lines = lines(digest_source)

    assert all_lines[0] == "Owner digest 2026-11-16"
    headers = [line for line in all_lines[1:] if not line.startswith("- ")]
    assert headers == ["Sessions waiting on you:", "Tickets no one is on:", "Ready to merge:"]


def test_caps_section_and_counts_rest_when_over_limit() -> None:
    digest_source = source(prs=[pr(number) for number in range(1, 6)])

    assert section(lines(digest_source, limit=3), "Ready to merge") == [
        "- acme/api#1 Add login form https://github.example/acme/api/pull/1",
        "- acme/api#2 Add login form https://github.example/acme/api/pull/2",
        "- acme/api#3 Add login form https://github.example/acme/api/pull/3",
        "- …and 2 more",
    ]


def test_cuts_item_line_when_longer_than_item_cap() -> None:
    long_title = "x" * 400
    claims = (local_claim(question="Merge?", asked_hours_ago=1, title=long_title),)

    (item,) = section(lines(source(tickets=[ticket("DEM-1")]), claims), "Sessions waiting on you")

    assert len(item) <= ITEM_CAP
    assert item.startswith("- xxxx")


def test_keeps_ticket_and_link_whole_when_waiting_line_over_item_cap() -> None:
    session = "s-" + "a" * 30
    link = f"https://claude.example/code/{session}"
    assert len(link) == 60
    question = "q" * MAX_QUESTION
    digest_source = source(
        tickets=[
            ticket(
                "DEM-1",
                claim=input_claim(
                    session=session, question=question, asked_hours_ago=1, title="Login form"
                ),
            )
        ]
    )

    (item,) = section(lines(digest_source), "Sessions waiting on you")

    assert len(item) <= ITEM_CAP
    assert item.startswith("- Login form (DEM-1): qqq")
    assert item.endswith(f"… {link}")


def test_cuts_title_after_question_when_waiting_line_still_over_item_cap() -> None:
    link = "https://claude.example/code/s-cloud"
    digest_source = source(
        tickets=[
            ticket(
                "DEM-1",
                claim=input_claim(question="Merge?", asked_hours_ago=1, title="t" * 400),
            )
        ]
    )

    (item,) = section(lines(digest_source), "Sessions waiting on you")

    assert len(item) == ITEM_CAP
    assert item.endswith(f"… (DEM-1): … {link}")


def test_keeps_url_whole_when_idle_line_over_item_cap() -> None:
    url = "https://linear.example/DEM/issue/DEM-1"
    digest_source = source(tickets=[ticket("DEM-1", title="t" * 400)])

    (item,) = section(lines(digest_source), "Tickets no one is on")

    assert len(item) <= ITEM_CAP
    assert item.startswith("- DEM-1 ttt")
    assert item.endswith(f"… (In Progress) {url}")


def test_keeps_url_whole_when_ready_line_over_item_cap() -> None:
    url = "https://github.example/acme/api/pull/41"
    digest_source = source(prs=[pr(41, title="t" * 400)])

    (item,) = section(lines(digest_source), "Ready to merge")

    assert len(item) <= ITEM_CAP
    assert item.startswith("- acme/api#41 ttt")
    assert item.endswith(f"… {url}")


def test_strips_control_characters_when_input_text_has_them() -> None:
    digest_source = source(
        tickets=[ticket("DEM-1", title="Login\x1b[31m form\x07\x00", state="In\tProgress")],
        prs=[pr(41, title="Add\r\nlogin\x7f form")],
    )

    all_lines = lines(digest_source)

    for line in all_lines:
        assert not any(ord(char) < 32 or ord(char) == 127 for char in line), repr(line)
    (idle_line,) = section(all_lines, "Tickets no one is on")
    (ready_line,) = section(all_lines, "Ready to merge")
    assert "Login" in idle_line and "form" in idle_line
    assert "Add" in ready_line and "login" in ready_line


@pytest.mark.parametrize(
    "document",
    [
        {
            "version": 1,
            "read_at": _at(0),
            "tickets": [ticket(f"DEM-{n}") for n in range(1, 202)],
            "prs": [],
        },
        {
            "version": 1,
            "read_at": _at(0),
            "tickets": [],
            "prs": [pr(n) for n in range(1, 202)],
        },
        {"version": 2, "read_at": _at(0), "tickets": [], "prs": []},
        {"version": 1, "read_at": _at(0), "tickets": [], "prs": [], "extra": True},
    ],
    ids=["tickets_201", "prs_201", "version_2", "extra_field"],
)
def test_refuses_input_when_over_bounds(document: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        DigestInput.model_validate(document)
