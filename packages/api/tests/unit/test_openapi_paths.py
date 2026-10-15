from agent_hub.api.app import create_app
from agent_hub.api.openapi_paths import (
    AGENT_SESSION_PATHS,
    CLARITY_PATHS,
    P2_PATHS,
    SERVED_PATHS,
    SKILL_PATHS,
    TICKET_PATHS,
    WORKFLOW_PATHS,
    document_paths,
)
from agent_hub.api.settings import ApiSettings

# The spec's "API surface in P2", with the path parameters named.
SPEC_PATHS = {
    ("post", "/api/v1/events/hooks"),
    ("get", "/api/v1/hubs"),
    ("post", "/api/v1/hubs"),
    ("delete", "/api/v1/hubs/{hub_id}"),
    ("get", "/api/v1/projects"),
    ("get", "/api/v1/projects/{project}"),
    ("get", "/api/v1/projects/{project}/now"),
    ("get", "/api/v1/projects/{project}/repos"),
    ("get", "/api/v1/needs-you"),
    ("get", "/api/v1/activity"),
    ("get", "/api/v1/search"),
    ("get", "/api/v1/sessions"),
    ("get", "/api/v1/sessions/{session_id}"),
    ("get", "/api/v1/sessions/{session_id}/summary"),
    ("get", "/api/v1/sessions/{session_id}/events"),
    ("get", "/api/v1/sessions/{session_id}/events/stream"),
    ("get", "/api/v1/sessions/{session_id}/files"),
    ("get", "/api/v1/sessions/{session_id}/cost"),
    ("get", "/api/v1/live-sessions"),
    ("get", "/api/v1/live-sessions/stream"),
    ("get", "/api/v1/workflow-runs"),
    ("get", "/api/v1/workflow-runs/{run_id}"),
    ("get", "/api/v1/workflow-runs/{run_id}/stream"),
    ("get", "/api/v1/approvals"),
    ("get", "/api/v1/approvals/{approval_id}"),
    ("get", "/api/v1/learnings"),
    ("get", "/api/v1/learnings/{learning_id}"),
    ("get", "/api/v1/features"),
    ("get", "/api/v1/features/{project}/{slug}"),
    ("get", "/api/v1/doctor/findings"),
    ("get", "/api/v1/collector/status"),
    ("get", "/api/v1/settings"),
    ("get", "/api/v1/events/stream"),
}


# The five paths control-plane clarity adds (AC-201.39), with the path parameters named.
CLARITY_SPEC_PATHS = {
    ("get", "/api/v1/sessions/{session_id}/problems"),
    ("post", "/api/v1/learnings/{learning_id}/accept"),
    ("post", "/api/v1/learnings/{learning_id}/reject"),
    ("get", "/api/v1/projects/{project}/brain"),
    ("get", "/api/v1/projects/{project}/brain/note"),
}


# The one path ticket planning adds (AC-136.33).
TICKET_SPEC_PATHS = {("get", "/api/v1/features/{project}/{slug}/tickets")}

# The three paths the Skills tab adds (AC-164.11, amendment A1), all GET.
SKILL_SPEC_PATHS = {
    ("get", "/api/v1/projects/{project}/skills"),
    ("get", "/api/v1/projects/{project}/skills/{kind}/{source}/{name}"),
    ("get", "/api/v1/projects/{project}/skills/{kind}/{source}/{name}/files/{file_id}"),
}


def test_lists_exactly_phase_two_paths_when_document_built(api_settings: ApiSettings) -> None:
    assert P2_PATHS == SPEC_PATHS
    assert document_paths(create_app(api_settings)) >= P2_PATHS


def test_lists_exactly_clarity_paths_when_document_built(api_settings: ApiSettings) -> None:
    assert CLARITY_PATHS == CLARITY_SPEC_PATHS
    assert document_paths(create_app(api_settings)) >= P2_PATHS | CLARITY_PATHS


def test_lists_ticket_path_when_document_built(api_settings: ApiSettings) -> None:
    # AC-136.33: the current paths plus the feature tickets read.
    assert TICKET_PATHS == TICKET_SPEC_PATHS
    assert document_paths(create_app(api_settings)) >= P2_PATHS | CLARITY_PATHS | TICKET_PATHS


