"""``hub agent``'s launch: Claude Code's argv, the repos' context text and the settings JSON.

Pure: the CLI reads ``hub.json`` and the repos' ``AGENTS.md``, writes the context file and execs.
The texts are the hub's old ``./agent`` launcher's, byte for byte, except the settings, which
are JSON-encoded (a hub path holding ``"`` broke the old string).
"""

import json
from collections.abc import Sequence

CLAUDE = "claude"


def context_text(sections: Sequence[tuple[str, bytes]]) -> bytes:
    """Each repo's ``AGENTS.md`` bytes under a header naming the repo, in the given order."""
    return b"".join(
        f"\n# Instructions for ../{name} (from {name}/AGENTS.md)\n\n".encode() + content
        for name, content in sections
    )


def settings_json(hub: str) -> str:
    """The ``--settings`` value: Claude Code's auto memory kept in the hub's brain."""
    return json.dumps({"autoMemoryDirectory": f"{hub}/brain/auto/workspace"})


def launch_argv(
    *, attached: Sequence[str], context_file: str, settings: str, extra: Sequence[str]
) -> list[str]:
    """``claude``, ``--add-dir`` per attached repo, the context file, the settings, ``extra``."""
    argv = [CLAUDE]
    for folder in attached:
        argv += ["--add-dir", folder]
    return [*argv, "--append-system-prompt-file", context_file, "--settings", settings, *extra]


def missing_repo_warning(path: str) -> str:
    """The line for a repo listed in ``hub.json`` with no folder in the workspace."""
    return f"warning: {path} not found (listed in hub.json); not attached"
