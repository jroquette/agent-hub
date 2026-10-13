from pydantic import TypeAdapter

from agent_hub.core.agent_sessions.records import RecordKind
from agent_hub.core.sessions.session import ProblemCounts
from agent_hub.core.testing.read_model_builders import (
    a_brain_note,
    a_brain_tree,
    a_cloud_session,
    a_feature_tickets,
    a_feature_view,
    a_finding_view,
    a_golden_path,
    a_hub_view,
    a_learning,
    a_learning_detail,
    a_log_record,
    a_permission_request,
    a_problem,
    a_project_summary,
    a_run,
    a_session,
    a_session_label,
    a_session_problems,
    a_ticket_snapshot,
    a_workdir,
    an_agent_session,
    an_approval,
    an_eval_record,
    an_issue_summary,
    an_open_permission,
)


def test_serializes_every_builder_when_defaults_used() -> None:
    views = [
        a_session(),
        a_run(),
        an_approval(),
        a_learning(),
        a_project_summary(),
        a_feature_view(),
        a_hub_view(),
        a_finding_view(),
    ]

    for view in views:
        assert type(view).model_validate_json(view.model_dump_json()) == view


def test_applies_override_when_builder_given_field() -> None:
    assert a_session(id="session-9").id == "session-9"


def test_serializes_clarity_builders_when_defaults_used() -> None:
    views = [
        a_session_label(),
        a_problem(),
        a_session_problems(),
        a_brain_tree(),
        a_brain_note(),
        a_learning_detail(),
        a_session(label=a_session_label(), problems=ProblemCounts(needs_you=1)),
    ]

    for view in views:
        assert type(view).model_validate_json(view.model_dump_json()) == view


def test_links_summary_to_problem_when_clarity_problems_built() -> None:
    problems = a_session_problems()

    assert problems.summary[0].event_id == problems.items[0].event_id


def test_serializes_tickets_builders_when_defaults_used() -> None:
    views = [
        an_issue_summary(),
        a_ticket_snapshot(),
        a_golden_path(),
        a_feature_tickets(),
        an_eval_record(),
    ]

    for view in views:
        assert type(view).model_validate_json(view.model_dump_json()) == view


def test_keeps_rows_and_planning_consistent_when_tickets_built() -> None:
    tickets = a_feature_tickets()
    refs = {row.ref for row in tickets.tickets}

    assert set(tickets.planning.order) <= refs
    assert {ref for layer in tickets.planning.layers for ref in layer} <= refs
    assert tickets.golden_path.phase == "implement"
    assert a_ticket_snapshot().summaries[0].id == an_issue_summary().id


def test_builds_every_record_kind_when_agent_session_builders_used() -> None:
    kinds = TypeAdapter(RecordKind).json_schema()["enum"]

    records = [a_log_record(kind, seq) for seq, kind in enumerate(kinds, start=1)]
    views = [an_agent_session(), a_permission_request(), a_workdir(), a_cloud_session()]

    assert [record.kind for record in records] == kinds
    assert all(record.model_dump(mode="json")["seq"] >= 1 for record in records)
    assert an_open_permission().suggestions[0].destination == "localSettings"
    assert all(view.model_dump(mode="json") for view in views)
