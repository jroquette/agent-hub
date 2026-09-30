"""What ``hub init`` prints when it wrote a hub: the counts, then the next steps (spec Q-1, Q-2).

Paths come from the user (``--dir``) or from the target folder, so each one is shown on its
line as is only when it is printable ASCII without a ``"``; any other path is shown as a JSON
string, so a newline in a name cannot break a line or fake one.
"""

import json
import shlex
from typing import Final

from agent_hub.core.hub_files.plan_init import InitPlan

# Only commands that work in this release: AGH-15 adds ./agent.
_REVIEW_STEP: Final = "review hub.json, AGENTS.project.md and README.md"
_COMMIT_STEP: Final = 'git add -A && git commit -m "Create the hub"'
_CLAUDE_STEP: Final = "start Claude Code in the hub folder: claude"
_UPGRADE_STEP: Final = "to upgrade later: edit platform.version in hub.json, then run hub sync"
_FIRST_PRINTABLE: Final = " "
_LAST_PRINTABLE: Final = "~"


def shown_path(path: str) -> str:
    """``path`` as is when it is printable ASCII without ``"``, else as a JSON string."""
    if all(_FIRST_PRINTABLE <= character <= _LAST_PRINTABLE for character in path) and (
        '"' not in path
    ):
        return path
    return json.dumps(path)


def shown_text(text: str) -> str:
    """``text`` as is when it holds no line break or other unprintable character, else as JSON."""
    return text if text.isprintable() else json.dumps(text)


def created_lines(plan: InitPlan, root: str) -> list[str]:
    """The created line, then the kept and removed lines when there is something to count.

    ``hub.lock`` is tool state and never counted; ``hub.json`` counts as a seeded file.
    """
    managed, seeded = len(plan.created_managed), len(plan.created_seeded)
    lines = [
        f"created {managed + seeded} files ({managed} managed, {seeded} seeded)"
        f" and {len(plan.created_links)} links in {shown_path(root)}"
    ]
    kept_seeded, kept_equal = len(plan.kept_seeded), len(plan.kept_equal)
    kept_links = len(plan.kept_links)
    if kept_seeded + kept_equal + kept_links > 0:
        links = f" and {kept_links} links" if kept_links else ""
        lines.append(
            f"kept {kept_seeded + kept_equal} files already there"
            f" ({kept_seeded} seeded, {kept_equal} equal to the render){links}"
        )
    if plan.leftovers:
        lines.append(f"removed {len(plan.leftovers)} leftover temporary files")
    return lines


def next_steps(root: str, *, git_present: bool) -> list[str]:
    """The numbered next steps; ``git init`` only when the hub folder holds no ``.git``."""
    # A path with a line break cannot be shell-quoted on one line: it is shown escaped instead.
    folder = shlex.quote(root) if root.isprintable() else shown_path(root)
    steps = [
        f"cd {folder}",
        *([] if git_present else ["git init"]),
        _REVIEW_STEP,
        _COMMIT_STEP,
        _CLAUDE_STEP,
        _UPGRADE_STEP,
    ]
    return ["Next steps:", *(f"  {number}. {step}" for number, step in enumerate(steps, start=1))]
