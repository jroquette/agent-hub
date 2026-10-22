"""``repos[].ui_paths``: the globs of a repo's screen paths (two-level flows D-12, AGH-474).

A glob has the shape of the guard's file globs (``WordFileGlob``: printable ASCII without space,
never starting with ``/``, no ``..`` segment, at most 200 characters), but is matched against
the whole path from the repo root: ``*`` and ``?`` stay inside one folder, a ``**`` segment spans
any number of folders, and hidden names match like any other. So ``apps/web/**`` matches every
file under ``apps/web``, and ``*.vue`` only the root's.
"""

import glob
import re
from typing import Annotated, Final

from pydantic import Field

from agent_hub.core.hub_config.environments import WordFileGlob

MAX_UI_PATHS: Final = 50

UiPaths = Annotated[tuple[WordFileGlob, ...], Field(min_length=1, max_length=MAX_UI_PATHS)]


def ui_path_pattern(ui_path: str) -> re.Pattern[str]:
    """The regex a ``ui_paths`` glob matches a repo-relative POSIX path with (``fullmatch``)."""
    return re.compile(glob.translate(ui_path, recursive=True, include_hidden=True, seps="/"))
