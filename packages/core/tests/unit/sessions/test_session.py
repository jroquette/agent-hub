import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from agent_hub.core.events.event import EventSource, EventType
from agent_hub.core.sessions.session import (
    Actor,
    ProblemCounts,
    Session,
    SessionCost,
    SessionLabel,
    SessionFileChange,
    SessionSummary,
    SummaryLine,
    TimelineEvent,
    TurnCost,
)
from agent_hub.core.testing.read_model_builders import EVENT_ID, a_session


def test_serializes_session_with_money_string_and_utc_millis_when_dumped() -> None:
    document = json.loads(a_session().model_dump_json())

    assert document["cost_usd"] == "0.0412"
    assert document["started_at"] == "2026-10-09T14:00:00.123Z"
    assert document["status"] == "live"
    assert document["derived"] is True
    assert document["sources_missing"] == ["otel", "github"]
    assert document["pr"] is None


def test_serializes_null_cost_when_model_has_no_price() -> None:
    session = a_session(cost_usd=None, cost_unknown_reason="Cost unknown: model x has no price")

    assert json.loads(session.model_dump_json())["cost_usd"] is None


def test_rejects_session_when_count_negative() -> None:
    with pytest.raises(ValidationError, match="turns"):
        a_session(turns=-1)


def test_serializes_summary_lines_with_event_ids_when_dumped() -> None:
    summary = SessionSummary(
        session_id="session-1",
        lines=(SummaryLine(text="Ran make check-fast: passed", event_id=EVENT_ID),),
        generated_at=datetime(2026, 10, 9, tzinfo=UTC),
    )

    document = json.loads(summary.model_dump_json())

    assert document["lines"] == [{"text": "Ran make check-fast: passed", "event_id": EVENT_ID}]
    assert (document["stored"], document["derived"]) == (False, True)


def test_serializes_file_change_when_dumped() -> None:
    change = SessionFileChange(
        repo="demo-api", path="src/app.py", ops=("edited",), added=3, removed=1, event_ids=()
    )

    assert change.model_dump(mode="json")["ops"] == ["edited"]


def test_rejects_file_change_when_operation_unknown() -> None:
    with pytest.raises(ValidationError, match="ops"):
        SessionFileChange.model_validate(
            {
                "repo": None,
                "path": "a",
                "ops": ["deleted"],
                "added": 0,
                "removed": 0,
                "event_ids": [],
            }
        )


def test_serializes_cost_series_when_dumped() -> None:
    cost = SessionCost(
        session_id="session-1",
        model="claude-opus-4-1",
        series=(
            TurnCost(
                turn=1, input=10, output=2, cache_read=0, cache_write=0, cost_usd=Decimal("0.1")
            ),
        ),
        total_usd=Decimal("0.1"),
        prices_as_of=date(2026, 10, 11),
    )

    document = json.loads(cost.model_dump_json())

    assert document["series"][0]["cost_usd"] == "0.1000"
    assert document["total_usd"] == "0.1000"
    assert document["prices_as_of"] == "2026-10-11"


def test_serializes_timeline_event_when_dumped() -> None:
    event = TimelineEvent(
        event_id=EVENT_ID,
        seq=4,
        project="demo",
        session="session-1",
        type=EventType.TOOL_CALL,
        timestamp=datetime(2026, 10, 9, 14, 5, 41, 882000, tzinfo=UTC),
        received_at=None,
        latency_ms=None,
        source=EventSource.CLAUDE_CODE,
        source_id="session-1:PreToolUse:toolu_1",
        repo=None,
        agent="main",
        workflow=None,
        step=None,
        payload={"tool": "Bash", "command": "make check"},
    )

    document = json.loads(event.model_dump_json())

    assert document["type"] == "tool.call"
    assert document["timestamp"] == "2026-10-09T14:05:41.882Z"
    assert (document["conflict"], document["merged_sources"]) == (False, [])


def test_serializes_label_when_session_has_issue() -> None:
    label = SessionLabel(
        issue="TIP-1511",
        workflow="/feature",
        workflows=("/feature", "/fix", "/create-plan"),
        repo="demo-api",
        branch="roquettejh/tip-1511-fix-login",
        worktree="tip-1511-fix-login",
    )
    main = Actor(kind="main")
    explorer = Actor(
        kind="subagent",
        type="Explore",
        agent_id="agent-1",
        description="map the collector",
        started_by_event_id=EVENT_ID,
    )

    document = json.loads(
        a_session(
            label=label,
            actors=(main, explorer),
            problems=ProblemCounts(needs_you=1, handled=2),
        ).model_dump_json()
    )

    assert document["label"]["issue"] == "TIP-1511"
    assert document["label"]["workflows"] == ["/feature", "/fix", "/create-plan"]
    assert document["label"]["derived"] is True
    assert document["actors"][0] == {
        "kind": "main",
        "type": None,
        "agent_id": None,
        "description": None,
        "started_by_event_id": None,
    }
    assert document["actors"][1]["started_by_event_id"] == EVENT_ID
    assert document["problems"] == {"needs_you": 1, "open": 0, "handled": 2, "by_you": 0}


def test_keeps_defaults_when_session_has_no_clarity_fields() -> None:
    session = a_session()

    assert (session.label, session.actors, session.problems) == (None, (), ProblemCounts())


def test_rejects_actor_when_kind_unknown() -> None:
    with pytest.raises(ValidationError, match="kind"):
        Actor.model_validate({"kind": "main-agent"})


def test_rejects_problem_counts_when_count_negative() -> None:
    with pytest.raises(ValidationError, match="needs_you"):
        ProblemCounts(needs_you=-1)


def test_marks_agent_deprecated_when_schema_built() -> None:
    schema = Session.model_json_schema()

    assert schema["properties"]["agent"]["deprecated"] is True
