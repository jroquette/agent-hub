"""The task name ``hub start`` gives an issue, and which task folders belong to it.

The slug is the title with only ``A``-``Z`` lowercased (``str.lower`` turns some non-ASCII
letters into ASCII ones, such as the Kelvin sign into ``k``); every run of other characters
outside ``[a-z0-9]`` becomes one ``-``, so non-ASCII letters are dropped (``Café`` gives
``caf``). A slug longer than ``MAX_SLUG_CHARS`` is cut to its longest prefix that ends at a word
end, or to its first ``MAX_SLUG_CHARS`` characters when its first word is longer.
"""

import re
import string
from typing import Final

MAX_SLUG_CHARS: Final = 40
_ASCII_LOWER: Final = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)
_SEPARATORS = re.compile(r"[^a-z0-9]+")


def title_slug(title: str) -> str:
    """The name part for ``title``: ``[a-z0-9]`` words joined by ``-``, at most 40 characters.

    It is ``""`` when the title holds no ASCII letter or digit.
    """
    slug = _SEPARATORS.sub("-", title.translate(_ASCII_LOWER)).strip("-")
    if len(slug) <= MAX_SLUG_CHARS:
        return slug
    # The last dash at or before the limit ends the last whole word that fits.
    word_end = slug.rfind("-", 0, MAX_SLUG_CHARS + 1)
    return slug[:word_end] if word_end > 0 else slug[:MAX_SLUG_CHARS]


def task_name(issue_id: str, title: str) -> str:
    """``<issue id lower>-<slug>``, or the lowercase issue id alone when the slug is empty."""
    slug = title_slug(title)
    return f"{issue_id.lower()}-{slug}" if slug else issue_id.lower()


def is_task_folder(folder: str, issue_id: str) -> bool:
    """True when ``folder`` is the issue's lowercase id, or that id followed by ``-``.

    ``dem-7`` and ``dem-7-x`` belong to ``DEM-7``; ``dem-70-x`` does not.
    """
    issue = issue_id.lower()
    return folder == issue or folder.startswith(f"{issue}-")


def task_folder_problem(folder: str, issue_id: str) -> str | None:
    """Why the issue's task ``folder`` is not a valid task name, or None.

    A valid one is ``<issue id lower>[-<desc>]`` with ``<desc>`` in ``[a-z0-9._-]``, the rule
    ``worktree_name_problem`` sets for every worktree name, so a name read back from disk is as
    safe to show, prompt with and branch from as a fresh one. ``folder`` is kept as is: the
    caller escapes it.
    """
    issue = issue_id.lower()
    if re.fullmatch(rf"{re.escape(issue)}(-[a-z0-9._-]+)?", folder):
        return None
    return (
        f"worktree {folder} is not a task name, {issue}[-<desc>] with <desc> in [a-z0-9._-];"
        " rename or remove it"
    )
