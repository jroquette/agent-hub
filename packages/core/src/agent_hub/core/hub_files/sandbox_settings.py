"""The sandbox exclusions the hub's own workflow needs (AGH-134).

The managed ``.claude/settings.json`` turns Claude Code's sandbox on: writes stay in the
workspace, the network goes through a filtering proxy that SSH never crosses. The hub's own
commands that reach a remote must run outside it, so the template lists them in
``sandbox.excludedCommands`` and ``hub doctor``'s ``sandbox.workflow`` checks they are there.

Claude Code matches an entry against the literal text of a Bash call: only a call that is exactly
that simple command escapes (no ``cd … &&``, ``;``, pipe, redirect or ``git -C``). So ``hub
worktree``, whose own ``git fetch`` would never match, is listed by its three spellings; a
broader ``make *`` or ``./hub *`` is never listed (a Makefile may hold deploy targets). An
excluded command still goes through Claude Code's permission prompt.
"""

from typing import Final

WORKFLOW_EXCLUDED_COMMANDS: Final = (
    "gh *",
    "git push *",
    "git fetch *",
    "git pull *",
    "git clone *",
    "git ls-remote *",
    "./hub worktree *",
    "hub worktree *",
    "make worktree *",
    "make worktree-remove *",
)
