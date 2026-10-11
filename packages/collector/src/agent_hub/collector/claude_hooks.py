"""Claude Code hook envelopes to canonical events (D8, E2-E4): the ``HookMapper`` adapter.

One row of the plan's table per hook; trigger-only hooks (Stop, SubagentStart, SubagentStop,
PreCompact, a Notification that is not a permission prompt) yield no event, and Stop,
SubagentStop and SessionEnd name the transcript to read next. An envelope carrying the guard's
or the Stop gate's decision yields the decision's event only (the sensor sends the hook itself
on its own). Every event is attributed from the envelope: project, repo, the ``hub run`` run,
step and attempt, and the subagent when the hook came from one.

``source_id`` (D8): ``<session>:<hook>:<tool_use_id>`` when the input has a tool use id, else
``<session>:<hook>:<sent_at>:<h16>``, ``h16`` being the first 16 hex digits of the SHA-256 of the
hook input's canonical JSON (sorted keys, compact).
"""

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Final, Literal

from agent_hub.collector import hook_fields as fields
from agent_hub.collector.tool_metadata import (
    COMMAND_LIMIT,
    FILE_PATH,
    NAME_LIMIT,
    first_line,
    learning_proposal,
    output_bytes,
    prompt_command,
    repo_root_of,
    short_text,
    shown_path,
    tool_call_payload,
)
from agent_hub.collector.transcript import TranscriptOrigin
from agent_hub.collector.transcript_tail import SessionOrigins
from agent_hub.core.events.event import Event, EventSource, EventType
from agent_hub.core.ingestion.hook_envelope import HookDecision, HookEnvelope
from agent_hub.core.ingestion.ingestion_ports import HookMapping, TranscriptRef
from agent_hub.core.json_form import JsonValue

RUN_WORKFLOW: Final = "issue-to-pr"
MAIN_AGENT: Final = "main"
INTERRUPTED: Final = "interrupted"