# The 17 route-method pairs agent sessions add (S3 + E11, AGH-165 P5).
AGENT_SESSION_SPEC_PATHS = {
    ("get", "/api/v1/agent-sessions/workdirs"),
    ("get", "/api/v1/agent-sessions/capabilities"),
    ("get", "/api/v1/agent-sessions/resumable"),
    ("get", "/api/v1/agent-sessions/cloud"),
    ("post", "/api/v1/agent-sessions/cloud"),
    ("post", "/api/v1/agent-sessions/cloud/{cloud_id}/messages"),
    ("get", "/api/v1/agent-sessions"),
    ("post", "/api/v1/agent-sessions"),
    ("get", "/api/v1/agent-sessions/{agent_session_id}"),
    ("delete", "/api/v1/agent-sessions/{agent_session_id}"),
    ("get", "/api/v1/agent-sessions/{agent_session_id}/events"),
    ("get", "/api/v1/agent-sessions/{agent_session_id}/stream"),
    ("post", "/api/v1/agent-sessions/{agent_session_id}/messages"),
    ("post", "/api/v1/agent-sessions/{agent_session_id}/interrupt"),
    ("post", "/api/v1/agent-sessions/{agent_session_id}/permissions/{request_id}"),
    ("post", "/api/v1/agent-sessions/{agent_session_id}/settings"),
    ("post", "/api/v1/agent-sessions/{agent_session_id}/close"),
}


def test_lists_agent_session_paths_when_document_built(api_settings: ApiSettings) -> None:
    # AC-165.48: today's paths plus exactly the 17 agent-session pairs.
    assert len(AGENT_SESSION_SPEC_PATHS) == 17
    assert AGENT_SESSION_PATHS == AGENT_SESSION_SPEC_PATHS
    assert SERVED_PATHS == (
        P2_PATHS | CLARITY_PATHS | TICKET_PATHS | SKILL_PATHS | AGENT_SESSION_PATHS | WORKFLOW_PATHS
    )
    assert document_paths(create_app(api_settings)) == SERVED_PATHS


def test_lists_skill_paths_when_document_built(api_settings: ApiSettings) -> None:
    # AC-164.11: today's paths plus the three skills reads, all GET, and nothing else.
    assert SKILL_PATHS == SKILL_SPEC_PATHS
    assert SERVED_PATHS == (
        P2_PATHS | CLARITY_PATHS | TICKET_PATHS | SKILL_PATHS | AGENT_SESSION_PATHS | WORKFLOW_PATHS
    )
    assert document_paths(create_app(api_settings)) == SERVED_PATHS


def test_lists_workflow_paths_when_document_built(api_settings: ApiSettings) -> None:
    # AC-213.15: today's paths plus the two workflow reads, both GET, and nothing else.
    assert {
        ("get", "/api/v1/workflows"),
        ("get", "/api/v1/workflows/{project}/{name}"),
    } == WORKFLOW_PATHS
    assert document_paths(create_app(api_settings)) == SERVED_PATHS


def test_marks_agent_deprecated_when_document_built(api_settings: ApiSettings) -> None:
    schemas = create_app(api_settings).openapi()["components"]["schemas"]

    assert schemas["Session"]["properties"]["agent"]["deprecated"] is True
    assert schemas["LiveTile"]["properties"]["agent"]["deprecated"] is True
    assert schemas["Learning"]["properties"]["target"]["deprecated"] is True
    assert "deprecated" not in schemas["Session"]["properties"]["label"]


def test_documents_action_problems_when_document_built(api_settings: ApiSettings) -> None:
    paths = create_app(api_settings).openapi()["paths"]

    for action in ("accept", "reject"):
        operation = paths[f"/api/v1/learnings/{{learning_id}}/{action}"]["post"]
        assert {"201", "409", "415", "502", "504"} <= set(operation["responses"]), action


def test_documents_problem_responses_when_document_built(api_settings: ApiSettings) -> None:
    document = create_app(api_settings).openapi()

    for path_item in document["paths"].values():
        for operation in path_item.values():
            assert {"4XX", "5XX"} <= set(operation["responses"]), operation["operationId"]
            assert "422" not in operation["responses"], operation["operationId"]
