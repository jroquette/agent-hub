"""The hook sensor's spool: the envelopes ``hub web`` did not take, read back for an import.

The sensor (``event_sensor.py``) appends each envelope the server did not take, the exact POST
body, as one line to ``SPOOL_FILE`` in the spool folder, while it holds an ``flock`` on
``LOCK_FILE``; a trim leaves a first line ``{"dropped": n}``. ``HookSpool.take`` moves the spool
aside under the same lock, to ``TAKEN_FILE`` (appended to it when an earlier take was never
removed), so the sensor starts a new spool, then parses every line of it (``parse_spool``). The
importer stores the events, then ``remove`` deletes the taken file, only when it is still the one
read (same device, inode and size): a crash in between leaves it, the next take reads it again,
and the store counts what it already holds as duplicates.

The folder and each file are opened by name without following a link (``O_NOFOLLOW``) and must be
this user's: a folder, and regular files of at most ``max_bytes``. Anything else raises
``HookSpoolError``. A missing folder or nothing spooled is ``None``.
"""

import fcntl
import json
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, ValidationError

from agent_hub.collector.errors import CollectorError
from agent_hub.collector.jsonl import (
    NESTED_TOO_DEEPLY,
    LineError,
    LineRejectedError,
    bounded_reason,
    json_object,
    validation_reason,
)
from agent_hub.core.ingestion.hook_envelope import (
    MAX_BODY_BYTES,
    MAX_JSON_DEPTH,
    HookEnvelope,
    json_depth_exceeds,
)

SPOOL_FILE: Final = "hook-spool.jsonl"
LOCK_FILE: Final = "hook-spool.lock"
TAKEN_FILE: Final = "hook-spool.taken.jsonl"
# The sensor keeps its spool under 8 MiB; a taken file grows past that only while imports fail.
MAX_TAKEN_BYTES: Final = 64 * 1_048_576
_FOLDER_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
# O_NONBLOCK: a FIFO swapped in cannot block the open; fstat then refuses it.
_FILE_FLAGS: Final = os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_READ_CHUNK: Final = 1_048_576


class HookSpoolError(CollectorError):
    """The spool folder or one of its files cannot be used (a link, not this user's, too large)."""


class SpooledEnvelope(BaseModel):
    """A valid envelope and the 1-based line it came from."""

    model_config = ConfigDict(frozen=True)

    line_number: int
    envelope: HookEnvelope


class SpoolLines(BaseModel):
    """What a spool holds: its envelopes in order, one error per bad line, the lines dropped."""

    model_config = ConfigDict(frozen=True)

    envelopes: tuple[SpooledEnvelope, ...]
    errors: tuple[LineError, ...]
    dropped: int


class TakenSpool(BaseModel):
    """A take's lines, and the taken file as it was read (for ``HookSpool.remove``)."""

    model_config = ConfigDict(frozen=True)

    lines: SpoolLines
    device: int
    inode: int
    size: int


def parse_spool(data: bytes) -> SpoolLines:
    """Every line of ``data``: an envelope, a count ``{"dropped": n}`` or an error.

    Blank lines are skipped but still count for line numbers; only ``\\n`` ends a line. A line
    over ``MAX_BODY_BYTES`` (more than the sensor ever sends) is an error, as is one that the
    live route would refuse: nested deeper than ``MAX_JSON_DEPTH``, or not an envelope.
    """
    envelopes: list[SpooledEnvelope] = []
    errors: list[LineError] = []
    dropped = 0
    for line_number, line in enumerate(data.split(b"\n"), start=1):
        if not line.strip():
            continue
        try:
            value = _line_value(line)
        except LineRejectedError as error:
            errors.append(LineError(line_number=line_number, reason=bounded_reason(str(error))))
            continue
        if isinstance(value, int):
            dropped += value
        else:
            envelopes.append(SpooledEnvelope(line_number=line_number, envelope=value))
    return SpoolLines(envelopes=tuple(envelopes), errors=tuple(errors), dropped=dropped)


def _line_value(line: bytes) -> HookEnvelope | int:
    if len(line) > MAX_BODY_BYTES:
        msg = f"longer than {MAX_BODY_BYTES} bytes"
        raise LineRejectedError(msg)
    if json_depth_exceeds(line):
        msg = f"nested deeper than {MAX_JSON_DEPTH} levels"
        raise LineRejectedError(msg)
    try:
        text = line.decode("utf-8")
    except UnicodeDecodeError as error:
        msg = f"not valid UTF-8 (byte {error.start})"
        raise LineRejectedError(msg) from error
    value = json_object(text)
    count = value.get("dropped")
    if len(value) == 1 and type(count) is int and count >= 0:
        return count
    try:
        return HookEnvelope.model_validate(value)
    except ValidationError as error:
        raise LineRejectedError(validation_reason(error)) from error
    except RecursionError as error:
        raise LineRejectedError(NESTED_TOO_DEEPLY) from error


