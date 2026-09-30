"""Load ``hub.json`` for a command, or print one line per problem and exit 1.

This module reads the file and prints; core's ``check_hub_document`` checks it, in the order of
docs/design/project-config.md § Versioning: the pin, then ``schema_version``, then the model.
The file is read once, as bytes, so a caller that copies it gets exactly what was checked.
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


def load_hub_json_or_exit(path: Path) -> LoadedHubJson:
    """The bytes and validated config in ``path``; on any problem, print its lines and exit 1."""
    content = _read_bytes_or_exit(path)
    checked = check_hub_document(_parse_or_exit(content), running_version=version(DISTRIBUTION))
    if not isinstance(checked, HubConfig):
        _fail(*checked)
    return LoadedHubJson(content=content, config=checked)


def load_hub_config_or_exit(path: Path) -> HubConfig:
    """The validated config in ``path``; on any problem, print its lines to stderr and exit 1."""
    return load_hub_json_or_exit(path).config


def _read_bytes_or_exit(path: Path) -> bytes:
    # The path is quoted and escaped, so it stays on the one line.
    shown_path = json.dumps(str(path))
    not_regular = ConfigProblem(ROOT_PATH, f"cannot read {shown_path}: not a regular file")
    # Opening a FIFO waits for a writer and a device can be endless: only a regular file is read,
    # so a FIFO found here is never opened. A path that does not exist is left to the open, which
    # names the reason.
    if path.exists() and not path.is_file():
        _fail(not_regular)
    try:
        descriptor = os.open(path, _OPEN_FLAGS)
        # What was opened is what gets read: a swap after the check above fails here instead.
        with open(descriptor, "rb") as opened:
            if not stat.S_ISREG(os.fstat(opened.fileno()).st_mode):
                _fail(not_regular)
            return opened.read()
    except OSError as error:
        reason = error.strerror or type(error).__name__
        _fail(ConfigProblem(ROOT_PATH, f"cannot read {shown_path}: {reason}"))


def _parse_or_exit(content: bytes) -> JsonValue:
    # Core parses the bytes; each problem it names is one line at the root.
    try:
        return load_json_bytes(content)
    except InvalidJsonError as error:
        _fail(ConfigProblem(ROOT_PATH, error.message))


def _fail(*problems: ConfigProblem) -> NoReturn:
    # Each problem is built on one line: text from the file is escaped where it is quoted.
    for problem in problems:
        typer.echo(f"{FILE_LABEL}: {problem.path}: {problem.message}", err=True)
    raise typer.Exit(FAILURE)
