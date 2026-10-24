"""Debugging a scenario run written as blocks (ADR 0049; docs/design/scenarios.md § Debugging):
its breakpoints, the engine's run control over them, and the debug commands.

A run's breakpoints are block addresses of its pinned tree (the snapshot's document), kept in
``breakpoints.json`` in the run folder: ``{"addresses": [...]}``, written whole (a temporary
file in the folder, then a rename, which replaces a link and never follows one), at most
``MAX_BREAKPOINTS_BYTES`` and ``MAX_BREAKPOINTS`` addresses, in the tree's declaration order.
Each change also appends a ``debug.breakpoints`` line (the set as written) and emits a
``debug.breakpoints`` event (its count). A change takes the breakpoints lock, and the run's own
lock when no process runs the run (dropping the record's torn tail first); while a process runs
it, the change goes beside it, so a breakpoint set during a run takes effect at its next layer.

``FileRunControl`` is the engine's ``RunControl`` for a version-2 run. ``debugging`` reads the
file, never through a link, as each layer starts; a file that cannot be read or parsed (or names
a block the tree does not hold) counts as no breakpoint and appends one
``debug.breakpoints_unreadable`` line (``reason``) per reason and process. A node pauses for a
breakpoint when it is an entry node (``BlockMap.run_entries``: a gated step's ``<step>__ask``
gate, an include's first nodes) of a block the file names, the outermost first. Step mode is on
while the record's last debug command is ``step``: then every leaf block (Do, Wait until, You,
Wait, and an Include as one block) pauses before its entry nodes, except the leaf the Step
released, the first leaf from the block the run paused before, in declaration order (so a Step
from before a container visits the first leaf inside it). The engine visits nodes layer by layer,
so Steps follow that order, not the file's: a Together's paths interleave, and a leaf the run
skips still takes a Step. The pause the run resumes from has taken up the breakpoints of every
block that node enters, at its first visit.

``hub scenario step|continue RUN`` take only a run in a debug pause: once its snapshot still
matches its ``content_hash`` and its ``debug.pause`` line can be read back, the command is
recorded (``debug.command``: ``command``, ``approver``, the paused ``node`` and ``number``, and
its event) under the run's lock, then the run resumes as ``hub workflow run --resume`` does. The
approver is the account (``getpass``), refused when none is known, as a gate decision is.

On an environment that is ``production: true`` in the effective config as read then, a start with
breakpoints, a breakpoints change that leaves any, a Step and a Continue are refused with a plain
reason, recording nothing; and a run that resumes there gets no run control, so no breakpoint or
step pauses it (the engine still goes on with a pass a debug pause stopped). A version-1 run has
no block addresses: every debug command on it is refused.
"""

import contextlib
import fcntl
import getpass
import json
import os
import stat
import tempfile
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

import typer

from agent_hub.cli.collect import hub_project_name
from agent_hub.cli.effective_config import load_effective_config_or_exit
from agent_hub.cli.run_log import now
from agent_hub.cli.workflow_command import (
    check_snapshot,
    continue_run,
    ended_check,
    existing_run,
)
from agent_hub.cli.workflow_runs import (
    DOCUMENT,
    SNAPSHOT,
    EventSink,
    RunInUseError,
    WorkflowRunError,
    append_record,
    drop_torn_tail,
    read_records,
    run_lock,
)
from agent_hub.core.approvals.decide_gate import NO_PERSON
from agent_hub.core.hub_config.effective_environments import (
    EffectiveEnvironments,
    effective_environments,
)
from agent_hub.core.json_form import JsonValue
from agent_hub.core.scenarios.access_policy import find_environment
from agent_hub.core.scenarios.run_record import (
    DEBUG_BREAKPOINTS,
    DEBUG_BREAKPOINTS_UNREADABLE,
    DEBUG_COMMAND,
    RunRecordError,
    debug_resume,
    fold_records,
)
from agent_hub.core.scenarios.scenario_events import ScenarioEvents
from agent_hub.core.scenarios.tree_translate import BlockMap, block_map
from agent_hub.core.workflows.document import WorkflowLoadError, is_tree
from agent_hub.core.workflows.plan import WorkflowPlan
from agent_hub.core.workflows.run_control import DebugPause, PauseReason
from agent_hub.core.workflows.substitution import echo

BREAKPOINTS: Final = "breakpoints.json"
BREAKPOINTS_LOCK: Final = "breakpoints.lock"
MAX_BREAKPOINTS_BYTES: Final = 64 << 10
MAX_BREAKPOINTS: Final = 512
# The blocks Step runs one at a time; containers and stages are entered.
LEAF_KINDS: Final = frozenset({"do", "wait_until", "you", "wait", "include"})
NO_ADDRESSES: Final = (
    "has no block addresses: only a scenario written as blocks (version 2) can be debugged"
)
OFF_PRODUCTION: Final = "debugging runs only off production"

