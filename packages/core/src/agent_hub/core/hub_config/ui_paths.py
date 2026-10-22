"""``repos[].ui_paths``: the globs of a repo's screen paths (two-level flows D-12, AGH-474).

A glob has the shape of the guard's file globs (``WordFileGlob``: printable ASCII without space,
never starting with ``/``, no ``..`` segment, at most 200 characters), but is matched against
the whole path from the repo root, case-sensitive: ``*`` and ``?`` stay inside one folder, a
``**`` segment spans any number of folders, and hidden names match like any other. So
``apps/web/**`` matches every file under ``apps/web``, and ``*.vue`` only the root's.

Two shapes are refused on top: ``[`` and ``]`` (a negated class such as ``[!a]`` matches ``/``,
so one segment's pattern could cross folders), and more than ``MAX_SEGMENT_STARS`` ``*`` in one
segment, a ``**`` segment counting as one (the translated regex backtracks badly on many).
"""

import glob
import re
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


def ui_path_pattern(ui_path: str) -> re.Pattern[str]:
    """The regex a ``ui_paths`` glob matches a repo-relative POSIX path with (``fullmatch``)."""
    return re.compile(glob.translate(ui_path, recursive=True, include_hidden=True, seps="/"))
