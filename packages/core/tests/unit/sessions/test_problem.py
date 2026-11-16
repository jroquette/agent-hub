import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agent_hub.core.sessions.problem import (
    Problem,
    ProblemKind,
    Resolution,
    SessionProblems,
)
from agent_hub.core.sessions.session import Actor, SummaryLine
from agent_hub.core.testing.read_model_builders import EVENT_ID

AT = datetime(2026, 10, 9, 14, 0, tzinfo=UTC)


def a_needs_you_problem() -> Problem:
    return Problem(
        event_id=EVENT_ID,
        kind=ProblemKind.GUARD_DENIED,
        tool="Bash",
        where="git push --force",
        message="rule push.force",
        at=AT,
        actor=Actor(kind="main"),
        resolution=Resolution.NEEDS_YOU,
    )


def test_serializes_problem_when_resolution_is_needs_you() -> None:
    document = json.loads(a_needs_you_problem().model_dump_json())

    assert document == {
        "event_id": EVENT_ID,
        "kind": "guard_denied",
        "tool": "Bash",
        "where": "git push --force",
        "message": "rule push.force",
        "at": "2026-10-09T14:00:00.000Z",
        "actor": {
            "kind": "main",
            "type": None,
            "agent_id": None,
            "description": None,
            "started_by_event_id": None,
        },
        "resolution": "needs_you",
        "resolved_by_event_id": None,
        "derived": True,
    }


def test_lists_every_kind_when_enum_read() -> None:
    assert {kind.value for kind in ProblemKind} == {
        "tool_failed",
        "command_exit",
        "guard_denied",
        "guard_ask_open",
        "guard_ask_declined",
        "interrupted",
        "gate_failed",
        "hook_failed",
    }
    assert {resolution.value for resolution in Resolution} == {
        "recovered",
        "agent_continued",
        "open",
        "needs_you",
        "by_you",
    }


def test_serializes_session_problems_when_summary_given() -> None:
    problems = SessionProblems(
        session_id="session-1",
        summary=(SummaryLine(text="1 problem needs you", event_id=EVENT_ID),),
        items=(a_needs_you_problem(),),
    )

    document = json.loads(problems.model_dump_json())

    assert document["summary"] == [{"text": "1 problem needs you", "event_id": EVENT_ID}]
    assert document["items"][0]["kind"] == "guard_denied"
    assert document["derived"] is True


def test_rejects_session_problems_when_summary_longer_than_five_lines() -> None:
    line = SummaryLine(text="x", event_id=EVENT_ID)

    with pytest.raises(ValidationError, match="summary"):
        SessionProblems(session_id="session-1", summary=(line,) * 6, items=())
