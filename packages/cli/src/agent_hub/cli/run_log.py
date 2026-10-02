"""The run's identity and records, outside core (E20): the run id, the clock and the writers.

A live run appends one JSON line per transition to ``<hub>/.agent-runs/<date>.jsonl`` and, when
it ends, one line to ``<hub>/brain/_inbox/runs/<date>.md``; ``<hub>`` is the hub's main checkout
and ``<date>`` the local date, as the old runner wrote them. ``ts`` is UTC, to the second.
"""

import datetime
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import typer

from agent_hub.cli.errors import RunLogError
from agent_hub.core.json_form import JsonValue
from agent_hub.core.runner.run_record import Stage, run_record

RUN_ID_LENGTH: Final = 8
RUNS_FOLDER: Final = Path(".agent-runs")
INBOX_FOLDER: Final = Path("brain", "_inbox", "runs")


def new_run_id() -> str:
    """A fresh run id: 8 hexadecimal characters, as the old runner wrote them."""
    return uuid.uuid4().hex[:RUN_ID_LENGTH]


def now() -> datetime.datetime:
    """The run's one clock read per record (tests replace it): aware, in UTC."""
    return datetime.datetime.now(datetime.UTC)


@dataclass(kw_only=True, slots=True)
class RunLog:
    """The live run's writers: its records and its inbox line, in the hub's main checkout."""

    hub: Path
    run_id: str
    issue_id: str
    repo: str
    state: Stage = field(default=Stage.PICKED)

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

    def inbox(self, line: str) -> None:
        """Append the run's line to the inbox file of the day."""
        try:
            self._append(INBOX_FOLDER, now(), suffix=".md", line=line)
        except OSError as error:
            raise RunLogError(error) from error

    def _append(self, folder: Path, moment: datetime.datetime, *, suffix: str, line: str) -> None:
        target = self.hub / folder
        target.mkdir(parents=True, exist_ok=True)
        day = moment.astimezone().date().isoformat()
        with (target / f"{day}{suffix}").open("a", encoding="utf-8") as file:
            file.write(line + "\n")
