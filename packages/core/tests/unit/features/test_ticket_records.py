"""A feature's ticket records and plan change requests (two-level-flows AC-2.5, AC-2.8, AC-2.14):
read into what the folds need, a malformed file kept as its problem."""

import json

from agent_hub.core.features.feature_status import RecordHead
from agent_hub.core.features.ticket_records import (
    MAX_CHANGE_REQUEST_FILES,
    MAX_PREFLIGHT_BYTES,
    ChangeRequest,
    change_requests,
    preflight_record,
)


def a_request(n: int = 1, *, ticket: str = "DEM-8", **fields: str) -> RecordHead:
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
    text = f"---\n{front}---\n# Plan change request {n}\n"
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
            n=1, ticket="DEM-8", status="open", plan_to=3, affected=("DEM-9",), problem=None
        ),
    )
    assert found.problem is None


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


def test_keeps_problem_when_decision_malformed() -> None:
    (request,) = change_requests((a_request(), a_decision(decision="maybe")), skipped=0).requests

    assert request.status is None
    assert request.problem == (
        "change-requests/1.decision.md could not be read (decision must be approved or "
        "declined). Fix it in a hub PR."
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
    record = preflight_record(a_preflight(drift="local", local_notes=["Moved helper."]))

    assert not isinstance(record, str)
    assert record is not None
    assert record.runs[-1].local_notes == ("Moved helper.",)


def test_names_json_path_when_preflight_malformed() -> None:
    assert preflight_record(a_preflight(drift="global")) == (
        "preflight.json could not be read (runs[0].drift: Input should be 'none', 'local' or "
        "'plan'). Fix it in a hub PR."
    )


def test_says_why_when_preflight_not_read() -> None:
    assert preflight_record(f"larger than {MAX_PREFLIGHT_BYTES} bytes") == (
        "preflight.json could not be read (larger than 65536 bytes). Fix it in a hub PR."
    )
    assert preflight_record(None) is None
