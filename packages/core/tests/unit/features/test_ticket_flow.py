"""A ticket's own flow (two-level-flows AC-1.8, AC-1.9, AC-1.13): its seven steps from records."""

from random import Random

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agent_hub.core.features.feature_reviews import ReviewOutcome, ReviewRecord
from agent_hub.core.features.feature_view import EvalRecord, Verdict
from agent_hub.core.features.golden_path import LINEAR_NOT_CONNECTED
from agent_hub.core.features.ticket_flow import TicketEvidence, ticket_flow
from agent_hub.core.features.ticket_view import TicketFlow, TicketRow
from agent_hub.core.testing.read_model_builders import a_ticket_row, an_eval_record
from agent_hub.core.tracker.tracker_reader import IssueState

_SEVEN = ("context", "preflight", "implement", "review", "eval", "pr", "merged")
_DONE = IssueState(name="Done", type="completed")
_STARTED = IssueState(name="In Progress", type="started")
_TODO = IssueState(name="Todo", type="unstarted")
# A step "has evidence" when a record (or Linear) says something about it.
_EVIDENCE = ("done", "current", "blocked")


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
) -> TicketFlow:
    flow = ticket_flow(
        _row() if row is None else row,
        TicketEvidence(rounds=rounds, reviews=reviews, evals=evals, unread=unread),
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
    evidence = TicketEvidence(rounds=frozenset(), reviews=(), evals=(), unread=None)

    assert ticket_flow(_row(children=("DEM-9",)), evidence) is None


_NAMES = ("DEM-8", "T2", "DEM-9")
_VERDICTS: tuple[Verdict, ...] = ("SHIP", "SHIP-WITH-OWNER-STEPS", "NO-SHIP")


@st.composite
def _evidence(draw: st.DrawFn) -> tuple[TicketRow, TicketEvidence]:
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
    evidence = TicketEvidence(rounds=rounds, reviews=reviews, evals=evals, unread=unread)
    return _row(state=None if unread else state), evidence


# AC-1.9: no generated flow has a "Not reached" step before a step with evidence.
@settings(max_examples=200, deadline=None)
@given(drawn=_evidence())
def test_finds_no_pending_before_evidence_when_records_generated_property(
    drawn: tuple[TicketRow, TicketEvidence],
) -> None:
    flow = ticket_flow(*drawn)
    assert flow is not None

    states = [step.state for step in flow.steps]
    last = max((i for i, state in enumerate(states) if state in _EVIDENCE), default=-1)
    assert "pending" not in states[:last]
    assert "unrecorded" not in states[last + 1 :]
    assert flow.current in _SEVEN


# AC-1.13: the same records give the same flow whatever the read order.
@settings(max_examples=100, deadline=None)
@given(drawn=_evidence(), pick=st.randoms(use_true_random=False))
def test_same_flow_when_read_order_shuffled_property(
    drawn: tuple[TicketRow, TicketEvidence], pick: Random
) -> None:
    row, evidence = drawn
    reviews, evals = list(evidence.reviews), list(evidence.evals)
    pick.shuffle(reviews)
    pick.shuffle(evals)
    shuffled = TicketEvidence(
        rounds=evidence.rounds, reviews=tuple(reviews), evals=tuple(evals), unread=evidence.unread
    )

    assert ticket_flow(row, evidence) == ticket_flow(row, shuffled)
