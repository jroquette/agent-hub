"""A ticket's own flow (two-level-flows AC-1.8, AC-1.9, AC-1.13, AC-2.5, AC-2.8, AC-2.14, AC-3.1,
AC-3.3): its seven steps from records."""

import json
from random import Random

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agent_hub.core.features.feature_reviews import ReviewOutcome, ReviewRecord
from agent_hub.core.features.feature_status import RecordHead
from agent_hub.core.features.feature_view import EvalRecord, Verdict
from agent_hub.core.features.golden_path import LINEAR_NOT_CONNECTED
from agent_hub.core.features.ticket_flow import TicketEvidence, ticket_evidence, ticket_flow
from agent_hub.core.features.ticket_records import (
    NO_REQUESTS,
    ChangeRequests,
    OutcomeFile,
    TicketFiles,
    change_requests,
)
from agent_hub.core.features.ticket_view import TicketFlow, TicketRow
from agent_hub.core.testing.read_model_builders import a_ticket_row, an_eval_record
from agent_hub.core.tracker.tracker_reader import IssueState

_SEVEN = ("context", "preflight", "implement", "review", "eval", "pr", "merged")
_DONE = IssueState(name="Done", type="completed")
_STARTED = IssueState(name="In Progress", type="started")
_TODO = IssueState(name="Todo", type="unstarted")
# A step "has evidence" when a record (or Linear) says something about it.
_EVIDENCE = ("done", "current", "blocked", "waiting", "stale")


def _row(**fields: object) -> TicketRow:
    """Ticket ``T2`` (``DEM-8``), in progress in Linear."""
    return a_ticket_row(**({"state": _STARTED} | fields))


def _review(
    ticket: str = "DEM-8", outcome: ReviewOutcome | None = "approved", pr: str | None = None
) -> ReviewRecord:
    return ReviewRecord(
        ticket=ticket,
        path=f"features/demo-feature/reviews/{ticket}.md",
        outcome=outcome,
        pr=pr,
        reviewed_at="2026-10-10",
        problem=None if outcome is not None else "outcome must be one of approved",
    )


def _eval(
    delivery: str = "dem-8",
    *,
    verdict: Verdict = "SHIP",
    tickets: tuple[str, ...] = ("DEM-8",),
    at: str | None = "2026-10-10",
    prs: tuple[str, ...] = (),
) -> EvalRecord:
    return an_eval_record(
        delivery=delivery,
        path=f"features/demo-feature/evals/{delivery}.md",
        verdict=verdict,
        tickets=tickets,
        acs=(),
        prs=prs,
        evaluated_at=at,
    )


def _flow(
    row: TicketRow | None = None,
    *,
    rounds: frozenset[str] = frozenset(),
    reviews: tuple[ReviewRecord, ...] = (),
    evals: tuple[EvalRecord, ...] = (),
    unread: str | None = None,
    tickets: tuple[TicketFiles, ...] = (),
    tickets_skipped: int = 0,
    requests: ChangeRequests = NO_REQUESTS,
    plan_version: int | None = None,
    outcomes: tuple[OutcomeFile, ...] = (),
    rows: tuple[TicketRow, ...] = (),
) -> TicketFlow:
    flow = ticket_flow(
        _row() if row is None else row,
        ticket_evidence(
            rounds=rounds,
            reviews=reviews,
            evals=evals,
            unread=unread,
            tickets=tickets,
            tickets_skipped=tickets_skipped,
            requests=requests,
            plan_version=plan_version,
            outcomes=outcomes,
            rows=rows,
        ),
    )
    assert flow is not None
    return flow


def _states(flow: TicketFlow) -> dict[str, str]:
    return {step.name: step.state for step in flow.steps}


def _step(flow: TicketFlow, name: str) -> tuple[str, str | None]:
    found = next(step for step in flow.steps if step.name == name)
    return found.state, found.meta


def test_lists_the_seven_ticket_steps_when_flow_built() -> None:
    flow = _flow()

    assert tuple(step.name for step in flow.steps) == _SEVEN


