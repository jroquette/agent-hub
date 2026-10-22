"""A feature's ticket records and plan change requests (two-level-flows AC-2.5, AC-2.8, AC-2.14,
AC-3.1, AC-3.3): read into what the folds need, a malformed file kept as its problem."""

import json
from datetime import UTC, datetime

import pytest

from agent_hub.core.features.feature_status import RecordHead
from agent_hub.core.features.feature_view import ChangeDecisionView
from agent_hub.core.features.ticket_records import (
    CHANGE_REQUEST_HEAD_BYTES,
    MAX_CHANGE_REQUEST_FILES,
    MAX_OUTCOME_BYTES,
    MAX_PREFLIGHT_BYTES,
    ChangeRequest,
    OutcomeFile,
    TicketOutcome,
    already_read,
    change_requests,
    outcome_record,
    preflight_record,
    recorded_outcomes,
    request_view,
    ticket_folder,
)


def a_request(
    n: int = 1, *, ticket: str = "DEM-8", proposal: str = "", **fields: str
) -> RecordHead:
    values = {
        "type": "change-request",
        "ticket": ticket,
        "status": "open",
        "plan_from": "2",
        "plan_to": "3",
        "affected": "[DEM-9]",
        "opened_at": "2026-10-21T09:30:00Z",
        "run_id": "implement-8",
    } | fields
    front = "".join(f"{key}: {value}\n" for key, value in values.items())
    text = f"---\n{front}---\n# Plan change request {n}\n{proposal}"
    return RecordHead(name=f"{n}.md", head=text.encode(), problem=None)


def a_decision(n: int = 1, decision: str = "approved", **fields: str) -> RecordHead:
    values = {
        "type": "change-request-decision",
        "decision": decision,
        "decided_by": "Dana Owner",
        "decided_at": "2026-10-21T10:00:00Z",
        "note": "Go ahead.",
    } | fields
    front = "".join(f"{key}: {value}\n" for key, value in values.items())
    return RecordHead(name=f"{n}.decision.md", head=f"---\n{front}---\n".encode(), problem=None)


def a_preflight(**run: object) -> bytes:
    entry: dict[str, object] = {
        "ran_at": "2026-10-21T09:30:00Z",
        "plan_version": 2,
        "commit": "4e1a9c2",
        "blockers_read": [],
        "input": "none",
        "input_text": None,
        "drift": "none",
        "local_notes": [],
        "change_request": None,
        "run_id": "implement-8",
    }
    return json.dumps(
        {"schema": "agent-hub/preflight/1", "ticket": "DEM-8", "runs": [entry | run]}
    ).encode()


def test_reads_open_when_request_has_no_decision() -> None:
    found = change_requests((a_request(),), skipped=0)

    assert found.requests == (
        ChangeRequest(
            n=1,
            ticket="DEM-8",
            status="open",
            plan_to=3,
            affected=("DEM-9",),
            problem=None,
            plan_from=2,
            opened_at="2026-10-21T09:30:00Z",
            run_id="implement-8",
            body="# Plan change request 1\n",
        ),
    )
    assert found.problem is None


# Q13: a request longer than the head read says so: the panel never shows a cut one as whole.
def test_marks_body_cut_when_head_full() -> None:
    long = a_request(proposal="x" * CHANGE_REQUEST_HEAD_BYTES)
    head = long.head[:CHANGE_REQUEST_HEAD_BYTES] if long.head else b""
    cut = RecordHead(name=long.name, head=head, problem=None)

    (whole,) = change_requests((a_request(),), skipped=0).requests
    (request,) = change_requests((cut,), skipped=0).requests

    assert (whole.body_cut, request.body_cut) == (False, True)


# Q15: the ticket route's view carries the cut flag with the body; the detail serves neither.
def test_serves_body_cut_only_with_body_when_viewed() -> None:
    long = a_request(proposal="x" * CHANGE_REQUEST_HEAD_BYTES)
    cut = RecordHead(
        name=long.name, head=(long.head or b"")[:CHANGE_REQUEST_HEAD_BYTES], problem=None
    )
    (request,) = change_requests((cut,), skipped=0).requests

    assert request_view(request, slug="demo", body=True).body_cut is True
    assert request_view(request, slug="demo").body_cut is False


