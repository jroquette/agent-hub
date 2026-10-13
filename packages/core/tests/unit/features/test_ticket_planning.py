from hypothesis import given, settings
from hypothesis import strategies as st

from agent_hub.core.features.feature_record import PlannedTicket, RecordAc
from agent_hub.core.features.ticket_planning import TicketBoard, ticket_board
from agent_hub.core.features.ticket_view import TicketEdge, TicketRow
from agent_hub.core.testing.read_model_builders import a_ticket_snapshot, an_issue_summary
from agent_hub.core.tracker.tracker_reader import IssueState, IssueStateType, IssueSummary

_STARTED = IssueState(name="In Progress", type="started")
_DONE = IssueState(name="Done", type="completed")
_CANCELED = IssueState(name="Canceled", type="canceled")


def _planned(number: int, *, blocked_by: tuple[int, ...] = (), **fields: object) -> PlannedTicket:
    values: dict[str, object] = {
        "key": f"T{number}",
        "id": f"DEM-{number}",
        "title": f"Ticket {number}",
        "blocked_by": tuple(f"T{blocker}" for blocker in blocked_by),
        "order": number,
    }
    return PlannedTicket.model_validate(values | fields)


def _summary(number: int, **fields: object) -> IssueSummary:
    values: dict[str, object] = {
        "id": f"DEM-{number}",
        "title": f"Ticket {number}",
        "state": _STARTED,
        "url": f"https://linear.app/demo/issue/DEM-{number}",
        "priority": 2,
        "blocks": (),
        "blocked_by": (),
    }
    return an_issue_summary(**(values | fields))


def _board(
    planned: tuple[PlannedTicket, ...],
    summaries: tuple[IssueSummary, ...] | None,
    *,
    external: tuple[IssueSummary, ...] = (),
    acs: tuple[RecordAc, ...] = (),
) -> TicketBoard:
    snapshot = (
        None
        if summaries is None
        else a_ticket_snapshot(summaries=summaries, missing=(), external=external)
    )
    return ticket_board(planned, acs, snapshot)


def _row(board: TicketBoard, ref: str) -> TicketRow:
    return next(row for row in board.rows if row.ref == ref)


def test_layers_tickets_when_plan_has_edges() -> None:
    planned = (
        _planned(1, priority=2, order=2),
        _planned(2, order=1),
        _planned(3, blocked_by=(1, 2)),
        _planned(4, order=4),
        _planned(5, blocked_by=(3,)),
        _planned(6),
    )
    summaries = (
        _summary(1, priority=2),
        _summary(2, priority=2),
        _summary(3, priority=0),
        _summary(4, priority=1),
        _summary(5),
        _summary(6, state=_DONE),
    )

    board = _board(planned, summaries)

    assert board.plan.layers == (("DEM-4", "DEM-2", "DEM-1"), ("DEM-3",), ("DEM-5",))
    assert board.plan.can_start == ("DEM-4", "DEM-2", "DEM-1")
    assert board.plan.order == ("DEM-4", "DEM-2", "DEM-1", "DEM-3", "DEM-5")
    assert board.plan.waiting == ("DEM-3", "DEM-5")
    assert _row(board, "DEM-5").waiting_on == ("DEM-3",)
    assert _row(board, "DEM-5").readiness == "waiting"
    assert _row(board, "DEM-6").readiness == "done"
    assert _row(board, "DEM-1").blocks == ("DEM-3",)


def test_puts_no_priority_last_when_layer_ties() -> None:
    planned = (_planned(1, order=1), _planned(2, order=2), _planned(3, order=3))
    summaries = (_summary(1, priority=0), _summary(2, priority=4), _summary(3, priority=None))

    board = _board(planned, summaries)

    assert board.plan.order == ("DEM-2", "DEM-1", "DEM-3")


