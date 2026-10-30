"""``make perf``'s fixture: a synthetic event database of about 90 days of sessions.

The plan (``plan_sessions``) and the events (``session_events``) are pure and seeded: the same
``--events`` and ``--seed`` give the same events, and every word comes from ``VOCABULARY`` or the
core builders (``a_session_events``, ``an_event``), so nothing real reaches the file. ``build``
writes them through the event store to ``<path>.partial``, checkpoints the WAL and renames, so a
half-built file never takes the final name; ``ensure`` keeps one such file per key
(``fixture-e<events>-s<seed>-h<alembic head>.db``) in a cache folder.

``python -m scripts.perf.fixture --events N --seed S --out PATH`` builds one by hand;
``--events`` defaults to ``$PERF_EVENTS``, else 400,000.
"""

import argparse
import os
import random
import sqlite3
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path

from alembic.script import ScriptDirectory

from agent_hub.core.events.event import Event
from agent_hub.core.json_form import JsonValue
from agent_hub.core.testing.builders import an_event
from agent_hub.core.testing.session_scenarios import ToolUse, a_session_events
from agent_hub.storage.event_store import open_event_store
from agent_hub.storage.migration import alembic_config

SEED = 599
DEFAULT_EVENTS = 400_000
PROJECT = "perf"
REPO = "perf-api"
CWD = "/work/perf-api"
FEATURE_SLUG = "search-index"
BRANCH_PREFIX = "perf/"
# AGH-7 is the feature's issue: every tenth session works on it and edits the feature's spec.
FEATURE_ISSUE = 7
ISSUE_KEYS = tuple(f"AGH-{n}" for n in range(1, 51))
FIXTURE_START = datetime(2026, 7, 1, 9, 0, 0, tzinfo=UTC)
SPAN = timedelta(days=90)
SESSION_SIZE = 160
BATCH = 5_000
# A session with no tool has a start, a prompt and an end.
SMALLEST_SESSION = 3
FEATURE_EVERY = 10
FAILURE_RATE = 0.05
JITTER_SECONDS = 600
FEATURE_SPEC = f"brain/features/{FEATURE_SLUG}/spec.md"
# The temp hub's perf brain (AGH-614): ``brain/tree-<n>/note-<nnn>.md``, outside
# ``brain/features/`` so no feature scan reads it, and the note the Brain page row opens.
BRAIN_FOLDERS = 6
NOTES_PER_FOLDER = 100
BRAIN_PAGE_NOTE = "tree-3/note-050.md"
WORDS = ("search", "index", "query", "cache", "events", "sessions", "report", "parser", "store")
COMMANDS = ("make check-fast", "make test", "git status", "git diff")
# Every word the fixture writes itself; the core builders add their own fixed ones.
VOCABULARY = (
    *WORDS,
    "perf",
    "api",
    "work",
    "agh",
    "src",
    "py",
    "brain",
    "features",
    "spec",
    "md",
    "path",
    "lines",
    "added",
    "removed",
    "new",
    "file",
    "command",
    "make",
    "check",
    "fast",
    "test",
    "git",
    "status",
    "diff",
    "Read",
    "Edit",
    "Bash",
)


@dataclass(frozen=True)
class PlannedSession:
    """One session of the fixture: its name, start, event count, branch and work."""

    session: str
    start: datetime
    size: int
    git_branch: str
    tools: tuple[ToolUse, ...]
    failed_tools: frozenset[int]
    padded: bool


def session_name(index: int) -> str:
    """The id of the fixture's ``index``-th session."""
    return f"perf-{index:05d}"


PAGE_SESSION = session_name(0)


def _tool(rng: random.Random) -> ToolUse:
    word = rng.choice(WORDS)
    kind = rng.randrange(3)
    if kind == 0:
        return ("Read", {"path": f"src/{word}.py"})
    if kind == 1:
        added, removed = rng.randint(0, 40), rng.randint(0, 20)
        edit: dict[str, JsonValue] = {
            "path": f"src/{word}.py",
            "lines_added": added,
            "lines_removed": removed,
            "new_file": False,
        }
        return ("Edit", edit)
    return ("Bash", {"command": rng.choice(COMMANDS)})


def _sizes(events: int) -> list[int]:
    count = max(1, round(events / SESSION_SIZE))
    if events < count * SMALLEST_SESSION:
        msg = f"cannot plan {events} events: a session holds at least {SMALLEST_SESSION}"
        raise ValueError(msg)
    base, remainder = divmod(events, count)
    return [base + (1 if index < remainder else 0) for index in range(count)]


