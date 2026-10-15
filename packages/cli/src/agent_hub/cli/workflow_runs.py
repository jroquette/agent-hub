"""A workflow run's record and events, for ``hub workflow run`` (ADR 0032).

A run lives in ``<hub>/.agent-runs/workflows/<run>/``: ``snapshot/`` holds the document as
``workflow.json`` and the prompts and scripts its nodes name, copied at start, so a resume runs
what the run started with (``content_hash`` is ``sha256:`` over those files, each framed by its
path and length); ``records.jsonl`` holds one JSON line per start, resume, step start, step end
(with its output and detail), retry, end and the agent sessions left. A resume rebuilds the
engine's ``RunState`` from those lines. The subfolder keeps these lines out of the dated
``.agent-runs/<date>.jsonl`` files that ``hub run`` writes and the retro and ``hub collect --runs``
read as issue-to-pr records.

Each recorder call also becomes events (``core.workflows.events``) appended through
``IngestEvents`` to the database ``hub collect`` uses, failing open as ``hub run``'s are: one
stderr line, then the run goes on without events.
"""

import hashlib
import json
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final

import typer

from agent_hub.cli.errors import CliError
from agent_hub.cli.run_log import now, open_default_event_store
from agent_hub.core.errors import AgentHubError
from agent_hub.core.events.event_store import EventStore
from agent_hub.core.ingestion.ingest_events import IngestEvents
from agent_hub.core.json_form import JsonValue
from agent_hub.core.workflows.events import WorkflowEvents
from agent_hub.core.workflows.failures import RetryRecord
from agent_hub.core.workflows.nodes import AgentNode, LoopNode, ScriptNode
from agent_hub.core.workflows.plan import WorkflowPlan
from agent_hub.core.workflows.ports import RunEnd, StepEnd, StepStart
from agent_hub.core.workflows.run_state import RunState
from agent_hub.core.workflows.substitution import NodeResult
from agent_hub.generator.workflow_discovery import PackFolder, resolve_pack_file

RUNS_ROOT: Final = Path(".agent-runs", "workflows")
SNAPSHOT: Final = "snapshot"
DOCUMENT: Final = "workflow.json"
RECORDS: Final = "records.jsonl"
RUN_ID_PATTERN: Final = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
UNAVAILABLE: Final = "hub workflow run: event store unavailable"
_STATES: Final = {"ok": "completed", "failed": "failed", "skipped": "skipped"}

type Record = dict[str, JsonValue]


class WorkflowRunError(CliError):
    """A run folder that cannot be made or read."""


def run_folder(hub: Path, run_id: str) -> Path:
    return hub / RUNS_ROOT / run_id


def snapshot_run(
    folder: Path, *, document: JsonValue, plan: WorkflowPlan, pack_root: Path
) -> tuple[Path, str]:
    """Make the run's folder and its snapshot; the snapshot's pack root and content hash."""
    snapshot = folder / SNAPSHOT
    try:
        folder.mkdir(parents=True)
    except FileExistsError:
        raise WorkflowRunError(f"the run {folder.name} already exists") from None
    files = {DOCUMENT: json.dumps(document, sort_keys=True).encode()}
    for pack_folder, relative in _pack_files(plan):
        source = resolve_pack_file(pack_root, pack_folder, relative)
        files[f"{pack_folder}/{relative}"] = source.read_bytes()
    digest = hashlib.sha256()
    for name in sorted(files):
        target = snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(files[name])
        digest.update(f"{name}\0{len(files[name])}\0".encode() + files[name])
    return snapshot, f"sha256:{digest.hexdigest()}"


def _pack_files(plan: WorkflowPlan) -> Iterator[tuple[PackFolder, str]]:
    for node in plan.document.nodes:
        if isinstance(node, AgentNode | LoopNode) and node.prompt_file is not None:
            yield "prompts", node.prompt_file
        elif isinstance(node, ScriptNode):
            yield "scripts", node.script


def read_records(folder: Path) -> list[Record]:
    try:
        lines = (folder / RECORDS).read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line]
    except (OSError, ValueError) as error:
        raise WorkflowRunError(f"cannot read the run {folder.name}: {error}") from None