def test_marks_implement_done_when_a_review_round_exists() -> None:
    assert _step(_flow(rounds=frozenset({"DEM-8"})), "implement") == ("done", None)
    # A round of another ticket says nothing about this one.
    assert _step(_flow(rounds=frozenset({"DEM-9"})), "implement") == ("pending", None)


def test_finds_records_when_they_name_the_plan_key() -> None:
    flow = _flow(
        rounds=frozenset({"T2"}),
        reviews=(_review("t2"),),
        evals=(_eval(tickets=("t2",)),),
    )

    assert [_step(flow, name)[0] for name in ("implement", "review", "eval")] == ["done"] * 3


def test_marks_review_done_when_record_approved() -> None:
    assert _step(_flow(reviews=(_review(),)), "review") == ("done", None)


def test_marks_review_current_when_changes_requested() -> None:
    flow = _flow(reviews=(_review(outcome="changes-requested"),))

    assert _step(flow, "review") == ("current", "Changes requested")
    assert flow.current == "review"


def test_counts_nothing_when_review_record_malformed() -> None:
    flow = _flow(reviews=(_review(outcome=None, pr="demo-api#12"),))

    assert set(_states(flow).values()) == {"pending"}


def test_reads_eval_from_latest_when_evals_name_the_ticket() -> None:
    older = _eval("dem-8", verdict="NO-SHIP", at="2026-10-09")
    newer = _eval("dem-8-r2", verdict="SHIP", at="2026-10-11")
    other = _eval("dem-9", verdict="NO-SHIP", tickets=("DEM-9",), at="2026-10-12")

    assert _step(_flow(evals=(newer, other, older)), "eval") == ("done", "SHIP")


def test_marks_eval_blocked_when_latest_eval_says_no_ship() -> None:
    flow = _flow(
        evals=(_eval(verdict="SHIP", at="2026-10-09"), _eval("dem-8-r2", verdict="NO-SHIP"))
    )

    assert _step(flow, "eval") == ("blocked", "NO-SHIP")
    assert flow.current == "eval"


def test_takes_conservative_verdict_when_latest_evals_unordered() -> None:
    first = _eval("dem-8", verdict="SHIP", at=None)
    second = _eval("t2-check", verdict="SHIP-WITH-OWNER-STEPS", at=None)

    assert _step(_flow(evals=(first, second)), "eval") == ("done", "SHIP-WITH-OWNER-STEPS")


@pytest.mark.parametrize(
    ("reviews", "evals", "state"),
    [
        ((_review(pr="demo-api#12"),), (), "done"),
        ((_review(pr="https://github.com/demo/demo-api/pull/12"),), (), "done"),
        ((), (_eval(prs=("demo-api#13",)),), "done"),
        ((_review(pr="demo-api#pending"),), (_eval(prs=("demo-api#pending",)),), "pending"),
        ((), (_eval(prs=("demo-api#13",), tickets=("DEM-9",)),), "pending"),
    ],
)
def test_marks_pr_done_when_review_or_eval_names_a_pull_request(
    reviews: tuple[ReviewRecord, ...], evals: tuple[EvalRecord, ...], state: str
) -> None:
    assert _step(_flow(reviews=reviews, evals=evals), "pr")[0] == state


def test_marks_merged_done_when_linear_says_completed() -> None:
    assert _step(_flow(_row(state=_DONE)), "merged") == ("done", None)
    assert _step(_flow(_row(state=_TODO)), "merged") == ("pending", None)


def test_marks_merged_unknown_when_linear_not_read() -> None:
    flow = _flow(_row(state=None), unread=LINEAR_NOT_CONNECTED)

    assert _step(flow, "merged") == ("unknown", LINEAR_NOT_CONNECTED)


# AC-1.9: a step with no record before one with evidence is "Not recorded", never "Not reached".
def test_reads_unrecorded_when_a_later_step_has_evidence() -> None:
    flow = _flow(reviews=(_review(),))

    assert _states(flow) == {
        "context": "unrecorded",
        "preflight": "unrecorded",
        "implement": "unrecorded",
        "review": "done",
        "eval": "pending",
        "pr": "pending",
        "merged": "pending",
    }


def test_reads_pending_when_nothing_after_has_evidence() -> None:
    flow = _flow(_row(state=_TODO))

    assert set(_states(flow).values()) == {"pending"}
    assert flow.current == "context"