type DebugCommand = Literal["step", "continue"]
type Change = Literal["add", "off", "set"]
type Record = dict[str, JsonValue]


@dataclass(frozen=True)
class RunBlocks:
    """A run's blocks as its plan runs them: the addresses in declaration order, each one's
    entry nodes, and which are leaves."""

    order: tuple[str, ...]
    entries: Mapping[str, tuple[str, ...]]
    leaves: frozenset[str]

    @classmethod
    def of(cls, tree: BlockMap, plan: WorkflowPlan) -> RunBlocks:
        leaves = frozenset(block.address for block in tree.blocks if block.kind in LEAF_KINDS)
        order = tuple(block.address for block in tree.blocks)
        return cls(order, tree.run_entries(plan), leaves)


class FileRunControl:
    """The ``RunControl`` of a version-2 scenario run: its breakpoints from ``breakpoints.json``,
    read as each layer starts, and step mode from its record's last debug command."""

    def __init__(
        self,
        folder: Path,
        blocks: RunBlocks,
        *,
        stepping: bool,
        resumed: DebugPause | None,
        note: Callable[[Record], None],
    ) -> None:
        self._folder, self._blocks, self._stepping, self._note = folder, blocks, stepping, note
        self._lock = threading.Lock()
        self._breakpoints: frozenset[str] = frozenset()
        self._asked: set[str] = set()
        self._noted: set[str] = set()
        self._known = frozenset(blocks.order)
        self._leaf_of = {
            node: address
            for address in blocks.order
            if address in blocks.leaves
            for node in blocks.entries.get(address, ())
        }
        self._blocks_of: dict[str, list[str]] = {}
        for address in blocks.order:
            for node in blocks.entries.get(address, ()):
                self._blocks_of.setdefault(node, []).append(address)
        self._released = _released(blocks, resumed) if stepping else None
        self._taken = frozenset(() if resumed is None else self._blocks_of.get(resumed.node, ()))

    def debugging(self) -> bool:
        found, reason = read_breakpoints(self._folder, self._known)
        with self._lock:
            self._breakpoints = found
            fresh = reason is not None and reason not in self._noted
            if reason is not None:
                self._noted.add(reason)
        if fresh:
            typer.echo(f"run {self._folder.name}: no breakpoint holds: {reason}", err=True)
            self._note({"event": DEBUG_BREAKPOINTS_UNREADABLE, "reason": reason})
        return self._stepping or bool(found)

    def pause_before(self, node: str) -> PauseReason | None:
        with self._lock:
            first = node not in self._asked
            self._asked.add(node)
            breakpoints = self._breakpoints
        leaf = self._leaf_of.get(node) if self._stepping else None
        if leaf is not None:
            return None if first and leaf == self._released else PauseReason(leaf, "step")
        for address in self._blocks_of.get(node, ()):
            if address in breakpoints and not (first and address in self._taken):
                return PauseReason(address, "breakpoint")
        return None


def _released(blocks: RunBlocks, resumed: DebugPause | None) -> str | None:
    """The leaf a Step releases: the first leaf from the block the run paused before."""
    if resumed is None or resumed.block not in blocks.order:
        return None
    start = blocks.order.index(resumed.block)
    return next((address for address in blocks.order[start:] if address in blocks.leaves), None)


def run_control(
    folder: Path,
    content: object,
    plan: WorkflowPlan,
    *,
    records: Sequence[Mapping[str, JsonValue]],
    resumed: DebugPause | None,
    production: bool,
    note: Callable[[Record], None],
) -> FileRunControl | None:
    """The run control of the run in ``folder`` on ``plan``, its snapshot's document
    ``content``; ``None`` for a version-1 run, which has no block addresses, and on a
    ``production`` environment, where no breakpoint or step pauses a run."""
    if production or not is_tree(content):
        return None
    blocks = RunBlocks.of(block_map(content), plan)
    stepping = fold_records(records).debug.stepping
    return FileRunControl(folder, blocks, stepping=stepping, resumed=resumed, note=note)


def pinned_tree(folder: Path) -> BlockMap:
    """The block map of the run's pinned tree (its snapshot's document); refused for a run of
    a version-1 scenario."""
    try:
        content = json.loads((folder / SNAPSHOT / DOCUMENT).read_bytes())
    except (OSError, ValueError) as error:
        raise WorkflowRunError(f"cannot load the scenario run's snapshot: {error}") from None
    if not is_tree(content):
        message = f"the run {folder.name} is of a version 1 scenario, which {NO_ADDRESSES}"
        raise WorkflowRunError(message)
    try:
        return block_map(content)
    except WorkflowLoadError as error:
        raise WorkflowRunError(f"cannot load the scenario run's snapshot: {error}") from None


