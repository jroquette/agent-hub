"""A feature folder's state (D23), from the files the generator read: pure, no I/O.

Placeholder until F.6 fills it.
"""

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True, slots=True)
class FeatureFolder:
    """What was read of ``brain/features/<slug>/``.

    ``files`` names the record files present as regular files. ``features_json`` holds the
    record's bytes, a one-line problem when it could not be read, or None when absent;
    ``spec_head`` and ``eval_head`` are the first bytes of ``spec.md`` and ``eval.md``.
    """

    slug: str
    files: tuple[str, ...]
    features_json: bytes | str | None = None
    spec_head: bytes | None = None
    eval_head: bytes | None = None
