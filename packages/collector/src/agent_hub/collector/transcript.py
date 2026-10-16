"""Claude Code transcript lines to canonical events, metadata only (D8, D11, E5).

A user prompt line becomes a ``message`` (size and turn, never its text); each ``tool_result``
block a ``tool.result`` (a failed one keeps its short ``error_message``, ADR 0023); an assistant
``text`` block a ``message``, ``thinking`` a ``reasoning`` and ``tool_use`` a ``tool.call``
(``tool_metadata``). ``turn`` counts the user prompt lines in file order. Token usage is kept
once per ``message.id`` (several lines repeat it): on that id's first ``message`` event, or on
a size-0 ``message`` added before its first block when the response starts with another block.
Every event of a line naming a ``gitBranch`` keeps it as ``git_branch`` (redacted,
``BRANCH_LIMIT`` characters). ``source_id``: ``<sessionId>:<uuid>[:<block index>]``.

A title line (``ai-title``, or ``custom-title`` from ``/rename``) becomes a ``session.title``
(ADR 0035): the title redacted and cut at ``NAME_LIMIT`` characters, at the timestamp of the last
user or assistant line before it (a title before any such line is skipped). Claude Code repeats
the line, so a title is kept only when it differs from the last one kept of its origin (a rename
back to an earlier title is kept again): ``source_id``
``<sessionId>:title:<origin>:<n, 6 digits>:<hash of the kept text>``, ``n`` counting the titles
of that origin kept so far, so titles that share a timestamp still sort in file order.

A line that is not a JSON object, is too long, has no valid timestamp or names a session id
longer than ``MAX_ID_CHARS`` is a problem reported with its line number; a line of another type,
or without the keys it needs, is ignored.
"""

import hashlib
import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePosixPath
from typing import Final

from pydantic import BaseModel, ConfigDict

from agent_hub.collector import transcript_fields as fields
from agent_hub.collector.hook_fields import mapping, text, whole_number
from agent_hub.collector.jsonl import LineError
from agent_hub.collector.tool_metadata import (
    BRANCH_LIMIT,
    NAME_LIMIT,
    error_message,
    first_line,
    learning_proposal,
    output_bytes,
    prompt_command,
    repo_root_of,
    short_text,
    tool_call_payload,
)
from agent_hub.core.events.event import (
    MAX_ID_CHARS,
    Event,
    EventSource,
    EventType,
    longer_than_cap,
)
from agent_hub.core.json_form import JsonValue

MAX_LINE_BYTES: Final = 1_048_576

type Payload = dict[str, JsonValue]
type Record = Mapping[str, JsonValue]


@dataclass(frozen=True, kw_only=True, slots=True)
class TranscriptOrigin:
    """Who the transcript's events belong to; ``session`` is used when a line names none."""

    project: str
    repo: str | None
    agent: str | None
    session: str


class TranscriptBatch(BaseModel):
    """What one parse produced, and the state the next parse of the same file continues from."""

    model_config = ConfigDict(frozen=True)

    events: tuple[Event, ...]
    problems: tuple[LineError, ...]
    end_turn: int
    seen_messages: frozenset[str]
    seen_titles: frozenset[str] = frozenset()
    last_timestamp: datetime | None = None


class _BadLineError(Exception):
    """A line that cannot be read; the message is the reason."""


@dataclass(kw_only=True, slots=True)
class _State:
    turn: int
    seen_messages: set[str] = field(default_factory=set)
    seen_titles: set[str] = field(default_factory=set)
    last_timestamp: datetime | None = None


@dataclass(frozen=True, kw_only=True, slots=True)
class _Line:
    origin: TranscriptOrigin
    session: str
    uuid: str
    timestamp: datetime
    repo_root: PurePosixPath | None
    git_branch: str | None = None

    def source_id(self, index: int | str | None = None) -> str:
        suffix = "" if index is None else f":{index}"
        return f"{self.session}:{self.uuid}{suffix}"

    def event(self, kind: EventType, source_id: str, payload: Payload) -> Event:
        return Event(
            project=self.origin.project,
            session=self.session,
            type=kind,
            timestamp=self.timestamp,
            source=EventSource.TRANSCRIPT,
            source_id=source_id,
            payload=payload
            if self.git_branch is None
            else payload | {"git_branch": self.git_branch},
            repo=self.origin.repo,
            agent=self.origin.agent,
        )


