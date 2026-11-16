"""``FileStartLedger``: each hub's ledger of scheduled starts, under ``.agent-runs/schedules/``.

``state.json`` (ADR 0048) holds the last slot started per workflow and the event ids seen per
source. Every change runs under an exclusive, non-blocking ``flock`` on ``state.lock`` (held: the
hub is busy, ``StartLedgerBusyError``), so two ``hub web`` processes never start one slot or event
twice. The state is read without following a link, up to ``MAX_LEDGER_BYTES``, and validated; a file
that is unreadable, too large or invalid raises ``StartLedgerError`` and is never overwritten. A new
state is written to an owner-only temp file in the same folder (``O_EXCL``), synced, then renamed
over ``state.json``, so a reader never sees half a file. The folder is owner-only too.
"""

import contextlib
import fcntl
import os
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from agent_hub.core.schedules.scheduled_starts import (
    StartLedgerBusyError,
    StartLedgerError,
    StartState,
)

LEDGER_FOLDER: Final = (".agent-runs", "schedules")
STATE_FILE: Final = "state.json"
LOCK_FILE: Final = "state.lock"
MAX_LEDGER_BYTES: Final = 1_048_576
_NO_LINK: Final = os.O_NOFOLLOW | os.O_CLOEXEC
_UNREADABLE: Final = "the schedule ledger cannot be read"


class FileStartLedger:
    """``StartLedger`` over files in each hub (see the module docstring)."""

    def update[R](self, hub_path: str, change: Callable[[StartState], tuple[StartState, R]]) -> R:
        folder = Path(hub_path, *LEDGER_FOLDER)
        with _locked(folder):
            state = _read(folder / STATE_FILE)
            new, result = change(state)
            if new != state:
                _write(folder, new)
            return result


@contextlib.contextmanager
def _locked(folder: Path) -> Iterator[None]:
    try:
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        handle = os.open(folder / LOCK_FILE, os.O_RDWR | os.O_CREAT | _NO_LINK, 0o600)
    except OSError:
        raise StartLedgerError("the schedule ledger's lock cannot be opened") from None
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise StartLedgerBusyError("another process holds the schedule ledger") from None
        yield
    finally:
        # Closing the descriptor releases the lock.
        os.close(handle)


def _read(path: Path) -> StartState:
    try:
        handle = os.open(path, os.O_RDONLY | _NO_LINK)
    except FileNotFoundError:
        return StartState()
    except OSError:
        raise StartLedgerError(_UNREADABLE) from None
    try:
        with os.fdopen(handle, "rb") as stream:
            raw = stream.read(MAX_LEDGER_BYTES + 1)
    except OSError:
        raise StartLedgerError(_UNREADABLE) from None
    if len(raw) > MAX_LEDGER_BYTES:
        raise StartLedgerError(f"the schedule ledger is larger than {MAX_LEDGER_BYTES} bytes")
    try:
        return StartState.model_validate_json(raw)
    except ValidationError:
        raise StartLedgerError("the schedule ledger is not valid; fix or remove it") from None


def _write(folder: Path, state: StartState) -> None:
    temporary = folder / f".state.{uuid.uuid4().hex}.tmp"
    try:
        handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NO_LINK, 0o600)
        with os.fdopen(handle, "wb") as stream:
            stream.write(state.model_dump_json().encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, folder / STATE_FILE)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise StartLedgerError("the schedule ledger cannot be written") from None
