"""Claude Code transcript (JSON Lines) fields: the one place their names appear.

The transcript format is internal to Claude Code and changes between versions: every read is a
lookup with a default and a type check, and unknown keys and line types are ignored.
"""

from typing import Final

# Line keys.
TYPE: Final = "type"
TIMESTAMP: Final = "timestamp"
SESSION_ID: Final = "sessionId"
UUID: Final = "uuid"
IS_SIDECHAIN: Final = "isSidechain"
GIT_BRANCH: Final = "gitBranch"
CWD: Final = "cwd"
MESSAGE: Final = "message"
# Line types mapped; every other one is ignored.
USER: Final = "user"
ASSISTANT: Final = "assistant"

# Message keys.
MESSAGE_ID: Final = "id"
MODEL: Final = "model"
ROLE: Final = "role"
CONTENT: Final = "content"
USAGE: Final = "usage"
# Usage keys, with the payload key each one is stored under.
USAGE_KEYS: Final = (
    ("input_tokens", "input_tokens"),
    ("output_tokens", "output_tokens"),
    ("cache_read_input_tokens", "cache_read_tokens"),
    ("cache_creation_input_tokens", "cache_write_tokens"),
)

# Content blocks.
BLOCK_TYPE: Final = "type"
TEXT: Final = "text"
THINKING: Final = "thinking"
TOOL_USE: Final = "tool_use"
TOOL_RESULT: Final = "tool_result"
TOOL_USE_BLOCK_ID: Final = "id"
TOOL_USE_NAME: Final = "name"
TOOL_USE_INPUT: Final = "input"
TOOL_RESULT_USE_ID: Final = "tool_use_id"
TOOL_RESULT_IS_ERROR: Final = "is_error"
TOOL_RESULT_CONTENT: Final = "content"