# Q19: only a cut head drops the replacement mark a split character leaves; a whole body keeps it.
def test_strips_split_character_only_when_head_cut() -> None:
    prefix = len(a_request().head or b"")
    # The head ends inside the two-byte "é": its first byte alone decodes to U+FFFD.
    long = a_request(proposal="x" * (CHANGE_REQUEST_HEAD_BYTES - prefix - 1) + "éé")
    cut = RecordHead(
        name=long.name, head=(long.head or b"")[:CHANGE_REQUEST_HEAD_BYTES], problem=None
    )
    whole = a_request(proposal="ends with \ufffd")

    (cut_request,) = change_requests((cut,), skipped=0).requests
    (whole_request,) = change_requests((whole,), skipped=0).requests

    assert cut_request.body is not None and not cut_request.body.rstrip().endswith("\ufffd")
    assert whole_request.body is not None and whole_request.body.rstrip().endswith("\ufffd")


# AGH-405 (S2-T7): hub web shows who decided a request, when and with what note.
def test_reads_decision_when_decision_file_exists() -> None:
    (request,) = change_requests((a_request(), a_decision(decision="declined")), skipped=0).requests

    assert request.decision == ChangeDecisionView(
        decision="declined",
        decided_by="Dana Owner",
        decided_at="2026-10-21T10:00:00Z",
        note="Go ahead.",
    )


def test_reads_no_note_when_decision_note_empty() -> None:
    (request,) = change_requests((a_request(), a_decision(note='""')), skipped=0).requests

    assert request.decision is not None
    assert request.decision.note is None


def test_folds_decision_into_status_when_decision_file_exists() -> None:
    found = change_requests(
        (a_decision(1), a_request(1), a_request(2), a_decision(2, "declined")), skipped=0
    )

    assert [(request.n, request.status) for request in found.requests] == [
        (1, "approved"),
        (2, "declined"),
    ]


def test_orders_requests_by_number_when_names_sort_otherwise() -> None:
    found = change_requests((a_request(10), a_request(2)), skipped=0)

    assert [request.n for request in found.requests] == [2, 10]


def test_ignores_other_names_when_folder_holds_notes() -> None:
    note = RecordHead(name="README.md", head=b"# Notes\n", problem=None)

    assert change_requests((note, a_decision(4)), skipped=0).requests == ()


def test_keeps_problem_when_request_malformed() -> None:
    found = change_requests((a_request(3, plan_to="three"),), skipped=0)

    (request,) = found.requests
    assert request.status is None
    assert request.ticket == "DEM-8"
    assert request.problem == (
        "change-requests/3.md could not be read (plan_to is not valid: three). Fix it in a hub PR."
    )


def test_refuses_edited_status_when_request_says_approved() -> None:
    (request,) = change_requests((a_request(status="approved"),), skipped=0).requests

    assert request.problem == (
        "change-requests/1.md could not be read (status must be open: a decision is its own "
        "file). Fix it in a hub PR."
    )


# AGH-402 review S4: a broken decision does not make the request known decided: it stays open.
def test_keeps_request_open_with_problem_when_decision_malformed() -> None:
    found = change_requests((a_request(), a_decision(decision="maybe")), skipped=0)

    (request,) = found.requests
    assert (request.status, request.ticket, request.plan_to) == ("open", "DEM-8", 3)
    assert request.problem == (
        "change-requests/1.decision.md could not be read (decision must be approved or "
        "declined). Fix it in a hub PR."
    )
    assert found.open == (request,)
    assert found.paused == frozenset({"DEM-8", "DEM-9"})


# AGH-402 review Q2: each validation branch of a request, by its problem line.
@pytest.mark.parametrize(
    ("fields", "why"),
    [
        ({"ticket": ""}, "ticket is missing"),
        ({"ticket": "dem 8"}, "ticket is not valid: dem 8"),
        ({"plan_to": ""}, "plan_to is missing"),
        ({"type": "eval"}, "type is eval, not change-request"),
        ({"affected": "[DEM-9, dem 10]"}, "affected has an invalid item: dem 10"),
    ],
    ids=["no ticket", "bad ticket", "no plan_to", "wrong type", "bad affected"],
)
def test_names_problem_when_request_field_invalid(fields: dict[str, str], why: str) -> None:
    (request,) = change_requests((a_request(3, **fields),), skipped=0).requests

    assert request.status is None
    assert request.problem == f"change-requests/3.md could not be read ({why}). Fix it in a hub PR."