def parse_transcript(
    content: str,
    *,
    origin: TranscriptOrigin,
    start_turn: int = 0,
    seen_messages: frozenset[str] = frozenset(),
    seen_titles: frozenset[str] = frozenset(),
    last_timestamp: datetime | None = None,
    max_line_bytes: int = MAX_LINE_BYTES,
) -> TranscriptBatch:
    """The events of every complete line of ``content``; bad lines become problems, never raise.

    ``start_turn``, ``seen_messages``, ``seen_titles`` and ``last_timestamp`` carry a previous
    parse of the same file forward, so a file read in pieces yields the same events as one read
    whole.
    """
    state = _State(
        turn=start_turn,
        seen_messages=set(seen_messages),
        seen_titles=set(seen_titles),
        last_timestamp=last_timestamp,
    )
    events: list[Event] = []
    problems: list[LineError] = []
    for number, line in enumerate(content.split("\n"), start=1):
        if not line.strip():
            continue
        try:
            events.extend(_line_events(_record(line, max_line_bytes), origin, state))
        except _BadLineError as error:
            problems.append(LineError(line_number=number, reason=str(error)))
    return TranscriptBatch(
        events=tuple(events),
        problems=tuple(problems),
        end_turn=state.turn,
        seen_messages=frozenset(state.seen_messages),
        seen_titles=frozenset(state.seen_titles),
        last_timestamp=state.last_timestamp,
    )


def _record(line: str, max_line_bytes: int) -> Record:
    if len(line.encode("utf-8", errors="replace")) > max_line_bytes:
        msg = f"line longer than {max_line_bytes} bytes"
        raise _BadLineError(msg)
    try:
        value = json.loads(line)
    except ValueError as error:
        reason = error.msg if isinstance(error, json.JSONDecodeError) else str(error)
        raise _BadLineError(f"invalid JSON: {reason}") from error
    except RecursionError as error:
        msg = "invalid JSON: nested too deeply"
        raise _BadLineError(msg) from error
    if not isinstance(value, dict):
        msg = "expected a JSON object"
        raise _BadLineError(msg)
    return value


def _line_events(record: Record, origin: TranscriptOrigin, state: _State) -> Iterator[Event]:
    kind = text(record, fields.TYPE)
    for title_type, title_key, title_origin in fields.TITLE_LINES:
        if kind == title_type:
            yield from _title_events(
                record, origin, state, key=title_key, title_origin=title_origin
            )
            return
    uuid = text(record, fields.UUID)
    message = mapping(record, fields.MESSAGE)
    if kind not in {fields.USER, fields.ASSISTANT} or uuid is None or not message:
        return
    session = text(record, fields.SESSION_ID) or origin.session
    if len(session) > MAX_ID_CHARS:
        raise _BadLineError(longer_than_cap(fields.SESSION_ID))
    line = _Line(
        origin=origin,
        session=session,
        uuid=uuid,
        timestamp=_timestamp(record),
        repo_root=repo_root_of(text(record, fields.CWD), origin.repo),
        git_branch=_git_branch(record),
    )
    state.last_timestamp = line.timestamp
    if kind == fields.USER:
        yield from _user_events(line, message.get(fields.CONTENT), state)
    else:
        yield from _assistant_events(line, message, state)


def _title_events(
    record: Record, origin: TranscriptOrigin, state: _State, *, key: str, title_origin: str
) -> Iterator[Event]:
    raw = text(record, key)
    session = text(record, fields.SESSION_ID) or origin.session
    if raw is None or state.last_timestamp is None or len(session) > MAX_ID_CHARS:
        return
    title = short_text(" ".join(raw.split()), NAME_LIMIT)
    digest = hashlib.sha256(title.encode()).hexdigest()[:16]
    stem = f"{session}:title:{title_origin}:"
    kept = sorted(seen for seen in state.seen_titles if seen.startswith(stem))
    if not title or (kept and kept[-1].endswith(f":{digest}")):
        return
    source_id = f"{stem}{len(kept):06d}:{digest}"
    state.seen_titles.add(source_id)
    yield Event(
        project=origin.project,
        session=session,
        type=EventType.SESSION_TITLE,
        timestamp=state.last_timestamp,
        source=EventSource.TRANSCRIPT,
        source_id=source_id,
        payload={"text": title, "origin": title_origin},
        repo=origin.repo,
        agent=origin.agent,
    )


def _git_branch(record: Record) -> str | None:
    branch = text(record, fields.GIT_BRANCH)
    return None if branch is None else short_text(branch, BRANCH_LIMIT)


def _timestamp(record: Record) -> datetime:
    value = record.get(fields.TIMESTAMP)
    try:
        moment = datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        moment = None
    if moment is None or moment.tzinfo is None:
        msg = "invalid timestamp: expected an ISO 8601 string with an offset"
        raise _BadLineError(msg)
    return moment


def _user_events(line: _Line, content: JsonValue, state: _State) -> Iterator[Event]:
    blocks = _blocks(content)
    results = [
        (index, block)
        for index, block in enumerate(blocks)
        if isinstance(block, dict) and _is(block, fields.TOOL_RESULT)
    ]
    if results:
        for index, block in results:
            yield line.event(EventType.TOOL_RESULT, line.source_id(index), _result(block, state))
        return
    if isinstance(content, str):
        prompt = content
    else:
        prompt = "".join(
            _text_of(block, fields.TEXT) for block in blocks if _is(block, fields.TEXT)
        )
        if not prompt:
            return
    state.turn += 1
    payload: Payload = {"role": "user", "chars": len(prompt), "turn": state.turn}
    command = prompt_command(prompt)
    if command is not None:
        payload["slash_command"] = command
    yield line.event(EventType.MESSAGE, line.source_id(), payload)


