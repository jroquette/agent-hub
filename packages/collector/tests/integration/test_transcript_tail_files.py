"""The live transcript tail on real files under a temporary ``~/.claude/projects`` (D9, E6)."""

import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_hub.collector.claude_hooks import ClaudeHookMapper
from agent_hub.collector.transcript_tail import MAX_TO_END_BYTES, TranscriptTail
from agent_hub.core.events.event import Event
from agent_hub.core.events.event_store import AppendResult
from agent_hub.core.ingestion.ingest_hook import IngestHook
from agent_hub.core.ingestion.ingestion_ports import TailResult, TranscriptRef
from agent_hub.core.ingestion.ingestion_status import IngestionCounters
from agent_hub.core.testing.fakes import InMemoryEventStore
from agent_hub.core.testing.hook_inputs import a_hook_input, an_envelope
from agent_hub.core.testing.transcript_lines import (
    TRANSCRIPT_SESSION,
    a_text_block,
    a_user_line,
    an_assistant_line,
    transcript_text,
)


@pytest.fixture
def projects(tmp_path: Path) -> Path:
    root = tmp_path / "home" / ".claude" / "projects"
    (root / "-work-demo-api").mkdir(parents=True)
    return root


def _tail(projects: Path, **options: int) -> TranscriptTail:
    return TranscriptTail(projects, **options)


def _read(tail: TranscriptTail, ref: TranscriptRef) -> TailResult:
    """One read, committed as ``IngestHook`` commits it once the events are stored."""
    result = tail.read_new(ref)
    if result.position is not None:
        tail.commit(result.position)
    return result


def _ref(path: Path, kind: str = "main") -> TranscriptRef:
    return TranscriptRef.model_validate(
        {
            "project": "demo",
            "repo": "demo-api",
            "agent": "main",
            "session": TRANSCRIPT_SESSION,
            "path": str(path),
            "kind": kind,
        }
    )


def test_reads_only_new_lines_when_offset_kept(projects: Path) -> None:
    path = projects / "-work-demo-api" / f"{TRANSCRIPT_SESSION}.jsonl"
    path.write_text(transcript_text([a_user_line("one")]))
    tail = _tail(projects)
    ref = _ref(path)

    first = _read(tail, ref)
    with path.open("a") as file:
        file.write(transcript_text([a_user_line("two"), an_assistant_line([a_text_block()])]))
    second = _read(tail, ref)
    third = _read(tail, ref)

    assert [event.payload["turn"] for event in first.events] == [1]
    assert [event.payload["turn"] for event in second.events] == [2, 2]
    assert third.events == ()
    assert not first.refused
    assert {event.project for event in second.events} == {"demo"}


def test_waits_for_newline_when_last_line_is_partial_line(projects: Path) -> None:
    path = projects / "-work-demo-api" / "s.jsonl"
    whole = transcript_text([a_user_line("one")])
    path.write_text(whole[:-10])
    tail = _tail(projects)
    ref = _ref(path)

    before = _read(tail, ref)
    with path.open("a") as file:
        file.write(whole[-10:])
    after = _read(tail, ref)

    assert before.events == ()
    assert before.skipped_lines == 0
    assert len(after.events) == 1


