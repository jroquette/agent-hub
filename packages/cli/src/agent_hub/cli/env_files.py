"""Write ``hub.json`` or ``hub.local.json`` for ``hub env``: only over the bytes it read.

A document is written in one form, its keys in the file's order, indented 2, UTF-8 and not
escaped, with a final newline (``document_bytes``). Before the write the file is read again and
compared with the bytes the command read: a file changed (or created) meanwhile is refused and
left as it is. The new bytes go to a temp file in the same folder, at the file's mode, then
``os.replace`` gives them the name, so the name never holds a partial write; a writer between the
check and the replace is overwritten (a narrow window, docs/design/environments.md). A file
that was absent is created with ``write_exclusive``, which never replaces one that appeared.
"""

import contextlib
import json
import os
import secrets
import stat
from pathlib import Path
from typing import Final

from agent_hub.cli.exclusive_write import TEMP_INFIX, sync_folder, write_exclusive
from agent_hub.core.json_form import InvalidJsonError, JsonValue, load_json_bytes
from agent_hub.generator.hub_config_files import UnreadFile, read_file_bytes

CHANGED_MESSAGE: Final = "{file} changed since it was read; run the command again"
_TEMP_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC


def document_bytes(document: JsonValue) -> bytes:
    """``document`` in ``hub env``'s form: the given key order, indent 2, one final newline."""
    text = json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False)
    return (text + "\n").encode("utf-8")


def is_reformatted(content: bytes) -> bool:
    """Whether writing ``content``'s document unchanged would give other bytes (Q-9)."""
    try:
        return document_bytes(load_json_bytes(content)) != content
    except InvalidJsonError:
        return True


def write_document(path: Path, *, read: bytes | None, content: bytes) -> str | None:
    """Write ``content`` as ``path`` when it still holds ``read`` (``None``: it was absent).

    ``None`` when written, else the one line that says why not; the file is then unchanged.
    An ``OSError``'s own text names paths, so the line shows only its reason.
    """
    changed = CHANGED_MESSAGE.format(file=path.name)
    found = read_file_bytes(path)
    current: bytes | None = None
    if isinstance(found, UnreadFile):
        if not found.is_missing:
            return f"{path.name}: {found.problem.message}"
    else:
        current = found
    if current != read:
        return changed
    try:
        if read is None:
            return None if write_exclusive(path.parent, path.name, content) else changed
        _replace(path, content)
    except OSError as error:
        return f"{path.name}: cannot write: {error.strerror or type(error).__name__}"
    return None


def _replace(path: Path, content: bytes) -> None:
    mode = stat.S_IMODE(os.stat(path).st_mode)
    temp = path.parent / f".{path.name}{TEMP_INFIX}{secrets.token_hex(4)}"
    descriptor = os.open(temp, _TEMP_FLAGS, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as file:
            os.fchmod(file.fileno(), mode)
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(temp)
        raise
    sync_folder(path.parent)