def test_reads_not_recorded_when_done_in_linear_without_review_record() -> None:
    flow = _flow(_row(state=_DONE))

    states = _states(flow)
    assert [states[name] for name in ("context", "preflight", "review")] == ["unrecorded"] * 3
    assert states["merged"] == "done"
    assert flow.current == "merged"


def test_names_current_step_when_first_not_done_after_evidence() -> None:
    flow = _flow(rounds=frozenset({"DEM-8"}))

    assert flow.current == "review"
    assert _step(flow, "review") == ("pending", None)


def test_gives_no_flow_when_ticket_is_an_epic() -> None:
    evidence = ticket_evidence(rounds=frozenset(), reviews=(), evals=(), unread=None)

    assert ticket_flow(_row(children=("DEM-9",)), evidence) is None


_NAMES = ("DEM-8", "T2", "DEM-9")
_VERDICTS: tuple[Verdict, ...] = ("SHIP", "SHIP-WITH-OWNER-STEPS", "NO-SHIP")
# Before and after the drawn preflight's run, and one an outcome's reader refuses.
_MERGED_AT = ("2026-10-21T08:00:00Z", "2026-10-22T08:00:00Z", "later")


@st.composite
def _evidence(draw: st.DrawFn) -> tuple[TicketRow, TicketEvidence, tuple[OutcomeFile, ...]]:
    state = draw(st.sampled_from((None, _DONE, _STARTED, _TODO)))
    reviews = tuple(
        _review(
            draw(st.sampled_from(_NAMES)),
            draw(st.sampled_from(("approved", "changes-requested", None))),
            draw(st.sampled_from((None, "demo-api#12", "demo-api#pending"))),
        )
        for _ in range(draw(st.integers(0, 3)))
    )
    evals = tuple(
        _eval(
            f"dem-8-r{number}",
            verdict=draw(st.sampled_from(_VERDICTS)),
            tickets=(draw(st.sampled_from(_NAMES)),),
            at=draw(st.sampled_from((None, "2026-10-09", "2026-10-10"))),
            prs=draw(st.sampled_from(((), ("demo-api#13",)))),
        )
        for number in range(1, draw(st.integers(0, 3)) + 1)
    )
    rounds = frozenset(draw(st.lists(st.sampled_from(_NAMES), max_size=2)))
    unread = draw(st.sampled_from((None, LINEAR_NOT_CONNECTED)))
    drift = draw(st.sampled_from(("none", "local", "plan", "global")))
    notes = ["Moved helper."] if drift == "local" else []
    record = _preflight({"drift": drift, "local_notes": notes})
    tickets = tuple(
        _files(
            name,
            brief=draw(st.booleans()),
            plan=draw(st.booleans()),
            preflight=draw(st.sampled_from((None, record))),
        )
        for name in draw(st.lists(st.sampled_from(_NAMES), max_size=2, unique=True))
    )
    decision = draw(st.sampled_from((None, "approved", "declined")))
    asking = draw(st.sampled_from(_NAMES))
    requests = draw(st.sampled_from((NO_REQUESTS, _requests((1, f"{asking} -> DEM-8", decision)))))
    outcomes = tuple(
        _outcome(name, merged_at=draw(st.sampled_from(_MERGED_AT)))
        for name in draw(st.lists(st.sampled_from(("DEM-7", *_NAMES)), max_size=2, unique=True))
    )
    evidence = ticket_evidence(
        rounds=rounds,
        reviews=reviews,
        evals=evals,
        unread=unread,
        tickets=tickets,
        requests=requests,
        plan_version=draw(st.sampled_from((None, 2, 3))),
        outcomes=outcomes,
    )
    return _row(state=None if unread else state), evidence, outcomes


# AC-1.9: no generated flow has a "Not reached" step before a step with evidence.
@settings(max_examples=200, deadline=None)
@given(drawn=_evidence())
def test_finds_no_pending_before_evidence_when_records_generated_property(
    drawn: tuple[TicketRow, TicketEvidence, tuple[OutcomeFile, ...]],
) -> None:
    flow = ticket_flow(*drawn[:2])
    assert flow is not None

    states = [step.state for step in flow.steps]
    last = max((i for i, state in enumerate(states) if state in _EVIDENCE), default=-1)
    assert "pending" not in states[: max(last, 0)]
    assert "unrecorded" not in states[last + 1 :]
    assert flow.current in _SEVEN