@st.composite
def _features(draw: st.DrawFn) -> tuple[tuple[PlannedTicket, ...], tuple[IssueSummary, ...]]:
    size = draw(st.integers(min_value=1, max_value=40))
    planned: list[PlannedTicket] = []
    summaries: list[IssueSummary] = []
    states: tuple[IssueStateType, ...] = ("unstarted", "started", "completed", "canceled")
    for number in range(1, size + 1):
        blockers = (
            draw(st.sets(st.integers(min_value=1, max_value=number - 1), max_size=4))
            if number > 1
            else set()
        )
        planned.append(
            _planned(
                number,
                blocked_by=tuple(sorted(blockers)),
                order=draw(st.integers(min_value=0, max_value=5)),
            )
        )
        kind = draw(st.sampled_from(states))
        summaries.append(
            _summary(
                number,
                state=IssueState(name=kind, type=kind),
                priority=draw(st.sampled_from((0, 1, 2, 3, 4, None))),
            )
        )
    return tuple(planned), tuple(summaries)


@settings(max_examples=150, deadline=None)
@given(feature=_features(), data=st.data())
def test_orders_topologically_when_dag_generated_property(
    feature: tuple[tuple[PlannedTicket, ...], tuple[IssueSummary, ...]], data: st.DataObject
) -> None:
    planned, summaries = feature

    board = _board(planned, summaries)

    active = {row.ref for row in board.rows if row.readiness not in ("done", "canceled")}
    position = {ref: index for index, ref in enumerate(board.plan.order)}
    assert set(position) == active
    assert board.plan.cycles == ()
    layer_of = {ref: index for index, layer in enumerate(board.plan.layers) for ref in layer}
    assert set(layer_of) == active
    for row in board.rows:
        for edge in row.blocked_by:
            if row.ref in active and edge.ref in active:
                assert position[edge.ref] < position[row.ref]
                assert layer_of[edge.ref] < layer_of[row.ref]
    shuffled = data.draw(st.permutations(planned))
    again = _board(tuple(shuffled), tuple(data.draw(st.permutations(summaries))))
    assert again == board


def test_flags_cycles_and_external_blockers_when_present() -> None:
    planned = (
        _planned(1, blocked_by=(2,)),
        _planned(2, blocked_by=(1,)),
        _planned(3),
        _planned(4),
        _planned(5, blocked_by=(1,)),
    )
    summaries = (
        _summary(1),
        _summary(2),
        _summary(3, blocked_by=("DEM-9",)),
        _summary(4, blocked_by=("DEM-10",)),
        _summary(5),
    )
    external = (
        _summary(10, title="Outside, done", state=_DONE),
        _summary(9, title="Outside, open"),
    )

    board = _board(planned, summaries, external=external)

    assert board.plan.cycles == (("DEM-1", "DEM-2"),)
    assert _row(board, "DEM-1").readiness == "in_cycle"
    assert all("DEM-1" not in layer and "DEM-2" not in layer for layer in board.plan.layers)
    assert _row(board, "DEM-5").readiness == "waiting"
    assert _row(board, "DEM-3").waiting_on == ("DEM-9",)
    assert _row(board, "DEM-4").readiness == "can_start"
    assert [(item.id, item.done) for item in board.plan.external_blockers] == [
        ("DEM-9", False),
        ("DEM-10", True),
    ]
    assert board.plan.external_blockers[1].state == _DONE
    assert board.plan.can_start == ("DEM-4",)


def test_tags_edges_and_finds_critical_path_when_sources_differ() -> None:
    planned = (
        _planned(1),
        _planned(2, blocked_by=(1,)),
        _planned(3),
        _planned(4, blocked_by=(3,)),
        _planned(5),
    )
    summaries = (
        _summary(1),
        _summary(2),
        _summary(3, blocked_by=("DEM-2",)),
        _summary(4, blocked_by=("DEM-3",)),
        _summary(5, blocks=("DEM-1",)),
    )

    board = _board(planned, summaries)

    assert _row(board, "DEM-2").blocked_by == (TicketEdge(ref="DEM-1", source="plan"),)
    assert _row(board, "DEM-3").blocked_by == (TicketEdge(ref="DEM-2", source="linear"),)
    assert _row(board, "DEM-4").blocked_by == (TicketEdge(ref="DEM-3", source="both"),)
    assert _row(board, "DEM-1").blocked_by == (TicketEdge(ref="DEM-5", source="linear"),)
    assert board.plan.critical_path == ("DEM-5", "DEM-1", "DEM-2", "DEM-3", "DEM-4")


