from agent_hub.core.testing.read_model_builders import (
    a_feature_view,
    a_finding_view,
    a_hub_view,
    a_learning,
    a_project_summary,
    a_run,
    a_session,
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
