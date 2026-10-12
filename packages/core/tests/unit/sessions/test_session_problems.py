from datetime import datetime, timedelta

import pytest

from agent_hub.core.events.event import Event
from agent_hub.core.events.stored_event import StoredEvent
from agent_hub.core.json_form import JsonValue
from agent_hub.core.redaction.redact import clip
from agent_hub.core.sessions.problem import MAX_SUMMARY_LINES, ProblemKind, Resolution
from agent_hub.core.sessions.session import Actor, ProblemCounts, SessionStatus
from agent_hub.core.sessions.session_problems import fold_problems, problem_counts
from agent_hub.core.testing.builders import an_event
from agent_hub.core.testing.session_scenarios import (
    SCENARIO_START,
    a_subagent_events,
    as_stored,
    shuffled,
)

ENDED = SessionStatus.ENDED


def _at(minute: int) -> datetime:
    return SCENARIO_START + timedelta(minutes=minute)


def _start() -> Event:
    return an_event(
        type="session.start",
        timestamp=_at(0),
        source_id="session-1:SessionStart",
        agent="main",
        payload={"cwd": "/work/demo-api"},
    )


def _call(minute: int, use: str, tool: str, **payload: JsonValue) -> Event:
    return an_event(
        type="tool.call",
        timestamp=_at(minute),
        source_id=f"session-1:PreToolUse:{use}",
        agent="main",
        payload={"tool": tool, "tool_use_id": use} | payload,
    )


def _result(minute: int, use: str, tool: str, *, status: str, **payload: JsonValue) -> Event:
    hook = {"ok": "PostToolUse", "denied": "guard"}.get(status, "PostToolUseFailure")
    return an_event(
        type="tool.result",
        timestamp=_at(minute),
        source_id=f"session-1:{hook}:{use}",
        agent="main",
        payload={"tool": tool, "tool_use_id": use, "status": status} | payload,
    )


def _ask(minute: int, use: str, **payload: JsonValue) -> Event:
    return an_event(
        type="gate.request",
        timestamp=_at(minute),
        source_id=f"session-1:guard_ask:{use}",
        agent="main",
        payload={"gate_id": use, "kind": "guard_ask"} | payload,
    )


def _prompt(minute: int) -> Event:
    return an_event(
        type="message",
        timestamp=_at(minute),
        source_id=f"session-1:UserPromptSubmit:{minute}",
        agent="main",
        payload={"role": "user", "chars": 12},
    )


def _end(minute: int) -> Event:
    return an_event(
        type="session.end",
        timestamp=_at(minute),
        source_id=f"session-1:SessionEnd:{minute}",
        agent="main",
        payload={"end_reason": "prompt_input_exit"},
    )


def _stop_gate(minute: int, result: str = "failed") -> Event:
    return an_event(
        type="gate.result",
        timestamp=_at(minute),
        source_id=f"session-1:stop_gate:{minute}",
        agent="main",
        payload={
            "gate_id": f"stop-{minute}",
            "kind": "stop_gate",
            "command": "make check-fast",
            "exit_code": 2 if result == "failed" else 0,
            "result": result,
        },
    )


type Case = tuple[list[Event], ProblemKind, str | None, str | None, str | None]

