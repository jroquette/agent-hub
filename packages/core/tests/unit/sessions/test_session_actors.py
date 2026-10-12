from datetime import timedelta

from agent_hub.core.sessions.session import Actor
from agent_hub.core.sessions.session_actors import fold_actors
from agent_hub.core.testing.session_scenarios import (
    SCENARIO_START,
    a_session_events,
    a_subagent_events,
    an_agent_call,
    as_stored,
    shuffled,
    stored_event_id,
)

MINUTE = timedelta(minutes=1)


def test_links_description_when_agent_call_brackets_subagent() -> None:
    main = a_session_events(tools=(), ended=False)
    call = an_agent_call(
        "toolu_agent_1", at=SCENARIO_START + 5 * MINUTE, done_at=SCENARIO_START + 20 * MINUTE
    )
    later_call = an_agent_call(
        "toolu_agent_2",
        subagent_type="Plan",
        description="Plan the change",
        at=SCENARIO_START + 30 * MINUTE,
    )
    explore = a_subagent_events("agent-a", start=SCENARIO_START + 6 * MINUTE)
    plan = a_subagent_events("agent-b", subagent_type="Plan", start=SCENARIO_START + 31 * MINUTE)
    stray = a_subagent_events(
        "agent-c", subagent_type="Explore", start=SCENARIO_START + 40 * MINUTE
    )
    events = as_stored([*main, *call, *later_call, *plan, *explore, *stray])
    call_id = stored_event_id(len(main) + 1)

    actors = fold_actors(events)

    assert actors == (
        Actor(kind="main"),
        Actor(
            kind="subagent",
            type="Explore",
            agent_id="agent-a",
            description="Find the session folds",
            started_by_event_id=call_id,
        ),
        Actor(
            kind="subagent",
            type="Plan",
            agent_id="agent-b",
            description="Plan the change",
            started_by_event_id=stored_event_id(len(main) + 3),
        ),
        Actor(kind="subagent", type="Explore", agent_id="agent-c"),
    )
    for seed in range(20):
        noisy = [*events, *shuffled(events, seed + 50)[:5]]
        assert fold_actors(shuffled(noisy, seed)) == actors


def test_leaves_description_empty_when_two_calls_overlap() -> None:
    main = a_session_events(tools=(), ended=False)
    first = an_agent_call("toolu_agent_1", at=SCENARIO_START + 5 * MINUTE)
    second = an_agent_call(
        "toolu_agent_2", description="Find the tests", at=SCENARIO_START + 5 * MINUTE + 1 * MINUTE
    )
    one = a_subagent_events("agent-a", start=SCENARIO_START + 8 * MINUTE)
    two = a_subagent_events("agent-b", start=SCENARIO_START + 9 * MINUTE)

    actors = fold_actors(as_stored([*main, *first, *second, *one, *two]))

    assert actors == (
        Actor(kind="main"),
        Actor(kind="subagent", type="Explore", agent_id="agent-a"),
        Actor(kind="subagent", type="Explore", agent_id="agent-b"),
    )


def test_lists_only_main_actor_when_no_subagent_ran() -> None:
    assert fold_actors(as_stored(a_session_events())) == (Actor(kind="main"),)