def test_leaves_done_tickets_off_critical_path_when_some_done() -> None:
    planned = (_planned(1), _planned(2, blocked_by=(1,)), _planned(3), _planned(4, blocked_by=(3,)))
    summaries = (_summary(1, state=_DONE), _summary(2), _summary(3), _summary(4))

    board = _board(planned, summaries)

    assert board.plan.critical_path == ("DEM-3", "DEM-4")


def test_unblocks_dependents_when_blocker_canceled() -> None:
    planned = (_planned(1), _planned(2, blocked_by=(1,)))
    summaries = (_summary(1, state=_CANCELED), _summary(2))

    board = _board(planned, summaries)

    assert _row(board, "DEM-1").readiness == "canceled"
    assert _row(board, "DEM-2").readiness == "can_start"
    assert _row(board, "DEM-2").waiting_on == ()
    assert board.plan.layers == (("DEM-2",),)


def test_drops_url_when_host_not_linear() -> None:
    urls = (
        "https://linear.app/acme/issue/DEM-1",
        "https://evil.example/x",
        "javascript:x",
        "http://linear.app/x",
        "https://linear.app.evil.example/x",
        "https://user@linear.app/x",
    )
    planned = tuple(_planned(index + 1) for index in range(len(urls)))
    summaries = tuple(
        _summary(index + 1, url=url, blocked_by=("DEM-9",) if index == 0 else ())
        for index, url in enumerate(urls)
    )
    external = (_summary(9, url="https://evil.example/y"),)

    board = _board(planned, summaries, external=external)

    assert [row.url for row in board.rows] == [urls[0], None, None, None, None, None]
    assert board.plan.external_blockers[0].url is None


def test_redacts_title_when_title_holds_secret() -> None:
    secret = "Rotate lin_api_" + "A1b2C3d4E5f6G7h8" + " and ghp_" + "abcdefgh12345678"
    planned = (_planned(1), _planned(2, title="Plan title ghp_" + "abcdefgh12345678"))
    summaries = (_summary(1, title=secret, assignee="x" * 120),)

    board = _board(planned, summaries)

    first = _row(board, "DEM-1")
    assert first.title == "Rotate [redacted: linear key] and [redacted: github token]"
    assert first.assignee is not None and len(first.assignee) == 80
    assert _row(board, "DEM-2").title == "Plan title [redacted: github token]"


def test_clips_title_when_title_too_long() -> None:
    board = _board((_planned(1),), (_summary(1, title="y" * 500),))

    assert len(_row(board, "DEM-1").title or "") == 200


def test_warns_when_relations_truncated() -> None:
    board = _board((_planned(1),), (_summary(1, relations_truncated=True),))

    assert any("DEM-1" in warning for warning in board.plan.warnings)


def test_reads_plan_edges_when_no_snapshot() -> None:
    planned = (_planned(1, id=None), _planned(2, blocked_by=(1,)))

    board = _board(planned, None)

    first, second = board.rows
    assert (first.ref, first.state, first.readiness, first.reviewed) == (
        "T1",
        None,
        "can_start",
        None,
    )
    assert second.readiness == "waiting"
    assert second.waiting_on == ("T1",)
    assert board.plan.order == ("T1", "DEM-2")


def test_marks_reviewed_when_completed_or_approved_record() -> None:
    planned = (_planned(1), _planned(2), _planned(3))
    summaries = (_summary(1, state=_DONE), _summary(2), _summary(3))
    snapshot = a_ticket_snapshot(summaries=summaries, missing=(), external=())

    board = ticket_board(planned, (), snapshot, approved=("dem-2",))
    fallback = ticket_board(planned, (), None, approved=("T3",))

    assert [row.reviewed for row in board.rows] == [True, True, False]
    assert [row.reviewed for row in fallback.rows] == [None, None, True]


