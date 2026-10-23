"""The hub the knowledge commands work on, its checkout's sources and its knowledge index
(AGH-391, ADR 0044: D-hub, D-sources, D-db, D-fts5).

The hub is the one the other hub commands use: ``AGENT_HUB_ROOT`` when set and not empty, else
the cwd, which must hold ``hub.json`` (exit 2). With ``--hub NAME`` it is instead the first hub
of the registry ``hub web`` reads (``hubs.json``) whose ``hub.json`` is valid against its own pin
and names the project NAME, as ``hub web`` maps a project name to a hub; an unknown NAME exits
1, and a hub pinned to another release exits 1 with the pin line, as any hub command there.
From a worktree of the hub repo, the main checkout is indexed (owner, Q-2), so a worktree and
its checkout share one index: the index names a hub by the real path of its main checkout
(P-1), and ``hub.json`` is read there.
"""

import os
import shutil
from collections.abc import Mapping
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, NamedTuple

import typer

from agent_hub.cli.command_exits import fail
from agent_hub.cli.database_path import default_database_path
from agent_hub.cli.errors import HomeDirectoryNotFoundError
from agent_hub.cli.hub_config_reader import (
    DISTRIBUTION,
    FILE_LABEL,
    load_hub_config_or_exit,
    read_hub_bytes,
)
from agent_hub.cli.hub_root import hub_checkout, hub_root_or_exit
from agent_hub.cli.init_report import shown_text
from agent_hub.cli.registry_path import default_registry_path
from agent_hub.core.hubs.hub_document import read_hub_document
from agent_hub.core.hubs.hub_registry import HubRegistryError
from agent_hub.hub_git.knowledge_checkout import GitKnowledgeCheckout
from agent_hub.storage.errors import StorageError
from agent_hub.storage.hub_registry import JsonHubRegistry
from agent_hub.storage.knowledge_index import SqliteKnowledgeIndex, open_knowledge_index

HubName = Annotated[
    str | None,
    typer.Option(
        "--hub",
        metavar="NAME",
        help="Use the registered hub (hubs.json, as hub web reads it) whose project is NAME.",
        show_default=False,
    ),
]
Database = Annotated[
    Path | None,
    typer.Option(
        "--db",
        envvar="AGENT_HUB_DB",
        help=(
            "Database file. Default: $XDG_DATA_HOME/agent-hub/agent-hub.db, "
            "or ~/.local/share/agent-hub/agent-hub.db."
        ),
        show_default=False,
    ),
]


class KnowledgeHub(NamedTuple):
    """The hub's main checkout (its real path is the index's key for the hub), its
    ``project.name`` and the ``repos[].dir`` of its ``hub.json``, as listed there."""

    checkout: Path
    project: str
    repo_dirs: tuple[str, ...]

    @property
    def key(self) -> str:
        """The name the index keeps the hub's rows under."""
        return str(self.checkout)


def knowledge_hub_or_exit(
    environ: Mapping[str, str], *, command: str, hub_name: str | None = None
) -> KnowledgeHub:
    """The hub ``hub <command>`` works on: the registered hub named ``hub_name`` when given,
    else the hub root; exit 2 when the root holds no ``hub.json``, 1 when the registry cannot
    be read or names no such hub, or the hub's main checkout cannot be found or its
    ``hub.json`` is not valid."""
    if hub_name is None:
        root = hub_root_or_exit(environ, command=command)
    else:
        root = _registered_hub_or_exit(hub_name, environ, command=command)
    checkout = hub_checkout(root, command=command, environ=environ)
    config = load_hub_config_or_exit(checkout / FILE_LABEL)
    return KnowledgeHub(
        checkout=checkout,
        project=config.project.name,
        repo_dirs=tuple(repo.dir for repo in config.repos),
    )


def _registered_hub_or_exit(name: str, environ: Mapping[str, str], *, command: str) -> Path:
    """The real path of the first registered hub whose ``hub.json`` is valid against its own pin
    and names the project ``name``, as ``hub web`` picks it; a registered hub whose ``hub.json``
    cannot be read or is not valid is not a candidate. A pin other than the installed ``hub`` is
    reported when the chosen hub's ``hub.json`` is loaded."""
    try:
        entries = JsonHubRegistry(default_registry_path(environ)).entries()
    except (HomeDirectoryNotFoundError, HubRegistryError) as error:
        fail(f"hub {command}: {error}")
    running = version(DISTRIBUTION)
    for entry in entries:
        content = read_hub_bytes(Path(entry.path) / FILE_LABEL)
        if not isinstance(content, bytes):
            continue
        document = read_hub_document(content, running_version=running)
        if document.config is not None and document.config.project.name == name:
            return Path(os.path.realpath(entry.path))
    fail(f"hub {command}: no registered hub named {shown_text(name)}")


def knowledge_checkout_or_exit(
    hub: KnowledgeHub, environ: Mapping[str, str], *, command: str
) -> GitKnowledgeCheckout:
    """The hub's sources as git lists them; exit 1 when git is not on ``PATH``.

    A repo of ``hub.json`` that is not checked out beside the hub gets one stderr line (D-sources);
    the checkout leaves it out of the listing, so its rows are dropped as vanished.
    """
    found = shutil.which("git", path=environ.get("PATH", os.defpath))
    if found is None:
        fail(f"hub {command}: git is not on PATH; install git")
    checkout = GitKnowledgeCheckout(
        hub.checkout, hub.repo_dirs, git=os.path.abspath(found), environ=environ
    )
    for name in checkout.not_checked_out():
        line = f"hub {command}: {name}: not checked out; its docs are not searched"
        typer.echo(shown_text(line), err=True)
    return checkout


def open_index_or_exit(db: Path | None, *, command: str) -> SqliteKnowledgeIndex:
    """The knowledge index in ``db``, else the default database ``hub collect`` writes to,
    migrated to head; exit 1 with one line when it cannot be opened or SQLite has no FTS5."""
    try:
        path = db or default_database_path(os.environ)
    except HomeDirectoryNotFoundError as error:
        fail(f"hub {command}: {error}")
    try:
        return open_knowledge_index(path)
    except StorageError as error:
        # Fts5UnavailableError is one: its message is D-fts5's line without the command.
        fail(f"hub {command}: {error}")
