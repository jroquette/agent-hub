"""The ``ClaudeAgentOptions`` of one session (AC-165.3) and where the user's ``claude`` is.

Setting sources stay at the CLI's defaults (user, project, local), so the workdir's CLAUDE.md,
hooks, skills and agents load as in a terminal. A permission mode is always passed: with none the
CLI runs ``auto`` (spike), which the web never offers. The CLI accepts ``default`` as it is, so
no mode is renamed (E15). The SDK runs the ``claude`` found on ``PATH`` (``cli_path``), never the
binary bundled in its wheel. The child's stderr is discarded: it may hold conversation text,
which no server log keeps.
"""

import os
import shutil
from collections.abc import Mapping
from typing import Final

from claude_agent_sdk import CanUseTool, ClaudeAgentOptions

from agent_hub.claude_sessions.environment import child_environment
from agent_hub.core.agent_sessions.driver import StartSpec

# One message from the CLI may be at most this large (the plan's bound; the SDK's default is 1 MiB).
MAX_BUFFER_BYTES: Final = 8 * 1024 * 1024
CLAUDE: Final = "claude"


def claude_path(environ: Mapping[str, str]) -> str | None:
    """The absolute path of the ``claude`` on ``environ``'s ``PATH``, or None."""
    search = environ.get("PATH")
    if not search:
        return None
    found = shutil.which(CLAUDE, path=search)
    return None if found is None else os.path.abspath(found)


def _discard(_line: str) -> None:
    """Drop one stderr line of the child."""


def sdk_options(
    spec: StartSpec,
    *,
    can_use_tool: CanUseTool,
    cli_path: str,
    environ: Mapping[str, str],
    max_buffer_size: int = MAX_BUFFER_BYTES,
) -> ClaudeAgentOptions:
    """The SDK options of a session started with ``spec``."""
    return ClaudeAgentOptions(
        cli_path=cli_path,
        cwd=spec.cwd,
        permission_mode=spec.mode,
        model=spec.model,
        resume=spec.resume,
        fork_session=spec.fork,
        session_id=spec.session_id,
        include_partial_messages=True,
        can_use_tool=can_use_tool,
        env=child_environment(environ, spec.environment_extra),
        max_buffer_size=max_buffer_size,
        stderr=_discard,
    )
