"""The live transcript tail on real files under a temporary ``~/.claude/projects`` (D9, E6)."""

import os
from pathlib import Path

import pytest

from agent_hub.collector.claude_hooks import ClaudeHookMapper
from agent_hub.collector.transcript_tail import TranscriptTail
from agent_hub.core.ingestion.ingestion_ports import TranscriptRef
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

    first = tail.read_new(ref)
    with path.open("a") as file:
        file.write(transcript_text([a_user_line("two"), an_assistant_line([a_text_block()])]))
    second = tail.read_new(ref)
    third = tail.read_new(ref)

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

    before = tail.read_new(ref)
    with path.open("a") as file:
        file.write(whole[-10:])
    after = tail.read_new(ref)

    assert before.events == ()
    assert before.skipped_lines == 0
    assert len(after.events) == 1


def test_refuses_path_when_outside_projects_folder(projects: Path, tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere.jsonl"
    outside.write_text(transcript_text([a_user_line()]))
    tail = _tail(projects)

    result = tail.read_new(_ref(outside))

    assert result.refused
    assert result.events == ()


def test_refuses_path_when_dot_dot_leaves_projects_folder(projects: Path, tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere.jsonl"
    outside.write_text(transcript_text([a_user_line()]))
    tail = _tail(projects)
    sneaky = projects / "-work-demo-api" / ".." / ".." / ".." / ".." / "elsewhere.jsonl"

    assert tail.read_new(_ref(sneaky)).refused


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

    assert tail.read_new(_ref(link)).refused
    assert tail.read_new(_ref(out_link)).refused


def test_refuses_path_when_not_a_regular_file(projects: Path) -> None:
    fifo = projects / "-work-demo-api" / "pipe.jsonl"
    os.mkfifo(fifo)
    folder = projects / "-work-demo-api" / "dir.jsonl"
    folder.mkdir()
    tail = _tail(projects)

    assert tail.read_new(_ref(fifo)).refused
    assert tail.read_new(_ref(folder)).refused
    assert tail.read_new(_ref(projects / "missing.jsonl")).refused


def test_reads_in_bounded_pieces_when_file_larger_than_max_bytes_offset(projects: Path) -> None:
    path = projects / "-work-demo-api" / "big.jsonl"
    path.write_text(transcript_text([a_user_line(f"prompt {n}") for n in range(30)]))
    tail = _tail(projects, max_bytes=2_000)
    ref = _ref(path)

    turns: list[object] = []
    for _ in range(40):
        turns.extend(event.payload["turn"] for event in tail.read_new(ref).events)

    assert turns == list(range(1, 31))


def test_skips_and_counts_line_when_longer_than_line_limit(projects: Path) -> None:
    path = projects / "-work-demo-api" / "long.jsonl"
    path.write_text(
        transcript_text([a_user_line("x" * 5_000), a_user_line("short"), a_user_line("y" * 300)])
    )
    tail = _tail(projects, max_bytes=1_000, max_line_bytes=600)
    ref = _ref(path)

    results = [tail.read_new(ref) for _ in range(12)]

    assert sum(result.skipped_lines for result in results) == 1
    assert [event.payload["chars"] for result in results for event in result.events] == [5, 300]


def test_rereads_from_start_when_file_truncated_offset(projects: Path) -> None:
    path = projects / "-work-demo-api" / "t.jsonl"
    path.write_text(transcript_text([a_user_line("one"), a_user_line("two")]))
    tail = _tail(projects)
    ref = _ref(path)
    tail.read_new(ref)

    path.write_text(transcript_text([a_user_line("new")]))
    result = tail.read_new(ref)

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
    result = tail.read_new(mapping.transcript)

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
