from datetime import timedelta
from decimal import Decimal

from agent_hub.core.events.stored_event import StoredEvent
from agent_hub.core.readmodels.live_tiles import failing_notice, live_tiles
from agent_hub.core.sessions.fold_session import fold_sessions, group_by_session
from agent_hub.core.sessions.session import ProblemCounts, SessionStatus
from agent_hub.core.sessions.session_problems import fold_problems
from agent_hub.core.testing.builders import an_event
from agent_hub.core.testing.session_scenarios import (
    SCENARIO_START,
    a_session_events,
    as_stored,
    usage_events,
)

BASH_FAILING = (
    ("Read", {"path": "src/app.py"}),
    ("Bash", {"command": "make check-fast"}),
    ("Bash", {"command": "make check-fast"}),
)


def _scene() -> tuple[list[StoredEvent], object]:
    waiting = a_session_events(
        "s-waiting", ended=False, start=SCENARIO_START + timedelta(minutes=25)
    )
    ask = an_event(
        session="s-waiting",
        type="gate.request",
        timestamp=waiting[-1].timestamp + timedelta(seconds=5),
        payload={"gate_id": "toolu_ask", "kind": "plan", "feature": "demo"},
    )
    live = a_session_events("s-live", ended=False, start=SCENARIO_START + timedelta(minutes=30))
    failing = a_session_events(
        "s-failing",
        ended=False,
        tools=BASH_FAILING,
        failed_tools=frozenset({1, 2}),
        start=SCENARIO_START + timedelta(minutes=31),
    )
    idle = a_session_events("s-idle", ended=False, start=SCENARIO_START + timedelta(minutes=20))
    ended_now = a_session_events("s-ended", start=SCENARIO_START + timedelta(minutes=29))
    ended_long_ago = a_session_events("s-old", start=SCENARIO_START)
    now = live[-1].timestamp + timedelta(minutes=1)
    events = as_stored(
        [
            *waiting,
            ask,
            *live,
            *failing,
            *idle,
            *ended_now,
            *ended_long_ago,
            *usage_events("s-live", turns=((100, 10, 0, 0),)),
        ]
    )
    return events, now


def test_groups_waiting_live_idle_then_recently_ended_when_tiles_built() -> None:
    events, now = _scene()
    sessions = fold_sessions(events, now=now)

    tiles = live_tiles(sessions, group_by_session(events), now=now)

    assert [(tile.id, tile.group) for tile in tiles] == [
        ("s-waiting", "waiting"),
        ("s-failing", "live"),
        ("s-live", "live"),
        ("s-idle", "idle"),
        ("s-ended", "ended_recently"),
    ]
    waiting = tiles[0]
    assert waiting.status == SessionStatus.WAITING
    assert waiting.waiting_reason == "Plan approval"
    assert tiles[1].failing_notice == "make check-fast failed 2 times in a row"
    assert tiles[2].failing_notice is None
    assert tiles[2].tokens_total == 110
    assert tiles[2].last_tool == "Bash"
    assert tiles[2].last_action == "Ran make check-fast"
    assert tiles[4].outcome is not None


def test_carries_run_budget_when_session_belongs_to_run() -> None:
    events = as_stored(a_session_events(run="r1", step="implement", attempt=1, ended=False))
    now = events[-1].event.timestamp
    sessions = fold_sessions(events, now=now)

    tiles = live_tiles(sessions, group_by_session(events), now=now, budgets={"r1": Decimal(10)})

    assert tiles[0].budget_usd == Decimal(10)
    assert (tiles[0].run_id, tiles[0].step, tiles[0].attempt) == ("r1", "implement", 1)


def test_notices_tool_errors_when_three_in_last_five_minutes() -> None:
    tools = tuple(("Grep", {"pattern": f"p{n}"}) for n in range(4))
    events = as_stored(
        a_session_events(tools=tools, failed_tools=frozenset({1, 2, 3}), ended=False)
    )
    last = events[-1].event.timestamp

    assert failing_notice(events, now=last) == "3 tool errors in the last 5 min"
    assert failing_notice(events, now=last + timedelta(minutes=10)) is None


def test_resets_streak_when_command_passes_between_failures() -> None:
    tools = tuple(("Bash", {"command": "make check"}) for _ in range(3))
    events = as_stored(a_session_events(tools=tools, failed_tools=frozenset({0, 2})))

    assert failing_notice(events, now=events[-1].event.timestamp + timedelta(hours=1)) is None


def test_notices_gate_streak_when_same_gate_fails_twice() -> None:
    gates = [
        an_event(
            type="gate.result",
            timestamp=SCENARIO_START + timedelta(minutes=minute),
            payload={
                "gate_id": f"g{minute}",
                "kind": "stop_gate",
                "result": "failed",
                "command": "make check-fast",
            },
        )
        for minute in (1, 2)
    ]

    notice = failing_notice(as_stored(gates), now=SCENARIO_START)

    assert notice == "make check-fast failed 2 times in a row"


CHECK_TWICE = (("Bash", {"command": "make check"}), ("Bash", {"command": "make check"}))


def test_names_needs_you_problem_when_problem_needs_owner() -> None:
    events = as_stored(
        a_session_events(
            tools=CHECK_TWICE,
            failed_tools=frozenset({1}),
            ended=False,
            git_branch="jdoe/dem-7-login",
        )
    )
    now = events[-1].event.timestamp + timedelta(minutes=10)
    sessions = fold_sessions(events, now=now)

    [tile] = live_tiles(sessions, group_by_session(events), now=now)

    assert tile.group == "idle"
    assert tile.problems == ProblemCounts(needs_you=1)
    assert tile.needs_you_problem == "Needs you: command_exit in make check"
    assert tile.label == sessions["session-1"].label
    assert tile.actors == sessions["session-1"].actors


def test_leaves_needs_you_empty_when_problems_handled() -> None:
    events = as_stored(
        a_session_events(tools=CHECK_TWICE, failed_tools=frozenset({0}), ended=False)
    )
    now = events[-1].event.timestamp + timedelta(minutes=10)
    sessions = fold_sessions(events, now=now)

    [tile] = live_tiles(sessions, group_by_session(events), now=now)

    assert tile.problems == ProblemCounts(handled=1)
    assert tile.needs_you_problem is None


def test_uses_given_problems_when_caller_folded_them() -> None:
    events = as_stored(
        a_session_events(tools=CHECK_TWICE, failed_tools=frozenset({1}), ended=False)
    )
    now = events[-1].event.timestamp + timedelta(minutes=10)
    sessions = fold_sessions(events, now=now)
    given = fold_problems(events, status=SessionStatus.IDLE)
    renamed = given.model_copy(
        update={
            "summary": tuple(
                line.model_copy(update={"text": f"given {line.text}"}) for line in given.summary
            )
        }
    )

    [tile] = live_tiles(
        sessions, group_by_session(events), now=now, problems={"session-1": renamed}
    )

    assert tile.needs_you_problem == "given Needs you: command_exit in make check"
