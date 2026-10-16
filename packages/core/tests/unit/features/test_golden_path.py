import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agent_hub.core.features.feature_record import PlannedTicket, RecordAc
from agent_hub.core.features.feature_view import GoldenPath, GoldenStep, TicketsSource
from agent_hub.core.features.golden_path import (
    LINEAR_NOT_CONNECTED,
    NO_EVALS,
    STEP_TITLES,
    EvalGate,
    GoldenInputs,
    golden_path,
    own_conditions,
)
from agent_hub.core.features.ticket_planning import ticket_board
from agent_hub.core.features.ticket_view import TicketRow
from agent_hub.core.testing.read_model_builders import (
    a_ticket_row,
    a_ticket_snapshot,
    an_issue_summary,
)
from agent_hub.core.tracker.tracker_reader import IssueState, IssueStateType

_FILES = ("spec.md", "research.md", "plan.md", "features.json")
_DONE = IssueState(name="Done", type="completed")
_STARTED = IssueState(name="In Progress", type="started")
_IN_REVIEW = IssueState(name="In Review", type="started")
_CANCELED = IssueState(name="Canceled", type="canceled")


def _ticket(number: int, **fields: object) -> TicketRow:
    values: dict[str, object] = {
        "ref": f"TIP-{1519 + number}",
        "key": f"T{number}",
        "id": f"TIP-{1519 + number}",
        "state": _STARTED,
        "order": number,
        "blocked_by": (),
        "blocks": (),
        "reviewed": False,
    }
    return a_ticket_row(**(values | fields))


def _acs(total: int, *, passing: int, withdrawn: int = 0) -> tuple[RecordAc, ...]:
    return tuple(
        RecordAc(
            id=f"AC-7.{number}",
            description="Given x, when y, then z",
            passes=number <= passing,
            withdrawn=number > total - withdrawn,
        )
        for number in range(1, total + 1)
    )


def _inputs(**fields: object) -> GoldenInputs:
    values: dict[str, object] = {
        "files": _FILES,
        "rows": (),
        "acs": (),
        "coverage": NO_EVALS,
        "source": "linear",
    }
    return GoldenInputs(**(values | fields))  # type: ignore[arg-type]


def _step(path: GoldenPath, name: str) -> GoldenStep:
    return next(step for step in path.steps if step.name == name)


def _states(path: GoldenPath) -> dict[str, str]:
    return {step.name: step.state for step in path.steps}


def _owner_case_rows() -> tuple[TicketRow, ...]:
    return (
        _ticket(1, state=_DONE, reviewed=True),
        *(_ticket(number) for number in range(2, 18)),
    )


@pytest.mark.parametrize(
    ("with_ids", "state", "meta"),
    [(17, "done", "17 of 17 created"), (15, "current", "15 of 17 created")],
)
def test_marks_tickets_when_ids_created(with_ids: int, state: str, meta: str) -> None:
    rows = tuple(
        _ticket(number)
        if number <= with_ids
        else _ticket(number, ref=f"T{number}", id=None, state=None)
        for number in range(1, 18)
    )

    path = golden_path(_inputs(rows=rows, acs=_acs(36, passing=0)))

    tickets = _step(path, "tickets")
    assert (tickets.state, tickets.meta) == (state, meta)
    assert tickets.progress is not None
    assert (tickets.progress.done, tickets.progress.total) == (with_ids, 17)


def test_folds_owner_case_when_one_ticket_done() -> None:
    inputs = _inputs(
        rows=_owner_case_rows(),
        acs=_acs(36, passing=3),
        coverage=EvalGate(evals=1, covered=3, owner_steps=0),
    )

    path = golden_path(inputs)

    assert path.phase == "implement"
    assert _states(path) == {
        "spec": "done",
        "research": "done",
        "plan": "done",
        "tickets": "done",
        "implement": "current",
        "review": "pending",
        "evaluate": "partial",
        "shipped": "pending",
    }
    assert _step(path, "implement").meta == "1/17 tickets · 3/36 ACs"
    assert _step(path, "review").meta == "1/17 reviewed"
    assert _step(path, "evaluate").meta == "partial: covers 3 of 36 ACs"
    assert _step(path, "evaluate").reason == "Implement is not done"
    assert _step(path, "shipped").reason == "Implement is not done"


def test_counts_reviewed_when_done_or_approved_record() -> None:
    rows = (
        _ticket(1, state=_IN_REVIEW, reviewed=False),
        _ticket(2, state=_DONE, reviewed=True),
        _ticket(3, state=_STARTED, reviewed=True),
        _ticket(4, state=_CANCELED, reviewed=False),
    )

    path = golden_path(_inputs(rows=rows, acs=_acs(3, passing=3), approved_reviews=1))

    review = _step(path, "review")
    assert review.meta == "2/3 reviewed"
    assert review.progress is not None
    assert (review.progress.done, review.progress.total) == (2, 3)
    assert review.state == "partial"
    assert _step(path, "implement").meta == "1/3 tickets · 3/3 ACs"
    assert _step(path, "tickets").meta == "3 of 3 created"


