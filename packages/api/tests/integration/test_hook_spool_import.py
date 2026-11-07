"""``hub web`` imports the hook sensor's spool when it starts, through the live hook path.

The spool is written as the sensor writes it (one envelope per line, mode 0600) into a temp
state folder that ``build_app`` is given; the app is the composed one (``open_composed``) on a temp
database and ``~/.claude/projects``. Every value is synthetic.
"""

import json
import logging
import os
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from agent_hub.api.settings import ApiSettings
from agent_hub.api.spool_import import SpoolImport
from agent_hub.collector.claude_hooks import ClaudeHookMapper
from agent_hub.collector.hook_spool import HookSpool
from agent_hub.collector.transcript_tail import TranscriptTail
from agent_hub.core.events.event import Event
from agent_hub.core.events.event_store import AppendResult
from agent_hub.core.ingestion.hook_envelope import HookEnvelope
from agent_hub.core.ingestion.ingest_hook import IngestHook
from agent_hub.core.ingestion.ingestion_status import IngestionCounters
from agent_hub.core.testing.builders import an_event
from agent_hub.core.testing.fakes import InMemoryEventStore
from agent_hub.core.testing.hook_inputs import a_hook_input, an_envelope
from agent_hub.core.testing.transcript_lines import (
    TRANSCRIPT_SESSION,
    a_text_block,
    a_user_line,
    an_assistant_line,
    transcript_text,
)
from agent_hub.storage.event_store import open_event_store

HOOKS = "/api/v1/events/hooks"
SPOOL_FILE = "hook-spool.jsonl"
# Synthetic, shaped like a key so the redaction would catch it; never a real secret.
SYNTHETIC_KEY = "sk-ant-api03-SYNTHETICsecretVALUE0123456789"


@pytest.fixture
def spool_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "state" / "agent-hub"
    folder.mkdir(parents=True, mode=0o700)
    return folder


def _spool(folder: Path, lines: Sequence[bytes]) -> Path:
    path = folder / SPOOL_FILE
    path.write_bytes(b"".join(line + b"\n" for line in lines))
    path.chmod(0o600)
    return path


def _line(envelope: HookEnvelope) -> bytes:
    return envelope.model_dump_json().encode()


def _tool_envelope(number: int) -> HookEnvelope:
    command = f"curl -H 'x-api-key: {SYNTHETIC_KEY}' https://example.invalid/{number}"
    hook = a_hook_input(
        "PreToolUse", tool_use_id=f"toolu_spool_{number}", tool_input={"command": command}
    )
    return an_envelope(hook)


def _kept(rows: Sequence[Event]) -> list[tuple[Any, ...]]:
    return sorted(
        (row.project, row.session, row.type, row.source, row.source_id, row.repo, row.agent)
        + (json.dumps(row.payload, sort_keys=True),)
        for row in rows
    )


def _left(folder: Path) -> list[str]:
    return sorted(name for name in os.listdir(folder) if not name.endswith(".lock"))


def test_stores_spooled_events_redacted_as_live_and_empties_spool_when_hub_web_starts(
    *,
    open_composed: Callable[..., Any],
    composed_settings: ApiSettings,
    spool_folder: Path,
    tmp_path: Path,
) -> None:
    envelopes = [_tool_envelope(number) for number in range(3)]
    _spool(spool_folder, [_line(envelope) for envelope in envelopes])

    spooled = open_composed(spool_folder=spool_folder)
    live = open_composed(replace(composed_settings, db_path=tmp_path / "live" / "agent-hub.db"))
    for envelope in envelopes:
        response = live.client.post(HOOKS, json=envelope.model_dump(mode="json"))
        assert response.status_code == 202, response.text

    rows = spooled.rows()
    assert sorted(row.source_id for row in rows) == [
        f"session-1:PreToolUse:toolu_spool_{number}" for number in range(3)
    ]
    assert SYNTHETIC_KEY not in json.dumps([row.payload for row in rows])
    assert _kept(rows) == _kept(live.rows())
    assert _left(spool_folder) == []


def test_stores_no_duplicate_when_same_spool_imported_twice(
    open_composed: Callable[..., Any], spool_folder: Path
) -> None:
    lines = [_line(_tool_envelope(number)) for number in range(2)]
    _spool(spool_folder, lines)
    first = open_composed(spool_folder=spool_folder)
    _spool(spool_folder, lines)  # a crash between the commit and the removal replays them

    open_composed(spool_folder=spool_folder)

    assert len(first.rows()) == 2
    assert _left(spool_folder) == []


