from random import Random

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agent_hub.core.features.feature_record import PlannedTicket, RecordAc
from agent_hub.core.features.feature_status import (
    FeatureFolder,
    RecordHead,
    feature_detail,
    feature_parts,
)
from agent_hub.core.features.feature_view import (
    AmendmentView,
    GoldenPath,
    GoldenStep,
    PlanView,
    TicketsSource,
    Verdict,
)
from agent_hub.core.features.golden_path import (
    LINEAR_NOT_CONNECTED,
    LINEAR_NOT_LOADED,
    NO_EVALS,
    STEP_TITLES,
    EvalGate,
    GoldenInputs,
    golden_path,
    own_conditions,
)
from agent_hub.core.features.ticket_planning import ticket_board
from agent_hub.core.features.ticket_snapshots import SnapshotRead
from agent_hub.core.features.ticket_view import TicketRow
from agent_hub.core.testing.read_model_builders import (
    a_ticket_row,
    a_ticket_snapshot,
    an_issue_summary,
)
from agent_hub.core.testing.tracker_reader_fakes import SNAPSHOT_TIME
from agent_hub.core.tracker.tracker_reader import (
    IssueState,
    IssueStateType,
    IssueSummary,
    TicketSnapshot,
)

_FILES = ("spec.md", "research.md", "plan.md", "features.json")
_DONE = IssueState(name="Done", type="completed")
_STARTED = IssueState(name="In Progress", type="started")
_IN_REVIEW = IssueState(name="In Review", type="started")
_BACKLOG = IssueState(name="Backlog", type="backlog")
_CANCELED = IssueState(name="Canceled", type="canceled")
_EIGHT = ("spec", "ux_design", "research", "plan", "tickets", "build", "acceptance", "shipped")