# AGH-402 review Q2, Q7 (A5): each validation branch of a decision, by its problem line.
@pytest.mark.parametrize(
    ("fields", "why"),
    [
        ({"type": "eval"}, "type is eval, not change-request-decision"),
        ({"decided_by": ""}, "decided_by is missing"),
        ({"decided_by": " Unknown "}, "decided_by names no person: Unknown"),
        ({"decided_at": ""}, "decided_at is missing"),
    ],
    ids=["wrong type", "no decided_by", "unknown decided_by", "no decided_at"],
)
def test_names_problem_when_decision_field_invalid(fields: dict[str, str], why: str) -> None:
    (request,) = change_requests((a_request(), a_decision(**fields)), skipped=0).requests

    assert request.status == "open"
    assert request.problem == (
        f"change-requests/1.decision.md could not be read ({why}). Fix it in a hub PR."
    )


def test_keeps_problem_when_request_unreadable() -> None:
    link = RecordHead(name="1.md", head=None, problem="not read as a regular file")

    (request,) = change_requests((link,), skipped=0).requests

    assert request.ticket is None
    assert request.problem == (
        "change-requests/1.md could not be read (not read as a regular file). Fix it in a hub PR."
    )


def test_says_not_all_read_when_files_over_cap() -> None:
    found = change_requests((a_request(),), skipped=1)

    assert found.problem == (
        f"more than {MAX_CHANGE_REQUEST_FILES} files in change-requests/; not all were read. "
        "Fix it in a hub PR."
    )


def test_lists_open_requests_and_paused_tickets_when_folded() -> None:
    found = change_requests(
        (a_request(1), a_decision(1), a_request(2, ticket="dem-10", affected="[DEM-8, DEM-11]")),
        skipped=0,
    )

    assert [request.n for request in found.open] == [2]
    assert found.paused == frozenset({"DEM-10", "DEM-8", "DEM-11"})
    assert found.approved_version == 3


def test_parses_record_when_preflight_valid() -> None:
    record = preflight_record(
        a_preflight(drift="local", local_notes=["Moved helper."]), folder="DEM-8"
    )

    assert not isinstance(record, str)
    assert record is not None
    assert record.runs[-1].local_notes == ("Moved helper.",)


def test_names_json_path_when_preflight_malformed() -> None:
    assert preflight_record(a_preflight(drift="global"), folder="DEM-8") == (
        "preflight.json could not be read (runs[0].drift: Input should be 'none', 'local' or "
        "'plan'). Fix it in a hub PR."
    )


def test_says_why_when_preflight_not_read() -> None:
    assert preflight_record(f"larger than {MAX_PREFLIGHT_BYTES} bytes", folder="DEM-8") == (
        "preflight.json could not be read (larger than 65536 bytes). Fix it in a hub PR."
    )
    assert preflight_record(None, folder="DEM-8") is None


# AGH-402 review Q9: a record filed under another ticket's folder drives no step.
def test_names_mismatch_when_preflight_ticket_differs_from_folder() -> None:
    assert preflight_record(a_preflight(), folder="DEM-9") == (
        "preflight.json could not be read (ticket: DEM-8 is not the folder's ticket DEM-9). "
        "Fix it in a hub PR."
    )
    assert not isinstance(preflight_record(a_preflight(), folder="dem-8"), str)


def test_picks_the_folder_the_flow_reads_when_key_and_id_folders_differ_in_case() -> None:
    folders = ["t2", "dem-8", "DEM-8x", "T2", "DEM-7"]

    assert ticket_folder(folders, ("T2", "DEM-8")) == "dem-8"
    assert ticket_folder(folders, ("T2",)) == "T2"
    assert ticket_folder(folders, ("T9",)) is None


def an_outcome(**fields: str) -> bytes:
    values = {
        "type": "ticket-outcome",
        "ticket": "DEM-7",
        "merged_at": "2026-10-22T08:00:00Z",
        "pr": "https://github.com/acme/demo-api/pull/4",
        "dependents": "[DEM-8, T3]",
    } | fields
    front = "".join(f"{key}: {value}\n" for key, value in values.items() if value != "-")
    return f"---\n{front}---\n\n# Outcome: DEM-7\n\n## What was built\n\nThe reader.\n".encode()


