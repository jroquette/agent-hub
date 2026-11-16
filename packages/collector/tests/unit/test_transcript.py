"""Transcript lines to canonical events: metadata only, usage once per message id (E5)."""

import json
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from agent_hub.collector.transcript import (
    TranscriptOrigin,
    parse_transcript,
)
from agent_hub.core.events.event import Event
from agent_hub.core.events.payload_keys import PAYLOAD_KEYS, kept_payload
from agent_hub.core.sessions.session_label import label_signals, session_label
from agent_hub.core.testing.session_scenarios import as_stored, shuffled
from agent_hub.core.testing.transcript_lines import (
    TRANSCRIPT_BRANCH,
    TRANSCRIPT_MODEL,
    TRANSCRIPT_SESSION,
    a_text_block,
    a_thinking_block,
    a_title_line,
    a_tool_result_line,
    a_tool_use_block,
    a_usage,
    a_user_line,
    an_assistant_line,
    transcript_text,
)

ORIGIN = TranscriptOrigin(project="demo", repo="demo-api", agent="main", session=TRANSCRIPT_SESSION)
SENTINEL = "SENTINEL-body-never-stored"


def _parse(lines: list[dict[str, Any]], **options: Any) -> list[Event]:
    return list(parse_transcript(transcript_text(lines), origin=ORIGIN, **options).events)


def test_maps_prompt_to_message_when_user_line_has_text() -> None:
    line = a_user_line(f"add {SENTINEL}")

    [event] = _parse([line])

    assert event.type == "message"
    assert event.source == "transcript"
    assert event.source_id == f"{TRANSCRIPT_SESSION}:{line['uuid']}"
    assert event.payload == {
        "role": "user",
        "chars": 4 + len(SENTINEL),
        "turn": 1,
        "git_branch": TRANSCRIPT_BRANCH,
    }
    assert (event.project, event.repo, event.agent) == ("demo", "demo-api", "main")
    assert event.timestamp.isoformat().startswith("2026-10-11T10:")
    assert SENTINEL not in event.model_dump_json()


def test_keeps_command_name_when_prompt_is_slash_command() -> None:
    [event] = _parse(
        [a_user_line("<command-name>/feature</command-name><command-args>x</command-args>")]
    )

    assert event.payload["slash_command"] == "/feature"


def test_counts_turns_in_file_order_when_several_prompts() -> None:
    events = _parse(
        [a_user_line("one"), an_assistant_line([a_text_block()]), a_user_line("two")],
        start_turn=4,
    )

    assert [event.payload["turn"] for event in events] == [5, 5, 6]


def test_returns_end_turn_when_batch_parsed() -> None:
    batch = parse_transcript(
        transcript_text([a_user_line(), a_user_line()]), origin=ORIGIN, start_turn=2
    )

    assert batch.end_turn == 4


def test_maps_blocks_with_index_when_assistant_line_has_several() -> None:
    line = an_assistant_line(
        [
            a_thinking_block(f"think {SENTINEL}"),
            a_text_block(f"text {SENTINEL}"),
            a_tool_use_block(
                "toolu_9", "Write", {"file_path": "/work/demo-api/a.py", "content": SENTINEL}
            ),
        ]
    )

    events = [
        event for event in _parse([a_user_line(), line])[1:] if "message_id" not in event.payload
    ]

    assert [event.type for event in events] == ["reasoning", "message", "tool.call"]
    assert [event.source_id for event in events] == [
        f"{TRANSCRIPT_SESSION}:{line['uuid']}:{index}" for index in range(3)
    ]
    assert events[0].payload == {
        "chars": len(f"think {SENTINEL}"),
        "turn": 1,
        "git_branch": TRANSCRIPT_BRANCH,
    }
    assert events[2].payload == {
        "tool": "Write",
        "tool_use_id": "toolu_9",
        "turn": 1,
        "path": "a.py",
        "lines_added": 1,
        "git_branch": TRANSCRIPT_BRANCH,
    }
    assert all(SENTINEL not in event.model_dump_json() for event in events)