def _ticket(number: int, **fields: object) -> TicketRow:
    values: dict[str, object] = {
        "ref": f"ACME-{1519 + number}",
        "key": f"T{number}",
        "id": f"ACME-{1519 + number}",
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


def _all_done(**fields: object) -> GoldenInputs:
    rows = tuple(_ticket(number, state=_DONE, reviewed=True) for number in range(1, 5))
    values: dict[str, object] = {
        "rows": rows,
        "acs": _acs(6, passing=6),
        "coverage": EvalGate(evals=2, covered=6, acceptance="SHIP"),
    }
    return _inputs(**(values | fields))


# two-level-flows AC-1.1: the golden path holds the eight feature steps, in order.
@pytest.mark.parametrize(
    "inputs",
    [_inputs(files=()), _inputs(), _all_done()],
    ids=["empty", "planned", "shipped"],
)
def test_names_eight_feature_steps_when_golden_path_computed(inputs: GoldenInputs) -> None:
    path = golden_path(inputs)

    assert tuple(step.name for step in path.steps) == _EIGHT
    assert tuple(STEP_TITLES) == _EIGHT
    assert path.phase in _EIGHT


# two-level-flows AC-1.2: a brief alone makes Spec current; Brief is never a step.
def test_makes_spec_current_when_brief_only() -> None:
    path = golden_path(_inputs(files=("brief.md",)))

    spec = _step(path, "spec")
    assert (spec.state, spec.meta) == ("current", "Brief only · spec not written")
    assert path.phase == "spec"
    assert [step.state for step in path.steps[1:]] == ["pending"] * 7
    assert "brief" not in {step.name for step in path.steps}


def test_omits_brief_only_meta_when_spec_skipped() -> None:
    path = golden_path(_inputs(files=("brief.md", "plan.md")))

    spec = _step(path, "spec")
    assert (spec.state, spec.meta) == ("skipped", None)


# two-level-flows AC-1.3: UX design.
def test_skips_ux_design_when_no_designs_and_later_record_exists() -> None:
    path = golden_path(_inputs(files=("spec.md", "research.md")))

    ux = _step(path, "ux_design")
    assert (ux.state, ux.meta) == ("skipped", "No screen change recorded")


def test_marks_ux_design_done_when_every_design_approved() -> None:
    path = golden_path(_inputs(files=("spec.md",), ux_designs=(True, True)))

    ux = _step(path, "ux_design")
    assert (ux.state, ux.meta) == ("done", "2 designs approved")
    assert path.phase == "research"


def test_counts_ux_design_drafts_when_one_not_approved() -> None:
    path = golden_path(_inputs(files=("spec.md",), ux_designs=(True, False)))

    ux = _step(path, "ux_design")
    assert (ux.state, ux.meta) == ("current", "2 designs · 1 draft")
    assert path.phase == "ux_design"


def test_keeps_ux_design_open_when_drafts_and_later_record_exists() -> None:
    path = golden_path(_inputs(ux_designs=(False,)))

    ux = _step(path, "ux_design")
    assert (ux.state, ux.meta) == ("current", "1 design · 1 draft")
    assert path.phase == "ux_design"


# two-level-flows AC-1.4: Plan's meta reads the plan's version.
def test_reads_version_in_plan_meta_when_amendments_listed() -> None:
    amendments = tuple(
        AmendmentView(id=f"A{n}", date="2026-10-20", who="Ana", title="t", anchor="Amendments")
        for n in (1, 2)
    )

    amended = golden_path(_inputs(plan=PlanView(version=3, amendments=amendments)))
    first = golden_path(_inputs(plan=PlanView(version=1)))

    assert (_step(amended, "plan").state, _step(amended, "plan").meta) == (
        "done",
        "v3 · 2 amendments",
    )
    assert _step(first, "plan").meta == "v1"


def test_marks_plan_meta_unknown_when_plan_too_large() -> None:
    problem = "plan.md is larger than 256 KiB; its version could not be read."

    path = golden_path(_inputs(plan=PlanView(version=None, problem=problem)))

    plan = _step(path, "plan")
    assert (plan.state, plan.reason) == ("unknown", problem)


# two-level-flows AC-1.5: Build counts the merged tickets.
def test_counts_merged_over_active_tickets_in_build_when_linear_read() -> None:
    rows = (
        _ticket(1, state=_DONE),
        _ticket(2, state=_STARTED),
        _ticket(3, state=_BACKLOG),
        _ticket(4, state=_CANCELED),
        _ticket(5, state=_BACKLOG, readiness="epic", children=("ACME-1521", "ACME-1522")),
    )

    path = golden_path(_inputs(rows=rows, acs=_acs(3, passing=1)))

    build = _step(path, "build")
    assert (build.state, build.meta) == ("current", "1 of 3 merged · 1 in progress")
    assert build.progress is not None
    assert (build.progress.done, build.progress.total) == (1, 3)
    assert path.phase == "build"


def test_marks_build_done_only_when_all_merged() -> None:
    merged = tuple(_ticket(number, state=_DONE) for number in (1, 2))
    in_review = (_ticket(1, state=_DONE), _ticket(2, state=_IN_REVIEW, reviewed=True))

    done = golden_path(_inputs(rows=merged))
    open_ = golden_path(_inputs(rows=in_review))

    assert (_step(done, "build").state, _step(done, "build").meta) == ("done", "2 of 2 merged")
    assert _step(open_, "build").state == "current"


@pytest.mark.parametrize(
    ("not_loaded", "meta"), [(False, LINEAR_NOT_CONNECTED), (True, LINEAR_NOT_LOADED)]
)
def test_marks_build_unknown_when_linear_not_read(*, not_loaded: bool, meta: str) -> None:
    rows = tuple(_ticket(number, state=None, reviewed=None) for number in range(1, 3))

    path = golden_path(_all_done(rows=rows, source="plan", not_loaded=not_loaded))

    build = _step(path, "build")
    assert (build.state, build.meta) == ("unknown", meta)
    assert path.phase == "build"


# AGH-322's partial rule, carried to Build: a step after the gate with some tickets merged.
def test_marks_build_partial_when_after_gate_and_some_merged() -> None:
    rows = (_ticket(1, state=_DONE), _ticket(2, ref="T2", id=None, state=None))

    path = golden_path(_inputs(rows=rows))

    build = _step(path, "build")
    assert path.phase == "tickets"
    assert (build.state, build.meta) == ("partial", "1 of 2 merged")
    assert build.reason == "Tickets is not done"


def test_keeps_build_pending_when_after_gate_and_none_merged() -> None:
    rows = (_ticket(1, state=_STARTED), _ticket(2, ref="T2", id=None, state=None))

    path = golden_path(_inputs(rows=rows))

    assert _step(path, "build").state == "pending"


# two-level-flows AC-1.6: Acceptance.
def test_marks_acceptance_done_when_whole_feature_ship() -> None:
    path = golden_path(_all_done())

    assert _step(path, "acceptance").state == "done"


def test_marks_acceptance_done_when_owner_steps_signed_off() -> None:
    gate = EvalGate(evals=2, covered=6, acceptance="SHIP-WITH-OWNER-STEPS")

    path = golden_path(_all_done(coverage=gate))

    acceptance = _step(path, "acceptance")
    assert (acceptance.state, acceptance.meta) == ("done", "Owner steps signed off")


def test_waits_on_owner_in_acceptance_when_owner_steps_unsigned() -> None:
    gate = EvalGate(evals=1, covered=6, owner_steps=2, acceptance="SHIP-WITH-OWNER-STEPS")

    path = golden_path(_all_done(coverage=gate))

    acceptance = _step(path, "acceptance")
    assert (acceptance.state, acceptance.meta) == ("current", "Waiting on you: sign off 2 ACs")
    assert acceptance.reason == "2 ACs wait on owner steps (SHIP-WITH-OWNER-STEPS)"
    assert (_step(path, "shipped").state, path.phase) == ("pending", "acceptance")
    assert _step(path, "shipped").reason == "Acceptance is not done"


# two-level-flows A9 (AGH-325 R2-m1): the meta names what is counted, singular for one AC.
def test_waits_on_one_ac_in_singular_when_one_owner_step_unsigned() -> None:
    gate = EvalGate(evals=1, covered=6, owner_steps=1, acceptance="SHIP-WITH-OWNER-STEPS")

    acceptance = _step(golden_path(_all_done(coverage=gate)), "acceptance")

    assert acceptance.meta == "Waiting on you: sign off 1 AC"
    assert acceptance.reason == "1 AC waits on owner steps (SHIP-WITH-OWNER-STEPS)"


def test_never_marks_acceptance_done_when_only_ticket_evals_cover_every_ac() -> None:
    gate = EvalGate(evals=4, covered=6)

    path = golden_path(_all_done(coverage=gate))

    acceptance = _step(path, "acceptance")
    assert acceptance.state != "done"
    assert path.phase == "acceptance"


def test_marks_acceptance_unrecorded_when_build_done_without_whole_feature_eval() -> None:
    rows = tuple(_ticket(number, state=_DONE) for number in range(1, 4))
    acs = (*_acs(23, passing=6), *_acs(1, passing=0, withdrawn=1))

    path = golden_path(_inputs(rows=rows, acs=acs, coverage=EvalGate(evals=3, covered=6)))

    acceptance = _step(path, "acceptance")
    assert acceptance.state == "unrecorded"
    assert acceptance.meta == "Ticket evals cover 6 of 23 ACs"
    assert path.phase == "acceptance"


def test_marks_acceptance_partial_when_after_gate_and_ticket_evals_cover_some() -> None:
    path = golden_path(
        _inputs(
            rows=_owner_case_rows(), acs=_acs(36, passing=3), coverage=EvalGate(evals=1, covered=3)
        )
    )

    assert path.phase == "build"
    assert _states(path)["acceptance"] == "partial"
    assert _step(path, "acceptance").meta == "Ticket evals cover 3 of 36 ACs"
    assert _step(path, "acceptance").reason == "Build is not done"


def test_says_no_ship_in_acceptance_meta_when_whole_feature_eval_no_ship() -> None:
    path = golden_path(_all_done(coverage=EvalGate(evals=2, covered=0, acceptance="NO-SHIP")))

    acceptance = _step(path, "acceptance")
    assert (acceptance.state, acceptance.meta) == ("current", "NO-SHIP")
    assert acceptance.reason == "the whole-feature eval says NO-SHIP"


def test_marks_acceptance_unknown_when_evals_over_cap() -> None:
    gate = EvalGate(evals=200, covered=6, skipped=4, acceptance="SHIP")

    path = golden_path(_all_done(coverage=gate))

    assert _step(path, "acceptance").state == "unknown"
    assert "more than 200 evals" in (_step(path, "acceptance").reason or "")


# two-level-flows AC-1.7: Shipped.
@pytest.mark.parametrize(
    ("merged", "verdict", "shipped"),
    [
        (True, "SHIP", True),
        (False, "SHIP", False),
        (True, "NO-SHIP", False),
        (True, None, False),
    ],
)
def test_marks_shipped_only_when_build_and_acceptance_done(
    *, merged: bool, verdict: Verdict | None, shipped: bool
) -> None:
    rows = (_ticket(1, state=_DONE), _ticket(2, state=_DONE if merged else _STARTED))

    path = golden_path(
        _all_done(rows=rows, coverage=EvalGate(evals=2, covered=6, acceptance=verdict))
    )

    assert (_step(path, "shipped").state == "done") is shipped
    assert (path.phase == "shipped") is shipped


def test_keeps_old_feature_unshipped_when_only_ticket_evals() -> None:
    gate = EvalGate(evals=4, covered=6)

    path = golden_path(_all_done(coverage=gate))

    assert _step(path, "acceptance").state == "unrecorded"
    assert _step(path, "acceptance").meta == "Ticket evals cover 6 of 6 ACs"
    assert _step(path, "shipped").state == "pending"


def test_shipped_when_every_gate_holds() -> None:
    path = golden_path(_all_done())

    assert path.phase == "shipped"
    assert _states(path) == dict.fromkeys(_EIGHT, "done") | {"ux_design": "skipped"}


@pytest.mark.parametrize("approved", [False, True])
def test_never_shipped_when_plan_fallback(*, approved: bool) -> None:
    rows = tuple(
        _ticket(number, state=None, reviewed=True if approved else None) for number in range(1, 5)
    )

    path = golden_path(_all_done(rows=rows, source="plan"))

    states = _states(path)
    assert "done" not in (states["build"], states["shipped"])
    assert states["build"] == "unknown"
    assert _step(path, "build").reason == LINEAR_NOT_CONNECTED
    assert states["shipped"] == "unknown"
    assert _step(path, "shipped").reason == LINEAR_NOT_CONNECTED
    assert all("GitHub" not in (step.meta or "") + (step.reason or "") for step in path.steps)


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
        rows=_owner_case_rows(), acs=_acs(36, passing=3), coverage=EvalGate(evals=1, covered=3)
    )

    path = golden_path(inputs)

    assert path.phase == "build"
    assert _states(path) == {
        "spec": "done",
        "ux_design": "skipped",
        "research": "done",
        "plan": "done",
        "tickets": "done",
        "build": "current",
        "acceptance": "partial",
        "shipped": "pending",
    }
    assert _step(path, "build").meta == "1 of 17 merged · 16 in progress"
    assert _step(path, "shipped").reason == "Build is not done"


