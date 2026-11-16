"""The brief cache's document: what ``hub brief --write-cache`` writes to ``.hub-cache/brief.json``.

Pure: a JSON object with ``made_at`` (seconds since the epoch) and ``brief`` (the brief's text),
which the SessionStart hook reads with the stdlib (ADR 0055). The folder ignores itself in git
(its ``.gitignore`` is ``*``). The hook refuses a file over ``CACHE_MAX_BYTES`` and cuts the brief
at ``BRIEF_MAX_CHARS``; the document keeps at most that many characters, so it always fits.
"""

import json
from typing import Final

CACHE_FOLDER: Final = ".hub-cache"
CACHE_FILE: Final = "brief.json"
GITIGNORE_FILE: Final = ".gitignore"
# The folder ignores everything in it, itself included, so the hub stays clean in git status.
GITIGNORE_TEXT: Final = "# Written by hub; ignores this whole folder.\n*\n"
MADE_AT_FIELD: Final = "made_at"
BRIEF_FIELD: Final = "brief"
CACHE_MAX_BYTES: Final = 64 * 1024
# At most 6 bytes a character (a \u00XX escape), so the document stays under CACHE_MAX_BYTES.
BRIEF_MAX_CHARS: Final = 8000


def brief_cache_document(brief: str, *, made_at: float) -> bytes:
    """The cache file's bytes for ``brief``, made at ``made_at`` (seconds since the epoch).

    UTF-8 JSON, the brief cut at ``BRIEF_MAX_CHARS`` characters.
    """
    document = {MADE_AT_FIELD: made_at, BRIEF_FIELD: brief[:BRIEF_MAX_CHARS]}
    return json.dumps(document, ensure_ascii=False, allow_nan=False).encode("utf-8")