type Payload = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class _Hook:
    """One envelope being mapped: its hook input, session and attribution."""

    envelope: HookEnvelope
    session: str

    @property
    def input(self) -> Mapping[str, JsonValue]:
        return self.envelope.hook

    @property
    def name(self) -> str:
        return fields.text(self.input, fields.HOOK_EVENT_NAME) or "unknown"

    @property
    def tool_use_id(self) -> str | None:
        return fields.text(self.input, fields.TOOL_USE_ID)

    @property
    def repo_root(self) -> PurePosixPath | None:
        return repo_root_of(fields.text(self.input, fields.CWD), self.envelope.repo)

    def hashed_id(self, label: str) -> str:
        canonical = json.dumps(self.input, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8", errors="replace")).hexdigest()[:16]
        return f"{self.session}:{label}:{self.envelope.sent_at.isoformat()}:{digest}"

    def tool_id(self, label: str) -> str:
        tool_use_id = self.tool_use_id
        return (
            self.hashed_id(label)
            if tool_use_id is None
            else f"{self.session}:{label}:{tool_use_id}"
        )

    def tool_keys(self) -> Payload:
        payload: Payload = {}
        tool = fields.text(self.input, fields.TOOL_NAME)
        if tool is not None:
            payload["tool"] = short_text(tool, NAME_LIMIT)
        if self.tool_use_id is not None:
            payload["tool_use_id"] = self.tool_use_id
        return payload

    def event(self, kind: EventType, source_id: str, payload: Payload) -> Event:
        envelope = self.envelope
        agent_type = fields.text(self.input, fields.AGENT_TYPE)
        agent_id = fields.text(self.input, fields.AGENT_ID)
        extra: Payload = {}
        if envelope.run is not None:
            extra["run"] = envelope.run
        if envelope.attempt is not None:
            extra["attempt"] = envelope.attempt
        if agent_id is not None:
            extra["agent_id"] = agent_id
        return Event(
            project=envelope.project,
            session=self.session,
            type=kind,
            timestamp=envelope.sent_at,
            source=EventSource.CLAUDE_CODE,
            source_id=source_id,
            payload=payload | extra,
            repo=envelope.repo,
            agent=short_text(agent_type, NAME_LIMIT) if agent_type else MAIN_AGENT,
            workflow=RUN_WORKFLOW if envelope.run is not None else None,
            step=envelope.step,
        )


class ClaudeHookMapper:
    """Maps a sensor envelope to canonical events; never raises on missing or odd hook keys.

    With ``origins``, each transcript it names is remembered with its project, repo and agent,
    so the transcript tail can attribute the transcript's events the same way.
    """

    def __init__(self, *, origins: SessionOrigins | None = None) -> None:
        self._origins = origins

    def map(self, envelope: HookEnvelope) -> HookMapping:
        """The events of ``envelope`` and, for Stop/SubagentStop/SessionEnd, its transcript."""
        session = fields.text(envelope.hook, fields.SESSION_ID)
        if session is None:
            return HookMapping(events=())
        hook = _Hook(envelope=envelope, session=session)
        if envelope.decision is not None:
            return HookMapping(events=(_decision_event(hook, envelope.decision),))
        handler = _HANDLERS.get(hook.name)
        events = () if handler is None else handler(hook)
        transcript = _transcript(hook)
        if transcript is not None and self._origins is not None:
            self._origins.remember(transcript, _origin(hook, transcript))
        return HookMapping(events=events, transcript=transcript)


def _origin(hook: _Hook, transcript: TranscriptRef) -> TranscriptOrigin:
    # The main transcript is the main agent's; a subagent's is its agent type's.
    agent_type = fields.text(hook.input, fields.AGENT_TYPE)
    is_subagent = transcript.kind == "subagent"
    agent = short_text(agent_type, NAME_LIMIT) if is_subagent and agent_type else MAIN_AGENT
    return TranscriptOrigin(
        project=hook.envelope.project, repo=hook.envelope.repo, agent=agent, session=hook.session
    )


def _session_start(hook: _Hook) -> tuple[Event, ...]:
    payload: Payload = {}
    for key, name in (
        ("trigger", fields.SOURCE),
        ("cwd", fields.CWD),
        ("permission_mode", fields.PERMISSION_MODE),
        ("model", fields.MODEL),
        ("transcript_path", fields.TRANSCRIPT_PATH),
    ):
        value = fields.text(hook.input, name)
        if value is not None:
            payload[key] = value
    return (hook.event(EventType.SESSION_START, hook.hashed_id(hook.name), payload),)


def _user_prompt(hook: _Hook) -> tuple[Event, ...]:
    payload: Payload = {"role": "user"}
    prompt = hook.input.get(fields.PROMPT)
    if isinstance(prompt, str):
        payload["chars"] = len(prompt)
        command = prompt_command(prompt)
        if command is not None:
            payload["slash_command"] = command
    return (hook.event(EventType.MESSAGE, hook.hashed_id(hook.name), payload),)


def _pre_tool_use(hook: _Hook) -> tuple[Event, ...]:
    tool = fields.text(hook.input, fields.TOOL_NAME) or ""
    tool_input = fields.mapping(hook.input, fields.TOOL_INPUT)
    metadata = tool_call_payload(tool, tool_input, repo_root=hook.repo_root)
    call = hook.event(EventType.TOOL_CALL, hook.tool_id(hook.name), hook.tool_keys() | metadata)
    proposal = (
        None
        if hook.tool_use_id is None
        else learning_proposal(tool, tool_input, tool_use_id=hook.tool_use_id)
    )
    if proposal is None:
        return (call,)
    proposal["author"] = call.agent
    learning_id = f"{hook.tool_id(hook.name)}:learning"
    return call, hook.event(EventType.LEARNING_PROPOSED, learning_id, proposal)


def _post_tool_use(hook: _Hook) -> tuple[Event, ...]:
    payload = hook.tool_keys() | {"status": "ok"}
    payload |= _duration(hook)
    size = output_bytes(hook.input.get(fields.TOOL_RESPONSE))
    if size is not None:
        payload["output_bytes"] = size
    return (hook.event(EventType.TOOL_RESULT, hook.tool_id(hook.name), payload),)


def _post_tool_use_failure(hook: _Hook) -> tuple[Event, ...]:
    payload = hook.tool_keys() | {"status": "error"}
    payload |= _duration(hook)
    error = fields.text(hook.input, fields.ERROR)
    if fields.flag(hook.input, fields.IS_INTERRUPT):
        payload["error_line"] = INTERRUPTED
    elif error is not None:
        payload["error_line"] = first_line(error)
    return (hook.event(EventType.TOOL_RESULT, hook.tool_id(hook.name), payload),)


def _notification(hook: _Hook) -> tuple[Event, ...]:
    if fields.text(hook.input, fields.NOTIFICATION_TYPE) != fields.PERMISSION_PROMPT:
        return ()
    source_id = hook.hashed_id(hook.name)
    payload: Payload = {"gate_id": source_id, "kind": "permission"}
    return (hook.event(EventType.GATE_REQUEST, source_id, payload),)


def _session_end(hook: _Hook) -> tuple[Event, ...]:
    reason = fields.text(hook.input, fields.REASON)
    payload: Payload = {}
    if reason is not None:
        payload["end_reason"] = short_text(reason, NAME_LIMIT)
    payload["outcome"] = "stopped" if reason in fields.STOPPED_REASONS else None
    return (hook.event(EventType.SESSION_END, hook.hashed_id(hook.name), payload),)


def _duration(hook: _Hook) -> Payload:
    duration = fields.whole_number(hook.input, fields.DURATION_MS)
    return {} if duration is None else {"duration_ms": duration}


_HANDLERS: Final[dict[str, Callable[[_Hook], tuple[Event, ...]]]] = {
    fields.SESSION_START: _session_start,
    fields.USER_PROMPT_SUBMIT: _user_prompt,
    fields.PRE_TOOL_USE: _pre_tool_use,
    fields.POST_TOOL_USE: _post_tool_use,
    fields.POST_TOOL_USE_FAILURE: _post_tool_use_failure,
    fields.NOTIFICATION: _notification,
    fields.SESSION_END: _session_end,
}


def _transcript(hook: _Hook) -> TranscriptRef | None:
    if hook.name in {fields.STOP, fields.SESSION_END}:
        path = fields.text(hook.input, fields.TRANSCRIPT_PATH)
        kind: Literal["main", "subagent"] = "main"
    elif hook.name == fields.SUBAGENT_STOP:
        path = fields.text(hook.input, fields.AGENT_TRANSCRIPT_PATH)
        kind = "subagent"
    else:
        return None
    if path is None:
        return None
    return TranscriptRef(session=hook.session, path=path, kind=kind)


def _decision_event(hook: _Hook, decision: HookDecision) -> Event:
    if decision.by == "stop_gate":
        return _stop_gate_block(hook, decision)
    if decision.kind == "ask":
        return _guard_ask(hook, decision)
    return _guard_deny(hook, decision)


def _guard_deny(hook: _Hook, decision: HookDecision) -> Event:
    payload = hook.tool_keys() | {"status": "denied"}
    if decision.rule is not None:
        payload["rule"] = short_text(decision.rule, NAME_LIMIT)
    payload["hook"] = "guard"
    return hook.event(EventType.TOOL_RESULT, hook.tool_id("guard"), payload)


def _guard_ask(hook: _Hook, decision: HookDecision) -> Event:
    source_id = hook.tool_id("guard_ask")
    payload: Payload = {"gate_id": hook.tool_use_id or source_id, "kind": "guard_ask"}
    path = fields.text(fields.mapping(hook.input, fields.TOOL_INPUT), FILE_PATH)
    if path is not None:
        payload["path"] = shown_path(path, repo_root=hook.repo_root)
    if decision.rule is not None:
        payload["rule"] = short_text(decision.rule, NAME_LIMIT)
    return hook.event(EventType.GATE_REQUEST, source_id, payload)


def _stop_gate_block(hook: _Hook, decision: HookDecision) -> Event:
    source_id = hook.hashed_id("stop_gate")
    payload: Payload = {"gate_id": source_id, "kind": "stop_gate"}
    if decision.command is not None:
        payload["command"] = short_text(decision.command, COMMAND_LIMIT)
    if decision.exit_code is not None:
        payload["exit_code"] = decision.exit_code
    payload["result"] = "failed"
    return hook.event(EventType.GATE_RESULT, source_id, payload)