def test_skips_research_when_plan_written() -> None:
    path = golden_path(_inputs(files=("spec.md", "plan.md")))

    assert [step.state for step in path.steps[:5]] == [
        "done",
        "skipped",
        "skipped",
        "done",
        "current",
    ]
    assert path.phase == "tickets"


def test_starts_at_spec_when_folder_empty() -> None:
    path = golden_path(_inputs(files=()))

    assert path.phase == "spec"
    assert _states(path)["research"] == "pending"


def test_counts_issues_md_when_no_tickets_planned() -> None:
    path = golden_path(_inputs(files=(*_FILES, "issues.md"), acs=_acs(2, passing=1)))

    assert _states(path)["tickets"] == "done"
    assert path.phase == "build"
    build = _step(path, "build")
    assert (build.state, build.meta, build.reason) == (
        "current",
        "No tickets planned",
        "no tickets planned",
    )


def test_excludes_withdrawn_when_counting_acs() -> None:
    rows = (_ticket(1, state=_DONE, reviewed=True),)
    acs = _acs(4, passing=3, withdrawn=1)

    path = golden_path(_inputs(rows=rows, acs=acs, coverage=EvalGate(evals=1, covered=3)))

    assert _step(path, "acceptance").meta == "Ticket evals cover 3 of 3 ACs"


