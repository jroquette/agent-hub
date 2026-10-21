"""``hub search``: ranked results from the hub's knowledge index (AGH-391, ADR 0044).

Every search first brings the hub's rows up to date with its checkout (``search_knowledge``):
the hub's ``brain/`` minus ``brain/auto/`` and each repo's ``docs/``. A file skipped when it is
examined is named on stderr. The results are printed as one block per result (D-output), or as
one JSON object with ``--json``. Every value shown is escaped so it cannot fake a line. Exit
codes: 0 with or without results, 1 failure (database, git, FTS5), 2 usage or not a hub.
"""

import os
from pathlib import Path
from typing import Annotated, Final, NoReturn

import typer

from agent_hub.cli.command_exits import fail
from agent_hub.cli.init_report import shown_text
from agent_hub.cli.knowledge_hub import (
    KnowledgeHub,
    knowledge_checkout_or_exit,
    knowledge_hub_or_exit,
    open_index_or_exit,
)
from agent_hub.core.json_form import JsonValue, dump_json
from agent_hub.core.knowledge.knowledge_index import KINDS, Kind, SearchHit
from agent_hub.core.knowledge.search_query import query_words
from agent_hub.core.knowledge.sync_knowledge import (
    KnowledgeCheckoutError,
    SearchOutcome,
    search_knowledge,
)
from agent_hub.storage.errors import StorageError

COMMAND: Final = "search"
# A query with no word, an unknown kind or a bad option, as Typer's own usage errors.
USAGE: Final = 2
_SEPARATOR: Final = "  "

Query = Annotated[
    list[str],
    typer.Argument(metavar="QUERY", help="Plain words; a result holds every one of them."),
]
Kinds = Annotated[
    list[str] | None,
    typer.Option(
        "--kind",
        metavar="KIND",
        help="Keep results of this kind (repeatable): " + ", ".join(KINDS) + ".",
        show_default=False,
    ),
]
AsJson = Annotated[bool, typer.Option("--json", help="Print one JSON object instead of lines.")]
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


def search(
    query: Query, *, kind: Kinds = None, as_json: AsJson = False, db: Database = None
) -> None:
    """Search the hub's brain and its repos' docs; the index is brought up to date first."""
    # Usage is checked before the hub, the database or git is touched (P-10).
    kinds = _kinds_or_exit(kind or [])
    text = " ".join(query)
    words = query_words(text)
    if not words:
        _usage("the query has no words")
    hub = knowledge_hub_or_exit(os.environ, command=COMMAND)
    checkout = knowledge_checkout_or_exit(hub, os.environ, command=COMMAND)
    index = open_index_or_exit(db, command=COMMAND)
    try:
        outcome = search_knowledge(index, checkout, hub.key, words=words, kinds=kinds)
    except (KnowledgeCheckoutError, StorageError) as error:
        fail(f"hub {COMMAND}: {error}")
    for skipped in outcome.report.skipped:
        typer.echo(f"hub {COMMAND}: skipped {shown_text(skipped.path)}: {skipped.reason}", err=True)
    if as_json:
        typer.echo(dump_json(_outcome_json(hub, text, outcome)).decode(), nl=False)
    elif outcome.results:
        typer.echo("\n\n".join(_block(hit) for hit in outcome.results))
    else:
        typer.echo(f"no results for {shown_text(text)}")


def _kinds_or_exit(given: list[str]) -> tuple[Kind, ...]:
    known: dict[str, Kind] = {name: name for name in KINDS}
    kinds: list[Kind] = []
    for name in given:
        found = known.get(name)
        if found is None:
            _usage(f"unknown kind {shown_text(name)}; the kinds are {', '.join(KINDS)}")
        kinds.append(found)
    return tuple(kinds)


def _usage(message: str) -> NoReturn:
    typer.echo(f"hub {COMMAND}: {message}", err=True)
    raise typer.Exit(USAGE)


def _block(hit: SearchHit) -> str:
    header = [shown_text(hit.path), hit.kind]
    if hit.status is not None:
        header.append(shown_text(hit.status))
    return "\n".join((_SEPARATOR.join(header), shown_text(hit.title), shown_text(hit.snippet)))


def _outcome_json(hub: KnowledgeHub, query: str, outcome: SearchOutcome) -> JsonValue:
    report = outcome.report
    return {
        "hub": hub.project,
        "query": query,
        "results": [
            {
                "path": hit.path,
                "kind": hit.kind,
                "title": hit.title,
                "status": hit.status,
                "provenance": hit.provenance,
                "snippet": hit.snippet,
            }
            for hit in outcome.results
        ],
        "sync": {
            "listed": report.listed,
            "read": report.read,
            "indexed": report.indexed,
            "dropped": report.dropped,
        },
        "skipped": [{"path": file.path, "reason": file.reason} for file in report.skipped],
    }
