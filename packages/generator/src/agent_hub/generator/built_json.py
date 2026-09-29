"""The JSON files the generator builds from the config (spec D5, Q-9, Q-10, Q-11).

Each builder returns a JSON value; ``render_hub`` writes it in the JSON byte form
(``json_form.dump_json``). A builder reads only the config: the same config builds the same value.
"""

from typing import Final, NamedTuple

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.generator.json_form import JsonValue

_PROJECT_MANIFEST_VERSION = "0.1.0"
_PROJECT_MANIFEST_DESCRIPTION = "Project agents, skills and guard extension of this hub."

_SETTINGS_SCHEMA: Final = "https://json.schemastore.org/claude-code-settings.json"
# Spec Q-11: read-only git commands run without a prompt; secret files are never read. Nothing
# else: the guard enforces the push and infra rules, and a project adds its own lists through
# `settings.project.json`.
_ALLOWED_COMMANDS: Final = (
    "Bash(git status *)",
    "Bash(git diff *)",
    "Bash(git log *)",
    "Bash(git show *)",
)
_DENIED_READS: Final = ("Read(**/*.pem)", "Read(**/*.key)")
# The base plugin's hooks, from the hub root: cloud sessions do not install repo plugins, so the
# managed settings wire the hooks themselves (docs/design/hub-generator.md § Hooks and plugin
# wiring).
_HOOKS_FOLDER: Final = "$CLAUDE_PROJECT_DIR/plugin/hub-workflow/hooks"


class HookEvent(NamedTuple):
    """One hook the managed settings wire: the event, its matcher (``None``: every tool or
    source), the base plugin hook file it runs and its timeout in seconds.
    """

    event: str
    matcher: str | None
    file: str
    timeout: int


# Spec AC-4.7 (Q-5): the base plugin's six hooks, with this hub's timeouts; `hooks.json` wires the
# same six for a plugin install.
HOOK_EVENTS: Final = (
    HookEvent("SessionStart", "startup|resume|clear|compact", "session_start.py", 20),
    HookEvent(
        "PreToolUse",
        "Bash|Read|Grep|Glob|Edit|Write|MultiEdit|NotebookEdit|WebFetch",
        "guard.py",
        10,
    ),
    HookEvent("PostToolUse", "Edit|Write|MultiEdit", "post_edit.py", 60),
    HookEvent("Stop", None, "stop_gate.py", 180),
    HookEvent("PreCompact", None, "pre_compact.py", 20),
    HookEvent("SessionEnd", None, "session_end.py", 10),
)


def managed_settings(config: HubConfig) -> JsonValue:
    """The managed ``.claude/settings.json``: the rules base every hub shares (spec D5).

    The schema, the authorship rule (empty attribution, no co-author line), the hooks block, the
    read-only git allows, the secret-read denies and the repos as additional directories
    (``../<dir>``, in ``hub.json`` order). Project settings (marketplace, plugins, sandbox,
    ``env``, skill overrides) come from the seeded ``settings.project.json``.
    """
    return {
        "$schema": _SETTINGS_SCHEMA,
        "attribution": {"commit": "", "pr": ""},
        "includeCoAuthoredBy": False,
        "hooks": {hook.event: [_hook_group(hook)] for hook in HOOK_EVENTS},
        "permissions": {
            "allow": list(_ALLOWED_COMMANDS),
            "deny": list(_DENIED_READS),
            "additionalDirectories": [f"../{repo.dir}" for repo in config.repos],
        },
    }


def _hook_group(hook: HookEvent) -> JsonValue:
    command: JsonValue = {
        "type": "command",
        "command": f'python3 "{_HOOKS_FOLDER}/{hook.file}"',
        "timeout": hook.timeout,
    }
    if hook.matcher is None:
        return {"hooks": [command]}
    return {"matcher": hook.matcher, "hooks": [command]}


def project_settings(config: HubConfig) -> JsonValue:
    """The seeded ``.claude/settings.project.json``: empty; the project adds its own settings."""
    return {}


def project_manifest(config: HubConfig) -> JsonValue:
    """The seeded project plugin manifest: the project's name, a first version, a description."""
    return {
        "name": config.project.name,
        "version": _PROJECT_MANIFEST_VERSION,
        "description": _PROJECT_MANIFEST_DESCRIPTION,
    }