def test_refuses_path_when_outside_projects_folder(projects: Path, tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere.jsonl"
    outside.write_text(transcript_text([a_user_line()]))
    tail = _tail(projects)

    result = _read(tail, _ref(outside))

    assert result.refused
    assert result.events == ()


def test_refuses_path_when_dot_dot_leaves_projects_folder(projects: Path, tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere.jsonl"
    outside.write_text(transcript_text([a_user_line()]))
    tail = _tail(projects)
    sneaky = projects / "-work-demo-api" / ".." / ".." / ".." / ".." / "elsewhere.jsonl"

    assert _read(tail, _ref(sneaky)).refused


def test_refuses_path_when_it_is_a_symlink(projects: Path, tmp_path: Path) -> None:
    target = projects / "-work-demo-api" / "real.jsonl"
    target.write_text(transcript_text([a_user_line()]))
    link = projects / "-work-demo-api" / "link.jsonl"
    link.symlink_to(target)
    outside = tmp_path / "outside.jsonl"
    outside.write_text(transcript_text([a_user_line()]))
    out_link = projects / "-work-demo-api" / "out.jsonl"
    out_link.symlink_to(outside)
    tail = _tail(projects)

    assert _read(tail, _ref(link)).refused
    assert _read(tail, _ref(out_link)).refused


def test_refuses_path_when_not_a_regular_file(projects: Path) -> None:
    fifo = projects / "-work-demo-api" / "pipe.jsonl"
    os.mkfifo(fifo)
    folder = projects / "-work-demo-api" / "dir.jsonl"
    folder.mkdir()
    tail = _tail(projects)

    assert _read(tail, _ref(fifo)).refused
    assert _read(tail, _ref(folder)).refused
    assert _read(tail, _ref(projects / "missing.jsonl")).refused


def test_reads_in_bounded_pieces_when_file_larger_than_max_bytes_offset(projects: Path) -> None:
    path = projects / "-work-demo-api" / "big.jsonl"
    path.write_text(transcript_text([a_user_line(f"prompt {n}") for n in range(30)]))
    tail = _tail(projects, max_bytes=2_000)
    ref = _ref(path)

    turns: list[object] = []
    for _ in range(40):
        turns.extend(event.payload["turn"] for event in _read(tail, ref).events)

    assert turns == list(range(1, 31))


def test_reads_every_complete_line_in_one_result_when_read_to_end_of_file_larger_than_max_bytes(
    projects: Path,
) -> None:
    path = projects / "-work-demo-api" / "big.jsonl"
    whole = transcript_text([a_user_line(f"prompt {n}") for n in range(31)])
    path.write_text(whole[:-10])
    tail = _tail(projects, max_bytes=2_000)
    ref = _ref(path)

    result = tail.read_to_end(ref)
    assert result.position is not None
    tail.commit(result.position)
    with path.open("a") as file:
        file.write(whole[-10:])
    after = tail.read_new(ref)

    assert [event.payload["turn"] for event in result.events] == list(range(1, 31))
    assert [event.payload["turn"] for event in after.events] == [31]


def test_stores_each_transcript_event_once_when_batch_has_two_stops_naming_large_transcript(
    projects: Path,
) -> None:
    path = projects / "-work-demo-api" / f"{TRANSCRIPT_SESSION}.jsonl"
    path.write_text(transcript_text([a_user_line(f"prompt {n}") for n in range(40)]))
    store = InMemoryEventStore()
    ingest = IngestHook(
        store,
        ClaudeHookMapper(),
        TranscriptTail(projects, max_bytes=path.stat().st_size // 3),
        status=IngestionCounters(clock=lambda: datetime(2026, 10, 11, tzinfo=UTC)),
    )
    stop = an_envelope(a_hook_input("Stop", transcript_path=str(path)))

    result = ingest.execute_all([stop, stop])

    assert result == AppendResult(appended=40, duplicates=0)
    turns = [event.payload["turn"] for event in store.read_all() if event.source == "transcript"]
    assert sorted(turns) == list(range(1, 41))


def _same_size_lines(path: Path, count: int) -> int:
    """``count`` user lines written to ``path``; the bytes of each (they all have that size)."""
    lines = [transcript_text([a_user_line(f"prompt {n:02d}")]) for n in range(count)]
    sizes = {len(line.encode()) for line in lines}
    assert len(sizes) == 1
    path.write_text("".join(lines))
    return sizes.pop()


def test_stops_at_budget_and_next_read_continues_there_when_read_to_end_passes_byte_budget(
    projects: Path,
) -> None:
    path = projects / "-work-demo-api" / "big.jsonl"
    line = _same_size_lines(path, 12)
    # Each read takes two lines and half of the third, so five lines' bytes are two reads that
    # move the offset four lines: the budget counts the bytes read, not the lines consumed.
    tail = _tail(projects, max_bytes=2 * line + line // 2, max_to_end_bytes=5 * line)
    ref = _ref(path)

    reads: list[list[object]] = []
    for _ in range(3):
        result = tail.read_to_end(ref)
        assert result.position is not None
        tail.commit(result.position)
        reads.append([event.payload["turn"] for event in result.events])
    last = tail.read_new(ref)

    assert reads == [[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12]]
    assert last.events == ()


def test_stores_next_piece_when_later_batch_names_transcript_over_to_end_budget(
    projects: Path,
) -> None:
    path = projects / "-work-demo-api" / f"{TRANSCRIPT_SESSION}.jsonl"
    line = _same_size_lines(path, 6)
    store = InMemoryEventStore()
    ingest = IngestHook(
        store,
        ClaudeHookMapper(),
        TranscriptTail(projects, max_bytes=line, max_to_end_bytes=4 * line),
        status=IngestionCounters(clock=lambda: datetime(2026, 10, 11, tzinfo=UTC)),
    )
    stop = an_envelope(a_hook_input("Stop", transcript_path=str(path)))

    first = ingest.execute_all([stop])
    first_turns = _transcript_turns(store.read_all())
    second = ingest.execute_all([stop])

    assert first == AppendResult(appended=4, duplicates=0)
    assert first_turns == [1, 2, 3, 4]
    assert second == AppendResult(appended=2, duplicates=0)
    assert _transcript_turns(store.read_all()) == [1, 2, 3, 4, 5, 6]


def test_reads_at_most_256_mib_when_read_to_end_given_no_budget() -> None:
    assert MAX_TO_END_BYTES == 256 * 1_048_576


def _transcript_turns(events: Sequence[Event]) -> list[object]:
    return sorted(event.payload["turn"] for event in events if event.source == "transcript")


def test_skips_and_counts_line_when_longer_than_line_limit(projects: Path) -> None:
    path = projects / "-work-demo-api" / "long.jsonl"
    path.write_text(
        transcript_text([a_user_line("x" * 5_000), a_user_line("short"), a_user_line("y" * 300)])
    )
    tail = _tail(projects, max_bytes=1_000, max_line_bytes=600)
    ref = _ref(path)

    results = [_read(tail, ref) for _ in range(12)]

    assert sum(result.skipped_lines for result in results) == 1
    assert [event.payload["chars"] for result in results for event in result.events] == [5, 300]


def test_rereads_from_start_when_file_truncated_offset(projects: Path) -> None:
    path = projects / "-work-demo-api" / "t.jsonl"
    path.write_text(transcript_text([a_user_line("one"), a_user_line("two")]))
    tail = _tail(projects)
    ref = _ref(path)
    _read(tail, ref)

    path.write_text(transcript_text([a_user_line("new")]))
    result = _read(tail, ref)

    assert [event.payload["chars"] for event in result.events] == [3]


def test_attributes_events_when_mapper_remembers_origin_of_stop_hook(projects: Path) -> None:
    path = projects / "-work-demo-api" / f"{TRANSCRIPT_SESSION}.jsonl"
    path.write_text(transcript_text([a_user_line()]))
    mapper = ClaudeHookMapper()
    tail = TranscriptTail(projects)

    mapping = mapper.map(
        an_envelope(a_hook_input("Stop", transcript_path=str(path)), project="other")
    )
    assert mapping.transcript is not None
    result = _read(tail, mapping.transcript)

    [event] = result.events
    assert (event.project, event.repo, event.agent) == ("other", "demo-api", "main")


def test_attributes_subagent_when_subagent_stop_names_its_transcript(projects: Path) -> None:
    path = projects / "-work-demo-api" / "agent-7.jsonl"
    path.write_text(transcript_text([a_user_line()]))
    hook = a_hook_input("SubagentStop", agent_transcript_path=str(path))

    mapping = ClaudeHookMapper().map(an_envelope(hook))
    assert mapping.transcript is not None
    result = TranscriptTail(projects).read_new(mapping.transcript)

    [event] = result.events
    assert event.agent == "Explore"


def test_attributes_events_from_ref_when_ref_names_project_repo_and_agent(projects: Path) -> None:
    path = projects / "-work-demo-api" / "u.jsonl"
    path.write_text(transcript_text([a_user_line()]))
    ref = TranscriptRef(
        project="other", repo=None, agent="Plan", session="s", path=str(path), kind="subagent"
    )

    result = TranscriptTail(projects).read_new(ref)

    [event] = result.events
    assert (event.project, event.repo, event.agent) == ("other", None, "Plan")


def test_returns_same_events_when_previous_read_not_committed(projects: Path) -> None:
    path = projects / "-work-demo-api" / f"{TRANSCRIPT_SESSION}.jsonl"
    path.write_text(transcript_text([a_user_line("one"), an_assistant_line([a_text_block()])]))
    tail = _tail(projects)
    ref = _ref(path)

    uncommitted = tail.read_new(ref)
    again = tail.read_new(ref)
    assert again.position is not None
    tail.commit(again.position)
    after_commit = tail.read_new(ref)

    assert len(uncommitted.events) == 2
    assert again.events == uncommitted.events
    assert after_commit.events == ()


def test_ignores_commit_when_position_is_stale(projects: Path) -> None:
    path = projects / "-work-demo-api" / f"{TRANSCRIPT_SESSION}.jsonl"
    path.write_text(transcript_text([a_user_line("one")]))
    tail = _tail(projects)
    ref = _ref(path)
    stale = tail.read_new(ref).position
    path.write_text(transcript_text([a_user_line("a much longer prompt")]))
    fresh = tail.read_new(ref)
    assert stale is not None

    tail.commit(stale)

    assert tail.read_new(ref).events == fresh.events


def test_rereads_lines_when_store_fails_once_during_hook_ingestion(projects: Path) -> None:
    path = projects / "-work-demo-api" / f"{TRANSCRIPT_SESSION}.jsonl"
    path.write_text(transcript_text([a_user_line("one"), an_assistant_line([a_text_block()])]))
    store = _FailingOnceStore()
    ingest = IngestHook(
        store,
        ClaudeHookMapper(),
        TranscriptTail(projects),
        status=IngestionCounters(clock=lambda: datetime(2026, 10, 11, tzinfo=UTC)),
    )
    stop = an_envelope(a_hook_input("Stop", transcript_path=str(path)))

    with pytest.raises(_StoreBusyError):
        ingest.execute(stop)
    retried = ingest.execute(stop)

    assert retried.appended == 2
    assert {event.source for event in store.read_all()} == {"transcript"}


class _FailingOnceStore(InMemoryEventStore):
    """Fails the first append that carries transcript events, as a busy database would."""

    def __init__(self) -> None:
        super().__init__()
        self.failed = False

    def append(self, events: Sequence[Event]) -> AppendResult:
        if not self.failed and any(event.source == "transcript" for event in events):
            self.failed = True
            raise _StoreBusyError
        return super().append(events)


class _StoreBusyError(Exception):
    pass
