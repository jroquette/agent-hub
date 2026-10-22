"""The paths ``hub mcp``'s ``read`` may serve (spec D-read): pure rules, no file is touched.

A path is hub-relative with ``/`` separators: 1..``MAX_PATH_CHARS`` characters, no NUL, no ``\\``,
not absolute, no empty, ``.`` or ``..`` segment, and a name the knowledge index looks at
(``is_indexed_name``: ``.md``, outside ``brain/auto/`` in any case). It lies under ``brain/`` or
under ``<dir>/docs/`` for a ``repos[].dir`` of ``hub.json``. Whether the file itself may be served
(no link, regular, size, UTF-8, listed by git, no secret) is checked by the read, not here.
"""

from collections.abc import Sequence
from typing import Final

from agent_hub.core.brain.brain_path import BRAIN_FOLDER
from agent_hub.core.knowledge.document_rules import is_indexed_name

MAX_PATH_CHARS: Final = 1024
PATH_NOT_ALLOWED: Final = "path not allowed"
_DOCS_FOLDER: Final = "docs"
_FORBIDDEN_CHARACTERS: Final = ("\x00", "\\")
_DOT_SEGMENTS: Final = frozenset({"", ".", ".."})
# ``<dir>/docs/<name>``: the repo folder, ``docs`` and at least one more segment.
_MIN_DOCS_SEGMENTS: Final = 3


def refusal(path: str, repo_dirs: Sequence[str]) -> str | None:
    """``PATH_NOT_ALLOWED`` when ``path`` breaks the grammar or lies outside the hub's sources
    (``brain/`` minus ``brain/auto/``, each of ``repo_dirs``'s ``docs/``); None when allowed."""
    if not _is_well_formed(path) or not is_indexed_name(path):
        return PATH_NOT_ALLOWED
    segments = path.split("/")
    if segments[0] == BRAIN_FOLDER or _is_repo_doc(segments, repo_dirs):
        return None
    return PATH_NOT_ALLOWED


def _is_well_formed(path: str) -> bool:
    if not 1 <= len(path) <= MAX_PATH_CHARS:
        return False
    if any(character in path for character in _FORBIDDEN_CHARACTERS):
        return False
    return not any(segment in _DOT_SEGMENTS for segment in path.split("/"))


def _is_repo_doc(segments: Sequence[str], repo_dirs: Sequence[str]) -> bool:
    return (
        len(segments) >= _MIN_DOCS_SEGMENTS
        and segments[0] in repo_dirs
        and segments[1] == _DOCS_FOLDER
    )