# AC-1.13: the same records give the same flow whatever the read order.
@settings(max_examples=100, deadline=None)
@given(drawn=_evidence(), pick=st.randoms(use_true_random=False))
def test_same_flow_when_read_order_shuffled_property(
    drawn: tuple[TicketRow, TicketEvidence, tuple[OutcomeFile, ...]], pick: Random
) -> None:
    row, evidence, outcomes = drawn
    reviews = list(evidence.reviews)
    evals = list(dict.fromkeys(e for named in evidence.evals.values() for e in named))
    pick.shuffle(reviews)
    pick.shuffle(evals)
    files = list(evidence.files.values())
    pick.shuffle(files)
    recorded = list(outcomes)
    pick.shuffle(recorded)
    shuffled = ticket_evidence(
        rounds=evidence.rounds,
        reviews=tuple(reviews),
        evals=tuple(evals),
        unread=evidence.unread,
        tickets=tuple(files),
        requests=evidence.requests,
        plan_version=evidence.approved,
        outcomes=tuple(recorded),
    )

    assert ticket_flow(row, evidence) == ticket_flow(row, shuffled)


# AGH-326 review R5: the verdict cache is no part of the evidence's value.
def test_compares_equal_when_only_the_verdict_cache_differs() -> None:
    evals = (_eval(),)
    folded = ticket_evidence(rounds=frozenset(), reviews=(), evals=evals, unread=None)
    fresh = ticket_evidence(rounds=frozenset(), reviews=(), evals=evals, unread=None)

    flow = ticket_flow(_row(), folded)

    assert flow is not None
    assert _step(flow, "eval") == ("done", "SHIP")
    assert folded == fresh


