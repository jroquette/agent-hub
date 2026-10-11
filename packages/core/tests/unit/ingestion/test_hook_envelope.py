from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from agent_hub.core.ingestion.hook_envelope import (
    MAX_BODY_BYTES,
    MAX_JSON_DEPTH,
    MAX_STRING_BYTES,
    HookDecision,
    HookEnvelope,
)


def an_envelope_document(**overrides: object) -> dict[str, Any]:
    document: dict[str, Any] = {
        "v": 1,
        "project": "demo",
        "repo": "demo-api",
        "run": None,
        "step": None,
        "attempt": None,
        "sent_at": "2026-10-11T10:00:00.123Z",
        "hook": {"hook_event_name": "PreToolUse", "session_id": "session-1"},
    }
    return document | overrides


def test_accepts_envelope_when_minimal_fields_given() -> None:
    envelope = HookEnvelope.model_validate(an_envelope_document())

    assert envelope.v == 1
    assert envelope.sent_at == datetime(2026, 10, 11, 10, 0, 0, 123000, tzinfo=UTC)
    assert envelope.hook["hook_event_name"] == "PreToolUse"
    assert envelope.decision is None


def test_accepts_decision_when_guard_denied() -> None:
    document = an_envelope_document(
        decision={
            "by": "guard",
            "kind": "deny",
            "rule": "push-to-main",
            "command": None,
            "exit_code": None,
        }
    )

    envelope = HookEnvelope.model_validate(document)

    assert envelope.decision == HookDecision(
        by="guard", kind="deny", rule="push-to-main", command=None, exit_code=None
    )


def test_accepts_run_fields_when_executor_session() -> None:
    envelope = HookEnvelope.model_validate(
        an_envelope_document(run="1a2b3c4d", step="implement", attempt=2)
    )

    assert (envelope.run, envelope.step, envelope.attempt) == ("1a2b3c4d", "implement", 2)


@pytest.mark.parametrize("version", [0, 2, "1", True, 1.0])
def test_rejects_envelope_when_version_is_not_one(version: object) -> None:
    with pytest.raises(ValidationError, match="v"):
        HookEnvelope.model_validate(an_envelope_document(v=version))


def test_rejects_envelope_when_unknown_key_present() -> None:
    with pytest.raises(ValidationError, match="extra"):
        HookEnvelope.model_validate(an_envelope_document(extra="x"))


@pytest.mark.parametrize("field", ["v", "project", "sent_at", "hook"])
def test_rejects_envelope_when_required_field_missing(field: str) -> None:
    document = an_envelope_document()
    del document[field]

    with pytest.raises(ValidationError, match=field):
        HookEnvelope.model_validate(document)


@pytest.mark.parametrize(
    ("by", "kind"), [("guard", "allow"), ("sensor", "deny")], ids=["kind", "by"]
)
def test_rejects_decision_when_by_or_kind_unknown(by: str, kind: str) -> None:
    decision = {"by": by, "kind": kind, "rule": None, "command": None, "exit_code": None}

    with pytest.raises(ValidationError):
        HookEnvelope.model_validate(an_envelope_document(decision=decision))


def test_rejects_envelope_when_project_empty() -> None:
    with pytest.raises(ValidationError, match="project"):
        HookEnvelope.model_validate(an_envelope_document(project=""))


def test_rejects_envelope_when_sent_at_has_no_offset() -> None:
    with pytest.raises(ValidationError, match="sent_at"):
        HookEnvelope.model_validate(an_envelope_document(sent_at="2026-10-11T10:00:00"))


def test_exposes_bounds_when_constants_read() -> None:
    assert (MAX_BODY_BYTES, MAX_STRING_BYTES, MAX_JSON_DEPTH) == (1_048_576, 65_536, 64)