def test_counts_epic_only_under_tickets_when_it_has_children() -> None:
    rows = (
        _ticket(
            1,
            state=_BACKLOG,
            readiness="epic",
            children=("ACME-1521", "ACME-1522"),
        ),
        _ticket(2, state=_IN_REVIEW, readiness="in_progress", reviewed=True, parent="ACME-1520"),
        _ticket(3, state=_IN_REVIEW, readiness="in_progress", reviewed=True, parent="ACME-1520"),
    )

    path = golden_path(_inputs(rows=rows, acs=_acs(18, passing=17)))

    assert _step(path, "tickets").meta == "3 of 3 created"
    assert _step(path, "build").meta == "0 of 2 merged · 2 in progress"


def test_reads_board_rows_when_ticket_in_review_without_record() -> None:
    planned = (PlannedTicket(key="T1", id="ACME-1520", order=1),)
    summary = an_issue_summary(
        id="ACME-1520",
        state=_IN_REVIEW,
        url="https://linear.app/demo/issue/ACME-1520",
        blocks=(),
        blocked_by=(),
    )
    snapshot = a_ticket_snapshot(summaries=(summary,), missing=(), external=())
    acs = _acs(1, passing=1)

    board = ticket_board(planned, acs, snapshot, approved=("ACME-1519", "T9"))
    path = golden_path(_inputs(rows=board.rows, acs=acs))

    build = _step(path, "build")
    assert (build.state, build.meta) == ("current", "0 of 1 merged · 1 in progress")