def _preflight(*runs: dict[str, object]) -> bytes:
    base: dict[str, object] = {
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
    entries = [base | run for run in runs] or [base]
    return json.dumps(
        {"schema": "agent-hub/preflight/1", "ticket": "DEM-8", "runs": entries}
    ).encode()


def _files(name: str = "DEM-8", **fields: object) -> TicketFiles:
    return TicketFiles(name=name, **fields)  # type: ignore[arg-type]


def _requests(*heads: tuple[int, str, str | None]) -> ChangeRequests:
    """Requests ``(n, "<ticket> -> <affected,...>", decision)``, planned from v2 to v3."""
    found: list[RecordHead] = []
    for n, names, decision in heads:
        ticket, _, affected = names.partition(" -> ")
        front = (
            f"---\nticket: {ticket}\nstatus: open\nplan_from: 2\nplan_to: 3\n"
            f"affected: [{affected}]\nopened_at: 2026-10-21\nrun_id: implement-8\n---\n"
        )
        found.append(RecordHead(name=f"{n}.md", head=front.encode(), problem=None))
        if decision is not None:
            text = (
                f"---\ndecision: {decision}\ndecided_by: Dana Owner\n"
                "decided_at: 2026-10-21T10:00:00Z\n---\n"
            )
            found.append(RecordHead(name=f"{n}.decision.md", head=text.encode(), problem=None))
    return change_requests(found, skipped=0)


def test_marks_context_done_when_ticket_brief_exists() -> None:
    flow = _flow(_row(state=_TODO), tickets=(_files(brief=True),))

    assert _step(flow, "context") == ("done", None)
    assert flow.current == "preflight"


def test_marks_preflight_done_when_latest_run_finds_no_drift() -> None:
    flow = _flow(tickets=(_files(brief=True, preflight=_preflight()),))

    assert _step(flow, "preflight") == ("done", None)
    assert flow.signal is None


# AC-2.5: local drift is recorded, keeps Preflight done and shows its notes count.
def test_counts_local_notes_when_latest_run_finds_local_drift() -> None:
    record = _preflight({"drift": "local", "local_notes": ["Moved helper.", "Renamed flag."]})

    flow = _flow(tickets=(_files(preflight=record),))

    assert _step(flow, "preflight") == ("done", "Local drift · 2 notes")
    assert flow.signal == "Local drift · 2 notes"


def test_says_one_note_when_local_drift_has_one_note() -> None:
    record = _preflight({"drift": "local", "local_notes": ["Moved helper."]})

    assert _flow(tickets=(_files(preflight=record),)).signal == "Local drift · 1 note"


def test_reads_latest_run_when_preflight_ran_twice() -> None:
    record = _preflight({"drift": "local", "local_notes": ["Moved helper."]}, {"drift": "none"})

    assert _step(_flow(tickets=(_files(preflight=record),)), "preflight") == ("done", None)


def test_finds_ticket_folder_when_it_names_the_plan_key() -> None:
    flow = _flow(tickets=(_files("t2", brief=True),))

    assert _step(flow, "context") == ("done", None)


def test_marks_implement_current_when_ticket_plan_written() -> None:
    flow = _flow(tickets=(_files(plan=True),))

    assert _step(flow, "implement") == ("current", "Ticket plan written")
    assert _step(flow, "preflight") == ("unrecorded", None)
    assert flow.current == "implement"


# AC-2.8: the asking ticket waits for the owner while its change request is open.
def test_waits_for_owner_when_ticket_asked_open_change_request() -> None:
    record = _preflight({"drift": "plan", "change_request": 1})

    flow = _flow(
        tickets=(_files(brief=True, preflight=record),),
        requests=_requests((1, "DEM-8 -> DEM-9", None)),
    )

    assert _step(flow, "preflight") == ("waiting", "Waiting for you")
    assert flow.signal == "Waiting for you: plan change"
    assert flow.current == "preflight"


# AC-2.14: a request whose run (and preflight record) is lost still waits for the owner.
def test_waits_for_owner_when_request_open_without_preflight_record() -> None:
    flow = _flow(requests=_requests((1, "dem-8 -> ", None)))

    assert _step(flow, "preflight") == ("waiting", "Waiting for you")


# AC-2.8: each affected ticket is held while the request is open.
def test_holds_affected_ticket_when_another_ticket_request_open() -> None:
    flow = _flow(_row(state=_TODO), requests=_requests((1, "DEM-7 -> DEM-8, DEM-9", None)))

    assert flow.signal == "Held: plan change pending"
    assert _step(flow, "preflight") == ("pending", None)


def test_holds_nothing_when_affected_ticket_already_merged() -> None:
    flow = _flow(_row(state=_DONE), requests=_requests((1, "DEM-7 -> DEM-8", None)))

    assert flow.signal is None


# AC-2.8: once approved, a preflight that checked an older plan version must run again.
def test_marks_preflight_stale_when_approved_plan_newer_than_latest_run() -> None:
    record = _preflight({"drift": "plan", "change_request": 1})

    flow = _flow(
        tickets=(_files(preflight=record),),
        requests=_requests((1, "DEM-8 -> DEM-9", "approved")),
        plan_version=2,
    )

    assert _step(flow, "preflight") == ("stale", "Plan v3 approved: re-run preflight")
    assert flow.signal == "Plan v3 approved: re-run preflight"


def test_marks_preflight_stale_when_plan_amended_after_latest_run() -> None:
    flow = _flow(tickets=(_files(preflight=_preflight()),), plan_version=4)

    assert _step(flow, "preflight") == ("stale", "Plan v4 approved: re-run preflight")


def test_keeps_preflight_done_when_merged_ticket_checked_older_plan() -> None:
    flow = _flow(_row(state=_DONE), tickets=(_files(preflight=_preflight()),), plan_version=4)

    assert _step(flow, "preflight") == ("done", None)


def test_marks_preflight_blocked_when_plan_drift_declined() -> None:
    record = _preflight({"drift": "plan", "change_request": 1})

    flow = _flow(
        tickets=(_files(preflight=record),), requests=_requests((1, "DEM-8 -> ", "declined"))
    )

    assert _step(flow, "preflight") == ("blocked", "Plan drift")


# NFR Robustness: a malformed preflight.json turns only its own step unknown.
def test_marks_only_preflight_unknown_when_preflight_malformed() -> None:
    record = _preflight({"drift": "global"})

    flow = _flow(tickets=(_files(brief=True, preflight=record),), reviews=(_review(),))

    assert _step(flow, "preflight") == (
        "unknown",
        "preflight.json could not be read (runs[0].drift: Input should be 'none', 'local' or "
        "'plan'). Fix it in a hub PR.",
    )
    assert _step(flow, "context") == ("done", None)
    assert _step(flow, "review") == ("done", None)


def test_marks_preflight_unknown_when_ticket_request_malformed() -> None:
    broken = RecordHead(
        name="1.md", head=b"---\nticket: DEM-8\nstatus: approved\n---\n", problem=None
    )

    flow = _flow(requests=change_requests((broken,), skipped=0))

    state, meta = _step(flow, "preflight")
    assert state == "unknown"
    assert meta is not None
    assert meta.startswith("change-requests/1.md could not be read (status must be open")


# AGH-402 review Q13/S7: the folders left unread over the 500 cap or the read budget alike.
def test_marks_context_and_preflight_unknown_when_ticket_folders_left_unread() -> None:
    flow = _flow(tickets=(_files("DEM-1", brief=True),), tickets_skipped=1)

    unread = (
        "not every folder in tickets/ was read (more than 500, or over the read budget). "
        "Fix it in a hub PR."
    )
    assert _step(flow, "context") == ("unknown", unread)
    assert _step(flow, "preflight") == ("unknown", unread)


# AGH-402 review Q2, S4, Q8: a broken decision shows on the asking ticket, which still waits.
def test_marks_preflight_unknown_and_keeps_waiting_when_decision_malformed() -> None:
    request = RecordHead(
        name="1.md",
        head=(
            b"---\nticket: DEM-8\nstatus: open\nplan_from: 2\nplan_to: 3\naffected: []\n"
            b"opened_at: 2026-10-21\nrun_id: implement-8\n---\n"
        ),
        problem=None,
    )
    decision = RecordHead(name="1.decision.md", head=b"---\ndecision: maybe\n---\n", problem=None)

    flow = _flow(requests=change_requests((request, decision), skipped=0))

    assert _step(flow, "preflight") == (
        "unknown",
        "change-requests/1.decision.md could not be read (decision must be approved or "
        "declined). Fix it in a hub PR.",
    )
    assert flow.signal == "Waiting for you: plan change"


# AGH-402 review Q8: the asking ticket is never held by its own request.
@pytest.mark.parametrize("skipped", [0, 1], ids=["malformed preflight", "folder unread"])
def test_keeps_waiting_signal_when_asking_ticket_preflight_unknown(skipped: int) -> None:
    files = (_files(preflight=_preflight({"drift": "global"})),) if not skipped else ()

    flow = _flow(
        tickets=files,
        tickets_skipped=skipped,
        requests=_requests((1, "DEM-8 -> DEM-8, DEM-9", None)),
    )

    assert _step(flow, "preflight")[0] == "unknown"
    assert flow.signal == "Waiting for you: plan change"


# AGH-402 review Q4: a ticket folder without brief.md has no context brief.
def test_keeps_context_unrecorded_when_ticket_folder_has_no_brief() -> None:
    flow = _flow(tickets=(_files(plan=True, preflight=_preflight()),))

    assert _step(flow, "context") == ("unrecorded", None)
    assert _step(flow, "preflight") == ("done", None)


# AGH-402 review Q5: a review round makes Implement done, ticket plan or not.
def test_marks_implement_done_when_ticket_plan_and_review_round_exist() -> None:
    flow = _flow(rounds=frozenset({"DEM-8"}), tickets=(_files(plan=True),))

    assert _step(flow, "implement") == ("done", None)


def _outcome(
    name: str = "DEM-8", merged_at: str = "2026-10-22T08:00:00Z", **fields: str
) -> OutcomeFile:
    values = {
        "type": "ticket-outcome",
        "ticket": name,
        "merged_at": merged_at,
        "pr": "demo-api#4",
        "dependents": "[DEM-9]",
    } | fields
    front = "".join(f"{key}: {value}\n" for key, value in values.items())
    return OutcomeFile(name=name, read=f"---\n{front}---\n# Outcome\n".encode())


# AC-3.1, D-5: an outcome makes the ticket merged, Linear's state aside.
@pytest.mark.parametrize("state", [_STARTED, _DONE, None])
def test_reads_outcome_recorded_when_ticket_outcome_exists(state: IssueState | None) -> None:
    unread = None if state is not None else LINEAR_NOT_CONNECTED

    flow = _flow(_row(state=state), outcomes=(_outcome("dem-8"),), unread=unread)

    assert _step(flow, "merged") == ("done", "Outcome recorded")
    assert _step(flow, "context") == ("unrecorded", None)
    assert flow.current == "merged"


def test_finds_the_outcome_when_its_folder_names_the_plan_key() -> None:
    flow = _flow(outcomes=(_outcome("T2"),))

    assert _step(flow, "merged") == ("done", "Outcome recorded")


# NFR Robustness: a malformed outcome turns only its own step unknown.
def test_marks_only_merged_unknown_when_outcome_malformed() -> None:
    flow = _flow(
        _row(state=_DONE),
        reviews=(_review(),),
        outcomes=(_outcome(merged_at="yesterday"),),
    )

    state, meta = _step(flow, "merged")
    assert state == "unknown"
    assert meta == (
        "outcome.md could not be read (merged_at needs a time with an offset). Fix it in a hub PR."
    )
    assert _step(flow, "review") == ("done", None)


# AC-3.3: a blocker merged after the ticket's latest preflight makes it stale.
def test_marks_preflight_stale_when_blocker_outcome_newer_than_latest_run() -> None:
    flow = _flow(
        tickets=(_files(brief=True, preflight=_preflight()),),
        outcomes=(_outcome("DEM-7", merged_at="2026-10-21T10:00:00+00:00"),),
    )

    assert _step(flow, "preflight") == ("stale", "DEM-7 merged: re-run preflight")
    assert flow.signal == "DEM-7 merged: re-run preflight"


def test_finds_the_blocker_outcome_when_its_folder_names_the_blocker_key() -> None:
    blocker = _row(ref="DEM-7", key="T1", id="DEM-7", blocked_by=(), state=_DONE)

    flow = _flow(
        tickets=(_files(preflight=_preflight()),),
        outcomes=(_outcome("t1", merged_at="2026-10-21T10:00:00Z", ticket="T1"),),
        rows=(blocker, _row()),
    )

    assert _step(flow, "preflight") == ("stale", "DEM-7 merged: re-run preflight")


@pytest.mark.parametrize(
    ("merged_at", "state"),
    [
        # The latest preflight ran after the merge: it is the newer entry.
        ("2026-10-21T09:00:00Z", "done"),
        ("2026-10-21T09:30:00Z", "done"),
        ("2026-10-21T09:30:01Z", "stale"),
    ],
)
def test_keeps_preflight_done_until_outcome_newer_than_latest_run(
    merged_at: str, state: str
) -> None:
    flow = _flow(
        tickets=(_files(preflight=_preflight({"drift": "none"})),),
        outcomes=(_outcome("DEM-7", merged_at=merged_at),),
    )

    assert _step(flow, "preflight")[0] == state


def test_keeps_preflight_done_when_merged_ticket_blocker_merged_later() -> None:
    flow = _flow(
        tickets=(_files(preflight=_preflight()),),
        outcomes=(_outcome("DEM-8"), _outcome("DEM-7", merged_at="2026-10-22T09:00:00Z")),
    )

    assert _step(flow, "preflight") == ("done", None)


def test_ignores_an_outcome_of_a_ticket_not_blocking_this_one() -> None:
    flow = _flow(
        tickets=(_files(preflight=_preflight()),),
        outcomes=(_outcome("DEM-9", merged_at="2026-10-22T09:00:00Z"),),
    )

    assert _step(flow, "preflight") == ("done", None)


def test_ignores_a_malformed_blocker_outcome_when_preflight_read() -> None:
    flow = _flow(
        tickets=(_files(preflight=_preflight()),),
        outcomes=(_outcome("DEM-7", merged_at="soon"),),
    )

    assert _step(flow, "preflight") == ("done", None)