KIND_CASES: dict[str, Case] = {
    "tool_failed": (
        [
            _call(1, "t1", "Edit", path="src/app.py"),
            _result(2, "t1", "Edit", status="error", error_message="String to replace not found"),
        ],
        ProblemKind.TOOL_FAILED,
        "Edit",
        "src/app.py",
        "String to replace not found",
    ),
    "command_exit": (
        [
            _call(1, "t1", "Bash", command="make check-fast"),
            _result(
                2, "t1", "Bash", status="error", error_message="Exit code 2 1 failed, 12 passed"
            ),
        ],
        ProblemKind.COMMAND_EXIT,
        "Bash",
        "make check-fast",
        "Exit code 2 1 failed, 12 passed",
    ),
    "guard_denied": (
        [
            _call(1, "t1", "Bash", command="git push --force"),
            _result(2, "t1", "Bash", status="denied", rule="push.force", hook="guard"),
        ],
        ProblemKind.GUARD_DENIED,
        "Bash",
        "git push --force",
        "rule push.force",
    ),
    "guard_ask_open": (
        [_call(1, "t1", "Edit", path="hub.json"), _ask(2, "t1", path="hub.json", rule="ask")],
        ProblemKind.GUARD_ASK_OPEN,
        "Edit",
        "hub.json",
        "rule ask",
    ),
    "guard_ask_declined": (
        [_call(1, "t1", "Edit", path="hub.json"), _ask(2, "t1", path="hub.json"), _prompt(3)],
        ProblemKind.GUARD_ASK_DECLINED,
        "Edit",
        "hub.json",
        None,
    ),
    "interrupted": (
        [
            _call(1, "t1", "Bash", command="sleep 600"),
            _result(2, "t1", "Bash", status="error", error_line="interrupted"),
        ],
        ProblemKind.INTERRUPTED,
        "Bash",
        "sleep 600",
        "interrupted",
    ),
    "gate_failed": (
        [_stop_gate(2)],
        ProblemKind.GATE_FAILED,
        None,
        "make check-fast",
        "make check-fast: exit code 2",
    ),
    "hook_failed": (
        [
            _call(1, "t1", "Write", path="notes.md"),
            _result(2, "t1", "Write", status="error", hook="lint", error_line="lint hook exited 1"),
        ],
        ProblemKind.HOOK_FAILED,
        "Write",
        "notes.md",
        "lint hook exited 1",
    ),
}


@pytest.mark.parametrize("name", sorted(KIND_CASES))
def test_classifies_problem_when_event_is_each_kind(name: str) -> None:
    events, kind, tool, where, message = KIND_CASES[name]
    stored = as_stored([_start(), *events])
    problem_event = stored[-1] if name != "guard_ask_declined" else stored[-2]

    [problem] = fold_problems(stored, status=SessionStatus.WAITING).items

    assert (problem.kind, problem.tool, problem.where, problem.message) == (
        kind,
        tool,
        where,
        message,
    )
    assert problem.at == problem_event.event.timestamp
    assert problem.event_id == problem_event.event_id
    assert problem.actor == Actor(kind="main")
    assert problem.derived is True


def test_names_subagent_actor_when_subagent_failed() -> None:
    failing = a_subagent_events(
        "agent-a",
        start=SCENARIO_START + timedelta(minutes=1),
        tools=(("Bash", {"command": "pytest"}),),
        failed_tools=frozenset({0}),
    )

    [problem] = fold_problems(as_stored([_start(), *failing]), status=ENDED).items

    assert problem.actor == Actor(kind="subagent", type="Explore", agent_id="agent-a")
    assert (problem.kind, problem.where, problem.message) == (
        ProblemKind.COMMAND_EXIT,
        "pytest",
        "exit status 2",
    )