def test_puts_usage_on_first_message_once_when_message_id_repeats_usage_once() -> None:
    usage = a_usage(1000, 200, cache_read=30, cache_write=40)
    first = an_assistant_line([a_text_block("a")], usage=usage, message_id="msg_7")
    second = an_assistant_line([a_text_block("b")], usage=usage, message_id="msg_7")

    events = _parse([first, second])

    assert events[0].payload == {
        "role": "assistant",
        "chars": 1,
        "turn": 0,
        "message_id": "msg_7",
        "model": TRANSCRIPT_MODEL,
        "input_tokens": 1000,
        "output_tokens": 200,
        "cache_read_tokens": 30,
        "cache_write_tokens": 40,
        "git_branch": TRANSCRIPT_BRANCH,
    }
    assert events[1].payload == {
        "role": "assistant",
        "chars": 1,
        "turn": 0,
        "git_branch": TRANSCRIPT_BRANCH,
    }


def test_adds_usage_message_when_message_id_starts_without_text_usage_once() -> None:
    line = an_assistant_line([a_tool_use_block()], message_id="msg_8")

    events = _parse([line])

    assert [event.type for event in events] == ["message", "tool.call"]
    assert events[0].source_id == f"{TRANSCRIPT_SESSION}:{line['uuid']}:usage"
    assert events[0].payload["chars"] == 0
    assert events[0].payload["message_id"] == "msg_8"


def test_skips_usage_when_message_id_seen_in_earlier_read_usage_once() -> None:
    first = parse_transcript(
        transcript_text([an_assistant_line([a_text_block()], message_id="msg_9")]),
        origin=ORIGIN,
    )
    later = parse_transcript(
        transcript_text([an_assistant_line([a_text_block()], message_id="msg_9")]),
        origin=ORIGIN,
        seen_messages=first.seen_messages,
    )

    [event] = later.events
    assert "input_tokens" not in event.payload


def test_maps_tool_result_status_and_error_line_when_user_line_has_results() -> None:
    error = "exit 1\nmake: *** [check] Error 1"
    ok = a_tool_result_line("toolu_1", content=[{"type": "text", "text": SENTINEL}])
    failed = a_tool_result_line("toolu_2", content=error, is_error=True)

    events = _parse([ok, failed])

    assert events[0].type == "tool.result"
    assert events[0].source_id == f"{TRANSCRIPT_SESSION}:{ok['uuid']}:0"
    assert events[0].payload == {
        "tool_use_id": "toolu_1",
        "status": "ok",
        "output_bytes": len(
            json.dumps([{"type": "text", "text": SENTINEL}], separators=(",", ":"))
        ),
        "turn": 0,
        "git_branch": TRANSCRIPT_BRANCH,
    }
    assert events[1].payload == {
        "tool_use_id": "toolu_2",
        "status": "error",
        "output_bytes": len(error),
        "error_line": "exit 1",
        "error_message": "exit 1 make: *** [check] Error 1",
        "turn": 0,
        "git_branch": TRANSCRIPT_BRANCH,
    }
    assert all(SENTINEL not in event.model_dump_json() for event in events)


def test_proposes_learning_when_tool_use_writes_brain_inbox_note() -> None:
    line = an_assistant_line(
        [
            a_tool_use_block(
                "toolu_5", "Write", {"file_path": "/w/hub/brain/_inbox/n.md", "content": "# T"}
            )
        ]
    )

    events = _parse([line])

    learning = events[-1]
    assert learning.type == "learning.proposed"
    assert learning.source_id == f"{TRANSCRIPT_SESSION}:{line['uuid']}:0:learning"
    assert learning.payload == {
        "proposal": "toolu_5",
        "text": "T",
        "target": "brain/_inbox/n.md",
        "author": "main",
        "git_branch": TRANSCRIPT_BRANCH,
    }


def test_keeps_git_branch_when_line_has_git_branch() -> None:
    token = "gh" + "p_" + "Z9y8X7w6" * 5
    lines = [
        a_user_line("prompt", gitBranch="jdoe/dem-9-" + "b" * 300),
        an_assistant_line(
            [a_text_block(), a_tool_use_block("toolu_s", "Skill", {"skill": "feature"})],
            gitBranch=f"leak-{token}",
        ),
        a_tool_result_line("toolu_s", gitBranch=""),
        a_user_line("no branch", gitBranch=...),
    ]

    events = _parse(lines)

    branches = [event.payload.get("git_branch") for event in events]
    first = branches[0]
    assert isinstance(first, str)
    assert first.startswith("jdoe/dem-9-")
    assert len(first) <= 200
    assert branches[1:3] == ["leak-[redacted: github token]"] * 2
    assert events[2].payload["skill"] == "feature"
    assert branches[3:] == [None, None]