def test_keeps_review_pending_when_in_review_without_approved_record() -> None:
    planned = (PlannedTicket(key="T1", id="DEMO-1520", order=1),)
    summary = an_issue_summary(
        id="DEMO-1520",
        state=_IN_REVIEW,
        url="https://linear.app/demo/issue/DEMO-1520",
        blocks=(),
        blocked_by=(),
    )
    snapshot = a_ticket_snapshot(summaries=(summary,), missing=(), external=())
    acs = _acs(1, passing=1)

    board = ticket_board(planned, acs, snapshot, approved=("DEMO-1519", "T9"))
    path = golden_path(_inputs(rows=board.rows, acs=acs, approved_reviews=0))

    (row,) = board.rows
    assert (row.state, row.reviewed) == (_IN_REVIEW, False)
    review = _step(path, "review")
    assert review.state == "pending"
    assert review.meta == "0/1 reviewed"


def test_marks_review_unknown_when_records_over_cap() -> None:
    rows = (_ticket(1, state=_DONE, reviewed=True),)

    path = golden_path(_inputs(rows=rows, acs=_acs(1, passing=1), reviews_skipped=3))

    assert _step(path, "review").state == "unknown"
    assert "more than" in (_step(path, "review").reason or "")


def _all_done(**fields: object) -> GoldenInputs:
    rows = tuple(_ticket(number, state=_DONE, reviewed=True) for number in range(1, 5))
    values: dict[str, object] = {
        "rows": rows,
        "acs": _acs(6, passing=6),
        "coverage": EvalGate(evals=2, covered=6, owner_steps=0),
    }
    return _inputs(**(values | fields))


def test_shipped_when_every_gate_holds() -> None:
    path = golden_path(_all_done())

    assert path.phase == "shipped"
    assert set(_states(path).values()) == {"done"}
    assert _step(path, "shipped").meta == "4/4 Done"


@pytest.mark.parametrize("approved", [False, True])
def test_never_shipped_when_plan_fallback(*, approved: bool) -> None:
    rows = tuple(
        _ticket(number, state=None, reviewed=True if approved else None) for number in range(1, 5)
    )

    path = golden_path(_all_done(rows=rows, source="plan", approved_reviews=4 if approved else 0))

    states = _states(path)
    assert "done" not in (states["implement"], states["review"], states["shipped"])
    assert states["implement"] == "unknown"
    assert _step(path, "implement").reason == LINEAR_NOT_CONNECTED
    assert _step(path, "implement").meta == "6/6 ACs"
    assert states["shipped"] == "unknown"
    assert _step(path, "shipped").reason == LINEAR_NOT_CONNECTED
    if approved:
        assert states["review"] == "blocked"
        assert _step(path, "review").reason == "Implement is unknown"
    else:
        assert states["review"] == "unknown"
        assert _step(path, "review").meta == LINEAR_NOT_CONNECTED
    assert all("GitHub" not in (step.meta or "") + (step.reason or "") for step in path.steps)


def test_says_not_loaded_when_cache_cold() -> None:
    rows = tuple(_ticket(number, state=None, reviewed=None) for number in range(1, 3))

    path = golden_path(_all_done(rows=rows, source="plan", not_loaded=True))

    assert "not loaded" in (_step(path, "shipped").reason or "")
    assert "not loaded" in (_step(path, "shipped").meta or "")


def test_waits_on_owner_steps_when_eval_ships_with_owner_steps() -> None:
    path = golden_path(_all_done(coverage=EvalGate(evals=1, covered=6, owner_steps=2)))

    evaluate = _step(path, "evaluate")
    assert (evaluate.state, evaluate.meta) == ("current", "waiting: owner steps")
    assert (_step(path, "shipped").state, path.phase) == ("blocked", "evaluate")
    assert _step(path, "shipped").reason == "Evaluate is not done"


def test_says_scope_not_recorded_when_legacy_eval_without_scope() -> None:
    gate = EvalGate(evals=1, covered=0, owner_steps=0, scope_recorded=False)

    path = golden_path(_all_done(coverage=gate))

    assert _step(path, "evaluate").meta == "partial: scope not recorded"
    assert _step(path, "evaluate").state == "current"


def test_marks_evaluate_unknown_when_evals_over_cap() -> None:
    gate = EvalGate(evals=200, covered=6, owner_steps=0, skipped=4)

    path = golden_path(_all_done(coverage=gate))

    assert _step(path, "evaluate").state == "unknown"
    assert "more than 200 evals" in (_step(path, "evaluate").reason or "")