# AC-3.1: the outcome's frontmatter, read as the Merged step and Build need it.
def test_reads_merged_at_pr_and_dependents_when_outcome_recorded() -> None:
    assert outcome_record(an_outcome(), folder="dem-7") == TicketOutcome(
        ticket="DEM-7",
        merged_at=datetime(2026, 10, 22, 8, 0, tzinfo=UTC),
        pr="https://github.com/acme/demo-api/pull/4",
        dependents=("DEM-8", "T3"),
    )
    assert outcome_record(an_outcome(dependents="[]", pr="demo-api#4"), folder="DEM-7") == (
        TicketOutcome(
            ticket="DEM-7",
            merged_at=datetime(2026, 10, 22, 8, 0, tzinfo=UTC),
            pr="demo-api#4",
            dependents=(),
        )
    )
    assert outcome_record(None, folder="DEM-7") is None


@pytest.mark.parametrize(
    ("fields", "why"),
    [
        ({"type": "ticket-brief"}, "type is ticket-brief, not ticket-outcome"),
        ({"ticket": "DEM-9"}, "ticket: DEM-9 is not the folder's ticket DEM-7"),
        ({"ticket": "-"}, "ticket is missing"),
        ({"merged_at": "-"}, "merged_at is missing"),
        ({"merged_at": "2026-10-22T08:00:00"}, "merged_at needs a time with an offset"),
        ({"merged_at": "2026-10-22"}, "merged_at needs a time with an offset"),
        ({"pr": "#pending"}, "pr names no pull request: #pending"),
        ({"pr": "-"}, "pr names no pull request: none"),
        ({"dependents": "[DEM-8, 9x]"}, "dependents has an invalid item: 9x"),
    ],
)
def test_names_the_problem_when_outcome_malformed(fields: dict[str, str], why: str) -> None:
    assert outcome_record(an_outcome(**fields), folder="DEM-7") == (
        f"outcome.md could not be read ({why}). Fix it in a hub PR."
    )


def test_says_why_when_outcome_not_read() -> None:
    assert outcome_record(f"larger than {MAX_OUTCOME_BYTES} bytes", folder="DEM-7") == (
        "outcome.md could not be read (larger than 16384 bytes). Fix it in a hub PR."
    )
    assert outcome_record(b"no frontmatter\n", folder="DEM-7") == (
        "outcome.md could not be read (no frontmatter). Fix it in a hub PR."
    )


def test_keeps_the_first_folder_by_name_when_outcomes_recorded_under_one_ticket() -> None:
    found = recorded_outcomes(
        (
            OutcomeFile(name="dem-7", read=an_outcome(merged_at="2026-10-22T09:00:00Z")),
            OutcomeFile(name="DEM-7", read=an_outcome()),
            OutcomeFile(name="DEM-9", read="a link, not a regular file"),
        )
    )

    assert sorted(found) == ["DEM-7", "DEM-9"]
    recorded = found["DEM-7"]
    assert isinstance(recorded, TicketOutcome)
    assert recorded.merged_at == datetime(2026, 10, 22, 8, 0, tzinfo=UTC)
    assert found["DEM-9"] == (
        "outcome.md could not be read (a link, not a regular file). Fix it in a hub PR."
    )


# AC-3.3: a preflight run since the merge that lists the blocker read its outcome.
def test_finds_the_run_that_read_the_outcome_when_blockers_read_name_the_blocker() -> None:
    merged = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
    before = a_preflight(ran_at="2026-10-21T08:00:00Z", blockers_read=["DEM-7"])
    since = a_preflight(ran_at="2026-10-21T09:30:00Z", blockers_read=["t1"])
    unread = a_preflight(ran_at="2026-10-21T09:30:00Z", blockers_read=["DEM-6"])

    for content, found in ((before, False), (since, True), (unread, False)):
        record = preflight_record(content, folder="DEM-8")
        assert not isinstance(record, str)
        run = already_read(record, names=("T1", "DEM-7"), merged_at=merged)
        assert (run is not None) is found
    assert already_read(None, names=("DEM-7",), merged_at=merged) is None


# AGH-473 review Q2: times compare as instants, whatever their offsets.
@pytest.mark.parametrize(
    ("ran_at", "found"), [("2026-10-21T06:30:00-03:00", True), ("2026-10-21T05:30:00-03:00", False)]
)
def test_compares_instants_when_run_and_merge_have_different_offsets(
    ran_at: str, *, found: bool
) -> None:
    record = preflight_record(a_preflight(ran_at=ran_at, blockers_read=["DEM-7"]), folder="DEM-8")
    assert not isinstance(record, str)

    run = already_read(record, names=("DEM-7",), merged_at=datetime(2026, 10, 21, 9, 0, tzinfo=UTC))

    assert (run is not None) is found
