"""Synthetic Claude Code hook inputs and sensor envelopes for tests, none from a real session.

The shapes follow the hook documentation summarised in the control-plane research
(``claude-code-fields.md``); the values are made up.
"""

import copy
from typing import Any, Final

from agent_hub.core.ingestion.hook_envelope import HookEnvelope

HOOK_SESSION: Final = "session-1"
HOOK_SENT_AT: Final = "2026-10-11T10:00:00.250Z"
HOOK_CWD: Final = "/work/demo-api"
HOOK_TRANSCRIPT: Final = "/home/dev/.claude/projects/-work-demo-api/session-1.jsonl"
SUBAGENT_TRANSCRIPT: Final = (
    "/home/dev/.claude/projects/-work-demo-api/session-1/subagents/agent-agent-7.jsonl"
)

_COMMON: Final[dict[str, Any]] = {
    "session_id": HOOK_SESSION,
    "transcript_path": HOOK_TRANSCRIPT,
    "cwd": HOOK_CWD,
    "permission_mode": "default",
}
_TOOL: Final[dict[str, Any]] = {
    "tool_name": "Bash",
    "tool_input": {"command": "make check-fast", "description": "Run the fast gate"},
    "tool_use_id": "toolu_01",
}
_SPECIFIC: Final[dict[str, dict[str, Any]]] = {
    "SessionStart": {"source": "startup", "model": "claude-opus-5-5"},
    "UserPromptSubmit": {"prompt": "/feature add the export button"},
    "PreToolUse": _TOOL,
    "PostToolUse": _TOOL
    | {
        "tool_response": {"stdout": "all checks passed", "stderr": "", "interrupted": False},
        "duration_ms": 1250,
    },
    "PostToolUseFailure": _TOOL
    | {"error": "Exit code 2\nmake: *** [check-fast] Error 2", "is_interrupt": False},
    "Notification": {
        "message": "Claude needs your permission to use Bash",
        "notification_type": "permission_prompt",
    },
    "Stop": {"stop_hook_active": False},
    "SubagentStart": {"agent_id": "agent-7", "agent_type": "Explore"},
    "SubagentStop": {
        "agent_id": "agent-7",
        "agent_type": "Explore",
        "agent_transcript_path": SUBAGENT_TRANSCRIPT,
        "stop_hook_active": False,
    },
    "PreCompact": {"trigger": "auto"},
    "SessionEnd": {"reason": "prompt_input_exit"},
}
HOOK_EVENT_NAMES: Final = tuple(_SPECIFIC)


def a_hook_input(event_name: str, **overrides: Any) -> dict[str, Any]:
    """A synthetic hook input of ``event_name`` (one of ``HOOK_EVENT_NAMES``); a fresh copy.

    An override set to ``...`` (Ellipsis) removes that key, so tests can drop optional ones.
    """
    hook: dict[str, Any] = copy.deepcopy(_COMMON | _SPECIFIC[event_name])
    hook["hook_event_name"] = event_name
    for key, value in overrides.items():
        if value is ...:
            hook.pop(key, None)
        else:
            hook[key] = value
    return hook


def an_envelope(hook: dict[str, Any], **overrides: Any) -> HookEnvelope:
    """The sensor's envelope around ``hook``: project ``demo``, repo ``demo-api``, no run."""
    document: dict[str, Any] = {
        "v": 1,
        "project": "demo",
        "repo": "demo-api",
        "run": None,
        "step": None,
        "attempt": None,
        "sent_at": HOOK_SENT_AT,
        "hook": hook,
    }
    return HookEnvelope.model_validate(document | overrides)
