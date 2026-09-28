"""``hub collect``: ingest canonical events from JSON Lines into the event database."""

import os
import sys
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from agent_hub.cli.database_path import default_database_path
from agent_hub.collector.errors import CollectorError
from agent_hub.collector.jsonl import ParsedEvent, parse_events, read_stream, read_text
from agent_hub.core.errors import EventConflictError
from agent_hub.core.events.event_store import AppendResult
from agent_hub.core.ingestion.ingest_events import IngestEvents
from agent_hub.storage.errors import StorageError
from agent_hub.storage.event_store import open_event_store

STDIN_ARGUMENT = Path("-")
# P3: invalid input, a conflict or a storage failure. Typer keeps 2 for usage errors.
FAILURE = 1


def collect(
    file: Annotated[
        Path | None,
        typer.Argument(
            metavar="FILE",
            help="JSON Lines file with one canonical event per line; stdin when omitted or '-'.",
            show_default=False,
        ),
    ] = None,
    *,
    db: Annotated[
        Path | None,
        typer.Option(
            "--db",
            envvar="AGENT_HUB_DB",
            help=(
                "Event database file. Default: $XDG_DATA_HOME/agent-hub/agent-hub.db, "
                "or ~/.local/share/agent-hub/agent-hub.db."
            ),
            show_default=False,
        ),
    ] = None,
) -> None:
    """Ingest canonical events from JSON Lines, all or nothing."""
    events = _parse_or_exit(_read_or_exit(file))
    # The database is resolved and opened only now, so bad input never creates one.
    result = _ingest_or_exit(events, db or default_database_path(os.environ))
    typer.echo(f"appended {result.appended}, duplicates {result.duplicates}")


def _read_or_exit(file: Path | None) -> str:
    try:
        if file is None or file == STDIN_ARGUMENT:
            return read_stream(sys.stdin.buffer, name="stdin")
        return read_text(file)
    except CollectorError as error:
        _fail(f"error: {error}")


def _parse_or_exit(text: str) -> list[ParsedEvent]:
    batch = parse_events(text)
    if batch.errors:
        _fail(*(f"line {error.line_number}: {error.reason}" for error in batch.errors))
    return list(batch.events)


def _ingest_or_exit(events: list[ParsedEvent], db_path: Path) -> AppendResult:
    try:
        return IngestEvents(open_event_store(db_path)).execute([item.event for item in events])
    except EventConflictError as error:
        line_number = events[error.position].line_number
        _fail(
            f"line {line_number}: conflict: event ({error.source}, {error.source_id}) "
            "differs from an event with the same key"
        )
    except StorageError as error:
        _fail(f"error: {error}")


def _fail(*messages: str) -> NoReturn:
    for message in messages:
        typer.echo(message, err=True)
    raise typer.Exit(FAILURE)
