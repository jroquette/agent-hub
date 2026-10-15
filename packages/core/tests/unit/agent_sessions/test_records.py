from datetime import UTC, datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from agent_hub.core.agent_sessions.agent_session import AgentSessionStatus
from agent_hub.core.agent_sessions.records import (
    AUDIT_RECORD_KINDS,
    DRIVER_RECORD_KINDS,
    Attachment,
    DeltaFrame,
    LogRecord,
    PermissionDecisionBody,
    RecordKind,
    StatusFrame,
    StreamItem,
    UserMessageBody,
)

AT = datetime(2026, 10, 13, 9, 0, 0, 250000, tzinfo=UTC)


def test_serializes_record_when_permission_decision_built() -> None:
    body = PermissionDecisionBody(request_id="req-1", decision="always", suggestion=0)

    record = LogRecord(
        seq=7, at=AT, kind="permission.decision", by="web", body=body.as_body(), text_bytes=0
    )

    assert record.model_dump(mode="json") == {
        "seq": 7,
        "at": "2026-10-13T09:00:00.250Z",
        "kind": "permission.decision",
        "by": "web",
        "body": {"request_id": "req-1", "decision": "always", "suggestion": 0},
        "text_bytes": 0,
    }


def test_leaves_deltas_out_when_record_kinds_listed() -> None:
    kinds = set(TypeAdapter(RecordKind).json_schema()["enum"])

    assert "text.delta" not in kinds
    assert kinds == DRIVER_RECORD_KINDS | AUDIT_RECORD_KINDS
    assert DRIVER_RECORD_KINDS.isdisjoint(AUDIT_RECORD_KINDS)


def test_refuses_record_when_seq_not_positive() -> None:
    with pytest.raises(ValidationError):
        LogRecord(seq=0, at=AT, kind="close", by="web", body={}, text_bytes=0)


def test_tells_frames_apart_when_stream_item_parsed() -> None:
    items: TypeAdapter[StreamItem] = TypeAdapter(StreamItem)

    delta = items.validate_python(
        {"frame": "delta", "after_seq": 3, "block": 0, "index": 1, "text": "Hi"}
    )
    status = items.validate_python({"frame": "status", "status": "idle"})

    assert delta == DeltaFrame(after_seq=3, block=0, index=1, text="Hi")
    assert status == StatusFrame(status=AgentSessionStatus.IDLE)


def test_omits_attachments_when_none() -> None:
    assert UserMessageBody(text="Hi").as_body() == {"text": "Hi"}


def test_serialises_screenshot_attachments_when_given() -> None:
    body = UserMessageBody(
        text="What is on this screen?",
        attachments=(Attachment(kind="screenshot", media_type="image/png", bytes=1234),),
    )

    assert body.as_body() == {
        "text": "What is on this screen?",
        "attachments": [{"kind": "screenshot", "media_type": "image/png", "bytes": 1234}],
    }
