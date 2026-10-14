"""Read an agent output and, for an eval output, its sibling and record (AGH-139 E12).

``hub validate-output`` reads through here. The output's folder is opened as a directory, then
every input is opened by name from a folder's descriptor with ``O_NOFOLLOW`` (``regular_files``):
the output itself, read up to ``MAX_OUTPUT_BYTES + 1`` bytes; for an eval output
``evals/<stem>.md`` beside it, its first ``EVAL_HEAD_BYTES``; and ``features.json`` in the parent
of the folder that actually holds the output (``..`` opened from that folder's descriptor), up to
``MAX_RECORD_BYTES + 1`` bytes. One byte over a bound is read so core can refuse the size.

Each read is the bytes, a one-line cause (a link, not a regular file, an OS error), or, for the
sibling and the record, None when absent. Nothing is written.
"""

import contextlib
import errno
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from agent_hub.core.features.feature_evals import EVAL_HEAD_BYTES
from agent_hub.core.features.feature_record import MAX_RECORD_BYTES
from agent_hub.core.features.output_models import MAX_OUTPUT_BYTES
from agent_hub.generator.regular_files import NOT_REGULAR, read_regular

NOT_READ_AS_REGULAR: Final = "not read as a regular file (links are never followed)"
RECORD_NAME: Final = "features.json"
_ABSENT: Final = os.strerror(errno.ENOENT)
_JSON_SUFFIX: Final = ".json"
_NOTE_SUFFIX: Final = ".md"
_FOLDER_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY


@dataclass(frozen=True, kw_only=True)
class EvalInputs:
    """What an eval output check reads: each the bytes, a cause, or None when absent.

    ``sibling_head`` and ``record`` are None too when ``content`` could not be read.
    """

    content: bytes | str
    sibling_head: bytes | str | None
    record: bytes | str | None


def read_output(path: Path) -> bytes | str:
    """The output's bytes (at most ``MAX_OUTPUT_BYTES + 1``) or the cause it was not read."""
    with _folder(path) as folder:
        if isinstance(folder, str):
            return folder
        return _content(folder, path.name)


def read_eval_inputs(path: Path) -> EvalInputs:
    """The eval output, its sibling's head and the feature record, read from the same folder."""
    with _folder(path) as folder:
        if isinstance(folder, str):
            return EvalInputs(content=folder, sibling_head=None, record=None)
        content = _content(folder, path.name)
        if isinstance(content, str):
            return EvalInputs(content=content, sibling_head=None, record=None)
        return EvalInputs(
            content=content, sibling_head=_sibling(folder, path.name), record=_record(folder)
        )


@contextlib.contextmanager
def _folder(path: Path) -> Iterator[int | str]:
    """The descriptor of the folder holding ``path``, or the cause it could not be opened."""
    try:
        descriptor = os.open(path.parent, _FOLDER_FLAGS)
    except OSError as error:
        yield _cause(error)
        return
    try:
        yield descriptor
    finally:
        os.close(descriptor)


def _content(folder: int, name: str) -> bytes | str:
    read = read_regular(folder, name, limit=MAX_OUTPUT_BYTES + 1)
    return _ABSENT if read is None else _shown(read)


def sibling_name(name: str) -> str | None:
    """The sibling record of the eval output ``<stem>.json``, ``<stem>.md``; else None."""
    stem = name.removesuffix(_JSON_SUFFIX)
    return None if stem == name else f"{stem}{_NOTE_SUFFIX}"


def _sibling(folder: int, name: str) -> bytes | str | None:
    """The head of the sibling record; None when the name has none or it is absent."""
    sibling = sibling_name(name)
    if sibling is None:
        return None
    read = read_regular(folder, sibling, limit=EVAL_HEAD_BYTES)
    return None if read is None else _shown(read)


def _record(folder: int) -> bytes | str | None:
    try:
        parent = os.open("..", _FOLDER_FLAGS, dir_fd=folder)
    except OSError as error:
        return _cause(error)
    try:
        read = read_regular(parent, RECORD_NAME, limit=MAX_RECORD_BYTES + 1)
    finally:
        os.close(parent)
    return None if read is None else _shown(read)


def _shown(read: bytes | str) -> bytes | str:
    return NOT_READ_AS_REGULAR if read == NOT_REGULAR else read


def _cause(error: OSError) -> str:
    return error.strerror or type(error).__name__
