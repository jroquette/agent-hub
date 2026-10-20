"""``HubDiscoveryFiles``: a hub's environment discoveries, one JSON file each (ADR 0043).

The folder is ``<hub>/.agent-runs/env-discoveries/``, made owner-only; a part of it that is a
link is refused, never followed. A new discovery's file is created exclusively (``O_EXCL``,
0600); a discard writes a temporary file beside it and renames it over the old one. A file that
is a link, over ``MAX_FILE_BYTES`` or not a record is skipped by the reads.
"""

import contextlib
import os
import re
import secrets
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from agent_hub.core.environment_discovery.discovery import (
    DISCOVERY_ID_PATTERN,
    DiscoveryRecord,
)
from agent_hub.core.json_form import InvalidJsonError, dump_json, load_json_bytes

FOLDER: Final = Path(".agent-runs", "env-discoveries")
MAX_FILE_BYTES: Final = 64 * 1024
MAX_FILES: Final = 500
_NEW_FILE: Final = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_READ_FILE: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
_DISCOVERY_ID: Final = re.compile(DISCOVERY_ID_PATTERN)


class DiscoveryFolderError(OSError):
    """The discoveries folder is not a plain folder of the hub."""


class HubDiscoveryFiles:
    """``DiscoveryRecords`` on the local file system."""

    def create(self, hub_path: str, record: DiscoveryRecord) -> None:
        """Create ``<id>.json``; ``FileExistsError`` when it exists."""
        folder = _made_folder(hub_path)
        descriptor = os.open(folder / _name(record.id), _NEW_FILE, 0o600)
        with os.fdopen(descriptor, "wb") as file:
            file.write(_bytes(record))

    def list(self, hub_path: str) -> tuple[DiscoveryRecord, ...]:
        """Every record that reads, at most ``MAX_FILES`` files by name."""
        folder = _existing_folder(hub_path)
        if folder is None:
            return ()
        names = sorted(path.name for path in folder.glob("*.json"))[:MAX_FILES]
        records = (_read(folder / name) for name in names)
        return tuple(record for record in records if record is not None)

    def get(self, hub_path: str, discovery_id: str) -> DiscoveryRecord | None:
        """One record, or None (unknown id, unreadable file)."""
        if _DISCOVERY_ID.fullmatch(discovery_id) is None:
            return None
        folder = _existing_folder(hub_path)
        if folder is None:
            return None
        record = _read(folder / _name(discovery_id))
        return record if record is not None and record.id == discovery_id else None

    def replace(self, hub_path: str, record: DiscoveryRecord) -> None:
        """Write ``record`` over its file: a temporary file, then a rename."""
        folder = _made_folder(hub_path)
        temporary = folder / f".{record.id}.{secrets.token_hex(4)}.tmp"
        descriptor = os.open(temporary, _NEW_FILE, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as file:
                file.write(_bytes(record))
            os.replace(temporary, folder / _name(record.id))
        except BaseException:
            with contextlib.suppress(OSError):
                temporary.unlink()
            raise


def _name(discovery_id: str) -> str:
    return f"{discovery_id}.json"


def _bytes(record: DiscoveryRecord) -> bytes:
    return dump_json(record.model_dump(mode="json"))


def _made_folder(hub_path: str) -> Path:
    """The discoveries folder, made owner-only where missing; a link is refused."""
    folder = Path(hub_path)
    for part in FOLDER.parts:
        folder = folder / part
        with contextlib.suppress(FileExistsError):
            folder.mkdir(mode=0o700)
        _refuse_link(folder)
    return folder


def _existing_folder(hub_path: str) -> Path | None:
    """The discoveries folder, None when absent; a link is refused."""
    folder = Path(hub_path)
    for part in FOLDER.parts:
        folder = folder / part
        if not folder.is_symlink() and not folder.exists():
            return None
        _refuse_link(folder)
    return folder


def _refuse_link(folder: Path) -> None:
    if folder.is_symlink() or not folder.is_dir():
        msg = f"{FOLDER} is not a folder of the hub"
        raise DiscoveryFolderError(msg)


def _read(path: Path) -> DiscoveryRecord | None:
    try:
        descriptor = os.open(path, _READ_FILE)
    except OSError:
        return None
    with os.fdopen(descriptor, "rb") as file:
        content = file.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        return None
    try:
        return DiscoveryRecord.model_validate(load_json_bytes(content, strict=True))
    except InvalidJsonError, ValidationError:
        return None