def append_record(folder: Path, record: Record) -> None:
    line = {"ts": now().isoformat(timespec="seconds"), **record}
    try:
        with (folder / RECORDS).open("a", encoding="utf-8") as file:
            file.write(json.dumps(line, sort_keys=True) + "\n")
    except OSError as error:
        raise WorkflowRunError(f"cannot write the run {folder.name}: {error}") from None


def prior_state(records: list[Record]) -> RunState:
    """The state a run left: each node's last result (a reuse keeps the one reused), the last
    attempt of each node, and the sessions it recorded last."""
    nodes: dict[str, NodeResult] = {}
    attempts: dict[str, int] = {}
    sessions: dict[str, str] = {}
    for record in records:
        node, event = record.get("node"), record.get("event")
        if event == "sessions" and isinstance(given := record.get("sessions"), dict):
            sessions = {key: value for key, value in given.items() if isinstance(value, str)}
        if not isinstance(node, str) or not isinstance(attempt := record.get("attempt"), int):
            continue
        attempts[node] = max(attempts.get(node, 0), attempt)
        state = _STATES.get(str(record.get("status")))
        if event == "step_end" and state and record.get("skip_cause") != "prior_success":
            output = record.get("output") if state == "completed" else None
            nodes[node] = NodeResult(state, output)  # type: ignore[arg-type]
    return RunState(nodes, attempts, sessions)


def ends_of(records: list[Record]) -> list[Record]:
    return [record for record in records if record.get("event") == "end"]


@dataclass(kw_only=True)
class EventSink:
    """Appends a run's new events through ``IngestEvents``; the first failure stops it."""

    event_store: Callable[[], EventStore] = field(default=open_default_event_store)
    sent: int = 0
    _ingest: IngestEvents | None = None
    _closed: bool = False

    def flush(self, events: WorkflowEvents) -> None:
        fresh, self.sent = events.events[self.sent :], len(events.events)
        if self._closed or not fresh:
            return
        try:
            if self._ingest is None:
                self._ingest = IngestEvents(self.event_store())
            self._ingest.execute(fresh)
        except (AgentHubError, OSError) as error:
            self._closed = True
            typer.echo(
                f"{UNAVAILABLE}: {' '.join(str(error).split()) or type(error).__name__}", err=True
            )


@dataclass(kw_only=True)
class RecordedRun:
    """The ``RunRecorder`` of ``hub workflow run``: the run's record, then its events."""

    folder: Path
    events: WorkflowEvents
    sink: EventSink

    def step_started(self, start: StepStart) -> None:
        self._record({"event": "step_start", "node": start.node, "attempt": start.attempt})
        self.events.step_started(start)
        self.sink.flush(self.events)

    def step_ended(self, end: StepEnd) -> None:
        record: Record = {
            "event": "step_end",
            "node": end.node,
            "attempt": end.attempt,
            "status": end.status,
            "failure_kind": end.failure_kind,
            "skip_cause": end.skip_cause,
            "origin": end.origin,
            "output": end.output,
            "detail": end.detail,
        }
        self._record(record)
        typer.echo(
            f"[{end.node}] {end.status}" + (f" ({end.failure_kind})" * bool(end.failure_kind))
        )
        self.events.step_ended(end)
        self.sink.flush(self.events)

    def retry_scheduled(self, node: str, retry: RetryRecord) -> None:
        delay = retry.delay.total_seconds()
        record: Record = {"event": "retry", "node": node, "attempt": retry.attempt}
        self._record({**record, "kind": retry.kind, "delay_s": delay})

    def run_ended(self, end: RunEnd) -> None:
        record: Record = {"event": "end", "status": end.status, "outcome": end.outcome}
        self._record({**record, "reason": end.reason})
        self.events.run_ended(end)
        self.sink.flush(self.events)

    def _record(self, record: Record) -> None:
        append_record(self.folder, record)


class SystemClock:
    """The engine's ``Clock`` for a live run."""

    def now(self) -> datetime:
        return now()

    def sleep(self, delay: timedelta) -> None:
        time.sleep(delay.total_seconds())
