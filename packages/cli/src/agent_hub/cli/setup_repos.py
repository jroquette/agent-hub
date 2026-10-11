"""``hub setup``'s git: the environment of every git call setup makes on its own.

No call may stop on a credential prompt (``GIT_TERMINAL_PROMPT=0``), the tracker key never
reaches git, and a location variable the caller set (``GIT_DIR``) never points git at another
repo than the one the call names.
"""

from collections.abc import Mapping

from agent_hub.cli.run_children import child_env

_NO_PROMPT = {"GIT_TERMINAL_PROMPT": "0"}


def setup_git_env(environ: Mapping[str, str]) -> dict[str, str]:
    """``environ`` for setup's own git: no tracker key, no location variable, no prompt."""
    return {**child_env(environ), **_NO_PROMPT}
