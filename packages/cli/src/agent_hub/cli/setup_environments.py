"""``hub setup``'s environments step: declare the developer's own environments, then list them.

On a terminal without ``--yes`` the step asks once whether to declare environments in
``hub.local.json``; then, until an empty name or the end of input, a name (``local``,
``staging`` and ``production`` are examples, never defaults), its access and whether it is
production (no unless answered ``y``, whatever the name). Each answer goes through ``hub env
add --local``'s path: core's ``add_environment``, the checks a read makes (the file, then the
rules across both files), and ``env_files``' writer over the bytes read. Only
``hub.local.json`` is written; committed environments go through ``hub env add`` and a PR.

Prompts and refusals go to stderr; a name is echoed only through ``shown_name``. An answer is
read up to ``ANSWER_LIMIT`` bytes: an over-long one is no answer, asked again once, then the
step ends. With ``--yes``, without a terminal, or when ``hub.local.json`` is unusable, nothing
is asked or written. A file that cannot be read, is no JSON object or breaks its own schema is
the identity item's ``hub.local.json is invalid`` (no item here; the view is ``hub.json``'s); a
file that breaks a rule across both files, which every command reading both refuses (doctor's
``config.schema`` too), gives a missing ``environments`` item with its lines. Otherwise the item lists the effective view and
prints only when something is declared (spec AM-1).
"""

import contextlib
import sys
from pathlib import Path
from typing import Final, cast

import typer

from agent_hub.cli import setup_identity
from agent_hub.cli.env_files import document_bytes, write_document
from agent_hub.cli.hub_config_reader import FILE_LABEL, local_lines
from agent_hub.cli.setup_identity import ANSWER_LIMIT, skip_line
from agent_hub.core.hub_config.effective_environments import (
    effective_environments,
    local_environment_problems,
)
from agent_hub.core.hub_config.environment_edits import (
    Document,
    EditRefusal,
    add_environment,
    shown_name,
)
from agent_hub.core.hub_config.local_config import (
    LOCAL_FILE,
    LOCAL_FILE_MAX_BYTES,
    TOO_LARGE_MESSAGE,
    LocalConfig,
    check_local_document,
)
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ROOT_PATH, ConfigProblem
from agent_hub.core.json_form import load_json_bytes
from agent_hub.core.workspace.setup_checklist import (
    ChecklistItem,
    environments_invalid_item,
    environments_item,
)
from agent_hub.generator.hub_config_files import UnreadFile, parse_json, read_file_bytes

DECLARE_PROMPT: Final = f"Declare your own environments now ({LOCAL_FILE})? [y/N] "
NAME_PROMPT: Final = "Environment name (for example local, staging, production; empty to stop): "
ACCESS_PROMPT: Final = "Access for {name} (read, write or ask): "
PRODUCTION_PROMPT: Final = "Is it production? [y/N] "
INVALID_NAME: Final = (
    "not a valid environment name: letters, digits and _, joined by . or -,"
    " at most 40 characters, no secret's shape"
)
INVALID_ACCESS: Final = "access must be read, write or ask"
_ACCESS: Final = frozenset({"read", "write", "ask"})
_YES: Final = frozenset({"y", "yes"})


class _StepEndedError(Exception):
    """An answer was over-long twice: the step ends."""


class _Local:
    """``hub.local.json`` as last read or written: its bytes (``None``: absent) and config."""

    def __init__(self, path: Path, content: bytes | None, config: LocalConfig) -> None:
        self.path = path
        self.content = content
        self.config = config


def environments_items(
    config: HubConfig, *, home: Path, is_confirmed_by_flag: bool
) -> list[ChecklistItem]:
    """The ``environments`` item after the step (none when nothing is declared), which asks
    only on a terminal without ``--yes`` and writes only ``home``'s ``hub.local.json``."""
    local = _read_local(home / LOCAL_FILE, config)
    if local is None:
        view = effective_environments(config, LocalConfig())
    elif not isinstance(local, _Local):
        return [environments_invalid_item(local_lines(local))]
    else:
        if not is_confirmed_by_flag and setup_identity.stdin_is_tty():
            with contextlib.suppress(_StepEndedError):
                _declare(config, local)
        view = effective_environments(config, local.config)
    item = environments_item(view)
    return [] if item is None else [item]