RESOLUTION_CASES: dict[str, tuple[list[Event], SessionStatus, Resolution, int | None]] = {
    "recovered": (
        [
            _call(1, "t1", "Bash", command="make check"),
            _result(2, "t1", "Bash", status="error", error_line="exit status 2"),
            _call(3, "t2", "Edit", path="src/app.py"),
            _result(4, "t2", "Edit", status="ok"),
            _call(5, "t3", "Bash", command="make check"),
            _result(6, "t3", "Bash", status="ok"),
            _end(7),
        ],
        ENDED,
        Resolution.RECOVERED,
        6,
    ),
    "agent_continued": (
        [
            _call(1, "t1", "Edit", path="src/app.py"),
            _result(2, "t1", "Edit", status="error", error_line="String not found"),
            _call(3, "t2", "Read", path="src/app.py"),
            _result(4, "t2", "Read", status="ok"),
            _end(5),
        ],
        ENDED,
        Resolution.AGENT_CONTINUED,
        3,
    ),
    "guard_denied_then_stop": (
        [
            _call(1, "t1", "Bash", command="git push --force"),
            _result(2, "t1", "Bash", status="denied", rule="push.force", hook="guard"),
            _end(3),
        ],
        ENDED,
        Resolution.NEEDS_YOU,
        None,
    ),
    "interrupt": (
        [
            _call(1, "t1", "Bash", command="sleep 600"),
            _result(2, "t1", "Bash", status="error", error_line="interrupted"),
            _prompt(3),
            _call(4, "t2", "Read", path="src/app.py"),
        ],
        ENDED,
        Resolution.BY_YOU,
        None,
    ),
    "open_guard_ask": (
        [_call(1, "t1", "Edit", path="hub.json"), _ask(2, "t1", path="hub.json")],
        SessionStatus.WAITING,
        Resolution.NEEDS_YOU,
        None,
    ),
}


@pytest.mark.parametrize("name", list(RESOLUTION_CASES))
def test_resolves_same_way_when_events_permuted(name: str) -> None:
    events, status, resolution, resolved_by = RESOLUTION_CASES[name]
    stored = as_stored([_start(), *events])
    expected = fold_problems(stored, status=status)

    [problem] = expected.items
    assert problem.resolution == resolution
    assert problem.resolved_by_event_id == (
        None if resolved_by is None else stored[resolved_by].event_id
    )
    for seed in range(50):
        noisy = shuffled([*stored, *shuffled(stored, seed + 100)[:3]], seed)
        assert fold_problems(noisy, status=status) == expected


def test_marks_declined_ask_by_you_when_turn_ended_without_tool_run() -> None:
    stored = as_stored([_start(), _call(1, "t1", "Edit"), _ask(2, "t1"), _prompt(3)])

    [problem] = fold_problems(stored, status=ENDED).items

    assert problem.resolution == Resolution.BY_YOU
    assert problem.resolved_by_event_id == stored[3].event_id


def test_recovers_gate_when_same_gate_passes_later() -> None:
    stored = as_stored([_start(), _stop_gate(1), _stop_gate(2, result="passed")])

    [problem] = fold_problems(stored, status=ENDED).items

    assert (problem.kind, problem.resolution) == (ProblemKind.GATE_FAILED, Resolution.RECOVERED)
    assert problem.resolved_by_event_id == stored[2].event_id


def test_uses_error_line_when_event_is_legacy() -> None:
    stored = as_stored(
        [
            _start(),
            _call(1, "t1", "Bash", command="make test"),
            _result(2, "t1", "Bash", status="error", error_line="exit status 1"),
            _call(3, "t2", "Edit", path="src/app.py"),
            _result(4, "t2", "Edit", status="error", error_line="String to replace not found"),
        ]
    )

    items = fold_problems(stored, status=ENDED).items

    assert [(item.kind, item.message) for item in items] == [
        (ProblemKind.COMMAND_EXIT, "exit status 1"),
        (ProblemKind.TOOL_FAILED, "String to replace not found"),
    ]


def test_prefers_error_message_when_both_texts_stored() -> None:
    stored = as_stored(
        [
            _start(),
            _call(1, "t1", "Bash", command="make test"),
            _result(
                2, "t1", "Bash", status="error", error_line="short", error_message="the longer text"
            ),
        ]
    )

    [problem] = fold_problems(stored, status=ENDED).items

    assert problem.message == "the longer text"


LONG_COMMAND = "make   check\n  && echo " + "x" * 400


