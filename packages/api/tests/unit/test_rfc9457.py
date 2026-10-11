import json
from typing import Any

from agent_hub.api.dependencies import ApiPorts
from agent_hub.api.rfc9457 import (
    PROBLEM_MEDIA_TYPE,
    PROBLEMS,
    NotImplementedInBuildError,
    busy_problem,
    hub_conflict_problem,
    hub_invalid_problem,
    hub_registry_problem,
    not_found_problem,
    problem,
)
from agent_hub.core.readmodels.read_ports import EntityNotFoundError


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


def test_names_entity_and_id_when_not_found_mapped() -> None:
    found = not_found_problem(EntityNotFoundError(entity="session", entity_id="abc"))

    assert (found.status, found.title, found.detail) == (
        404,
        "Session not found",
        "No session with id 'abc'.",
    )


def test_says_busy_without_cause_when_busy_mapped() -> None:
    found = busy_problem(RuntimeError("database is locked at /home/demo/a.db"))

    assert (found.status, found.title) == (503, "Collector database busy")
    assert found.detail is not None
    assert "/home/demo" not in found.detail


def test_adds_extension_members_when_given() -> None:
    response = problem(400, title="Invalid", members={"errors": [{"parameter": "limit"}]})

    assert json.loads(bytes(response.body))["errors"] == [{"parameter": "limit"}]


def test_maps_every_table_entry_to_its_own_status_when_table_read() -> None:
    assert {error_type.__name__ for error_type in PROBLEMS} >= {
        "EntityNotFoundError",
        "EventConflictError",
        "DatabaseAccessError",
        "InvalidParameterError",
        "BodyTooLargeError",
        "NotImplementedInBuildError",
    }


class _Problem:
    def __init__(self, pointer: str, message: str) -> None:
        self.pointer = pointer
        self.message = message


class HubInvalidError(Exception):
    """Stands in for core/hubs' error (stream F) until the composition registers the real one."""

    def __init__(self, title: str, problems: tuple[object, ...]) -> None:
        self.title = title
        self.problems = problems
        super().__init__(f"{title} in /home/demo/demo-hub")


def test_lists_pointers_when_hub_invalid_mapped() -> None:
    error = HubInvalidError(
        "Invalid hub.json",
        (_Problem("/repos/0/check_fast", "required"), ("/project/name", "too short")),
    )

    found = hub_invalid_problem(error)

    assert (found.status, found.title) == (422, "Invalid hub.json")
    assert found.members == {
        "errors": [
            {"pointer": "/repos/0/check_fast", "message": "required"},
            {"pointer": "/project/name", "message": "too short"},
        ]
    }


def test_answers_conflict_when_hub_conflict_mapped() -> None:
    found = hub_conflict_problem(RuntimeError("project demo is registered from /home/demo/hub"))

    assert (found.status, found.title) == (409, "Hub already registered")


def test_hides_cause_when_hub_registry_unreadable() -> None:
    found = hub_registry_problem(RuntimeError("/home/demo/.config/agent-hub/hubs.json: EACCES"))

    assert (found.status, found.title) == (503, "Hub registry unreadable")
    assert found.detail is not None
    assert "hubs.json" not in found.detail


def test_answers_registered_problem_when_extra_error_raised(open_client: Any, fakes: Any) -> None:
    hubs = fakes.HubReadModels(failure=HubInvalidError("No hub.json", ()))

    with open_client(
        ports=ApiPorts(hub_read_models=hubs), problems={HubInvalidError: hub_invalid_problem}
    ) as client:
        response = client.post("/api/v1/hubs", json={"path": "/home/demo/nothing"})

    assert response.status_code == 422
    assert response.json()["title"] == "No hub.json"
    assert response.json()["errors"] == []
