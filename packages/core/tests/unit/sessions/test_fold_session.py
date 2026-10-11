from datetime import timedelta
from decimal import Decimal

from agent_hub.core.readmodels.fact_keys import canonical_events
from agent_hub.core.sessions.fold_session import fold_sessions, group_by_session
from agent_hub.core.sessions.session import Outcome, SessionStatus
from agent_hub.core.testing.builders import an_event
from agent_hub.core.testing.session_scenarios import (
    SCENARIO_START,
    a_run_events,
    a_session_events,
    as_stored,
    learning_events,
    shuffled,
    usage_events,
    with_transcript_copies,
)

NOW = SCENARIO_START + timedelta(hours=1)
TOOLS = (
    ("Read", {"path": "src/app.py"}),
    ("Edit", {"path": "src/app.py", "lines_added": 3, "lines_removed": 1}),
    ("Bash", {"command": "make check-fast"}),
    ("Bash", {"command": "make check"}),
)


def test_folds_counts_and_end_when_session_ended() -> None:
    events = as_stored(
        [
            *a_session_events(tools=TOOLS, failed_tools=frozenset({2})),
            *usage_events(turns=((1000, 200, 0, 0), (500, 100, 0, 0))),
            *learning_events(),
        ]
    )

    session = fold_sessions(events, now=NOW)["session-1"]

    assert session.project == "demo"
    assert session.repo == "demo-api"
    assert session.agent == "main"
    assert session.status == SessionStatus.ENDED
    assert session.outcome == Outcome.STOPPED
    assert session.end_reason == "prompt_input_exit"
    assert session.end_inferred is False
    assert session.tool_counts == {"Read": 1, "Edit": 1, "Bash": 2}
    assert session.files_touched == 1
    assert session.errors == 1
    assert session.turns == 2
    assert session.learnings_proposed == 1
    assert session.model == "claude-opus-5-5"
    assert session.tokens is not None
    assert session.tokens.input == 1500
    assert session.cost_usd == Decimal("0.012")
    assert session.has_transcript is True
    assert session.started_at == SCENARIO_START
    assert session.ended_at == session.segments[-1].ended_at


def test_folds_same_session_when_events_shuffled_with_duplicates_and_copies() -> None:
    events = as_stored(
        [
            *with_transcript_copies(a_session_events(tools=TOOLS, failed_tools=frozenset({3}))),
            *usage_events(turns=((1000, 200, 0, 0),), split_blocks=2),
        ]
    )
    expected = fold_sessions(events, now=NOW)

    for seed in range(50):
        noisy = shuffled([*events, *shuffled(events, seed + 100)[:7]], seed)
        assert fold_sessions(noisy, now=NOW) == expected
    session = expected["session-1"]
    assert session.tool_counts == {"Read": 1, "Edit": 1, "Bash": 2}
    assert session.errors == 1


def test_never_creates_session_when_only_executor_github_or_linear_events_name_it() -> None:
    events = as_stored(
        [
            *a_run_events(),
            an_event(session="unknown-1", source="github", type="decision"),
            an_event(session="unknown-2", source="linear", type="decision"),
            an_event(session="unknown-3", source="executor", type="gate.result"),
        ]
    )

    assert fold_sessions(events, now=NOW) == {}


def test_belongs_to_run_step_and_attempt_when_started_by_hub_run() -> None:
    events = as_stored(
        [
            *a_session_events(run="1a2b3c4d", step="implement", attempt=2),
            *a_run_events("1a2b3c4d", issue="DEM-7"),
        ]
    )

    session = fold_sessions(events, now=NOW)["session-1"]

    assert (session.run_id, session.step, session.attempt, session.issue) == (
        "1a2b3c4d",
        "implement",
        2,
        "DEM-7",
    )


def test_waits_when_guard_ask_open() -> None:
    events = a_session_events(ended=False)
    ask = an_event(
        type="gate.request",
        timestamp=events[-1].timestamp + timedelta(seconds=10),
        payload={"gate_id": "toolu_ask", "kind": "guard_ask"},
    )

    session = fold_sessions(as_stored([*events, ask]), now=ask.timestamp + timedelta(minutes=8))[
        "session-1"
    ]

    assert session.status == SessionStatus.WAITING


def test_infers_end_when_session_silent_for_thirty_minutes() -> None:
    events = a_session_events(ended=False)

    session = fold_sessions(as_stored(events), now=events[-1].timestamp + timedelta(minutes=31))[
        "session-1"
    ]

    assert session.status == SessionStatus.ENDED
    assert (session.outcome, session.end_reason, session.end_inferred) == (
        None,
        "no_end_event",
        True,
    )


def test_counts_guard_denials_and_cost_reason_when_model_unknown() -> None:
    denial = an_event(
        type="tool.result",
        payload={"tool": "Bash", "tool_use_id": "toolu_deny", "status": "denied", "rule": "push"},
    )
    events = as_stored([*a_session_events(), denial, *usage_events(model="claude-unknown-9")])

    session = fold_sessions(events, now=NOW)["session-1"]

    assert session.guard_denials == 1
    assert session.cost_usd is None
    assert session.cost_unknown_reason == "Cost unknown: model claude-unknown-9 has no price"


def test_folds_each_session_apart_when_events_mix_sessions() -> None:
    events = as_stored([*a_session_events("s-a"), *a_session_events("s-b", repo="demo-web")])

    sessions = fold_sessions(events, now=NOW)

    assert sorted(sessions) == ["s-a", "s-b"]
    assert sessions["s-b"].repo == "demo-web"
    assert sessions["s-a"].tokens is None
    assert sessions["s-a"].has_transcript is False


def test_counts_learning_once_when_hook_and_transcript_both_propose_it() -> None:
    [from_transcript] = learning_events(proposal="toolu_9")
    from_hook = from_transcript.model_copy(
        update={"source": "claude_code", "source_id": "session-1:PreToolUse:toolu_9"}
    )
    events = as_stored([*a_session_events(), from_transcript, from_hook])

    session = fold_sessions(events, now=NOW)["session-1"]

    assert session.learnings_proposed == 1


def test_groups_events_in_canonical_order_when_events_shuffled() -> None:
    events = as_stored([*a_session_events("s-1"), *a_session_events("s-2")])

    groups = group_by_session(shuffled(events, seed=5))

    assert set(groups) == {"s-1", "s-2"}
    for group in groups.values():
        assert canonical_events(group) is group
        assert group == canonical_events(list(group))
