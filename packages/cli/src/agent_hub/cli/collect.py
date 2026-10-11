"""``hub collect``: ingest events into the event database, all or nothing.

Three inputs, one at a time: canonical events as JSON Lines (FILE or stdin), a Claude Code
transcript (``--transcript FILE``, mapped to metadata-only events) or ``hub run`` records
(``--runs PATH``, a ``.agent-runs`` file or folder). Every event is redacted on the way in
(``IngestEvents``). A bad line, an over-bound input or a conflict writes nothing and exits 1.

Transcripts and run records name no project: ``--project`` does, else the ``hub.json`` of the hub
that holds the ``.agent-runs`` folder, else that of the hub root (``AGENT_HUB_ROOT`` or the cwd).
"""

import json
import os
import stat
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Annotated, Final, NoReturn

import typer

from agent_hub.cli.database_path import default_database_path
from agent_hub.cli.errors import CliError
from agent_hub.cli.hub_config_reader import FILE_LABEL, read_hub_bytes
from agent_hub.cli.hub_root import HUB_ROOT_VARIABLE
from agent_hub.collector.errors import CollectorError, InputNotFoundError, InputUnreadableError
from agent_hub.collector.jsonl import ParsedEvent, parse_events, read_stream, read_text
from agent_hub.collector.run_records import RunEventMapper, RunRecordError
from agent_hub.collector.transcript import TranscriptOrigin, parse_transcript
from agent_hub.core.errors import EventConflictError
from agent_hub.core.events.event import Event
from agent_hub.core.events.event_store import AppendResult
from agent_hub.core.ingestion.ingest_events import IngestEvents
from agent_hub.core.json_form import JsonValue
from agent_hub.storage.errors import StorageError
from agent_hub.storage.event_store import open_event_store

STDIN_ARGUMENT = Path("-")
# P3: invalid input, a conflict or a storage failure. Typer keeps 2 for usage errors.
FAILURE = 1
MAX_TRANSCRIPT_BYTES: Final = 256 * 1_048_576
MAX_RUN_FILES: Final = 1_000
MAX_RUN_FILE_BYTES: Final = 64 * 1_048_576
RUNS_FOLDER: Final = ".agent-runs"
RUN_FILE_SUFFIX: Final = ".jsonl"
TRANSCRIPT_AGENT: Final = "main"
ONE_INPUT: Final = "use only one of FILE, --transcript and --runs"
NO_PROJECT: Final = "error: no project: pass --project NAME or run in a hub folder"
# O_NONBLOCK: a FIFO swapped in after the check cannot block the open; fstat then refuses it.
_OPEN_FLAGS: Final = os.O_RDONLY | os.O_NONBLOCK


