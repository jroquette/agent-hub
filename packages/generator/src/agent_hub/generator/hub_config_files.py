"""Read ``hub.json`` and ``hub.local.json`` into their bytes and configs, or the problems that stop
them, without exiting.

This module reads the files; core's ``check_hub_document`` checks ``hub.json``, in the order of
docs/design/project-config.md § Versioning: the pin, then ``schema_version``, then the model.
The file is read once, as bytes, so a caller that copies it gets exactly what was checked.
``read_hub_bytes`` returns only the bytes read and ``read_hub_json`` the problems;
``load_hub_document`` also tells an absent file apart, for a caller that adds a hint.
``read_local_json`` reads the developer's ``hub.local.json`` the same way, capped at
``LOCAL_FILE_MAX_BYTES``; an absent one sets nothing. The cli's ``hub_config_reader`` re-exports
these and adds the readers that print and exit; the control plane reads registered hubs here.
"""

import json
import os
import stat
from pathlib import Path
from typing import NamedTuple

from agent_hub.core.hub_config.document_check import check_hub_document
from agent_hub.core.hub_config.local_config import (
    LOCAL_FILE_MAX_BYTES,
    LocalConfig,
    check_local_document,
)
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ROOT_PATH, ConfigProblem
from agent_hub.core.json_form import InvalidJsonError, JsonValue, load_json_bytes

# O_NONBLOCK: a FIFO swapped in after the check cannot block the open; fstat then refuses it.
# No O_NOFOLLOW: a link to a regular file is read, as it always was.
_OPEN_FLAGS = os.O_RDONLY | os.O_NONBLOCK


class LoadedHubJson(NamedTuple):
    """The bytes of a ``hub.json`` exactly as read, and the config they hold."""

    content: bytes
    config: HubConfig


class UnreadFile(NamedTuple):
    """Why a file could not be read, and whether it was absent (a caller's hint)."""

    problem: ConfigProblem
    is_missing: bool


def read_hub_json(path: Path, *, running_version: str) -> LoadedHubJson | tuple[ConfigProblem, ...]:
    """The bytes and validated config in ``path``, or the problems that stop its use.

    The pin must equal ``running_version``. Tell the two apart with
    ``isinstance(result, LoadedHubJson)``: a NamedTuple is a tuple too.
    """
    loaded = load_hub_document(path, running_version=running_version)
    return (loaded.problem,) if isinstance(loaded, UnreadFile) else loaded


def read_hub_bytes(path: Path) -> bytes | tuple[ConfigProblem, ...]:
    """The bytes in ``path`` as read, or the problem that stopped the read; nothing is checked."""
    content = read_file_bytes(path)
    return (content.problem,) if isinstance(content, UnreadFile) else content


def load_hub_document(
    path: Path, *, running_version: str
) -> LoadedHubJson | UnreadFile | tuple[ConfigProblem, ...]:
    """The bytes and config in ``path``, why it was not read, or the problems of its content."""
    content = read_file_bytes(path)
    if isinstance(content, UnreadFile):
        return content
    parsed = parse_json(content)
    if isinstance(parsed, ConfigProblem):
        return (parsed,)
    checked = check_hub_document(parsed, running_version=running_version)
    if not isinstance(checked, HubConfig):
        return checked
    return LoadedHubJson(content=content, config=checked)


def read_local_json(path: Path) -> LocalConfig | tuple[ConfigProblem, ...]:
    """The developer's local config in ``path``, ``LocalConfig()`` when absent, or its problems.

    Read as ``hub.json`` is (a regular file only, never blocking on a FIFO), up to
    ``LOCAL_FILE_MAX_BYTES``.
    """
    content = read_file_bytes(path, max_bytes=LOCAL_FILE_MAX_BYTES)
    if isinstance(content, UnreadFile):
        return LocalConfig() if content.is_missing else (content.problem,)
    parsed = parse_json(content)
    if isinstance(parsed, ConfigProblem):
        return (parsed,)
    return check_local_document(parsed)


def read_file_bytes(path: Path, *, max_bytes: int | None = None) -> bytes | UnreadFile:
    """The bytes of the regular file at ``path``, up to ``max_bytes`` when given, or why not."""
    # The path is quoted and escaped, so it stays on the one line.
    shown_path = json.dumps(str(path))
    too_large = UnreadFile(
        ConfigProblem(ROOT_PATH, f"cannot read {shown_path}: larger than {max_bytes} bytes"),
        is_missing=False,
    )
    not_regular = UnreadFile(
        ConfigProblem(ROOT_PATH, f"cannot read {shown_path}: not a regular file"), is_missing=False
    )
    # Opening a FIFO waits for a writer and a device can be endless: only a regular file is read,
    # so a FIFO found here is never opened. A path that does not exist is left to the open, which
    # names the reason.
    if path.exists() and not path.is_file():
        return not_regular
    try:
        descriptor = os.open(path, _OPEN_FLAGS)
        # What was opened is what gets read: a swap after the check above fails here instead.
        with open(descriptor, "rb") as opened:
            found = os.fstat(opened.fileno())
            if not stat.S_ISREG(found.st_mode):
                return not_regular
            if max_bytes is None:
                return opened.read()
            if found.st_size > max_bytes:
                return too_large
            # One byte more than allowed tells a file that grew after the fstat.
            content = opened.read(max_bytes + 1)
            return too_large if len(content) > max_bytes else content
    except OSError as error:
        reason = error.strerror or type(error).__name__
        return UnreadFile(
            ConfigProblem(ROOT_PATH, f"cannot read {shown_path}: {reason}"),
            is_missing=isinstance(error, FileNotFoundError),
        )


def parse_json(content: bytes) -> JsonValue | ConfigProblem:
    """The parsed document, or core's problem with it as one line at the root."""
    try:
        return load_json_bytes(content)
    except InvalidJsonError as error:
        return ConfigProblem(ROOT_PATH, error.message)
