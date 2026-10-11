"""The run's identity and records, outside core (E20): the run id, the clock and the writers.

A live run appends one JSON line per transition to ``<hub>/.agent-runs/<date>.jsonl`` and, when
it ends, one line to ``<hub>/brain/_inbox/runs/<date>.md``; ``<hub>`` is the hub's main checkout
and ``<date>`` the local date, as the old runner wrote them. ``ts`` is UTC, to the second.

Each record is also mapped to executor events (``run_records``) and appended to the event
database ``hub collect`` uses (D9), failing open: a busy database skips that record's events
with one ``hub run: event store busy, record skipped: <reason>`` line; any other failure prints
one ``hub run: event store unavailable: <reason>`` line and the run goes on without events.
"""

import datetime
import json
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import typer

from agent_hub.cli.collect import hub_project_name
from agent_hub.cli.database_path import default_database_path
from agent_hub.cli.errors import RunLogError
from agent_hub.collector.run_records import RunEventMapper
from agent_hub.core.errors import AgentHubError
from agent_hub.core.events.event_store import EventStore
from agent_hub.core.ingestion.ingest_events import IngestEvents
from agent_hub.core.json_form import JsonValue
from agent_hub.core.runner.run_record import Stage, run_record
from agent_hub.storage.event_store import DatabaseBusyError, open_event_store

RUN_ID_LENGTH: Final = 8
RUNS_FOLDER: Final = Path(".agent-runs")
INBOX_FOLDER: Final = Path("brain", "_inbox", "runs")
DATABASE_VARIABLE: Final = "AGENT_HUB_DB"
UNAVAILABLE: Final = "hub run: event store unavailable"
BUSY: Final = "hub run: event store busy, record skipped"


def new_run_id() -> str:
    """A fresh run id: 8 hexadecimal characters, as the old runner wrote them."""
    return uuid.uuid4().hex[:RUN_ID_LENGTH]


def now() -> datetime.datetime:
    """The run's one clock read per record (tests replace it): aware, in UTC."""
    return datetime.datetime.now(datetime.UTC)


def open_default_event_store() -> EventStore:
    """The event database ``hub collect`` would use: ``AGENT_HUB_DB``, else the default path."""
    given = os.environ.get(DATABASE_VARIABLE)
    return open_event_store(Path(given) if given else default_database_path(os.environ))


@dataclass(kw_only=True, slots=True)
class _RunEvents:
    """The run's event writer, opened at its first record."""

    ingest: IngestEvents
    mapper: RunEventMapper


@dataclass(kw_only=True, slots=True)
class RunLog:
    """The live run's writers: its records, their events and its inbox line, in the hub's main
    checkout. ``event_store`` opens the event database, once, at the first record."""

    hub: Path
    run_id: str
    issue_id: str
    repo: str
    state: Stage = field(default=Stage.PICKED)
    event_store: Callable[[], EventStore] = field(default=open_default_event_store)
    _events: _RunEvents | None = field(default=None, init=False)
    _is_store_unavailable: bool = field(default=False, init=False)

    def record(self, event: str, data: dict[str, JsonValue] | None = None) -> None:
        """Append the transition's record and show ``[STATE] event`` on stdout."""
        moment = now()
        line = run_record(
            ts=moment.astimezone(datetime.UTC).isoformat(timespec="seconds"),
            run_id=self.run_id,
            issue_id=self.issue_id,
            repo=self.repo,
            state=self.state,
            event=event,
            live=True,
            data=data or {},
        )
        typer.echo(f"[{self.state}] {event}")
        try:
            self._append(RUNS_FOLDER, moment, suffix=".jsonl", line=json.dumps(line))
        except OSError as error:
            raise RunLogError(error) from error
        self._store(line)

    def inbox(self, line: str) -> None:
        """Append the run's line to the inbox file of the day."""
        try:
            self._append(INBOX_FOLDER, now(), suffix=".md", line=line)
        except OSError as error:
            raise RunLogError(error) from error

    def _store(self, line: dict[str, JsonValue]) -> None:
        """Append the record's events; busy skips the record, any other failure stops the events."""
        if self._is_store_unavailable:
            return
        try:
            if self._events is None:
                project = hub_project_name(self.hub) or self.hub.name
                self._events = _RunEvents(
                    ingest=IngestEvents(self.event_store()), mapper=RunEventMapper(project=project)
                )
            self._events.ingest.execute(self._events.mapper.map(line))
        except DatabaseBusyError as error:
            typer.echo(f"{BUSY}: {_reason(error)}", err=True)
        except (AgentHubError, OSError) as error:
            self._is_store_unavailable = True
            typer.echo(f"{UNAVAILABLE}: {_reason(error)}", err=True)

    def _append(self, folder: Path, moment: datetime.datetime, *, suffix: str, line: str) -> None:
        target = self.hub / folder
        target.mkdir(parents=True, exist_ok=True)
        day = moment.astimezone().date().isoformat()
        with (target / f"{day}{suffix}").open("a", encoding="utf-8") as file:
            file.write(line + "\n")


def _reason(error: Exception) -> str:
    return " ".join(str(error).split()) or type(error).__name__
