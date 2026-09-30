"""Read ``hub.json`` into its bytes and config, or the problems that stop it.

This module reads the file; core's ``check_hub_document`` checks it, in the order of
docs/design/project-config.md § Versioning: the pin, then ``schema_version``, then the model.
The file is read once, as bytes, so a caller that copies it gets exactly what was checked.
``read_hub_bytes`` returns only the bytes read and ``read_hub_json`` the problems;
``load_hub_json_or_exit`` prints one line per problem and exits 1.
"""

import json
import os
import stat
from importlib.metadata import version
from pathlib import Path
from typing import NamedTuple, NoReturn

import typer

from agent_hub.core.hub_config.document_check import check_hub_document
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ROOT_PATH, ConfigProblem
from agent_hub.core.json_form import InvalidJsonError, JsonValue, load_json_bytes

# The installed release of the hub command, which a hub's pin must equal.
DISTRIBUTION = "agent-hub-cli"
FILE_LABEL = "hub.json"
# An invalid hub.json. Typer keeps 2 for usage errors.
FAILURE = 1
# O_NONBLOCK: a FIFO swapped in after the check cannot block the open; fstat then refuses it.
# No O_NOFOLLOW: a link to a regular file is read, as it always was.
_OPEN_FLAGS = os.O_RDONLY | os.O_NONBLOCK


class LoadedHubJson(NamedTuple):
    """The bytes of a ``hub.json`` exactly as read, and the config they hold."""

    content: bytes
    config: HubConfig


class _Unread(NamedTuple):
    # Why the file could not be read, and whether it was absent (the exiting reader's hint).
    problem: ConfigProblem
    is_missing: bool


def read_hub_json(path: Path) -> LoadedHubJson | tuple[ConfigProblem, ...]:
    """The bytes and validated config in ``path``, or the problems that stop its use.

    Tell the two apart with ``isinstance(result, LoadedHubJson)``: a NamedTuple is a tuple too.
    """
    loaded = _load(path)
    return (loaded.problem,) if isinstance(loaded, _Unread) else loaded


def read_hub_bytes(path: Path) -> bytes | tuple[ConfigProblem, ...]:
    """The bytes in ``path`` as read, or the problem that stopped the read; nothing is checked."""
    content = _read_bytes(path)
    return (content.problem,) if isinstance(content, _Unread) else content


def load_hub_json_or_exit(path: Path, *, missing_hint: str | None = None) -> LoadedHubJson:
    """The bytes and validated config in ``path``; on any problem, print its lines and exit 1.

    When ``path`` does not exist and ``missing_hint`` is given, the hint is one more line.
    """
    loaded = _load(path)
    if isinstance(loaded, _Unread):
        _fail(loaded.problem, hint=missing_hint if loaded.is_missing else None)
    if not isinstance(loaded, LoadedHubJson):
        _fail(*loaded)
    return loaded


def load_hub_config_or_exit(path: Path) -> HubConfig:
    """The validated config in ``path``; on any problem, print its lines to stderr and exit 1."""
    return load_hub_json_or_exit(path).config


def _load(path: Path) -> LoadedHubJson | _Unread | tuple[ConfigProblem, ...]:
    content = _read_bytes(path)
    if isinstance(content, _Unread):
        return content
    parsed = _parse(content)
    if isinstance(parsed, ConfigProblem):
        return (parsed,)
    checked = check_hub_document(parsed, running_version=version(DISTRIBUTION))
    if not isinstance(checked, HubConfig):
        return checked
    return LoadedHubJson(content=content, config=checked)


def _read_bytes(path: Path) -> bytes | _Unread:
    # The path is quoted and escaped, so it stays on the one line.
    shown_path = json.dumps(str(path))
    not_regular = _Unread(
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
            if not stat.S_ISREG(os.fstat(opened.fileno()).st_mode):
                return not_regular
            return opened.read()
    except OSError as error:
        reason = error.strerror or type(error).__name__
        return _Unread(
            ConfigProblem(ROOT_PATH, f"cannot read {shown_path}: {reason}"),
            is_missing=isinstance(error, FileNotFoundError),
        )


def _parse(content: bytes) -> JsonValue | ConfigProblem:
    # Core parses the bytes; each problem it names is one line at the root.
    try:
        return load_json_bytes(content)
    except InvalidJsonError as error:
        return ConfigProblem(ROOT_PATH, error.message)


def _fail(*problems: ConfigProblem, hint: str | None = None) -> NoReturn:
    # Each problem is built on one line: text from the file is escaped where it is quoted.
    for problem in problems:
        typer.echo(f"{FILE_LABEL}: {problem.path}: {problem.message}", err=True)
    if hint is not None:
        typer.echo(f"{FILE_LABEL}: {hint}", err=True)
    raise typer.Exit(FAILURE)
