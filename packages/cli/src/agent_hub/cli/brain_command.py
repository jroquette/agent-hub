"""``hub brain``: the hub's brain as the knowledge index sees it (AGH-391, ADR 0044).

``hub brain reindex`` drops the hub's knowledge rows and rebuilds them from its checkout
(``sync_knowledge`` with ``rebuild``), so an edit that kept a file's size and mtime is seen;
other hubs' rows are untouched (D-reindex). Every skipped file is named on stderr, as by
``hub search`` (D-skipreport). Exit codes: 0 done, 1 failure (database, git, FTS5, registry,
unknown ``--hub``), 2 usage or not a hub.
"""

import os
from typing import Final

import typer

from agent_hub.cli.command_exits import fail
from agent_hub.cli.init_report import shown_text
from agent_hub.cli.knowledge_hub import (
    Database,
    HubName,
    knowledge_checkout_or_exit,
    knowledge_hub_or_exit,
    open_index_or_exit,
)
from agent_hub.core.knowledge.sync_knowledge import KnowledgeCheckoutError, sync_knowledge
from agent_hub.storage.errors import StorageError

REINDEX_COMMAND: Final = "brain reindex"

brain_app = typer.Typer(
    name="brain", no_args_is_help=True, help="Work on the hub's brain and its knowledge index."
)


@brain_app.command("reindex")
def reindex(*, hub_name: HubName = None, db: Database = None) -> None:
    """Drop the hub's knowledge index rows and rebuild them from its checkout."""
    hub = knowledge_hub_or_exit(os.environ, command=REINDEX_COMMAND, hub_name=hub_name)
    checkout = knowledge_checkout_or_exit(hub, os.environ, command=REINDEX_COMMAND)
    index = open_index_or_exit(db, command=REINDEX_COMMAND)
    try:
        report = sync_knowledge(index, checkout, hub.key, rebuild=True)
    except (KnowledgeCheckoutError, StorageError) as error:
        fail(f"hub {REINDEX_COMMAND}: {error}")
    for skipped in report.skipped:
        line = f"hub {REINDEX_COMMAND}: skipped {shown_text(skipped.path)}: {skipped.reason}"
        typer.echo(line, err=True)
    project = shown_text(hub.project)
    typer.echo(f"reindexed {report.indexed} files for {project} ({len(report.skipped)} skipped)")
