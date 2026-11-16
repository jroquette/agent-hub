"""``hubs.json``, the hub registry of the control plane (D18), as a ``HubRegistry``.

The caller resolves the file's location (``$XDG_CONFIG_HOME/agent-hub/hubs.json`` or
``~/.config/agent-hub/hubs.json``). The file is ``{"hubs": [{id, path, added_at}]}``: read as a
regular file only (no link followed, a FIFO never blocks), at most ``MAX_REGISTRY_BYTES`` and
``MAX_HUBS`` hubs; written whole to a temporary file in the same folder (mode 0600), then put in
place with ``os.replace``, so a reader sees the old file or the new one. A folder created here is
0700. Any failure raises ``HubRegistryError`` naming the file and the reason on one line.
"""

import contextlib
import json
import os
import stat
import tempfile
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_hub.core.hub_config.problems import one_line
from agent_hub.core.hubs.hub_registry import (
    MAX_HUBS,
    HubConflictError,
    HubRegistryError,
    to_milliseconds,
)
from agent_hub.core.hubs.registered_hub import RegisteredHub
from agent_hub.core.json_form import InvalidJsonError, dump_json, load_json_bytes
from agent_hub.core.readmodels.read_ports import EntityNotFoundError

MAX_REGISTRY_BYTES: Final = 1_048_576
_OPEN_FLAGS: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
_FOLDER_MODE: Final = 0o700


class _RegistryFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    hubs: tuple[RegisteredHub, ...] = Field(default=(), max_length=MAX_HUBS)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class JsonHubRegistry:
    """The registry kept in one JSON file; one writer at a time within the process."""

    def __init__(self, path: Path, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self._path = path
        self._clock = clock
        self._lock = threading.Lock()

    def entries(self) -> tuple[RegisteredHub, ...]:
        """Every registered hub, in registration order; none when the file is absent."""
        return self._read().hubs

    def add(self, path: str) -> RegisteredHub:
        """Register ``path`` with a new UUIDv7 id."""
        with self._lock:
            hubs = self._read().hubs
            if any(entry.path == path for entry in hubs):
                msg = f"hub {path!r} is registered already"
                raise HubConflictError(msg)
            if len(hubs) >= MAX_HUBS:
                raise self._error(f"holds {MAX_HUBS} hubs already, the most it keeps")
            entry = RegisteredHub(
                id=str(uuid.uuid7()), path=path, added_at=to_milliseconds(self._clock())
            )
            self._write((*hubs, entry))
            return entry

    def remove(self, hub_id: str) -> None:
        """Forget the hub with ``hub_id``."""
        with self._lock:
            hubs = self._read().hubs
            kept = tuple(entry for entry in hubs if entry.id != hub_id)
            if len(kept) == len(hubs):
                raise EntityNotFoundError(entity="hub", entity_id=hub_id)
            self._write(kept)

    def _read(self) -> _RegistryFile:
        content = self._read_bytes()
        if content is None:
            return _RegistryFile()
        try:
            return _RegistryFile.model_validate(load_json_bytes(content))
        except InvalidJsonError as error:
            raise self._error(error.message) from None
        except ValidationError as error:
            first = error.errors()[0]
            where = ".".join(str(part) for part in first["loc"])
            raise self._error(f"{where}: {first['msg']}") from None

    def _read_bytes(self) -> bytes | None:
        try:
            descriptor = os.open(self._path, _OPEN_FLAGS)
        except FileNotFoundError:
            return None
        except OSError as error:
            raise self._error(f"cannot read: {_reason(error)}") from None
        with open(descriptor, "rb") as opened:
            found = os.fstat(opened.fileno())
            if not stat.S_ISREG(found.st_mode):
                raise self._error("not a regular file")
            content = opened.read(MAX_REGISTRY_BYTES + 1)
        if len(content) > MAX_REGISTRY_BYTES:
            raise self._error(f"larger than {MAX_REGISTRY_BYTES} bytes")
        return content

    def _write(self, hubs: tuple[RegisteredHub, ...]) -> None:
        content = dump_json(json.loads(_RegistryFile(hubs=hubs).model_dump_json()))
        folder = self._path.parent
        temporary: str | None = None
        try:
            folder.mkdir(mode=_FOLDER_MODE, parents=True, exist_ok=True)
            # mkstemp creates the file 0600, so the registry is never readable by others.
            descriptor, temporary = tempfile.mkstemp(dir=folder, prefix=".hubs.", suffix=".tmp")
            with open(descriptor, "wb") as written:
                written.write(content)
                written.flush()
                os.fsync(written.fileno())
            os.replace(temporary, self._path)
            temporary = None
        except OSError as error:
            raise self._error(f"cannot write: {_reason(error)}") from None
        finally:
            if temporary is not None:
                with contextlib.suppress(OSError):
                    os.unlink(temporary)

    def _error(self, reason: str) -> HubRegistryError:
        return HubRegistryError(one_line(f"hub registry {json.dumps(str(self._path))}: {reason}"))


def _reason(error: OSError) -> str:
    return error.strerror or type(error).__name__