def test_adds_transcript_events_when_spooled_stop_names_transcript(
    open_composed: Callable[..., Any], projects_root: Path, spool_folder: Path
) -> None:
    transcript = projects_root / "-work-demo-api" / f"{TRANSCRIPT_SESSION}.jsonl"
    transcript.write_text(
        transcript_text([a_user_line("one"), an_assistant_line([a_text_block()])]),
        encoding="utf-8",
    )
    stop = an_envelope(a_hook_input("Stop", transcript_path=str(transcript)))
    _spool(spool_folder, [_line(stop)])

    composed = open_composed(spool_folder=spool_folder)

    rows = composed.rows()
    assert [row.source for row in rows] == ["transcript", "transcript"]
    assert {(row.project, row.repo, row.session) for row in rows} == {
        ("demo", "demo-api", TRANSCRIPT_SESSION)
    }


def test_imports_valid_lines_and_drops_bad_ones_when_spool_has_bad_line(
    open_composed: Callable[..., Any], spool_folder: Path
) -> None:
    _spool(
        spool_folder,
        [_line(_tool_envelope(1)), b"{not json", b'{"dropped": 2}', _line(_tool_envelope(2))],
    )

    composed = open_composed(spool_folder=spool_folder)

    assert sorted(row.source_id for row in composed.rows()) == [
        "session-1:PreToolUse:toolu_spool_1",
        "session-1:PreToolUse:toolu_spool_2",
    ]
    assert _left(spool_folder) == []


def test_skips_conflicting_envelope_and_imports_the_rest_when_stored_event_differs(
    open_composed: Callable[..., Any], composed_settings: ApiSettings, spool_folder: Path
) -> None:
    stored = an_event(source_id="session-1:PreToolUse:toolu_spool_1", payload={"tool": "Read"})
    store = open_event_store(composed_settings.db_path)
    store.append([stored])
    store.close()
    _spool(spool_folder, [_line(_tool_envelope(1)), _line(_tool_envelope(2))])

    composed = open_composed(spool_folder=spool_folder)

    assert sorted(row.source_id for row in composed.rows()) == [
        "session-1:PreToolUse:toolu_spool_1",
        "session-1:PreToolUse:toolu_spool_2",
    ]
    assert stored in composed.rows()
    assert _left(spool_folder) == []


def test_starts_and_imports_nothing_when_spool_folder_is_link(
    open_composed: Callable[..., Any], spool_folder: Path, tmp_path: Path
) -> None:
    _spool(spool_folder, [_line(_tool_envelope(1))])
    link = tmp_path / "link"
    os.symlink(spool_folder, link)

    composed = open_composed(spool_folder=link)

    assert composed.client.get("/api/v1/collector/status").status_code == 200
    assert composed.rows() == []
    assert _left(spool_folder) == [SPOOL_FILE]


def test_imports_nothing_when_no_spool_folder_given(
    open_composed: Callable[..., Any], spool_folder: Path
) -> None:
    _spool(spool_folder, [_line(_tool_envelope(1))])

    composed = open_composed()

    assert composed.rows() == []
    assert _left(spool_folder) == [SPOOL_FILE]


class _BatchStore(InMemoryEventStore):
    """Records the size of each batch it is asked to append."""

    def __init__(self) -> None:
        super().__init__()
        self.batches: list[int] = []

    def append(self, events: Sequence[Event]) -> AppendResult:
        self.batches.append(len(events))
        return super().append(events)


@pytest.mark.anyio
async def test_appends_in_bounded_batches_and_logs_size_first_when_spool_imported(
    spool_folder: Path, projects_root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _spool(spool_folder, [_line(_tool_envelope(number)) for number in range(5)] + [b"{not json"])
    store = _BatchStore()
    ingest = IngestHook(
        store,
        ClaudeHookMapper(),
        TranscriptTail(projects_root),
        status=IngestionCounters(clock=lambda: datetime(2026, 10, 11, tzinfo=UTC)),
    )
    caplog.set_level(logging.INFO)

    await SpoolImport(HookSpool(spool_folder), ingest, batch_size=2).start()

    logged = [
        record.getMessage() for record in caplog.records if record.name == SpoolImport.__module__
    ]
    assert store.batches == [2, 2, 1]
    assert logged[0] == "hook spool import started: 5 envelopes, 1 bad lines"
    assert len(store.read_all()) == 5
    assert _left(spool_folder) == []