def test_lists_acs_and_linear_only_ids_when_record_names_them() -> None:
    acs = (
        RecordAc(id="AC-7.1", description="d", passes=True, ticket="T1"),
        RecordAc(id="AC-7.2", description="d", passes=False, ticket="DEM-1"),
        RecordAc(id="AC-7.3", description="d", passes=False, ticket="T1", withdrawn=True),
        RecordAc(id="AC-7.4", description="d", passes=False, ticket="DEM-7"),
    )
    snapshot = a_ticket_snapshot(summaries=(_summary(7),), missing=(), external=())

    board = ticket_board((_planned(1, id=None, title=None),), acs, snapshot, linear=("DEM-7", "T1"))

    first, linear_only = board.rows
    assert (first.ref, first.acs, first.title) == ("T1", ("AC-7.1",), None)
    assert (linear_only.key, linear_only.id, linear_only.acs) == (None, "DEM-7", ("AC-7.4",))
    assert linear_only.title == "Ticket 7"


def test_warns_when_blocker_unknown_or_duplicate_key() -> None:
    planned = (
        _planned(1, blocked_by=()),
        PlannedTicket(key="T2", id="DEM-2", blocked_by=("T9",)),
        _planned(1, id="DEM-11"),
    )

    board = _board(planned, None)

    assert [row.ref for row in board.rows] == ["DEM-1", "DEM-2"]
    assert any("T9" in warning for warning in board.plan.warnings)
    assert any("T1" in warning and "twice" in warning for warning in board.plan.warnings)


def _external_plan_board(ops: IssueSummary | None, *, as_external: bool = False) -> TicketBoard:
    planned = (PlannedTicket(key="T1", id="DEM-1", blocked_by=("OPS-7",)),)
    read = () if ops is None else (ops,)
    summaries = (_summary(1), *(() if as_external else read))
    snapshot = a_ticket_snapshot(
        summaries=summaries, missing=(), external=read if as_external else ()
    )
    return ticket_board(planned, (), snapshot)


def _ops(state: IssueState) -> IssueSummary:
    return _summary(
        7, id="OPS-7", title="Outside", state=state, url="https://linear.app/demo/issue/OPS-7"
    )


def test_starts_dependent_when_plan_only_external_blocker_completed() -> None:
    for as_external in (False, True):
        board = _external_plan_board(_ops(_DONE), as_external=as_external)

        row = _row(board, "DEM-1")
        assert (row.readiness, row.waiting_on) == ("can_start", ())
        assert board.plan.can_start == ("DEM-1",)
        (blocker,) = board.plan.external_blockers
        assert (blocker.id, blocker.state, blocker.url, blocker.done) == (
            "OPS-7",
            _DONE,
            "https://linear.app/demo/issue/OPS-7",
            True,
        )


def test_waits_on_plan_only_external_blocker_when_not_completed() -> None:
    board = _external_plan_board(_ops(_STARTED))

    row = _row(board, "DEM-1")
    assert (row.readiness, row.waiting_on) == ("waiting", ("OPS-7",))
    (blocker,) = board.plan.external_blockers
    assert (blocker.state, blocker.done) == (_STARTED, False)


def test_keeps_plan_only_external_blocker_unknown_when_not_read() -> None:
    planned = (PlannedTicket(key="T1", id="DEM-1", blocked_by=("OPS-7",)),)

    unread = _external_plan_board(None)
    plan_only = ticket_board(planned, (), None)

    for board in (unread, plan_only):
        assert _row(board, "DEM-1").waiting_on == ("OPS-7",)
        (blocker,) = board.plan.external_blockers
        assert (blocker.state, blocker.url, blocker.done) == (None, None, False)


def test_redacts_state_name_when_state_holds_secret() -> None:
    secret = "lin_api_" + "Z9y8X7w6V5u4T3s2"
    leaky = IssueState(name=f"Blocked {secret}", type="started")
    planned = (_planned(1),)
    summaries = (_summary(1, state=leaky, blocked_by=("DEM-9",)),)
    external = (_summary(9, state=leaky),)

    board = _board(planned, summaries, external=external)

    states = (_row(board, "DEM-1").state, board.plan.external_blockers[0].state)
    for state in states:
        assert state is not None
        assert secret not in state.name
        assert state.name == "Blocked [redacted: linear key]"
        assert state.type == "started"
