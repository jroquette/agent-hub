from agent_hub.core.sessions.session import ProblemCounts
from agent_hub.core.skills.skill_view import ItemKind, Mode, Origin
from agent_hub.core.testing.read_model_builders import (
    a_brain_note,
    a_brain_tree,
    a_bundled_file_text,
    a_catalog_item,
    a_feature_tickets,
    a_feature_view,
    a_finding_view,
    a_golden_path,
    a_hook_detail,
    a_hub_view,
    a_learning,
    a_learning_detail,
    a_problem,
    a_project_summary,
    a_run,
    a_session,
    a_session_label,
    a_session_problems,
    a_skill_catalog,
    a_skill_detail,
    a_skill_usage,
    a_ticket_snapshot,
    an_agent_detail,
    an_approval,
    an_eval_record,
    an_issue_summary,
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


def test_serializes_skill_builders_when_defaults_used() -> None:
    views = [
        a_catalog_item(),
        a_skill_catalog(),
        a_skill_detail(),
        an_agent_detail(),
        a_hook_detail(),
        a_bundled_file_text(),
        a_skill_usage(),
    ]

    for view in views:
        assert type(view).model_validate_json(view.model_dump_json()) == view


def test_keeps_ids_consistent_when_skill_builders_used() -> None:
    detail = a_skill_detail()
    catalog = a_skill_catalog()

    assert detail.id == f"{detail.kind}/{detail.source}/{detail.name}"
    assert {item.kind for item in catalog.items} == set(ItemKind)
    assert (detail.origin, detail.mode) == (Origin.MANAGED, Mode.BOTH)
    assert a_bundled_file_text().id in {file.id for file in detail.files}
    assert an_agent_detail().used_by[0].id == detail.id
    assert a_hook_detail().hook is not None
    assert a_catalog_item(name="beta").name == "beta"
