import json

from agent_hub.api.rfc9457 import PROBLEM_MEDIA_TYPE, NotImplementedInBuildError, problem


def test_writes_problem_document_when_problem_built() -> None:
    response = problem(404, title="Session not found", detail="No session 'abc'.", instance="/x")

    assert response.status_code == 404
    assert response.media_type == PROBLEM_MEDIA_TYPE == "application/problem+json"
    assert json.loads(bytes(response.body)) == {
        "type": "about:blank",
        "title": "Session not found",
        "status": 404,
        "detail": "No session 'abc'.",
        "instance": "/x",
    }


def test_leaves_out_optional_members_when_not_given() -> None:
    response = problem(500, title="Internal error")

    assert json.loads(bytes(response.body)) == {
        "type": "about:blank",
        "title": "Internal error",
        "status": 500,
    }


def test_names_route_when_not_implemented_raised() -> None:
    error = NotImplementedInBuildError("GET /api/v1/sessions")

    assert str(error) == "GET /api/v1/sessions is not implemented in this build"