@pytest.mark.parametrize(
    ("tool", "payload", "where"),
    [
        ("Bash", {"command": LONG_COMMAND}, clip(" ".join(LONG_COMMAND.split()), 120)),
        ("Read", {"path": "src/app.py"}, "src/app.py"),
        ("Grep", {"pattern": "def fold_", "path": "src"}, "def fold_"),
        ("WebFetch", {"url": "https://example.com/docs"}, "https://example.com/docs"),
        (
            "mcp__github__create_issue",
            {"mcp_server": "github", "mcp_tool": "create_issue"},
            "github.create_issue",
        ),
        ("Skill", {"skill": "hub-workflow:create-plan"}, "/create-plan"),
        ("Agent", {"subagent_type": "Explore"}, None),
    ],
)
def test_derives_where_when_call_paired(
    tool: str, payload: dict[str, JsonValue], where: str | None
) -> None:
    stored = as_stored(
        [
            _start(),
            _call(1, "t1", tool, **payload),
            _result(2, "t1", tool, status="error", error_line="boom"),
        ]
    )

    [problem] = fold_problems(stored, status=ENDED).items

    assert (problem.tool, problem.where) == (tool, where)
    assert problem.where is None or len(problem.where) <= 120


def test_leaves_where_empty_when_call_missing() -> None:
    stored = as_stored([_start(), _result(2, "t1", "Edit", status="error", error_line="boom")])

    [problem] = fold_problems(stored, status=ENDED).items

    assert (problem.tool, problem.where, problem.message) == ("Edit", None, "boom")


def test_marks_open_when_error_is_last_event_of_live_session() -> None:
    stored = as_stored(
        [
            _start(),
            _call(1, "t1", "Bash", command="make check"),
            _result(2, "t1", "Bash", status="error", error_line="exit status 2"),
        ]
    )

    [live] = fold_problems(stored, status=SessionStatus.LIVE).items
    [idle] = fold_problems(stored, status=SessionStatus.IDLE).items

    assert live.resolution == Resolution.OPEN
    assert idle.resolution == Resolution.NEEDS_YOU


def test_writes_summary_lines_when_problems_exist() -> None:
    stored = as_stored(
        [
            _start(),
            _call(1, "t1", "Edit", path="src/app.py"),
            _result(2, "t1", "Edit", status="error", error_line="String not found"),
            _call(3, "t2", "Bash", command="make check"),
            _result(4, "t2", "Bash", status="error", error_line="exit status 2"),
            _call(5, "t3", "Bash", command="make check"),
            _result(6, "t3", "Bash", status="ok"),
            _call(7, "t4", "Bash", command="sleep 600"),
            _result(8, "t4", "Bash", status="error", error_line="interrupted"),
            _call(9, "t5", "Bash", command="git push --force"),
            _result(10, "t5", "Bash", status="denied", rule="push.force", hook="guard"),
            _stop_gate(11),
            _end(12),
        ]
    )

    problems = fold_problems(stored, status=ENDED)

    assert problems.session_id == "session-1"
    assert [line.text for line in problems.summary] == [
        "5 problems: 2 need you, 2 handled by the agent, 1 by you",
        "Needs you: guard_denied in git push --force",
        "Needs you: gate_failed in make check-fast",
        "Handled by the agent: tool_failed in src/app.py",
        "Handled by the agent: command_exit in make check",
    ]
    assert len(problems.summary) == MAX_SUMMARY_LINES
    assert [line.event_id for line in problems.summary] == [
        stored[n].event_id for n in (10, 10, 11, 2, 4)
    ]
    assert [item.event_id for item in problems.items] == [
        stored[n].event_id for n in (2, 4, 8, 10, 11)
    ]
    assert problem_counts(problems.items) == ProblemCounts(needs_you=2, handled=2, by_you=1)


def test_writes_no_summary_when_session_has_no_problem() -> None:
    stored: list[StoredEvent] = as_stored(
        [_start(), _call(1, "t1", "Read", path="a.py"), _result(2, "t1", "Read", status="ok")]
    )

    problems = fold_problems(stored, status=ENDED)

    assert (problems.summary, problems.items) == ((), ())
    assert problem_counts(problems.items) == ProblemCounts()
