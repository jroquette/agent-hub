"""``repos[].ui_paths``: the globs of a repo's screen paths (two-level flows D-12, AGH-474).

A glob has the shape of the guard's file globs (``WordFileGlob``: printable ASCII without space,
never starting with ``/``, no ``..`` segment, at most 200 characters), but is matched against
the whole path from the repo root, case-sensitive: ``*`` and ``?`` stay inside one folder, a
``**`` segment spans any number of folders, and hidden names match like any other. So
``apps/web/**`` matches every file under ``apps/web``, and ``*.vue`` only the root's.

Matching goes segment by segment: each segment that is not ``**`` is matched with
``fnmatchcase`` against one path segment, and the ``**`` segments by one pass over (glob
segment, path segment), so a failing match costs at most one segment match per pair. A middle
or leading ``**`` matches zero or more folders; a trailing one at least one name, so a folder
alone (``apps/web`` for ``apps/web/**``) never matches.

Two shapes are refused on top: ``[`` and ``]`` (a negated class such as ``[!a]`` would match
``/`` in a whole-path matcher, and the rule keeps globs portable to one), and more than
``MAX_SEGMENT_STARS`` ``*`` in one segment, a ``**`` segment counting as one, which bounds the
cost of each segment match.
"""

from fnmatch import fnmatchcase
from typing import Annotated, Final

from pydantic import AfterValidator, Field
from pydantic_core import PydanticCustomError

from agent_hub.core.hub_config.environments import WordFileGlob

MAX_UI_PATHS: Final = 50
MAX_SEGMENT_STARS: Final = 3


def _plain_wildcards(value: str) -> str:
    if "[" in value or "]" in value:
        raise PydanticCustomError("ui_path_bracket", "must not hold [ or ]")
    for segment in value.split("/"):
        stars = 1 if segment == "**" else segment.count("*")
        if stars > MAX_SEGMENT_STARS:
            raise PydanticCustomError(
                "ui_path_wildcards",
                "a path segment holds more than {cap} * (a ** segment counts as one)",
                {"cap": MAX_SEGMENT_STARS},
            )
    return value


UiPathGlob = Annotated[WordFileGlob, AfterValidator(_plain_wildcards)]
UiPaths = Annotated[tuple[UiPathGlob, ...], Field(min_length=1, max_length=MAX_UI_PATHS)]


RECURSIVE: Final = "**"


def ui_path_matches(ui_path: str, path: str) -> bool:
    """Whether a ``ui_paths`` glob matches a repo-relative POSIX path, segment by segment."""
    globs = ui_path.split("/")
    names = path.split("/")
    last = len(globs) - 1
    # ``reach[j]``: the globs from the current index on match ``names[j:]``; filled from the end.
    reach = [False] * len(names) + [True]
    for index in range(last, -1, -1):
        segment = globs[index]
        row = [False] * (len(names) + 1)
        for start in range(len(names), -1, -1):
            if segment == RECURSIVE and index == last:
                row[start] = start < len(names)
            elif segment == RECURSIVE:
                row[start] = reach[start] or (start < len(names) and row[start + 1])
            else:
                row[start] = (
                    start < len(names) and reach[start + 1] and fnmatchcase(names[start], segment)
                )
        reach = row
    return reach[0]
