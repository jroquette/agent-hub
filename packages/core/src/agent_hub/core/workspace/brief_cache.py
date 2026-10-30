"""The brief cache's document: what ``hub brief --write-cache`` writes to ``.hub-cache/brief.json``.

Pure: a JSON object with ``made_at`` (seconds since the epoch) and ``brief`` (the brief's text),
which the SessionStart hook reads with the stdlib (ADR 0055).
"""


def brief_cache_document(brief: str, *, made_at: float) -> bytes:
    """The cache file's bytes for ``brief``, made at ``made_at`` (seconds since the epoch)."""
    raise NotImplementedError
