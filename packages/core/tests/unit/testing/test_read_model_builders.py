from agent_hub.core.sessions.session import ProblemCounts
from agent_hub.core.testing.read_model_builders import (
    a_brain_note,
    a_brain_tree,
    a_feature_view,
    a_finding_view,
    a_hub_view,
    a_learning,
    a_learning_detail,
    a_problem,
    a_project_summary,
    a_run,
    a_session,
    a_session_label,
    a_session_problems,
    an_approval,
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
