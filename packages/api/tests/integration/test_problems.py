import json
import logging
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent_hub.api.composition import COMPOSED_PROBLEMS
from agent_hub.api.dependencies import ApiPorts
from agent_hub.storage.errors import DatabaseAccessError
from agent_hub.storage.event_store import DatabaseBusyError

# Synthetic, shaped like a key so a leak would be obvious; never a real secret.
LEAK_SAMPLE = "sk-ant-api03-SYNTHETICsecretVALUE0123456789"


@pytest.mark.parametrize(
    ("path", "entity", "entity_id"),
    [
        ("/api/v1/sessions/nope-session", "session", "nope-session"),
        ("/api/v1/workflow-runs/0badc0ffee00", "run", "0badc0ffee00"),
        ("/api/v1/approvals/toolu_nope", "approval", "toolu_nope"),
        ("/api/v1/learnings/learning-nope", "learning", "learning-nope"),
        ("/api/v1/projects/nope-project", "project", "nope-project"),
        ("/api/v1/features/demo/nope-feature", "feature", "demo/nope-feature"),
        ("/api/v1/sessions/nope-session/cost", "session", "nope-session"),
    ],
)
def test_answers_not_found_problem_naming_id_when_entity_unknown(
    wired: Any, *, path: str, entity: str, entity_id: str
) -> None:
    response = wired.client.get(path)

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == {
        "type": "about:blank",
        "title": f"{entity.capitalize()} not found",
        "status": 404,
        "detail": f"No {entity} with id '{entity_id}'.",
        "instance": path,
    }


def test_answers_generic_problem_without_secret_when_internal_error(
    wired: Any, caplog: pytest.LogCaptureFixture
) -> None:
    wired.events.failure = RuntimeError(
        f"cannot fold payload {{'command': 'export K={LEAK_SAMPLE}'}}"
    )
    caplog.set_level(logging.DEBUG)

    response = wired.client.get("/api/v1/sessions", params={"project": "demo"})

    assert response.status_code == 500
    assert response.json() == {
        "type": "about:blank",
        "title": "Internal server error",
        "status": 500,
        "instance": "/api/v1/sessions",
    }
    logged = caplog.text + "".join(str(record.__dict__) for record in caplog.records)
    assert LEAK_SAMPLE not in response.text
    assert LEAK_SAMPLE not in logged
    assert "Traceback" not in logged
    assert all(record.exc_info is None for record in caplog.records)
    assert any(getattr(record, "error_type", None) == "RuntimeError" for record in caplog.records)


def test_answers_internal_problem_when_hook_ingestion_fails_on_secret_payload(
    open_client: Any, caplog: pytest.LogCaptureFixture
) -> None:
    class FailingIngest:
        def execute(self, envelope: object) -> object:
            raise ValueError(f"bad payload: {json.dumps(getattr(envelope, 'hook', {}))}")

    caplog.set_level(logging.DEBUG)
    envelope = {
        "v": 1,
        "project": "demo",
        "sent_at": "2026-10-11T12:00:00Z",
        "hook": {"hook_event_name": "PreToolUse", "tool_input": {"command": f"echo {LEAK_SAMPLE}"}},
    }
    with open_client(ports=ApiPorts(ingest_hook=FailingIngest())) as client:
        response = client.post("/api/v1/events/hooks", json=envelope)

    assert response.status_code == 500
    assert LEAK_SAMPLE not in response.text
    assert LEAK_SAMPLE not in caplog.text
    assert "Traceback" not in caplog.text


@pytest.fixture
def busy_client(open_client: Any, fakes: SimpleNamespace) -> Iterator[TestClient]:
    events = fakes.EventReadModels(failure=DatabaseBusyError("database is locked"))
    with open_client(
        ports=ApiPorts(event_read_models=events), problems=COMPOSED_PROBLEMS
    ) as client:
        yield client


def test_answers_service_unavailable_problem_when_database_busy(busy_client: TestClient) -> None:
    response = busy_client.get("/api/v1/approvals")

    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["title"] == "Collector database busy"


def test_answers_unavailable_problem_when_database_unreadable(wired: Any) -> None:
    wired.events.failure = DatabaseAccessError(f"/home/demo/a.db: disk I/O error {LEAK_SAMPLE}")

    response = wired.client.get("/api/v1/workflow-runs")

    assert response.status_code == 503
    assert response.json()["title"] == "Collector database unavailable"
    assert LEAK_SAMPLE not in response.text


@pytest.mark.parametrize(
    ("params", "parameter"),
    [
        ({"limit": "0"}, "limit"),
        ({"limit": "201"}, "limit"),
        ({"cost_min": "abc"}, "cost_min"),
        ({"cursor": "x" * 513}, "cursor"),
        ({"status": "sleeping"}, "status"),
        ({"cost_min": "5", "cost_max": "1"}, "cost_min"),
        ({"from": "2026-10-11T00:00:00Z", "to": "2026-10-10T00:00:00Z"}, "started_from"),
    ],
)
def test_answers_bad_request_naming_parameter_when_query_invalid(
    wired: Any, params: dict[str, str], parameter: str
) -> None:
    response = wired.client.get("/api/v1/sessions", params=params)

    assert response.status_code == 400, response.text
    problem = response.json()
    assert problem["title"] == "Invalid request parameter"
    assert f"'{parameter}'" in problem["detail"]
    assert problem["errors"][0]["parameter"] == parameter
    assert wired.events.calls == []


def test_answers_bad_request_when_search_text_missing(wired: Any) -> None:
    response = wired.client.get("/api/v1/search")

    assert response.status_code == 400
    assert response.json()["errors"] == [
        {"location": "query", "parameter": "q", "message": "Field required"}
    ]


def test_answers_not_found_problem_when_api_path_unknown(wired: Any) -> None:
    response = wired.client.get("/api/v1/nope")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["status"] == 404


def test_answers_method_not_allowed_problem_when_method_wrong(wired: Any) -> None:
    response = wired.client.delete("/api/v1/sessions")

    assert response.status_code == 405
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["title"] == "Method Not Allowed"
