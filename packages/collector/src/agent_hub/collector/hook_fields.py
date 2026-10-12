"""Claude Code hook input fields: the one place their names appear, and tolerant readers.

Hook inputs change between Claude Code versions and are partly undocumented, so every read is a
lookup with a default and a type check: a missing key or a value of another type reads as None,
and unknown keys are ignored.
"""

from collections.abc import Mapping
from typing import Final

from agent_hub.core.json_form import JsonValue

type HookInput = Mapping[str, JsonValue]

# Common to every hook.
SESSION_ID: Final = "session_id"
TRANSCRIPT_PATH: Final = "transcript_path"
CWD: Final = "cwd"
HOOK_EVENT_NAME: Final = "hook_event_name"
PERMISSION_MODE: Final = "permission_mode"
# Set only inside a subagent (and on SubagentStart/SubagentStop).
AGENT_ID: Final = "agent_id"
AGENT_TYPE: Final = "agent_type"
# SessionStart
SOURCE: Final = "source"
MODEL: Final = "model"
# UserPromptSubmit
PROMPT: Final = "prompt"
# What the hook sensor sends in place of the prompt (S1): its length and leading /name.
PROMPT_CHARS: Final = "prompt_chars"
PROMPT_SLASH_COMMAND: Final = "prompt_slash_command"
# PreToolUse, PostToolUse, PostToolUseFailure
TOOL_NAME: Final = "tool_name"
TOOL_INPUT: Final = "tool_input"
TOOL_USE_ID: Final = "tool_use_id"
# PostToolUse
TOOL_RESPONSE: Final = "tool_response"
# What the hook sensor sends in place of the tool's output (S1): its UTF-8 size.
TOOL_RESPONSE_BYTES: Final = "tool_response_bytes"
DURATION_MS: Final = "duration_ms"
# PostToolUseFailure
ERROR: Final = "error"
IS_INTERRUPT: Final = "is_interrupt"
# Notification
NOTIFICATION_TYPE: Final = "notification_type"
PERMISSION_PROMPT: Final = "permission_prompt"
# SubagentStop
AGENT_TRANSCRIPT_PATH: Final = "agent_transcript_path"
# SessionEnd
REASON: Final = "reason"

# hook_event_name values.
SESSION_START: Final = "SessionStart"
USER_PROMPT_SUBMIT: Final = "UserPromptSubmit"
PRE_TOOL_USE: Final = "PreToolUse"
POST_TOOL_USE: Final = "PostToolUse"
POST_TOOL_USE_FAILURE: Final = "PostToolUseFailure"
NOTIFICATION: Final = "Notification"
STOP: Final = "Stop"
SUBAGENT_START: Final = "SubagentStart"
SUBAGENT_STOP: Final = "SubagentStop"
PRE_COMPACT: Final = "PreCompact"
SESSION_END: Final = "SessionEnd"
# SessionEnd reasons that mean the user stopped the session.
STOPPED_REASONS: Final = frozenset({"clear", "logout", "prompt_input_exit"})


def text(hook: HookInput, name: str) -> str | None:
    """The non-empty string at ``name``, else None."""
    value = hook.get(name)
    return value if isinstance(value, str) and value else None


def whole_number(hook: HookInput, name: str) -> int | None:
    """The integer at ``name`` (a boolean is not one), else None."""
    value = hook.get(name)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def flag(hook: HookInput, name: str) -> bool:
    """Whether ``name`` holds ``true``."""
    return hook.get(name) is True


def mapping(hook: HookInput, name: str) -> Mapping[str, JsonValue]:
    """The object at ``name``, else an empty one."""
    value = hook.get(name)
    return value if isinstance(value, dict) else {}