def collect(
    context: typer.Context,
    file: Annotated[
        Path | None,
        typer.Argument(
            metavar="FILE",
            help="JSON Lines file with one canonical event per line; stdin when omitted or '-'.",
            show_default=False,
        ),
    ] = None,
    *,
    transcript: Annotated[
        Path | None,
        typer.Option(
            "--transcript",
            help="A Claude Code transcript (.jsonl) to ingest as metadata-only events.",
            show_default=False,
        ),
    ] = None,
    runs: Annotated[
        Path | None,
        typer.Option(
            "--runs",
            help="hub run records: a .agent-runs/<date>.jsonl file or a .agent-runs folder.",
            show_default=False,
        ),
    ] = None,
    project: Annotated[
        str | None,
        typer.Option(
            "--project",
            help="Project of --transcript and --runs events. Default: the hub's project.name.",
            show_default=False,
        ),
    ] = None,
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
    """Ingest events (JSON Lines, a transcript or run records), all or nothing."""
    if sum(given is not None for given in (file, transcript, runs)) > 1:
        context.fail(ONE_INPUT)
    if transcript is not None:
        events = _transcript_events(transcript, project=_project_or_exit(project, runs=None))
        result = _ingest_or_exit(events, _database(db), position=_no_position)
    elif runs is not None:
        events = _run_events(runs, project=_project_or_exit(project, runs=runs))
        result = _ingest_or_exit(events, _database(db), position=_no_position)
    else:
        parsed = _parse_or_exit(_read_or_exit(file))
        result = _ingest_or_exit(
            [item.event for item in parsed],
            _database(db),
            position=lambda index: f"line {parsed[index].line_number}: ",
        )
    typer.echo(f"appended {result.appended}, duplicates {result.duplicates}")


def _database(db: Path | None) -> Path:
    # The database is resolved and opened only after the input is read, so bad input never
    # creates one.
    return db or _default_database_path_or_exit()


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


def _transcript_events(path: Path, *, project: str) -> list[Event]:
    text = _bounded_text_or_exit(path, MAX_TRANSCRIPT_BYTES)
    origin = TranscriptOrigin(project=project, repo=None, agent=TRANSCRIPT_AGENT, session=path.stem)
    batch = parse_transcript(text, origin=origin)
    if batch.problems:
        _fail(*(f"line {problem.line_number}: {problem.reason}" for problem in batch.problems))
    return list(batch.events)


def _run_events(path: Path, *, project: str) -> list[Event]:
    mapper = RunEventMapper(project=project)
    events: list[Event] = []
    errors: list[str] = []
    for run_file in _run_files_or_exit(path):
        name = _quoted(run_file)
        text = _bounded_text_or_exit(run_file, MAX_RUN_FILE_BYTES)
        for number, line in enumerate(text.split("\n"), start=1):
            if not line.strip():
                continue
            try:
                events.extend(mapper.map(_record(line)))
            except RunRecordError as error:
                errors.append(f"{name}: line {number}: {error}")
    if errors:
        _fail(*errors)
    return events


def _record(line: str) -> dict[str, JsonValue]:
    try:
        value = json.loads(line)
    except ValueError as error:
        reason = error.msg if isinstance(error, json.JSONDecodeError) else str(error)
        raise RunRecordError(f"invalid JSON: {reason}") from error
    except RecursionError as error:
        msg = "invalid JSON: nested too deeply"
        raise RunRecordError(msg) from error
    if not isinstance(value, dict):
        msg = "expected a JSON object"
        raise RunRecordError(msg)
    return value


def _run_files_or_exit(path: Path) -> list[Path]:
    if not path.exists():
        _fail(f"error: input file not found: {_quoted(path)}")
    if not path.is_dir():
        return [path]
    files = sorted(
        entry
        for entry in path.iterdir()
        if entry.suffix == RUN_FILE_SUFFIX and entry.is_file() and not entry.is_symlink()
    )
    if len(files) > MAX_RUN_FILES:
        _fail(f"error: {_quoted(path)}: more than {MAX_RUN_FILES} {RUN_FILE_SUFFIX} files")
    return files


def _bounded_text_or_exit(path: Path, max_bytes: int) -> str:
    try:
        return _bounded_text(path, max_bytes)
    except CollectorError as error:
        _fail(f"error: {error}")


def _bounded_text(path: Path, max_bytes: int) -> str:
    """The UTF-8 text of the regular file ``path``, refused when larger than ``max_bytes``."""
    quoted = _quoted(path)
    try:
        descriptor = os.open(path, _OPEN_FLAGS)
    except FileNotFoundError as error:
        msg = f"input file not found: {quoted}"
        raise InputNotFoundError(msg) from error
    except OSError as error:
        msg = f"cannot read {quoted}: {error.strerror or error}"
        raise InputUnreadableError(msg) from error
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
        os.close(descriptor)
        why = (
            "not a regular file"
            if not stat.S_ISREG(info.st_mode)
            else f"larger than {max_bytes} bytes"
        )
        msg = f"cannot read {quoted}: {why}"
        raise InputUnreadableError(msg)
    with os.fdopen(descriptor, "rb") as stream:
        return read_stream(stream, name=quoted)


def _project_or_exit(project: str | None, *, runs: Path | None) -> str:
    if project:
        return project
    for hub in _hub_candidates(runs):
        name = hub_project_name(hub)
        if name is not None:
            return name
    _fail(NO_PROJECT)


def _hub_candidates(runs: Path | None) -> list[Path]:
    candidates: list[Path] = []
    if runs is not None:
        folder = runs if runs.is_dir() else runs.parent
        if folder.resolve().name == RUNS_FOLDER:
            candidates.append(folder.resolve().parent)
    candidates.append(Path(os.environ.get(HUB_ROOT_VARIABLE) or Path.cwd()))
    return candidates


def hub_project_name(hub: Path) -> str | None:
    """``project.name`` of the hub's ``hub.json``, read leniently; None when unreadable."""
    content = read_hub_bytes(hub / FILE_LABEL)
    if not isinstance(content, bytes):
        return None
    try:
        document = json.loads(content)
    except ValueError:
        return None
    section = document.get("project") if isinstance(document, dict) else None
    name = section.get("name") if isinstance(section, dict) else None
    return name if isinstance(name, str) and name else None


def _default_database_path_or_exit() -> Path:
    try:
        return default_database_path(os.environ)
    except CliError as error:
        _fail(f"error: {error}")


def _no_position(_index: int) -> str:
    return ""


def _ingest_or_exit(
    events: Sequence[Event], db_path: Path, *, position: Callable[[int], str]
) -> AppendResult:
    try:
        return IngestEvents(open_event_store(db_path)).execute(events)
    except EventConflictError as error:
        # source_id comes from the input: quoted and escaped, so it stays on this one line.
        _fail(
            f"{position(error.position) or 'error: '}conflict: event ({error.source}, "
            f"{json.dumps(error.source_id)}) differs from an event with the same key"
        )
    except StorageError as error:
        _fail(f"error: {error}")


def _quoted(path: Path) -> str:
    # The path comes from the user: quoted and escaped, so a message stays on one line.
    return json.dumps(str(path))


def _fail(*messages: str) -> NoReturn:
    for message in messages:
        typer.echo(message, err=True)
    raise typer.Exit(FAILURE)