def _result(block: Mapping[str, JsonValue], state: _State) -> Payload:
    payload: Payload = {}
    tool_use_id = text(block, fields.TOOL_RESULT_USE_ID)
    if tool_use_id is not None:
        payload["tool_use_id"] = tool_use_id
    is_error = block.get(fields.TOOL_RESULT_IS_ERROR) is True
    payload["status"] = "error" if is_error else "ok"
    content = block.get(fields.TOOL_RESULT_CONTENT)
    size = output_bytes(content)
    if size is not None:
        payload["output_bytes"] = size
    if is_error:
        error = _result_text(content)
        payload["error_line"] = first_line(error)
        message = error_message(error)
        if message is not None:
            payload["error_message"] = message
    payload["turn"] = state.turn
    return payload


def _result_text(content: JsonValue) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(_text_of(block, fields.TEXT) for block in _blocks(content))


def _assistant_events(line: _Line, message: Record, state: _State) -> Iterator[Event]:
    content = message.get(fields.CONTENT)
    blocks: Sequence[JsonValue] = (
        [{fields.BLOCK_TYPE: fields.TEXT, fields.TEXT: content}]
        if isinstance(content, str)
        else _blocks(content)
    )
    usage = _new_usage(message, state)
    if usage is not None and not (blocks and _is(blocks[0], fields.TEXT)):
        payload: Payload = {"role": "assistant", "chars": 0, "turn": state.turn}
        yield line.event(EventType.MESSAGE, line.source_id("usage"), payload | usage)
        usage = None
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        for event in _block_events(line, block, index=index, turn=state.turn):
            if usage is not None and event.type == EventType.MESSAGE:
                event = event.model_copy(update={"payload": event.payload | usage})
                usage = None
            yield event


def _block_events(
    line: _Line, block: Mapping[str, JsonValue], *, index: int, turn: int
) -> Iterator[Event]:
    if _is(block, fields.TEXT):
        size = len(_text_of(block, fields.TEXT))
        payload: Payload = {"role": "assistant", "chars": size, "turn": turn}
        yield line.event(EventType.MESSAGE, line.source_id(index), payload)
    elif _is(block, fields.THINKING):
        payload = {"chars": len(_text_of(block, fields.THINKING)), "turn": turn}
        yield line.event(EventType.REASONING, line.source_id(index), payload)
    elif _is(block, fields.TOOL_USE):
        yield from _tool_use_events(line, block, index=index, turn=turn)


def _tool_use_events(
    line: _Line, block: Mapping[str, JsonValue], *, index: int, turn: int
) -> Iterator[Event]:
    name = text(block, fields.TOOL_USE_NAME) or ""
    tool_use_id = text(block, fields.TOOL_USE_BLOCK_ID)
    tool_input = mapping(block, fields.TOOL_USE_INPUT)
    payload: Payload = {}
    if name:
        payload["tool"] = short_text(name, NAME_LIMIT)
    if tool_use_id is not None:
        payload["tool_use_id"] = tool_use_id
    payload["turn"] = turn
    payload |= tool_call_payload(name, tool_input, repo_root=line.repo_root)
    yield line.event(EventType.TOOL_CALL, line.source_id(index), payload)
    if tool_use_id is None:
        return
    proposal = learning_proposal(name, tool_input, tool_use_id=tool_use_id)
    if proposal is not None:
        proposal["author"] = line.origin.agent
        source_id = f"{line.source_id(index)}:learning"
        yield line.event(EventType.LEARNING_PROPOSED, source_id, proposal)


def _new_usage(message: Record, state: _State) -> Payload | None:
    message_id = text(message, fields.MESSAGE_ID)
    if message_id is None or message_id in state.seen_messages:
        return None
    state.seen_messages.add(message_id)
    usage = mapping(message, fields.USAGE)
    payload: Payload = {"message_id": message_id}
    model = text(message, fields.MODEL)
    if model is not None:
        payload["model"] = short_text(model, NAME_LIMIT)
    for name, key in fields.USAGE_KEYS:
        tokens = whole_number(usage, name)
        if tokens is not None:
            payload[key] = tokens
    return payload


def _blocks(content: JsonValue) -> list[JsonValue]:
    return content if isinstance(content, list) else []


def _is(block: object, kind: str) -> bool:
    return isinstance(block, dict) and block.get(fields.BLOCK_TYPE) == kind


def _text_of(block: object, key: str) -> str:
    value = block.get(key) if isinstance(block, dict) else None
    return value if isinstance(value, str) else ""