def test_skips_research_when_plan_written() -> None:
    path = golden_path(_inputs(files=("spec.md", "plan.md")))

    assert [step.state for step in path.steps[:4]] == ["done", "skipped", "done", "current"]
    assert path.phase == "tickets"


def test_starts_at_spec_when_folder_empty() -> None:
    path = golden_path(_inputs(files=()))

    assert path.phase == "spec"
    assert _states(path)["research"] == "pending"


def test_counts_issues_md_when_no_tickets_planned() -> None:
    path = golden_path(_inputs(files=(*_FILES, "issues.md"), acs=_acs(2, passing=1)))

    assert _states(path)["tickets"] == "done"
    assert (path.phase, _step(path, "implement").meta) == ("implement", "1/2 ACs")


def test_excludes_withdrawn_when_counting_acs() -> None:
    rows = (_ticket(1, state=_DONE, reviewed=True),)
    acs = _acs(4, passing=3, withdrawn=1)

    path = golden_path(
        _inputs(rows=rows, acs=acs, coverage=EvalGate(evals=1, covered=3, owner_steps=0))
    )

    assert _step(path, "implement").meta == "1/1 tickets · 3/3 ACs"
    assert _step(path, "evaluate").meta == "covers 3 of 3 ACs"
    assert path.phase == "shipped"


_STATE_TYPES: tuple[IssueStateType | None, ...] = (None, "started", "completed", "canceled")


@st.composite
def _feature_inputs(draw: st.DrawFn) -> GoldenInputs:
    rows = []
    for number in range(1, draw(st.integers(min_value=0, max_value=6)) + 1):
        kind = draw(st.sampled_from(_STATE_TYPES))
        has_id = draw(st.booleans())
        rows.append(
            _ticket(
                number,
                ref=f"TIP-{1519 + number}" if has_id else f"T{number}",
                id=f"TIP-{1519 + number}" if has_id else None,
                state=None if kind is None else IssueState(name=kind, type=kind),
                reviewed=draw(st.sampled_from((None, False, True))),
            )
        )
    total = draw(st.integers(min_value=0, max_value=6))
    source: TicketsSource = draw(st.sampled_from(("linear", "plan")))
    return GoldenInputs(
        files=tuple(
            draw(st.lists(st.sampled_from((*_FILES, "issues.md")), unique=True, max_size=5))
        ),
        rows=tuple(rows),
        acs=_acs(
            total,
            passing=draw(st.integers(min_value=0, max_value=total)),
            withdrawn=draw(st.integers(min_value=0, max_value=total)),
        ),
        coverage=EvalGate(
            evals=draw(st.integers(min_value=0, max_value=3)),
            covered=draw(st.integers(min_value=0, max_value=total)),
            owner_steps=draw(st.integers(min_value=0, max_value=1)),
            scope_recorded=draw(st.booleans()),
            skipped=draw(st.sampled_from((0, 0, 0, 1))),
        ),
        approved_reviews=draw(st.integers(min_value=0, max_value=2)),
        reviews_skipped=draw(st.sampled_from((0, 0, 0, 1))),
        source=source,
        not_loaded=draw(st.booleans()),
    )


@settings(max_examples=400, deadline=None)
@given(inputs=_feature_inputs())
def test_keeps_steps_monotonic_when_states_generated_property(inputs: GoldenInputs) -> None:
    path = golden_path(inputs)

    holds = own_conditions(inputs)
    open_steps = [i for i, step in enumerate(path.steps) if step.state not in ("done", "skipped")]
    if not open_steps:
        assert path.phase == "shipped"
        return
    gate = path.steps[open_steps[0]]
    assert path.phase == gate.name
    for step in path.steps[open_steps[0] + 1 :]:
        assert step.state != "done"
        if holds[step.name] is True and step.state != "skipped":
            assert step.state == "blocked"
            assert STEP_TITLES[gate.name] in (step.reason or "")
    assert all("GitHub" not in (step.meta or "") + (step.reason or "") for step in path.steps)
    if inputs.source == "plan" and any(row.state is None for row in inputs.rows):
        assert path.steps[-1].state != "done"


def test_counts_in_progress_tickets_in_implement_meta_when_started() -> None:
    rows = (
        _ticket(1, state=_IN_REVIEW, readiness="in_progress"),
        _ticket(2, state=_STARTED, readiness="in_progress"),
        _ticket(3, state=IssueState(name="Backlog", type="backlog"), readiness="can_start"),
    )

    path = golden_path(_inputs(rows=rows, acs=_acs(18, passing=17)))

    implement = _step(path, "implement")
    assert implement.meta == "0/3 tickets · 2 in progress · 17/18 ACs"
    assert implement.state == "current"
