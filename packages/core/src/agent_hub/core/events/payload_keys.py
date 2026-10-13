"""The payload keys each event type may store (D11 "Payload kept"): metadata only.

This table is the one source of truth for what an event's payload holds once stored. The
collector's mappers build payloads from it, and ``IngestEvents`` trims every event to it, so an
entry point that builds its own payload (a JSON Lines file for ``hub collect``) cannot store a
prompt, an output or a file body under a key the table does not list: such keys are dropped,
never rejected. Values are not checked here; redaction (D10) runs first on everything.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from agent_hub.core.events.event import EventType
from agent_hub.core.json_form import JsonValue

# Any type may say which ``hub run`` run, step and attempt it belongs to (D6), which subagent
# emitted it (E4), and the git branch its transcript line names (AGH-201).
COMMON_PAYLOAD_KEYS: Final = frozenset({"run", "step", "attempt", "agent_id", "git_branch"})


_USAGE: Final = frozenset(
    {
        "message_id",
        "model",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
    }
)
_GATE: Final = frozenset(
    {
        "gate_id",
        "kind",
        "name",
        "command",
        "path",
        "rule",
        "feature",
        "result",
        "exit_code",
        "duration_ms",
        "approver",
        "where",
        # Executor gates also carry their run's issue, repo and mode (live or dry run).
        "issue",
        "repo",
        "mode",
    }
)
_EXECUTOR: Final = frozenset(
    {"issue", "repo", "status", "stage", "reason", "caps", "pr_url", "cost_usd", "mode", "outcome"}
)
_LEARNING: Final = frozenset(
    {
        "text",
        "target",
        "author",
        "proposal",
        "brain_path",
        "commit",
        "reason",
        "provenance",
        # A decision taken in the app records the pull request it opened (ADR 0024).
        "pr_url",
        "branch",
        "state",
    }
)

_BY_TYPE: Final[dict[EventType, frozenset[str]]] = {
    EventType.SESSION_START: frozenset(
        {"trigger", "cwd", "git_branch", "permission_mode", "model", "transcript_path"}
    ),
    EventType.SESSION_END: frozenset({"end_reason", "outcome"}),
    EventType.MESSAGE: frozenset({"role", "chars", "turn", "slash_command"}) | _USAGE,
    EventType.REASONING: frozenset({"chars", "turn"}),
    EventType.DECISION: frozenset({"text", "turn"}),
    EventType.TOOL_CALL: frozenset(
        {
            "tool",
            "tool_use_id",
            "turn",
            "path",
            "lines_added",
            "lines_removed",
            "new_file",
            "command",
            "pattern",
            "url",
            "mcp_server",
            "mcp_tool",
            "arg_keys",
            "subagent_type",
            "description",
            # The Skill tool's skill name and SendMessage's recipient (80 chars, ADR 0023).
            "skill",
            "to",
        }
    ),
    EventType.TOOL_RESULT: frozenset(
        {
            "tool",
            "tool_use_id",
            "turn",
            "status",
            "exit_code",
            "duration_ms",
            "output_bytes",
            "error_line",
            # A failed tool's error text: redacted, whitespace collapsed, 300 chars (ADR 0023).
            "error_message",
            "rule",
            "hook",
        }
    ),
    EventType.GATE_REQUEST: _GATE,
    EventType.GATE_RESULT: _GATE,
    EventType.LEARNING_PROPOSED: _LEARNING,
    EventType.LEARNING_ACCEPTED: _LEARNING,
    EventType.LEARNING_REJECTED: _LEARNING,
    EventType.STEP_START: _EXECUTOR,
    EventType.STEP_END: _EXECUTOR,
    EventType.RUN_END: _EXECUTOR,
    # A stored summary is short lines written for the reader (D17).
    EventType.SESSION_SUMMARY: frozenset({"text", "lines"}),
}

PAYLOAD_KEYS: Final[Mapping[EventType, frozenset[str]]] = MappingProxyType(
    {event_type: keys | COMMON_PAYLOAD_KEYS for event_type, keys in _BY_TYPE.items()}
)

# The (event type, key) pairs this release added to the allow-list (ADR 0023): ``git_branch`` on
# every type but ``session.start`` (which stored it before), ``skill`` and ``to`` on
# ``tool.call``, ``error_message`` on ``tool.result``. An event stored before them that is
# re-ingested with them is the same event: equal once its type's added keys are removed.
_ADDED_BY_TYPE_V2: Final[dict[EventType, frozenset[str]]] = {
    EventType.TOOL_CALL: frozenset({"skill", "to"}),
    EventType.TOOL_RESULT: frozenset({"error_message"}),
}
ADDED_KEYS_V2: Final[Mapping[EventType, frozenset[str]]] = MappingProxyType(
    {
        event_type: _ADDED_BY_TYPE_V2.get(event_type, frozenset())
        | (frozenset() if event_type == EventType.SESSION_START else frozenset({"git_branch"}))
        for event_type in _BY_TYPE
    }
)

# The executor's caps (budget, max turns, model, transport) are an object of these keys only.
CAPS_KEYS: Final = frozenset({"budget", "max_turns", "model", "transport"})


def kept_payload(event_type: EventType, payload: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """``payload`` with only the keys ``event_type`` may store; the others are dropped."""
    allowed = PAYLOAD_KEYS[event_type]
    kept = {key: value for key, value in payload.items() if key in allowed}
    caps = kept.get("caps")
    if isinstance(caps, dict):
        kept["caps"] = {key: value for key, value in caps.items() if key in CAPS_KEYS}
    return kept