_STATE_TYPES: tuple[IssueStateType | None, ...] = (None, "started", "completed", "canceled")
_VERDICTS: tuple[Verdict | None, ...] = (None, "SHIP", "SHIP-WITH-OWNER-STEPS", "NO-SHIP")


@st.composite
def _feature_inputs(draw: st.DrawFn) -> GoldenInputs:
    rows = []
    for number in range(1, draw(st.integers(min_value=0, max_value=6)) + 1):
        kind = draw(st.sampled_from(_STATE_TYPES))
        has_id = draw(st.booleans())
        rows.append(
            _ticket(
                number,
                ref=f"ACME-{1519 + number}" if has_id else f"T{number}",
                id=f"ACME-{1519 + number}" if has_id else None,
                state=None if kind is None else IssueState(name=kind, type=kind),
                reviewed=draw(st.sampled_from((None, False, True))),
            )
        )
    total = draw(st.integers(min_value=0, max_value=6))
    source: TicketsSource = draw(st.sampled_from(("linear", "plan")))
    files = (*_FILES, "issues.md", "brief.md")
    return GoldenInputs(
        files=tuple(draw(st.lists(st.sampled_from(files), unique=True, max_size=6))),
        rows=tuple(rows),
        acs=_acs(
            total,
            passing=draw(st.integers(min_value=0, max_value=total)),
            withdrawn=draw(st.integers(min_value=0, max_value=total)),
        ),
        coverage=EvalGate(
            evals=draw(st.integers(min_value=0, max_value=3)),
            covered=draw(st.integers(min_value=0, max_value=total)),
            owner_steps=draw(st.sampled_from((None, 0, 1))),
            skipped=draw(st.sampled_from((0, 0, 0, 1))),
            acceptance=draw(st.sampled_from(_VERDICTS)),
        ),
        ux_designs=tuple(draw(st.lists(st.booleans(), max_size=3))),
        ux_problem=draw(st.sampled_from((None, None, None, "ux-a.md could not be read"))),
        plan=draw(
            st.sampled_from(
                (None, PlanView(version=1), PlanView(version=None, problem="plan.md too large"))
            )
        ),
        source=source,
        not_loaded=draw(st.booleans()),
    )


