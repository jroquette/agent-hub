"""A workflow run's record and events, for ``hub workflow run`` (ADR 0032).

A run lives in ``<hub>/.agent-runs/workflows/<run>/``: ``snapshot/`` holds the document as
``workflow.json``, each workflow it includes as ``includes/<name>.json``, and the prompts and
scripts its nodes name, copied at start, so a resume runs
what the run started with (``content_hash`` is ``sha256:`` over those files, each framed by its
path and length); ``records.jsonl`` holds one JSON line per start, resume, step start, step end
(with its output and detail), retry, gate (its rendered message, choices and due time), gate
decision (the answer's text), end and the agent sessions left. A resume rebuilds the engine's
``RunState`` from those lines, and its gates' answers from the decision lines. The subfolder
keeps these lines out of the dated ``.agent-runs/<date>.jsonl`` files that ``hub run`` writes and
the retro and ``hub collect --runs`` read as issue-to-pr records.

Each recorder call also becomes events (``core.workflows.events``) appended through
``IngestEvents`` to the database ``hub collect`` uses, failing open as ``hub run``'s are: one
stderr line, then the run goes on without events.
"""

import contextlib
import fcntl
import hashlib
import json
import os
import re
import time
from collections.abc import Callable, Iterator, Mapping
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
from agent_hub.core.workflows.document import WorkflowDocument, parse_workflow
from agent_hub.core.workflows.events import WorkflowEvents
from agent_hub.core.workflows.failures import RetryRecord
from agent_hub.core.workflows.gates import GateAnswer, OpenGate, gate_id
from agent_hub.core.workflows.includes import IncludeResolver
from agent_hub.core.workflows.nodes import AgentNode, LoopNode, ScriptNode
from agent_hub.core.workflows.plan import WorkflowPlan
from agent_hub.core.workflows.ports import GateRequest, RunEnd, StepEnd, StepStart
from agent_hub.core.workflows.run_state import HeldGroup, RunState
from agent_hub.core.workflows.substitution import NodeResult
from agent_hub.generator.workflow_discovery import PackFolder, PackPathError, resolve_pack_file

RUNS_ROOT: Final = Path(".agent-runs", "workflows")
SNAPSHOT: Final = "snapshot"
DOCUMENT: Final = "workflow.json"
INCLUDES: Final = "includes"
INCLUDE_NAME: Final = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
RECORDS: Final = "records.jsonl"
LOCK: Final = "lock"
MAX_SNAPSHOT_FILE_BYTES: Final = 1 << 20
MAX_RECORDS_BYTES: Final = 64 << 20
RUN_ID_PATTERN: Final = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
UNAVAILABLE: Final = "hub workflow run: event store unavailable"
_STATES: Final = {"ok": "completed", "failed": "failed", "skipped": "skipped"}

type Record = dict[str, JsonValue]


class WorkflowRunError(CliError):
    """A run folder that cannot be made or read."""


def run_folder(hub: Path, run_id: str) -> Path:
    return hub / RUNS_ROOT / run_id


def make_run(folder: Path) -> None:
    """Make the run's folder; refused when the run already exists."""
    try:
        folder.mkdir(parents=True)
    except FileExistsError:
        raise WorkflowRunError(f"the run {folder.name} already exists") from None
    except OSError as error:
        raise WorkflowRunError(f"cannot make the run {folder.name}: {error}") from None


@contextlib.contextmanager
def run_lock(folder: Path) -> Iterator[None]:
    """Hold ``<run>/lock`` (an exclusive ``flock``) for the block; refused while another
    process holds it. The lock file is opened without following a link."""
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        descriptor = os.open(folder / LOCK, flags, 0o600)
    except OSError as error:
        raise WorkflowRunError(f"cannot lock the run {folder.name}: {error}") from None
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise WorkflowRunError(
                f"the run {folder.name} is in use by another hub workflow run"
            ) from None
        yield
    finally:
        os.close(descriptor)