def test_keeps_error_message_when_tool_result_is_error() -> None:
    token = "gh" + "p_" + "Z9y8X7w6" * 5
    content = [
        {"type": "text", "text": "Exit code 1\n\n  error: " + token},
        {"type": "text", "text": "x" * 400},
    ]

    [failed, ok] = _parse(
        [
            a_tool_result_line("toolu_e", content=content, is_error=True),
            a_tool_result_line("toolu_o", content="fine\nmore"),
        ]
    )

    message = failed.payload["error_message"]
    assert isinstance(message, str)
    assert message.startswith("Exit code 1 error: [redacted: github token] xxx")
    assert len(message) <= 300
    assert "error_message" not in ok.payload


def test_maps_title_once_at_previous_line_time_when_title_line_repeats() -> None:
    prompt = a_user_line()
    lines = [
        a_title_line("ignored: no earlier line"),
        prompt,
        a_title_line("Export  orders\nas CSV"),
        an_assistant_line([a_text_block()]),
        a_title_line("Export orders as CSV"),
        a_title_line("Orders export", origin="custom"),
    ]

    titles = [event for event in _parse(lines) if event.type == "session.title"]

    assert [event.payload for event in titles] == [
        {"text": "Export orders as CSV", "origin": "ai"},
        {"text": "Orders export", "origin": "custom"},
    ]
    assert titles[0].timestamp == _parse([prompt])[0].timestamp
    assert titles[0].source_id.startswith(f"{TRANSCRIPT_SESSION}:title:ai:")
    assert (titles[0].session, titles[0].repo, titles[0].agent) == (
        TRANSCRIPT_SESSION,
        "demo-api",
        "main",
    )


def test_redacts_and_clips_title_when_title_has_secret_or_is_long() -> None:
    secret = "gh" + "p_" + "A1b2C3d4" * 4
    lines = [a_user_line(), a_title_line(f"Rotate {secret} " + "x" * 200)]

    [title] = [event for event in _parse(lines) if event.type == "session.title"]

    assert secret not in title.model_dump_json()
    assert len(str(title.payload["text"])) <= 80


def test_maps_title_once_when_file_is_read_in_pieces() -> None:
    first = [a_user_line(), a_title_line()]
    second = [a_title_line(), a_title_line("Renamed", origin="custom")]
    whole = parse_transcript(transcript_text([*first, *second]), origin=ORIGIN)

    head = parse_transcript(transcript_text(first), origin=ORIGIN)
    tail = parse_transcript(
        transcript_text(second),
        origin=ORIGIN,
        start_turn=head.end_turn,
        seen_messages=head.seen_messages,
        seen_titles=head.seen_titles,
        last_timestamp=head.last_timestamp,
    )

    assert [*head.events, *tail.events] == list(whole.events)


def test_keeps_rename_back_and_file_order_when_titles_share_timestamp() -> None:
    lines = [
        a_user_line(),
        a_title_line("Alpha", origin="custom"),
        a_title_line("Beta", origin="custom"),
        a_title_line("Beta", origin="custom"),
        a_title_line("Alpha", origin="custom"),
    ]

    titles = [event for event in _parse(lines) if event.type == "session.title"]

    assert [event.payload["text"] for event in titles] == ["Alpha", "Beta", "Alpha"]
    assert len({event.timestamp for event in titles}) == 1
    for seed in range(5):
        stored = as_stored(shuffled(titles, seed))
        assert session_label(label_signals(stored)).title == "Alpha"


def test_ignores_line_when_type_is_not_mapped() -> None:
    lines = [
        {"type": "summary", "summary": SENTINEL},
        {"type": "system", "uuid": "u", "timestamp": "2026-10-11T10:00:00Z"},
        a_user_line(uuid=None),
        a_user_line(message=None),
    ]

    batch = parse_transcript(transcript_text(lines), origin=ORIGIN)

    assert batch.events == ()
    assert batch.problems == ()


