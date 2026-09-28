"""Load ``hub.json`` for a command, or print one line per problem and exit 1.

This module reads the file and prints; core's ``check_hub_document`` checks it, in the order of
docs/design/project-config.md § Versioning: the pin, then ``schema_version``, then the model.
"""

import json
from importlib.metadata import version
from pathlib import Path
from typing import NoReturn

import typer

from agent_hub.core.hub_config.document_check import check_hub_document
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ROOT_PATH, ConfigProblem

# The installed release of the hub command, which a hub's pin must equal.
DISTRIBUTION = "agent-hub-cli"
FILE_LABEL = "hub.json"
# Written as an escape: the character itself is invisible in the source.
BYTE_ORDER_MARK = "\N{ZERO WIDTH NO-BREAK SPACE}"
# An invalid hub.json. Typer keeps 2 for usage errors.
FAILURE = 1


def load_hub_config_or_exit(path: Path) -> HubConfig:
    """The validated config in ``path``; on any problem, print its lines to stderr and exit 1."""
    checked = check_hub_document(
        _read_document_or_exit(path), running_version=version(DISTRIBUTION)
    )
    if not isinstance(checked, HubConfig):
        _fail(*checked)
    return checked


def _read_document_or_exit(path: Path) -> object:
    return _parse_or_exit(_read_text_or_exit(path))


def _read_text_or_exit(path: Path) -> str:
    # The path is quoted and escaped, so it stays on the one line.
    shown_path = json.dumps(str(path))
    # Opening a FIFO waits for a writer and a device can be endless: only a regular file is read.
    # A path that does not exist is left to the read, which names the reason.
    if path.exists() and not path.is_file():
        _fail(ConfigProblem(ROOT_PATH, f"cannot read {shown_path}: not a regular file"))
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        reason = error.strerror or type(error).__name__
        _fail(ConfigProblem(ROOT_PATH, f"cannot read {shown_path}: {reason}"))
    except UnicodeDecodeError as error:
        _fail(ConfigProblem(ROOT_PATH, f"not UTF-8 text: byte {error.start} cannot be decoded"))


def _parse_or_exit(text: str) -> object:
    if text.startswith(BYTE_ORDER_MARK):
        _fail(
            ConfigProblem(
                ROOT_PATH,
                "not valid JSON: the file starts with a UTF-8 byte order mark; save it without one",
            )
        )
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        _fail(
            ConfigProblem(
                ROOT_PATH,
                f"not valid JSON: {error.msg} at line {error.lineno} column {error.colno}",
            )
        )
    except ValueError:
        # Python reads integers of at most 4300 digits (sys.get_int_max_str_digits()).
        _fail(
            ConfigProblem(
                ROOT_PATH,
                "not valid JSON here: a number has more than 4300 digits,"
                " which this reader does not accept",
            )
        )
    except RecursionError:
        _fail(ConfigProblem(ROOT_PATH, "not valid JSON here: it is nested too deeply"))


def _fail(*problems: ConfigProblem) -> NoReturn:
    # Each problem is built on one line: text from the file is escaped where it is quoted.
    for problem in problems:
        typer.echo(f"{FILE_LABEL}: {problem.path}: {problem.message}", err=True)
    raise typer.Exit(FAILURE)