# two-level-flows AC-1.13: no step is done while an earlier one is neither done nor skipped.
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
        assert step.state not in ("done", "unrecorded")
        if holds[step.name] is True and step.state != "skipped":
            assert step.state == "blocked"
            assert STEP_TITLES[gate.name] in (step.reason or "")
    assert all("GitHub" not in (step.meta or "") + (step.reason or "") for step in path.steps)
    if inputs.source == "plan" and any(row.state is None for row in inputs.rows):
        assert path.steps[-1].state != "done"


_RECORD = (
    b'{"tickets": ['
    b'{"key": "T1", "id": "ACME-1520", "order": 1}, {"key": "T2", "id": "ACME-1521", "order": 2}'
    b'], "acs": ['
    b'{"id": "AC-7.1", "description": "d", "passes": true, "ticket": "T1"},'
    b'{"id": "AC-7.2", "description": "d", "passes": false, "ticket": "T2"},'
    b'{"id": "AC-7.3", "description": "d", "passes": false, "verification": "manual"}'
    b"]}"
)


def _eval_head(name: str, *, verdict: str, scope: str, at: str, owner: bool = False) -> RecordHead:
    provenance = "provenance: owner\n" if owner else ""
    text = (
        f"---\ntype: eval\ndelivery: {name}\nverdict: {verdict}\n{scope}\n"
        f"evaluated_at: {at}\n{provenance}---\n# Eval\n"
    )
    return RecordHead(name=f"{name}.md", head=text.encode(), problem=None)


def _ux_head(name: str, status: str) -> RecordHead:
    return RecordHead(name=name, head=f"---\nstatus: {status}\n---\n".encode(), problem=None)


def _folder(*evals: RecordHead, **fields: object) -> FeatureFolder:
    values: dict[str, object] = {
        "slug": "demo-feature",
        "files": ("spec.md", "plan.md", "issues.md", "features.json"),
        "features_json": _RECORD,
        "evals": evals,
    }
    return FeatureFolder(**(values | fields))  # type: ignore[arg-type]


def _summary(issue_id: str, state: IssueState) -> IssueSummary:
    return an_issue_summary(
        id=issue_id,
        state=state,
        url=f"https://linear.app/demo/issue/{issue_id}",
        blocks=(),
        blocked_by=(),
    )


def _linear(*summaries: IssueSummary) -> SnapshotRead:
    return SnapshotRead(
        snapshot=TicketSnapshot(summaries=summaries, missing=(), external=()),
        source="linear",
        stale=False,
        as_of=SNAPSHOT_TIME,
        failure=None,
        detail=None,
        http_status=None,
    )


_MERGED = _linear(_summary("ACME-1520", _DONE), _summary("ACME-1521", _DONE))
_WHOLE_OWNER = _eval_head(
    "feature", verdict="SHIP-WITH-OWNER-STEPS", scope="acs: all", at="2026-10-10"
)
_SIGNOFF = _eval_head(
    "owner-signoff",
    verdict="SHIP",
    scope="acs: [AC-7.1, AC-7.2, AC-7.3]",
    at="2026-10-11",
    owner=True,
)