def test_reports_line_number_when_line_is_not_json_object() -> None:
    text = (
        "not json\n"
        + transcript_text([a_user_line()])
        + "[1, 2]\n\n"
        + '{"type": "user", "uuid": "u", "timestamp": 3, "message": {"content": "x"}}\n'
    )

    batch = parse_transcript(text, origin=ORIGIN)

    assert [problem.line_number for problem in batch.problems] == [1, 3, 5]
    assert len(batch.events) == 1


def test_skips_line_when_longer_than_limit() -> None:
    text = transcript_text([a_user_line("x" * 200)])

    batch = parse_transcript(text, origin=ORIGIN, max_line_bytes=100)

    assert batch.events == ()
    assert [problem.reason for problem in batch.problems] == ["line longer than 100 bytes"]


def test_uses_origin_session_when_line_lacks_session_id() -> None:
    [event] = _parse([a_user_line(sessionId=None)])

    assert event.session == TRANSCRIPT_SESSION


_JSON = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=20),
    lambda inner: (
        st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=8), inner, max_size=4)
    ),
    max_leaves=12,
)
_LINE_KEYS = st.sampled_from(
    ["type", "timestamp", "sessionId", "uuid", "message", "isSidechain", "cwd", "gitBranch"]
)
_MESSAGE_KEYS = st.sampled_from(["id", "model", "role", "content", "usage"])
_BLOCK = st.fixed_dictionaries(
    {"type": st.sampled_from(["text", "thinking", "tool_use", "tool_result", "image"])},
    optional={
        "text": _JSON,
        "thinking": _JSON,
        "id": _JSON,
        "name": st.sampled_from(
            ["Bash", "Edit", "Write", "mcp__a__b", "Agent", "Skill", "SendMessage"]
        )
        | _JSON,
        "input": _JSON,
        "tool_use_id": _JSON,
        "is_error": _JSON,
        "content": _JSON,
    },
)
_MESSAGE = st.dictionaries(_MESSAGE_KEYS, _JSON | st.lists(_BLOCK, max_size=4), max_size=5)
_LINE = st.dictionaries(
    _LINE_KEYS,
    st.sampled_from(["user", "assistant", "2026-10-11T10:00:00Z", "u-1"]) | _JSON | _MESSAGE,
    max_size=8,
)


@settings(max_examples=300, deadline=None)
@given(lines=st.lists(_LINE | _JSON, max_size=6))
def test_never_raises_and_keeps_only_table_keys_when_lines_arbitrary_property(
    lines: list[Any],
) -> None:
    text = "".join(json.dumps(line) + "\n" for line in lines)

    batch = parse_transcript(text, origin=ORIGIN)

    for event in batch.events:
        assert set(event.payload) <= PAYLOAD_KEYS[event.type]


def test_maps_only_payload_kept_keys_when_every_record_kind_parsed() -> None:
    lines = [
        a_user_line("prompt"),
        an_assistant_line(
            [
                a_thinking_block("thinking"),
                a_text_block("answer"),
                a_tool_use_block(
                    "toolu_w", "Write", {"file_path": "/x/brain/_inbox/n.md", "content": "# T"}
                ),
                a_tool_use_block("toolu_b", "Bash", {"command": "make check"}),
            ],
            usage=a_usage(),
        ),
        a_tool_result_line("toolu_b", content="out", is_error=True),
        a_title_line(),
    ]

    events = _parse(lines)

    assert {event.type for event in events} >= {
        "message",
        "reasoning",
        "tool.call",
        "tool.result",
        "session.title",
    }
    for event in events:
        assert kept_payload(event.type, event.payload) == event.payload, event.type


def test_reports_problem_when_session_id_longer_than_cap() -> None:
    lines = [a_user_line(sessionId="s" * 201), a_user_line("kept")]

    batch = parse_transcript(transcript_text(lines), origin=ORIGIN)

    assert [problem.line_number for problem in batch.problems] == [1]
    assert batch.problems[0].reason == "sessionId: longer than 200 characters"
    assert [event.payload["chars"] for event in batch.events] == [4]