def addresses_in(
    tree: BlockMap, given: Sequence[str], *, whose: str = "the scenario"
) -> tuple[str, ...]:
    """``given`` in the tree's declaration order, each once; refused naming the first address
    the tree (``whose``) does not hold, or past ``MAX_BREAKPOINTS``."""
    unknown = next((address for address in given if tree.block(address) is None), None)
    if unknown is not None:
        raise WorkflowRunError(f"{whose} has no block {echo(unknown)}")
    wanted = set(given)
    ordered = tuple(block.address for block in tree.blocks if block.address in wanted)
    if len(ordered) > MAX_BREAKPOINTS:
        raise WorkflowRunError(f"a run takes at most {MAX_BREAKPOINTS} breakpoints")
    return ordered


def read_breakpoints(folder: Path, known: frozenset[str]) -> tuple[frozenset[str], str | None]:
    """The addresses ``breakpoints.json`` holds, and why it counts as none when it cannot be
    read, is not the expected JSON or names an address not in ``known``; a missing file is no
    breakpoint and no reason."""
    try:
        data = _read_file(folder / BREAKPOINTS)
    except FileNotFoundError:
        return frozenset(), None
    except OSError as error:
        return frozenset(), f"{BREAKPOINTS} cannot be read: {error.strerror or error}"
    if data is None:
        limit = f"at most {MAX_BREAKPOINTS_BYTES} bytes"
        return frozenset(), f"{BREAKPOINTS} is not a regular file of {limit}"
    addresses = _addresses(data)
    if addresses is None:
        shown = f"a list of at most {MAX_BREAKPOINTS} addresses"
        return frozenset(), f"{BREAKPOINTS} is not an object with {shown}"
    unknown = next((address for address in addresses if address not in known), None)
    if unknown is not None:
        return frozenset(), f"{BREAKPOINTS} names {echo(unknown)}, not a block of the run's tree"
    return frozenset(addresses), None


def _read_file(path: Path) -> bytes | None:
    """The file's bytes, opened through no link (nor blocking on a FIFO); ``None`` when it is
    not a regular file or passes ``MAX_BREAKPOINTS_BYTES``."""
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    with os.fdopen(os.open(path, flags), "rb") as file:
        if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
            return None
        data = file.read(MAX_BREAKPOINTS_BYTES + 1)
    return None if len(data) > MAX_BREAKPOINTS_BYTES else data


def _addresses(data: bytes) -> list[str] | None:
    try:
        parsed = json.loads(data)
    except ValueError:
        return None
    addresses = parsed.get("addresses") if isinstance(parsed, dict) else None
    if not isinstance(addresses, list) or len(addresses) > MAX_BREAKPOINTS:
        return None
    texts = [item for item in addresses if isinstance(item, str)]
    return texts if len(texts) == len(addresses) else None


def write_breakpoints(folder: Path, addresses: Sequence[str]) -> None:
    """Replace ``breakpoints.json`` whole: a temporary file in the run folder, then a rename."""
    data = json.dumps({"addresses": list(addresses)}).encode() + b"\n"
    try:
        descriptor, name = tempfile.mkstemp(dir=folder, prefix=f".{BREAKPOINTS}.", suffix=".tmp")
        try:
            with os.fdopen(descriptor, "wb") as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            os.replace(name, folder / BREAKPOINTS)
        except BaseException:
            Path(name).unlink(missing_ok=True)
            raise
    except OSError as error:
        message = f"cannot write the run {folder.name}'s breakpoints: {error.strerror or error}"
        raise WorkflowRunError(message) from None


def record_breakpoints(
    hub: Path, folder: Path, addresses: Sequence[str], *, header: Mapping[str, JsonValue]
) -> None:
    """Write ``addresses`` as the run's breakpoints, then their record line and event."""
    write_breakpoints(folder, addresses)
    earlier = read_records(folder)
    number = 1 + sum(1 for line in earlier if line.get("event") == DEBUG_BREAKPOINTS)
    append_record(folder, {"event": DEBUG_BREAKPOINTS, "addresses": list(addresses)})
    events = _events(hub, folder, header)
    events.breakpoints_set(len(addresses), number=number, at=now())
    EventSink().flush(events)


def on_production(view: EffectiveEnvironments, environment: str) -> bool:
    """Whether ``environment`` is ``production: true`` in ``view``."""
    found = find_environment(view, environment)
    return found is not None and found.production