# two-level-flows A3: the owner's sign-off after a SHIP-WITH-OWNER-STEPS whole-feature eval.
def test_marks_acceptance_done_when_owner_signoff_follows_whole_feature_eval() -> None:
    unsigned = feature_parts(_folder(_WHOLE_OWNER), _MERGED).golden_path
    signed = feature_parts(_folder(_WHOLE_OWNER, _SIGNOFF), _MERGED).golden_path

    waiting = _step(unsigned, "acceptance")
    assert (waiting.state, waiting.meta) == ("current", "Waiting on you: sign off 3 ACs")
    done = _step(signed, "acceptance")
    assert (done.state, done.meta) == ("done", "Owner steps signed off")
    assert signed.phase == "shipped"


def test_keeps_acceptance_waiting_when_owner_signoff_predates_whole_feature_eval() -> None:
    early = _eval_head(
        "owner-signoff",
        verdict="SHIP",
        scope="acs: [AC-7.1, AC-7.2, AC-7.3]",
        at="2026-10-09",
        owner=True,
    )

    path = feature_parts(_folder(_WHOLE_OWNER, early), _MERGED).golden_path

    assert _step(path, "acceptance").meta == "Waiting on you: sign off 3 ACs"


# two-level-flows AC-1.6: ticket evals never sign the owner steps off.
def test_keeps_acceptance_waiting_when_ticket_evals_ship_after_whole_feature_eval() -> None:
    ticket_ship = _eval_head(
        "acme-1520", verdict="SHIP", scope="acs: [AC-7.1, AC-7.2, AC-7.3]", at="2026-10-11"
    )

    path = feature_parts(_folder(_WHOLE_OWNER, ticket_ship), _MERGED).golden_path

    acceptance = _step(path, "acceptance")
    assert (acceptance.state, acceptance.meta) == ("current", "Waiting on you: sign off 3 ACs")


# two-level-flows A6: a legacy eval.md without scope is whole-feature; it needs a sign-off too.
def test_keeps_acceptance_waiting_when_legacy_eval_ships_with_owner_steps() -> None:
    legacy = b"# Eval\n\n**Verdict: SHIP-WITH-OWNER-STEPS.** One manual step left.\n"

    path = feature_parts(_folder(files=(*_folder().files, "eval.md"), eval_head=legacy), _MERGED)

    acceptance = _step(path.golden_path, "acceptance")
    assert (acceptance.state, acceptance.meta) == ("current", "Waiting on you: sign off 3 ACs")


# two-level-flows A3 (AGH-325 Q2): no AC to count is no sign-off, so the owner steps still wait.
def test_keeps_acceptance_waiting_when_owner_steps_eval_has_no_live_ac() -> None:
    planned_only = b'{"tickets": [{"key": "T1", "id": "ACME-1520", "order": 1}], "acs": []}'
    merged = _linear(_summary("ACME-1520", _DONE))

    path = feature_parts(_folder(_WHOLE_OWNER, features_json=planned_only), merged).golden_path

    acceptance = _step(path, "acceptance")
    assert (acceptance.state, acceptance.meta) == (
        "current",
        "Waiting on owner steps · no ACs listed",
    )
    assert path.phase == "acceptance"


# The hub's workflows-engine: no features.json, ticket SWOS evals, then an acs:all SWOS final.md.
_WORKFLOWS_FINAL = _eval_head(
    "final",
    verdict="SHIP-WITH-OWNER-STEPS",
    scope="tickets: [AGH-213, AGH-232]\nacs: all",
    at="2026-10-16T09:15:00Z",
)
_WORKFLOWS_SLICE = _eval_head(
    "slice-7-r2",
    verdict="SHIP-WITH-OWNER-STEPS",
    scope="tickets: [AGH-213, AGH-232]\nacs: [AC-213.19, AC-213.20]",
    at="2026-10-16T08:49:11Z",
)


def test_keeps_acceptance_waiting_when_folder_is_shaped_like_workflows_engine() -> None:
    folder = _folder(
        _WORKFLOWS_SLICE,
        _WORKFLOWS_FINAL,
        files=("research.md", "plan.md", "issues.md"),
        features_json=None,
    )
    signoff = _eval_head(
        "owner-signoff", verdict="SHIP", scope="tickets: [AGH-213]", at="2026-10-17", owner=True
    )
    signed = _folder(
        _WORKFLOWS_SLICE, _WORKFLOWS_FINAL, signoff, files=folder.files, features_json=None
    )

    waiting = _step(feature_parts(folder).golden_path, "acceptance")
    after = _step(feature_parts(signed).golden_path, "acceptance")

    assert (waiting.state, waiting.meta) == ("partial", "Waiting on owner steps · no ACs listed")
    assert (after.state, after.meta) == ("blocked", "Owner steps signed off")