def plan_sessions(*, events: int, seed: int) -> list[PlannedSession]:
    """Sessions of about 160 events each that add up to exactly ``events``, spread over 90 days."""
    rng = random.Random(seed)  # noqa: S311 - a reproducible fixture, not a secret
    sizes = _sizes(events)
    planned: list[PlannedSession] = []
    for index, size in enumerate(sizes):
        feature = index % FEATURE_EVERY == 0
        issue = FEATURE_ISSUE if feature else rng.randint(1, len(ISSUE_KEYS))
        tool_count = (size - SMALLEST_SESSION) // 2
        tools = tuple(_tool(rng) for _ in range(tool_count))
        if feature and tools:
            spec_edit: ToolUse = ("Edit", {"path": FEATURE_SPEC, "lines_added": rng.randint(1, 20)})
            tools = (spec_edit, *tools[1:])
        failed = frozenset(p for p in range(tool_count) if rng.random() < FAILURE_RATE)
        jitter = timedelta(seconds=rng.randrange(JITTER_SECONDS))
        planned.append(
            PlannedSession(
                session=session_name(index),
                start=FIXTURE_START + SPAN * index / len(sizes) + jitter,
                size=size,
                git_branch=f"{BRANCH_PREFIX}agh-{issue}-{rng.choice(WORDS)}",
                tools=tools,
                failed_tools=failed,
                padded=(size - SMALLEST_SESSION) % 2 == 1,
            )
        )
    return planned


def session_events(planned: PlannedSession) -> list[Event]:
    """The ``planned.size`` events of one session; an even size gets one more user prompt."""
    events = a_session_events(
        planned.session,
        project=PROJECT,
        repo=REPO,
        start=planned.start,
        tools=planned.tools,
        failed_tools=planned.failed_tools,
        cwd=CWD,
        git_branch=planned.git_branch,
    )
    if planned.padded:
        at = planned.start + timedelta(seconds=90)
        events.insert(
            2,
            an_event(
                project=PROJECT,
                session=planned.session,
                repo=REPO,
                agent="main",
                type="message",
                timestamp=at,
                source_id=f"{planned.session}:UserPromptSubmit:{at.isoformat()}:00000000000000ff",
                payload={"role": "user", "chars": 42, "git_branch": planned.git_branch},
            ),
        )
    return events


def _all_events(events: int, seed: int) -> Iterator[Event]:
    for planned in plan_sessions(events=events, seed=seed):
        yield from session_events(planned)


@cache
def alembic_head() -> str:
    """The storage migrations' head revision: part of the cache key."""
    head = ScriptDirectory.from_config(alembic_config("sqlite://")).get_current_head()
    if head is None:
        msg = "the storage migrations have no head revision"
        raise RuntimeError(msg)
    return head


def cache_path(cache_dir: Path, *, events: int, seed: int, head: str) -> Path:
    """The cached fixture's file for this key."""
    return cache_dir / f"fixture-e{events}-s{seed}-h{head}.db"


def _partial_files(path: Path) -> list[Path]:
    return sorted(path.parent.glob(f"{path.name}.partial*"))


def _remove_partials(path: Path) -> None:
    for leftover in _partial_files(path):
        leftover.unlink(missing_ok=True)


def build(path: Path, *, events: int, seed: int) -> None:
    """Write the fixture to ``path``: through ``<path>.partial``, WAL checkpointed, then renamed."""
    partial = Path(f"{path}.partial")
    _remove_partials(path)
    try:
        store = open_event_store(partial)
        batch: list[Event] = []
        for event in _all_events(events, seed):
            batch.append(event)
            if len(batch) == BATCH:
                store.append(batch)
                batch = []
        if batch:
            store.append(batch)
        # The store's engine keeps no pooled connection, so the file is free to switch modes.
        connection = sqlite3.connect(partial)
        try:
            # Leaving WAL mode checkpoints the log and removes -wal and -shm: one file to copy.
            connection.execute("PRAGMA journal_mode=DELETE").fetchall()
        finally:
            connection.close()
        leftovers = [p for p in _partial_files(path) if p != partial]
        if leftovers:
            msg = f"the fixture build left {', '.join(str(p) for p in leftovers)}"
            raise RuntimeError(msg)
        partial.replace(path)
    except BaseException:
        _remove_partials(path)
        raise


type Builder = Callable[..., None]


def ensure(
    cache_dir: Path, *, events: int, seed: int, rebuild: bool, builder: Builder = build
) -> Path:
    """The cached fixture for this key, built first when missing or when ``rebuild`` is set."""
    path = cache_path(cache_dir, events=events, seed=seed, head=alembic_head())
    if path.is_file() and not rebuild:
        return path
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        builder(path, events=events, seed=seed)
    except BaseException:
        _remove_partials(path)
        raise
    return path


def main(argv: Sequence[str], environ: Mapping[str, str]) -> int:
    """Build one fixture file; exit 0 when written."""
    parser = argparse.ArgumentParser(prog="python -m scripts.perf.fixture", description=__doc__)
    parser.add_argument(
        "--events", type=int, default=int(environ.get("PERF_EVENTS", DEFAULT_EVENTS))
    )
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    out: Path = args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    build(out, events=args.events, seed=args.seed)
    print(f"wrote {args.events} events to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], os.environ))