def snapshot_run(
    folder: Path,
    *,
    document: JsonValue,
    plan: WorkflowPlan,
    pack_root: Path,
    includes: Mapping[str, JsonValue] | None = None,
) -> tuple[Path, str]:
    """Write the run's snapshot; its pack root and content hash. Each pack file is read once
    and at most ``MAX_SNAPSHOT_FILE_BYTES``; each included workflow is kept as
    ``includes/<name>.json`` (``snapshot_includes`` resolves them on resume)."""
    snapshot = folder / SNAPSHOT
    files = {DOCUMENT: json.dumps(document, sort_keys=True).encode()}
    for name, included in (includes or {}).items():
        files[f"{INCLUDES}/{name}.json"] = json.dumps(included, sort_keys=True).encode()
    for pack_folder, relative in sorted(set(_pack_files(plan))):
        name = f"{pack_folder}/{relative}"
        try:
            source = resolve_pack_file(pack_root, pack_folder, relative)
            with source.open("rb") as file:
                data = file.read(MAX_SNAPSHOT_FILE_BYTES + 1)
        except (PackPathError, OSError) as error:
            raise WorkflowRunError(f"cannot copy {name}: {error}") from None
        if len(data) > MAX_SNAPSHOT_FILE_BYTES:
            raise WorkflowRunError(f"{name} is larger than {MAX_SNAPSHOT_FILE_BYTES} bytes")
        files[name] = data
    try:
        for name, data in files.items():
            target = snapshot / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    except OSError as error:
        raise WorkflowRunError(f"cannot write the run's snapshot: {error}") from None
    return snapshot, snapshot_hash(snapshot)


def snapshot_hash(snapshot: Path) -> str:
    """``sha256:`` over the snapshot's files in name order, each as ``<name>\\0<len>\\0<bytes>``;
    a link in it is refused."""
    digest = hashlib.sha256()
    try:
        paths = sorted(
            path for path in snapshot.rglob("*") if path.is_symlink() or not path.is_dir()
        )
        for path in paths:
            if path.is_symlink() or not path.is_file():
                raise WorkflowRunError(f"the snapshot holds a link or a special file: {path.name}")
            data = path.read_bytes()
            name = path.relative_to(snapshot).as_posix()
            digest.update(f"{name}\0{len(data)}\0".encode() + data)
    except OSError as error:
        raise WorkflowRunError(f"cannot read the run's snapshot: {error}") from None
    return f"sha256:{digest.hexdigest()}"


def snapshot_includes(snapshot: Path) -> IncludeResolver:
    """Resolve an include from the run's snapshot: the workflow as the run started with it."""

    def resolve(name: str) -> WorkflowDocument | None:
        path = snapshot / INCLUDES / f"{name}.json"
        if not INCLUDE_NAME.fullmatch(name) or not path.is_file():
            return None
        try:
            return parse_workflow(json.loads(path.read_bytes()))
        except (OSError, ValueError) as error:
            raise WorkflowRunError(f"cannot read the snapshot of {name}: {error}") from None

    return resolve


def _pack_files(plan: WorkflowPlan) -> Iterator[tuple[PackFolder, str]]:
    for node in plan.all_nodes():
        if isinstance(node, AgentNode | LoopNode) and node.prompt_file is not None:
            yield "prompts", node.prompt_file
        elif isinstance(node, ScriptNode):
            yield "scripts", node.script


def read_records(folder: Path) -> list[Record]:
    """The run's records; a last line without its newline (a torn write) is left out. A file
    past ``MAX_RECORDS_BYTES``, or a line that is not one JSON object, is refused."""
    try:
        with (folder / RECORDS).open("rb") as file:
            data = file.read(MAX_RECORDS_BYTES + 1)
    except OSError as error:
        raise WorkflowRunError(f"cannot read the run {folder.name}: {error}") from None
    if len(data) > MAX_RECORDS_BYTES:
        raise WorkflowRunError(f"cannot read the run {folder.name}: its record is too large")
    lines = data.split(b"\n")
    records: list[Record] = []
    # The last item follows the last newline: empty, or a line cut short.
    for line in lines[:-1]:
        try:
            value = json.loads(line)
        except ValueError:
            value = None
        if not isinstance(value, dict):
            raise WorkflowRunError(f"cannot read the run {folder.name}: a record is not an object")
        records.append(value)
    return records


def drop_torn_tail(folder: Path) -> None:
    """Cut ``records.jsonl`` back to its last newline, so the next record starts on a line of
    its own after a torn write. Called under the run's lock, before the first append."""
    try:
        with (folder / RECORDS).open("r+b") as file:
            size = file.seek(0, os.SEEK_END)
            start = max(0, size - MAX_RECORDS_BYTES)
            file.seek(start)
            data = file.read()
            if data.endswith(b"\n") or not data:
                return
            file.truncate(start + data.rfind(b"\n") + 1)
    except OSError as error:
        raise WorkflowRunError(f"cannot repair the run {folder.name}: {error}") from None