# two-level-flows A3: the sign-off is never the acceptance eval nor the header verdict.
def test_never_makes_owner_signoff_the_acceptance_eval_when_it_lists_acs() -> None:
    alone = feature_detail(_folder(_SIGNOFF), project="demo", read=_MERGED)
    after = feature_detail(_folder(_WHOLE_OWNER, _SIGNOFF), project="demo", read=_MERGED)

    assert (alone.acceptance_eval, alone.verdict, alone.verdict_line) == (None, None, None)
    assert _step(alone.golden_path, "acceptance").state == "unrecorded"
    assert after.acceptance_eval is not None
    assert after.acceptance_eval.delivery == "feature"
    assert after.verdict == "SHIP-WITH-OWNER-STEPS"


# two-level-flows AC-1.3: a 51st design left unread could be a draft: the step cannot be done.
def test_marks_ux_design_unknown_when_designs_over_cap() -> None:
    approved = tuple(_ux_head(f"ux-{n:02}.md", "approved") for n in range(50))

    read = feature_parts(_folder(ux_designs=approved)).golden_path
    over = feature_parts(_folder(ux_designs=approved, ux_skipped=1)).golden_path

    assert _step(read, "ux_design").state == "done"
    ux = _step(over, "ux_design")
    assert (ux.state, ux.reason) == ("unknown", "more than 50 UX designs; not all were read")


def test_counts_ux_design_draft_when_design_is_a_link() -> None:
    linked = RecordHead(name="ux-a.md", head=None, problem="not a regular file")
    designs = (_ux_head("ux-b.md", "approved"), linked)

    path = feature_parts(_folder(ux_designs=designs)).golden_path

    ux = _step(path, "ux_design")
    assert (ux.state, ux.meta) == ("current", "2 designs · 1 draft")


def test_counts_ux_design_draft_when_design_has_no_frontmatter() -> None:
    plain = RecordHead(name="ux-a.md", head=b"# A screen\n", problem=None)

    path = feature_parts(_folder(ux_designs=(plain,))).golden_path

    assert _step(path, "ux_design").meta == "1 design · 1 draft"


# two-level-flows AC-1.13: the same records give the same golden path whatever the read order.
@settings(max_examples=100, deadline=None)
@given(pick=st.randoms(use_true_random=False), size=st.integers(0, 6))
def test_same_answer_when_read_order_shuffled_property(pick: Random, size: int) -> None:
    scopes = ("acs: all", "acs: [AC-7.1]", "tickets: [ACME-1521]", "acs: [AC-7.2, AC-7.3]")
    evals = [
        _eval_head(
            f"dem-{n}",
            verdict=pick.choice(("SHIP", "SHIP-WITH-OWNER-STEPS", "NO-SHIP")),
            scope=pick.choice(scopes),
            at=f"2026-10-{pick.randint(10, 12)}",
            owner=pick.random() < 0.3,
        )
        for n in range(size)
    ]
    designs = [_ux_head(f"ux-{n}.md", pick.choice(("approved", "draft"))) for n in range(3)]
    summaries = [
        _summary(f"ACME-{1520 + n}", pick.choice((_DONE, _STARTED, _CANCELED))) for n in range(2)
    ]
    reordered = [list(items) for items in (evals, designs, summaries)]
    for items in reordered:
        pick.shuffle(items)
    first, second = (
        feature_parts(
            _folder(*order[0], ux_designs=tuple(order[1])), _linear(*order[2])
        ).golden_path
        for order in ((evals, designs, summaries), reordered)
    )

    assert first == second
