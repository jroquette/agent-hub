"""Read ``hub.json`` into its bytes and config, or the problems that stop it, for the installed
``hub``.

The readers that do not exit live in ``agent_hub.generator.hub_config_files`` (the control plane
reads registered hubs with them too) and are re-exported here: ``read_hub_bytes``,
``read_local_json``, and ``read_hub_json``, whose pin is checked against the installed release.
``load_hub_json_or_exit`` prints one line per problem and exits 1; ``local_lines`` gives the
lines of ``hub.local.json``'s problems.
"""

from importlib.metadata import version
from pathlib import Path
from typing import NoReturn

import typer

from agent_hub.core.hub_config.local_config import LOCAL_FILE
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ConfigProblem
from agent_hub.generator import hub_config_files
from agent_hub.generator.hub_config_files import (
    LoadedHubJson,
    UnreadFile,
    load_hub_document,
    read_hub_bytes,
    read_local_json,
)

__all__ = [
    "DISTRIBUTION",
    "FAILURE",
    "FILE_LABEL",
    "LoadedHubJson",
    "load_hub_config_or_exit",
    "load_hub_json_or_exit",
    "local_lines",
    "read_hub_bytes",
    "read_hub_json",
    "read_local_json",
]

# The installed release of the hub command, which a hub's pin must equal.
DISTRIBUTION = "agent-hub-cli"
FILE_LABEL = "hub.json"
# An invalid hub.json. Typer keeps 2 for usage errors.
FAILURE = 1


def read_hub_json(path: Path) -> LoadedHubJson | tuple[ConfigProblem, ...]:
    """The bytes and validated config in ``path``, or the problems that stop its use.

    The pin must equal the installed ``hub``. Tell the two apart with
    ``isinstance(result, LoadedHubJson)``: a NamedTuple is a tuple too.
    """
    return hub_config_files.read_hub_json(path, running_version=version(DISTRIBUTION))


def load_hub_json_or_exit(path: Path, *, missing_hint: str | None = None) -> LoadedHubJson:
    """The bytes and validated config in ``path``; on any problem, print its lines and exit 1.

    When ``path`` does not exist and ``missing_hint`` is given, the hint is one more line.
    """
    loaded = load_hub_document(path, running_version=version(DISTRIBUTION))
    if isinstance(loaded, UnreadFile):
        _fail(loaded.problem, hint=missing_hint if loaded.is_missing else None)
    if not isinstance(loaded, LoadedHubJson):
        _fail(*loaded)
    return loaded


def load_hub_config_or_exit(path: Path) -> HubConfig:
    """The validated config in ``path``; on any problem, print its lines to stderr and exit 1."""
    return load_hub_json_or_exit(path).config


def local_lines(problems: tuple[ConfigProblem, ...]) -> list[str]:
    """One ``hub.local.json: <path>: <message>`` line per problem."""
    return [_line(LOCAL_FILE, problem) for problem in problems]


def _fail(*problems: ConfigProblem, hint: str | None = None) -> NoReturn:
    # Each problem is built on one line: text from the file is escaped where it is quoted.
    for problem in problems:
        typer.echo(_line(FILE_LABEL, problem), err=True)
    if hint is not None:
        typer.echo(f"{FILE_LABEL}: {hint}", err=True)
    raise typer.Exit(FAILURE)


def _line(label: str, problem: ConfigProblem) -> str:
    return f"{label}: {problem.path}: {problem.message}"
