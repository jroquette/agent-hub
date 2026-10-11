import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent_hub.api.dependencies import ApiPorts
from agent_hub.core.ingestion.hook_envelope import MAX_BODY_BYTES
from agent_hub.core.ingestion.ingest_hook import IngestHook
from agent_hub.core.ingestion.ingestion_ports import TailPosition, TailResult, TranscriptRef
from agent_hub.core.ingestion.ingestion_status import IngestionCounters
from agent_hub.storage.event_store import SqliteEventStore, open_event_store

# Synthetic, shaped like a key so the redaction would catch it; never a real secret.
SYNTHETIC_KEY = "sk-ant-api03-SYNTHETICsecretVALUE0123456789"

ENVELOPE: dict[str, Any] = {
    "v": 1,
    "project": "demo",
    "repo": "demo-api",
    "sent_at": "2026-10-11T12:00:00.250Z",
    "hook": {
        "hook_event_name": "PreToolUse",
        "session_id": "session-1",
        "tool_name": "Bash",
        "tool_use_id": "toolu_demo_1",
        "tool_input": {"command": "make check"},
    },
}


class NoTranscript:
    def read_new(self, ref: TranscriptRef) -> TailResult:
        return TailResult(events=())

    def commit(self, position: TailPosition) -> None:
        return None


@pytest.fixture
def store(tmp_path: Path) -> SqliteEventStore:
    return open_event_store(tmp_path / "events.db")


@pytest.fixture
def hooks_client(open_client: Any, fakes: Any, store: SqliteEventStore) -> Iterator[TestClient]:
    counters = IngestionCounters(clock=fakes.Clock().now)
    ingest = IngestHook(store, fakes.HookMapper(), NoTranscript(), status=counters)
    with open_client(ports=ApiPorts(ingest_hook=ingest, counters=counters)) as client:
        yield client


def test_reports_duplicate_and_keeps_one_row_when_envelope_posted_twice(
    hooks_client: TestClient, store: SqliteEventStore
) -> None:
    first = hooks_client.post("/api/v1/events/hooks", json=ENVELOPE)
    second = hooks_client.post("/api/v1/events/hooks", json=ENVELOPE)

    assert (first.status_code, first.json()) == (202, {"appended": 1, "duplicates": 0})
    assert (second.status_code, second.json()) == (202, {"appended": 0, "duplicates": 1})
    (stored,) = store.read_all()
    assert (stored.project, stored.session, stored.repo) == ("demo", "session-1", "demo-api")


def _without(name: str) -> dict[str, Any]:
    return {key: value for key, value in ENVELOPE.items() if key != name}


def _nested(depth: int) -> dict[str, Any]:
    value: Any = "leaf"
    for _ in range(depth):
        value = [value]
    return ENVELOPE | {"hook": ENVELOPE["hook"] | {"tool_input": value}}


@pytest.mark.parametrize(
    "body",
    [
        _without("project"),
        _without("sent_at"),
        ENVELOPE | {"v": 2},
        ENVELOPE | {"v": True},
        ENVELOPE | {"surprise": 1},
        ENVELOPE | {"project": ""},
        ENVELOPE | {"sent_at": "yesterday"},
        ENVELOPE | {"hook": "PreToolUse"},
        ENVELOPE | {"decision": {"by": "nobody", "kind": "deny"}},
        _nested(70),
        [ENVELOPE],
    ],
)
def test_rejects_unprocessable_problem_and_appends_nothing_when_envelope_malformed(
    hooks_client: TestClient, store: SqliteEventStore, body: object
) -> None:
    response = hooks_client.post("/api/v1/events/hooks", json=body)

    assert response.status_code == 422, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["title"] == "Invalid request body"
    assert store.read_all() == []


def test_rejects_unprocessable_problem_when_body_not_json(
    hooks_client: TestClient, store: SqliteEventStore
) -> None:
    response = hooks_client.post(
        "/api/v1/events/hooks", content=b"{not json", headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422
    assert store.read_all() == []


def test_rejects_unprocessable_problem_when_nesting_too_deep_for_parser(
    hooks_client: TestClient, store: SqliteEventStore
) -> None:
    body = b"[" * 5000 + b"]" * 5000

    response = hooks_client.post(
        "/api/v1/events/hooks", content=body, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422
    assert "deeper than 64" in response.json()["detail"]
    assert store.read_all() == []


def test_rejects_too_large_problem_and_appends_nothing_when_envelope_over_cap(
    hooks_client: TestClient, store: SqliteEventStore
) -> None:
    hook = ENVELOPE["hook"] | {"padding": "x" * MAX_BODY_BYTES}
    body = json.dumps(ENVELOPE | {"hook": hook}).encode()

    response = hooks_client.post(
        "/api/v1/events/hooks", content=body, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 413
    assert response.headers["content-type"] == "application/problem+json"
    assert store.read_all() == []


def test_stores_redacted_bash_call_when_sensor_envelope_posted_to_composed_app(
    composed: Any,
) -> None:
    hook = ENVELOPE["hook"] | {"tool_input": {"command": f"ANTHROPIC_API_KEY={SYNTHETIC_KEY} make"}}

    response = composed.client.post("/api/v1/events/hooks", json=ENVELOPE | {"hook": hook})

    assert (response.status_code, response.json()) == (202, {"appended": 1, "duplicates": 0})
    (stored,) = composed.rows()
    assert (stored.type, stored.source, stored.session) == ("tool.call", "claude_code", "session-1")
    assert stored.payload["tool"] == "Bash"
    assert stored.payload["command"] == "ANTHROPIC_API_KEY=[redacted: anthropic key] make"