def refuse_on_production(hub: Path, environment: str, *, what: str) -> None:
    """Refuse ``what`` when ``environment`` is ``production: true`` in the effective config as
    read now."""
    effective = load_effective_config_or_exit(hub)
    if on_production(effective_environments(effective.config, effective.local), environment):
        raise WorkflowRunError(
            f"{environment} is a production environment: {what} is refused there ({OFF_PRODUCTION})"
        )


def change_breakpoints(
    hub: Path, run: str, given: Sequence[str], *, change: Change
) -> tuple[str, ...]:
    """Add (``add``), remove (``off``) or replace (``set``) the breakpoints of scenario run
    ``run``; the set written. Nothing is written when it is refused."""
    folder = existing_run(hub, run)
    with _changing(folder):
        header, tree = _debuggable(folder, run)
        named = addresses_in(tree, given, whose=f"the run {run}'s pinned tree")
        current, _ = read_breakpoints(folder, frozenset(block.address for block in tree.blocks))
        kept = {"add": current | set(named), "off": current - set(named), "set": set(named)}
        written = addresses_in(tree, sorted(kept[change]))
        if written:
            refuse_on_production(hub, str(header.get("environment")), what="setting breakpoints")
        record_breakpoints(hub, folder, written, header=header)
    return written


@contextlib.contextmanager
def _changing(folder: Path) -> Iterator[None]:
    """Hold the breakpoints lock and, when no process runs the run, the run's lock (its
    record's torn tail dropped); while one runs it, its record is sound and the change goes
    beside it."""
    with _breakpoints_lock(folder), contextlib.ExitStack() as stack:
        try:
            stack.enter_context(run_lock(folder))
        except RunInUseError:
            pass
        else:
            drop_torn_tail(folder)
        yield


@contextlib.contextmanager
def _breakpoints_lock(folder: Path) -> Iterator[None]:
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        descriptor = os.open(folder / BREAKPOINTS_LOCK, flags, 0o600)
    except OSError as error:
        message = f"cannot lock the run {folder.name}'s breakpoints: {error}"
        raise WorkflowRunError(message) from None
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise WorkflowRunError(
                f"the run {folder.name}'s breakpoints are being changed by another command"
            ) from None
        yield
    finally:
        os.close(descriptor)


def send_command(hub: Path, run: str, command: DebugCommand) -> int:
    """Record ``command`` for scenario run ``run``, in a debug pause, then resume it; the
    resumed run's exit code."""
    folder = existing_run(hub, run)
    with run_lock(folder):
        drop_torn_tail(folder)
        header, _ = _debuggable(folder, run)
        records = read_records(folder)
        refuse_on_production(hub, str(header.get("environment")), what=f"a {command}")
        pause = fold_records(records).debug.pause
        if pause is None:
            raise WorkflowRunError(
                f"the run {run} is not in a debug pause: {command} resumes only a run paused"
                " by a breakpoint or by step"
            )
        # The resume's own checks first: a command it would refuse is not recorded.
        check_snapshot(folder, header)
        try:
            debug_resume(records)
        except RunRecordError as error:
            raise WorkflowRunError(f"cannot resume the run {run}: {error}") from None
        approver = debug_approver(command)
        line: Record = {"event": DEBUG_COMMAND, "command": command, "approver": approver}
        append_record(folder, line | {"node": pause.node, "number": pause.number})
        events = _events(hub, folder, header)
        at = now()
        events.debug_commanded(
            command, approver=approver, node=pause.node, number=pause.number, at=at
        )
        EventSink().flush(events)
        typer.echo(f"run {run}: {command} from {pause.block}")
        return continue_run(hub, folder)


def debug_approver(command: str) -> str:
    """The account sending ``command``; refused when none is known (no fallback), as a gate
    decision's approver is."""
    try:
        account = getpass.getuser()
    except KeyError, OSError:
        message = f"the {command} names no person (no account name is known)"
        raise WorkflowRunError(message) from None
    if account.strip().lower() in NO_PERSON:
        raise WorkflowRunError(f"the {command} names no person (approver {account!r})")
    return account


def _debuggable(folder: Path, run: str) -> tuple[Mapping[str, JsonValue], BlockMap]:
    """The start record and pinned tree of scenario run ``run``; refused for another run, a
    version-1 scenario's or one that ended done or cancelled."""
    records = read_records(folder)
    header = records[0] if records else {}
    if header.get("kind") != "scenario":
        raise WorkflowRunError(f"{run} is not a scenario run")
    tree = pinned_tree(folder)
    ended_check(folder)
    return header, tree


def _events(hub: Path, folder: Path, header: Mapping[str, JsonValue]) -> ScenarioEvents:
    project = hub_project_name(hub) or hub.name
    label = str(header.get("workflow"))
    return ScenarioEvents(project=project, run_id=folder.name, workflow=label)
