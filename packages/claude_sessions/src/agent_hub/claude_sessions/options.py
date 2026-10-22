"""The ``ClaudeAgentOptions`` of one session (AC-165.3) and where the user's ``claude`` is.

Setting sources stay at the CLI's defaults (user, project, local), so the workdir's CLAUDE.md,
hooks, skills and agents load as in a terminal; a session outside the hub also loads the hub's
plugins (``StartSpec.plugin_dirs``), so its skills and agents answer there too. A permission
mode is always passed: with none the CLI runs ``auto`` (spike), which the web never offers. The
CLI accepts ``default`` as it is, so no mode is renamed (E15). The SDK runs the ``claude`` found
on ``PATH`` (``cli_path``), never the binary bundled in its wheel. The child's stderr is
discarded: it may hold conversation text, which no server log keeps.

The child loses the hub's declared credentials (``environment``). An investigation session
(``StartSpec.tool_policy``, P-17) gets only the built-in tools ``Read``, ``Glob``, ``Grep``,
``Write`` and ``Bash``, and a ``PreToolUse`` hook on every tool that denies what core's
``tool_verdict`` refuses (an allowed call goes on to the permission mode as any other); its
``system_prompt`` is appended to Claude Code's own, so the tools keep their instructions.

A ``read_only`` session (ADR 0046) gets only ``READ_ONLY_TOOLS``: they are its whole tool set
(``tools``) and allowed outright (``allowed_tools``); every tool that writes, runs a command or
reaches the network is removed as well (``disallowed_tools``) and no MCP server loads
(``strict_mcp_config`` with none given). The setting sources stay, so the project's guard hooks
still run; ``PermissionBridge`` denies any other request such a session still makes.
"""

import os
import shutil
from collections.abc import Mapping
from typing import Final

from claude_agent_sdk import (
    CanUseTool,
    ClaudeAgentOptions,
    HookCallback,
    HookContext,
    HookInput,
    HookJSONOutput,
    HookMatcher,
)
from claude_agent_sdk.types import SystemPromptPreset

from agent_hub.claude_sessions.environment import child_environment, masked_names
from agent_hub.core.agent_sessions.driver import READ_ONLY_TOOLS, StartSpec
from agent_hub.core.scenarios.investigation import INVESTIGATION_TOOLS, ToolPolicy, tool_verdict

# One message from the CLI may be at most this large (the plan's bound; the SDK's default is 1 MiB).
MAX_BUFFER_BYTES: Final = 8 * 1024 * 1024
CLAUDE: Final = "claude"
# The tools a read-only session must never have: they write, run commands, reach the network
# or start other agents.
WRITE_TOOLS: Final = (
    "Bash",
    "BashOutput",
    "KillShell",
    "Edit",
    "MultiEdit",
    "Write",
    "NotebookEdit",
    "WebFetch",
    "WebSearch",
    "Task",
    "Agent",
)


def claude_path(environ: Mapping[str, str]) -> str | None:
    """The absolute path of the ``claude`` on ``environ``'s ``PATH``, or None."""
    search = environ.get("PATH")
    if not search:
        return None
    found = shutil.which(CLAUDE, path=search)
    return None if found is None else os.path.abspath(found)


def _discard(_line: str) -> None:
    """Drop one stderr line of the child."""


def tool_hook(policy: ToolPolicy) -> HookCallback:
    """The ``PreToolUse`` hook holding a session to ``policy``: a refused call is denied with
    its reason; an allowed one answers nothing, so the permission mode decides as usual."""

    async def hook(
        hook_input: HookInput, _tool_use_id: str | None, _context: HookContext
    ) -> HookJSONOutput:
        tool = hook_input.get("tool_name")
        given = hook_input.get("tool_input")
        verdict = tool_verdict(
            policy,
            tool if isinstance(tool, str) else "",
            given if isinstance(given, dict) else {},
        )
        if verdict.allowed:
            return {}
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": verdict.reason,
            }
        }

    return hook


def _system_prompt(spec: StartSpec) -> SystemPromptPreset | None:
    if spec.system_prompt is None:
        return None
    return {"type": "preset", "preset": "claude_code", "append": spec.system_prompt}


def _tools(policy: ToolPolicy | None, *, read_only: bool) -> list[str] | None:
    """The built-in tools a session has: an investigation's, a read-only session's, else all."""
    if policy is not None:
        return list(INVESTIGATION_TOOLS)
    return list(READ_ONLY_TOOLS) if read_only else None


def sdk_options(
    spec: StartSpec,
    *,
    can_use_tool: CanUseTool,
    cli_path: str,
    environ: Mapping[str, str],
    max_buffer_size: int = MAX_BUFFER_BYTES,
) -> ClaudeAgentOptions:
    """The SDK options of a session started with ``spec``."""
    env = child_environment(environ, spec.environment_extra, hidden=spec.hidden_environment)
    env.update(dict.fromkeys(masked_names((environ, os.environ), spec.hidden_environment), ""))
    policy = spec.tool_policy
    read_only = spec.tool_access == "read_only"
    return ClaudeAgentOptions(
        tools=_tools(policy, read_only=read_only),
        allowed_tools=list(READ_ONLY_TOOLS) if read_only else [],
        disallowed_tools=list(WRITE_TOOLS) if read_only else [],
        strict_mcp_config=read_only,
        add_dirs=list(spec.add_dirs),
        cli_path=cli_path,
        cwd=spec.cwd,
        permission_mode=spec.mode,
        model=spec.model,
        resume=spec.resume,
        fork_session=spec.fork,
        session_id=spec.session_id,
        include_partial_messages=True,
        can_use_tool=can_use_tool,
        env=env,
        max_buffer_size=max_buffer_size,
        stderr=_discard,
        plugins=[{"type": "local", "path": path} for path in spec.plugin_dirs],
        hooks=None
        if policy is None
        else {"PreToolUse": [HookMatcher(matcher=None, hooks=[tool_hook(policy)])]},
        system_prompt=_system_prompt(spec),
    )