def _read_local(path: Path, config: HubConfig) -> _Local | tuple[ConfigProblem, ...] | None:
    """The developer's file as read, an absent one as empty; its problems across both files;
    ``None`` when the file itself is unusable (the identity item reports it)."""
    found = read_file_bytes(path, max_bytes=LOCAL_FILE_MAX_BYTES)
    if isinstance(found, UnreadFile):
        return _Local(path, None, LocalConfig()) if found.is_missing else None
    parsed = parse_json(found)
    if isinstance(parsed, ConfigProblem):
        return None
    checked = check_local_document(parsed)
    if not isinstance(checked, LocalConfig):
        return None
    across = local_environment_problems(config, checked)
    if across:
        return across
    return _Local(path, found, checked)


def _declare(config: HubConfig, local: _Local) -> None:
    if not _is_yes(_ask(DECLARE_PROMPT)):
        return
    while name := _ask(NAME_PROMPT):
        # A taken or invalid name is refused before its access is asked.
        refusal = _name_refusal(config, local, name)
        if refusal is not None:
            _say(refusal)
            continue
        access = _ask(ACCESS_PROMPT.format(name=name))
        if access not in _ACCESS:
            _say(INVALID_ACCESS)
            continue
        is_production = _is_yes(_ask(PRODUCTION_PROMPT))
        refusal = _add(config, local, name, access=access, is_production=is_production)
        _say(refusal or f"{LOCAL_FILE}: added environment {name}")


def _name_refusal(config: HubConfig, local: _Local, name: str) -> str | None:
    """Why ``name`` cannot be added: not a valid name, or declared in either file; or None."""
    if shown_name(name) != name:
        return INVALID_NAME
    taken = _added(config, local, name, entry={})
    return taken.message if isinstance(taken, EditRefusal) else None


def _added(
    config: HubConfig, local: _Local, name: str, *, entry: Document
) -> Document | EditRefusal:
    """The developer's document with ``name`` added last, or why not (a name already taken)."""
    # The file was read and checked as a JSON object; an absent one is an empty one.
    document = cast("Document", {} if local.content is None else load_json_bytes(local.content))
    return add_environment(
        document,
        name,
        entry,
        declared=dict.fromkeys(config.environments, FILE_LABEL),
        file=LOCAL_FILE,
    )


def _add(
    config: HubConfig, local: _Local, name: str, *, access: str, is_production: bool
) -> str | None:
    """Add ``name`` to the developer's file, checked as a read checks it; the refusal, or None."""
    entry: Document = {"access": access}
    if is_production:
        entry["production"] = True
    edited = _added(config, local, name, entry=entry)
    if isinstance(edited, EditRefusal):
        return edited.message
    checked = check_local_document(edited)
    # Unreachable today: the name and access were checked, and a taken name refused, before
    # the edit; kept so a new rule on the file refuses here rather than at the next read.
    if not isinstance(checked, LocalConfig):  # pragma: no cover - see above
        return "; ".join(local_lines(checked))
    across = local_environment_problems(config, checked)
    if across:  # pragma: no cover - see above
        return "; ".join(local_lines(across))
    content = document_bytes(edited)
    if len(content) > LOCAL_FILE_MAX_BYTES:
        return "; ".join(local_lines((ConfigProblem(ROOT_PATH, TOO_LARGE_MESSAGE),)))
    refusal = write_document(local.path, read=local.content, content=content)
    if refusal is not None:
        return refusal
    local.content, local.config = content, checked
    return None


def _ask(prompt: str) -> str:
    """The answer to ``prompt``, stripped; ``""`` at the end of input. An over-long answer is
    asked again once; a second one ends the step (``_StepEndedError``)."""
    for _ in range(2):
        typer.echo(prompt, err=True, nl=False)
        answer = sys.stdin.buffer.readline(ANSWER_LIMIT)
        if len(answer) < ANSWER_LIMIT or answer.endswith(b"\n"):
            return answer.decode("utf-8", errors="replace").strip()
        skip_line()
    raise _StepEndedError


def _is_yes(answer: str) -> bool:
    return answer.lower() in _YES


def _say(line: str) -> None:
    typer.echo(f"hub setup: {line}", err=True)