def append_record(folder: Path, record: Record) -> None:
    line = {"ts": now().isoformat(timespec="seconds"), **record}
    try:
        with (folder / RECORDS).open("a", encoding="utf-8") as file:
            file.write(json.dumps(line, sort_keys=True) + "\n")
    except OSError as error:
        raise WorkflowRunError(f"cannot write the run {folder.name}: {error}") from None


def prior_state(records: list[Record]) -> RunState:
    """The state a run left: each node's last result (a reuse keeps the one reused), the last
    attempt of each node, the sessions it recorded last, and the gates no step end closed."""
    nodes: dict[str, NodeResult] = {}
    attempts: dict[str, int] = {}
    sessions: dict[str, str] = {}
    gates: dict[str, OpenGate] = {}
    groups: dict[str, HeldGroup] = {}
    for record in records:
        node, event = record.get("node"), record.get("event")
        if event == "sessions" and isinstance(given := record.get("sessions"), dict):
            sessions = {key: value for key, value in given.items() if isinstance(value, str)}
        if event == "held" and isinstance(held := record.get("groups"), dict):
            groups = {key: group for key, value in held.items() if (group := _held(value))}
        if not isinstance(node, str) or not isinstance(attempt := record.get("attempt"), int):
            continue
        attempts[node] = max(attempts.get(node, 0), attempt)
        if event == "gate":
            gates[node] = OpenGate(attempt, _instant(record.get("due")))
        elif event == "step_end":
            gates.pop(node, None)
            groups.pop(node, None)
        state = _STATES.get(str(record.get("status")))
        if event == "step_end" and state and record.get("skip_cause") != "prior_success":
            output = record.get("output") if state == "completed" else None
            nodes[node] = NodeResult(state, output)  # type: ignore[arg-type]
    return RunState(nodes, attempts, sessions, gates, groups)


def held_record(state: RunState) -> Record:
    """The ``held`` record of a paused run: each group paused inside an iteration."""
    groups: dict[str, JsonValue] = {
        group_id: {
            "attempt": held.attempt,
            "iteration": held.iteration,
            "previous": _results(held.previous),
            "current": _results(held.current),
        }
        for group_id, held in state.groups.items()
    }
    return {"event": "held", "groups": groups}


def _results(results: Mapping[str, NodeResult]) -> JsonValue:
    return {
        node: {"state": result.state, "output": result.output} for node, result in results.items()
    }


def _held(value: JsonValue) -> HeldGroup | None:
    if not isinstance(value, dict):
        return None
    attempt, iteration = value.get("attempt"), value.get("iteration")
    if not isinstance(attempt, int) or not isinstance(iteration, int):
        return None
    return HeldGroup(
        attempt, iteration, _parsed(value.get("previous")), _parsed(value.get("current"))
    )


def _parsed(value: JsonValue) -> dict[str, NodeResult]:
    results: dict[str, NodeResult] = {}
    for node, result in (value if isinstance(value, dict) else {}).items():
        if isinstance(result, dict) and result.get("state") in _STATES.values():
            results[node] = NodeResult(result["state"], result.get("output"))  # type: ignore[arg-type]
    return results


def _instant(value: JsonValue) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


class RecordedAnswers:
    """The ``GateAnswers`` of a run: its ``decision`` records, by node and attempt."""

    def __init__(self, records: list[Record]) -> None:
        self.answers: dict[tuple[str, int], GateAnswer] = {}
        for record in records:
            node, attempt = record.get("node"), record.get("attempt")
            if record.get("event") != "decision" or not isinstance(node, str):
                continue
            if isinstance(attempt, int):
                choice, text = record.get("choice"), record.get("text")
                self.answers.setdefault(
                    (node, attempt),
                    GateAnswer(
                        choice if isinstance(choice, str) else None,
                        text if isinstance(text, str) else None,
                    ),
                )

    def answer(self, node: str, attempt: int) -> GateAnswer | None:
        return self.answers.get((node, attempt))


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

    def gate_requested(self, request: GateRequest) -> None:
        due = None if request.due is None else request.due.isoformat()
        record: Record = {"event": "gate", "node": request.node, "attempt": request.attempt}
        self._record(
            record
            | {
                "gate_id": gate_id(self.folder.name, request.node, request.attempt),
                "kind": request.kind,
                "form": request.form,
                "choices": list(request.choices),
                "message": request.text,
                "due": due,
            }
        )
        self.events.gate_requested(request)
        self.sink.flush(self.events)

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
