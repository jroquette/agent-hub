"""``PUT /projects/{project}/config/local``: the Hub config screen's "Edit my local settings".

It rewrites the keys the screen edits in the hub's ``hub.local.json`` (the developer's identity,
tracker transport and own blocked entries) and keeps every other key the file holds
(environments, repo services, ``_`` comments). The result is checked with the model the CLI
reads the file with before anything is written, so the screen cannot save a file every command
would refuse; an empty result removes the file. Never committed: the file is per developer.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_hub.core.hub_config.local_config import (
    LOCAL_FILE,
    LOCAL_FILE_MAX_BYTES,
    LocalConfig,
    check_local_document,
)
from agent_hub.core.hubs.hub_registry import HubInvalidError
from agent_hub.core.hubs.registered_hub import ValidationProblem

INVALID_TITLE: Final = "These local settings are not valid"
_IDENTITY = ("branch_prefix", "author_name", "author_email")
_BLOCKED = ("blocked_words", "blocked_words_files", "blocked_words_env")
_MAX_ITEMS = 200
_MAX_TEXT = 200


class LocalSettings(BaseModel):
    """What the screen edits; an empty text or ``None`` removes the key from the file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    branch_prefix: str | None = Field(default=None, max_length=_MAX_TEXT)
    author_name: str | None = Field(default=None, max_length=_MAX_TEXT)
    author_email: str | None = Field(default=None, max_length=_MAX_TEXT)
    transport: Literal["api", "mcp"] | None = None
    blocked_words: tuple[str, ...] = Field(default=(), max_length=_MAX_ITEMS)
    blocked_words_files: tuple[str, ...] = Field(default=(), max_length=_MAX_ITEMS)
    blocked_words_env: tuple[str, ...] = Field(default=(), max_length=_MAX_ITEMS)


def write_local_settings(hub_path: str, settings: LocalSettings) -> None:
    """Merge ``settings`` into ``hub.local.json``; ``HubInvalidError`` (422) when invalid."""
    path = Path(hub_path, LOCAL_FILE)
    document = _read(path)
    project = _object(document, "project")
    for key in _IDENTITY:
        value = getattr(settings, key)
        _set(project, key, value.strip() if isinstance(value, str) else None)
    tracker = _object(document, "tracker")
    _set(tracker, "transport", settings.transport)
    guard = _object(document, "guard")
    for key in _BLOCKED:
        items = [item.strip() for item in getattr(settings, key) if item.strip()]
        _set(guard, key, list(dict.fromkeys(items)) or None)
    for key, section in (("project", project), ("tracker", tracker), ("guard", guard)):
        _set(document, key, section or None)
    checked = check_local_document(document)
    if not isinstance(checked, LocalConfig):
        raise HubInvalidError(
            INVALID_TITLE,
            problems=tuple(_problem(problem.path, problem.message) for problem in checked),
        )
    if not document:
        path.unlink(missing_ok=True)
        return
    content = (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode()
    if len(content) > LOCAL_FILE_MAX_BYTES:
        raise HubInvalidError(
            INVALID_TITLE, problems=(_problem("$", "the file would be too large"),)
        )
    _replace(path, content)


def _problem(pointer: str, message: str) -> ValidationProblem:
    return ValidationProblem(pointer=pointer, message=message)


def _read(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {}
    try:
        document = json.loads(raw)
    except ValueError as error:
        raise HubInvalidError(
            "hub.local.json is not valid JSON",
            problems=(_problem("$", "fix or remove the file first"),),
        ) from error
    if not isinstance(document, dict):
        raise HubInvalidError(INVALID_TITLE, problems=(_problem("$", "must be a JSON object"),))
    return document


def _object(document: dict[str, Any], key: str) -> dict[str, Any]:
    value = document.get(key)
    return dict(value) if isinstance(value, dict) else {}


def _set(target: dict[str, Any], key: str, value: object) -> None:
    if value is None or value == "":
        target.pop(key, None)
    else:
        target[key] = value


def _replace(path: Path, content: bytes) -> None:
    """Write next to the file, then rename over it, so a reader never sees half a file."""
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".hub.local.", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
