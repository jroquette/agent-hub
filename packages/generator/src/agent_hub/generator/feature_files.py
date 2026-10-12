"""Read a hub's feature folders, ``brain/features/<slug>/`` (D23), for the control plane.

Bounded and never through a link: each folder on the way (``brain``, ``features``, the slug) is
opened relative to its parent with ``O_NOFOLLOW``, so a linked folder is skipped; a slug starting
with ``.`` is skipped, as a shell glob does, and at most ``MAX_FEATURE_FOLDERS`` are read, in name
order. In each folder only the record files are looked at, as regular files: ``features.json``
whole up to ``MAX_RECORD_BYTES`` (else a one-line problem), ``spec.md`` and ``eval.md`` up to
``HEAD_BYTES``. What the files mean is core's (``feature_status``).
"""

import contextlib
import errno
import os
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from agent_hub.core.features.feature_status import (
    EVAL,
    HEAD_BYTES,
    RECORD,
    RECORD_FILES,
    SPEC,
    FeatureFolder,
)

MAX_FEATURE_FOLDERS: Final = 500
MAX_RECORD_BYTES: Final = 1_048_576
FEATURES_PATH: Final = ("brain", "features")
NOT_REGULAR: Final = "not a regular file"
_FOLDER_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_FILE_FLAGS: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK


def read_feature_folders(hub_root: Path) -> tuple[FeatureFolder, ...]:
    """Every feature folder of the hub at ``hub_root``; none when ``brain/features`` is absent."""
    with _features_folder(hub_root) as folder:
        if folder is None:
            return ()
        return tuple(_read_folder(folder, slug) for slug in _slugs(folder))


@contextlib.contextmanager
def _features_folder(hub_root: Path) -> Iterator[int | None]:
    opened: list[int] = []
    try:
        parent = os.open(hub_root, os.O_RDONLY | os.O_DIRECTORY)
        opened.append(parent)
        for name in FEATURES_PATH:
            parent = os.open(name, _FOLDER_FLAGS, dir_fd=parent)
            opened.append(parent)
    except OSError:
        yield None
    else:
        yield parent
    finally:
        for descriptor in opened:
            os.close(descriptor)


def _slugs(folder: int) -> list[str]:
    slugs: list[str] = []
    for name in sorted(os.listdir(folder)):
        if len(slugs) >= MAX_FEATURE_FOLDERS:
            break
        if name.startswith("."):
            continue
        with contextlib.suppress(OSError):
            if stat.S_ISDIR(os.stat(name, dir_fd=folder, follow_symlinks=False).st_mode):
                slugs.append(name)
    return slugs


def _read_folder(parent: int, slug: str) -> FeatureFolder:
    try:
        folder = os.open(slug, _FOLDER_FLAGS, dir_fd=parent)
    except OSError:
        return FeatureFolder(slug=slug, files=())
    try:
        reads = {name: _read(folder, name) for name in RECORD_FILES}
    finally:
        os.close(folder)
    record = reads[RECORD]
    return FeatureFolder(
        slug=slug,
        files=tuple(name for name, read in reads.items() if isinstance(read, bytes)),
        features_json=_record(record),
        spec_head=_head(reads[SPEC]),
        eval_head=_head(reads[EVAL]),
    )


def _record(read: bytes | str | None) -> bytes | str | None:
    if isinstance(read, bytes) and len(read) > MAX_RECORD_BYTES:
        return f"larger than {MAX_RECORD_BYTES} bytes"
    return read


def _head(read: bytes | str | None) -> bytes | None:
    return read[:HEAD_BYTES] if isinstance(read, bytes) else None


def _read(folder: int, name: str) -> bytes | str | None:
    """The file's first bytes (one more than any bound), its problem, or None when absent."""
    try:
        descriptor = os.open(name, _FILE_FLAGS, dir_fd=folder)
    except FileNotFoundError:
        return None
    except OSError as error:
        # ELOOP: the name is a link, never followed.
        return (
            NOT_REGULAR if error.errno == errno.ELOOP else (error.strerror or type(error).__name__)
        )
    with open(descriptor, "rb") as opened:
        if not stat.S_ISREG(os.fstat(opened.fileno()).st_mode):
            return NOT_REGULAR
        return opened.read(max(MAX_RECORD_BYTES, HEAD_BYTES) + 1)
