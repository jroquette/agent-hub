import pytest
from pydantic import ValidationError

from agent_hub.core.ingestion.ingestion_ports import HookMapping, TailResult, TranscriptRef
from agent_hub.core.testing.builders import an_event


def test_keeps_fields_when_transcript_ref_built() -> None:
    ref = TranscriptRef(session="session-1", path="/home/u/.claude/projects/x/s.jsonl", kind="main")

    assert (ref.session, ref.kind) == ("session-1", "main")


def test_accepts_subagent_kind_when_transcript_ref_built() -> None:
    ref = TranscriptRef(
        session="session-1", path="/home/demo/.local/share/agent-hub/agent-1.jsonl", kind="subagent"
    )

    assert ref.kind == "subagent"


def test_rejects_transcript_ref_when_kind_unknown() -> None:
    with pytest.raises(ValidationError, match="kind"):
        TranscriptRef.model_validate({"session": "s", "path": "/p", "kind": "sidechain"})


@pytest.mark.parametrize("field", ["session", "path"])
def test_rejects_transcript_ref_when_field_empty(field: str) -> None:
    document = {"session": "s", "path": "/p", "kind": "main"} | {field: ""}

    with pytest.raises(ValidationError, match=field):
        TranscriptRef.model_validate(document)


def test_holds_events_and_transcript_ref_when_mapping_built() -> None:
    event = an_event()
    ref = TranscriptRef(session="session-1", path="/p", kind="main")

    mapping = HookMapping(events=(event,), transcript=ref)

    assert mapping.events == (event,)
    assert mapping.transcript == ref


def test_defaults_counts_when_tail_result_built() -> None:
    result = TailResult(events=())

    assert (result.refused, result.skipped_lines) == (False, 0)


def test_rejects_tail_result_when_skipped_lines_negative() -> None:
    with pytest.raises(ValidationError, match="skipped_lines"):
        TailResult(events=(), skipped_lines=-1)