class HookSpool:
    """The sensor's spool in ``folder`` (see the module docstring)."""

    def __init__(self, folder: Path, *, max_bytes: int = MAX_TAKEN_BYTES) -> None:
        self._folder = folder
        self._max_bytes = max_bytes

    def take(self) -> TakenSpool | None:
        """What was spooled and not yet removed, parsed; None when nothing was."""
        directory = self._open_folder()
        if directory is None:
            return None
        try:
            with _locked(directory):
                self._move_spool(directory)
            return self._read_taken(directory)
        except OSError as error:
            raise HookSpoolError(_cannot_use(self._folder, error)) from error
        finally:
            os.close(directory)

    def remove(self, taken: TakenSpool) -> None:
        """Delete the taken file when it is still the one ``taken`` read; else leave it."""
        directory = self._open_folder()
        if directory is None:
            return
        try:
            with _locked(directory):
                info = _stat_of(directory, TAKEN_FILE)
                if info is not None and _identity(info) == (taken.device, taken.inode, taken.size):
                    os.unlink(TAKEN_FILE, dir_fd=directory)
        except OSError as error:
            raise HookSpoolError(_cannot_use(self._folder, error)) from error
        finally:
            os.close(directory)

    def _open_folder(self) -> int | None:
        try:
            directory = os.open(self._folder, _FOLDER_FLAGS)
        except FileNotFoundError:
            return None
        except OSError as error:
            msg = f"cannot open {_quoted(self._folder)}: {error.strerror or error}"
            raise HookSpoolError(msg) from error
        info = os.fstat(directory)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            os.close(directory)
            msg = f"cannot open {_quoted(self._folder)}: not a folder of this user"
            raise HookSpoolError(msg)
        return directory

    def _move_spool(self, directory: int) -> None:
        """The spool renamed to the taken file, or appended to it when one is left."""
        info = _stat_of(directory, SPOOL_FILE)
        if info is None:
            return
        self._check_file(SPOOL_FILE, info)
        if _stat_of(directory, TAKEN_FILE) is None:
            os.rename(SPOOL_FILE, TAKEN_FILE, src_dir_fd=directory, dst_dir_fd=directory)
            return
        data = self._read(directory, SPOOL_FILE)
        taken = os.open(TAKEN_FILE, os.O_WRONLY | os.O_APPEND | _FILE_FLAGS, dir_fd=directory)
        try:
            self._check_file(TAKEN_FILE, os.fstat(taken))
            _write_all(taken, data)
        finally:
            os.close(taken)
        os.unlink(SPOOL_FILE, dir_fd=directory)

    def _read_taken(self, directory: int) -> TakenSpool | None:
        try:
            descriptor = os.open(TAKEN_FILE, os.O_RDONLY | _FILE_FLAGS, dir_fd=directory)
        except FileNotFoundError:
            return None
        try:
            info = os.fstat(descriptor)
            self._check_file(TAKEN_FILE, info)
            data = _read_all(descriptor)
        finally:
            os.close(descriptor)
        device, inode, size = _identity(info)
        return TakenSpool(lines=parse_spool(data), device=device, inode=inode, size=size)

    def _read(self, directory: int, name: str) -> bytes:
        descriptor = os.open(name, os.O_RDONLY | _FILE_FLAGS, dir_fd=directory)
        try:
            self._check_file(name, os.fstat(descriptor))
            return _read_all(descriptor)
        finally:
            os.close(descriptor)

    def _check_file(self, name: str, info: os.stat_result) -> None:
        quoted = _quoted(self._folder / name)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            msg = f"cannot read {quoted}: not a regular file of this user"
            raise HookSpoolError(msg)
        if info.st_size > self._max_bytes:
            msg = f"cannot read {quoted}: larger than {self._max_bytes} bytes"
            raise HookSpoolError(msg)


@contextmanager
def _locked(directory: int) -> Iterator[None]:
    """The spool's lock, held as the sensor holds it while it writes; closing releases it."""
    lock = os.open(LOCK_FILE, os.O_RDWR | os.O_CREAT | _FILE_FLAGS, 0o600, dir_fd=directory)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield
    finally:
        os.close(lock)


def _stat_of(directory: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _identity(info: os.stat_result) -> tuple[int, int, int]:
    return info.st_dev, info.st_ino, info.st_size


def _read_all(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    while chunk := os.read(descriptor, _READ_CHUNK):
        chunks.append(chunk)
    return b"".join(chunks)


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(descriptor, view) :]


def _cannot_use(folder: Path, error: OSError) -> str:
    return f"cannot use {_quoted(folder)}: {error.strerror or error}"


def _quoted(path: Path) -> str:
    # The path comes from the environment: quoted and escaped, so a message stays on one line.
    return json.dumps(str(path))
