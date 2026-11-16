"""``hub claim take TICKET --session ID``, ``hub claim wait TICKET --session ID --question TEXT``
and ``hub claim release TICKET --session ID``: the local record of which session works on a
ticket (ADR 0064, plan decisions P4 and P5), and the owner question it waits on (AGH-811).

``take`` writes ``.agent-runs/claims/<ticket>.json`` in the hub (``Claim``'s seven fields: the
ticket, the session, its Claude Code process id and start time, the hub folder, when it was
claimed and its last activity; its three optional ones, ``question``, ``asked_at`` and
``title``, appear in the file only once set) and prints one JSON line, its ``verdict``:

- ``claimed``: there was no claim; this session now holds it.
- ``refreshed``: this session already held it; ``last_activity`` (and the process) moves,
  ``claimed_at`` and ``title`` stay, and ``question`` and ``asked_at`` are cleared (the session
  works again).
- ``live``: another session holds it and still works (``claim_state``, AM-3); nothing is
  written, and ``holder`` names that session.
- ``took_over``: another session held it and has ended; this session now holds it, and
  ``previous`` and ``reason`` say whose claim it replaced and why it was stale.

``wait`` records the owner question this session stopped on, when it asked it, and ``--title``
(the session's title, when given) in the claim when this session holds it (``waiting``), else
changes nothing (``not_held``). A question that is empty, longer than ``MAX_QUESTION``
characters, or holds a line break or another character that does not print, is refused with
exit 2 before any file is read; so is such a title, or one longer than ``MAX_TEXT``.

``release`` removes the file when this session holds it (``released``), else changes nothing
(``not_held``). Every line holds ``verdict`` and ``ticket``; ``take``'s also hold ``holder``
(``session``, ``pid``, ``hub``), the session that holds the claim once the command ends.

The process id (P5) is the nearest ancestor of this command whose command line is Claude Code's:
argv0's base name is ``claude``, or it is ``node`` and argv1's is. The walk starts at the parent
and reads one ``ps -o ppid=,lstart=,args= -p <pid>`` per level, at most ``MAX_LEVELS``, each
killed after ``PS_TIMEOUT`` seconds, its ``args`` cut at ``MAX_ARGS_CHARS``. No match, or a
``ps`` that fails, records ``pid`` and ``started`` as null, and the claim goes stale on time
alone (AM-3). Whether another session's process still runs is read the same way, with
``ps -o lstart= -p <pid>``: a failing exit with no output at all means the process is gone;
when ``ps`` cannot run, or fails and prints anything, that claim counts as live.

``take`` reads the host's process table, which the sandbox hides, so the hub's settings run
``hub claim`` outside it. Each subcommand writes a file, so no allow rule covers it: it asks (P3).

Every read, decision and write runs under an exclusive, non-blocking ``flock`` on
``.agent-runs/claims/.lock`` (as ``api/start_ledger.py``): held by another ``hub claim``, the
command prints one line and exits 1, writing nothing. The folder is made owner-only when this
command creates it; a folder that already exists keeps its mode. A claim is read without
following a link, up to ``MAX_CLAIM_BYTES``, and validated as a ``Claim`` for that ticket; one
that cannot be read exits 2 with ``cannot read the claim <path>: <why>`` and is never
overwritten. A new claim goes to an owner-only temp file in the folder (``O_EXCL``), then is
renamed over the claim, so a reader sees the old claim or the new one, never a part. The folder
is not synced after the rename (as ``api/start_ledger.py``): a crash right after it can leave the
old claim. A failed write removes the temp file and exits 1. A ticket outside
``TICKET_PATTERN`` (so the file name cannot leave the folder) or a session id outside
``SAFE_SEGMENT`` is refused with exit 2 before any file is read.

Exit codes: 0 for every verdict, 1 for a held lock or a failed write, 2 for a bad argument or an
unreadable claim.
"""

import contextlib
import fcntl
import json
import os
import re
import stat
import uuid
from collections.abc import Callable, Iterator, Sequence
from os import getppid
from pathlib import Path
from typing import Annotated, Final

import typer
from pydantic import ValidationError

from agent_hub.cli.child_process import ChildResult, run_child
from agent_hub.cli.command_exits import fail
from agent_hub.cli.errors import ChildTimedOutError
from agent_hub.cli.hub_root import hub_root_or_exit
from agent_hub.cli.init_report import shown_path
from agent_hub.cli.workflow_runs import SystemClock
from agent_hub.core.claims.claim import (
    MAX_QUESTION,
    MAX_TEXT,
    TICKET_PATTERN,
    Claim,
    Live,
    Stale,
    claim_state,
)
from agent_hub.core.hub_config.text_shapes import SAFE_SEGMENT

COMMAND: Final = "claim"
CLAIMS_FOLDER: Final = (".agent-runs", "claims")
LOCK_FILE: Final = ".lock"
# A claim file is at most this many bytes; a larger one is unreadable.
MAX_CLAIM_BYTES: Final = 4096
# The walk to the Claude Code process reads at most this many ancestors.
MAX_LEVELS: Final = 10
# One ``ps`` call is killed after this many seconds.
PS_TIMEOUT: Final = 5.0
# Each ancestor's command line is cut to this many characters.
MAX_ARGS_CHARS: Final = 4096
UNREADABLE_EXIT: Final = 2
# ``lstart`` is five words: ``Sat Nov 15 10:04:27 2026``.
_LSTART_WORDS: Final = 5
_PS_OUTPUT_LIMIT: Final = 2 * MAX_ARGS_CHARS
_CLAUDE: Final = "claude"
_NODE: Final = "node"
_TICKET: Final = re.compile(TICKET_PATTERN)
_SESSION: Final = re.compile(SAFE_SEGMENT)
_NO_LINK: Final = os.O_NOFOLLOW | os.O_CLOEXEC
_TICKET_HINT: Final = "give a tracker id such as AGH-827: capitals and digits, a dash, a number"
_SESSION_HINT: Final = (
    f"give the session id from the session brief: letters, digits, '_', '.' and '-',"
    f" at most {MAX_TEXT} characters"
)
_QUESTION_HINT: Final = (
    f"give the question in one line of at most {MAX_QUESTION} characters,"
    " with no line break, tab or control character"
)
_TITLE_HINT: Final = (
    f"give the session title in one line of at most {MAX_TEXT} characters,"
    " with no line break, tab or control character"
)
# The optional claim fields left out of the file while they are None.
_OPTIONAL_FIELDS: Final = ("question", "asked_at", "title")

# Runs one ``ps`` call; raises ``ChildTimedOutError`` or ``OSError`` when it gives no result.
type Ps = Callable[[Sequence[str]], ChildResult]

claim_app = typer.Typer(
    name=COMMAND,
    no_args_is_help=True,
    help="Record which session works on a ticket: take or release its claim.",
)

Ticket = Annotated[str, typer.Argument(metavar="TICKET", help="The tracker id, such as AGH-827.")]
Session = Annotated[
    str,
    typer.Option("--session", metavar="ID", help="This session's id, from the session brief."),
]
Question = Annotated[
    str,
    typer.Option(
        "--question", metavar="TEXT", help="The owner question this session stopped on, one line."
    ),
]
Title = Annotated[
    str | None,
    typer.Option("--title", metavar="TEXT", help="This session's title, when it has one."),
]


class _UnreadableClaimError(Exception):
    """The claim file exists but cannot be taken as a claim; the message says why."""


class _ProcessTableError(Exception):
    """``ps`` gave no answer: whether the process runs cannot be told."""


class _PsProbe:
    """``ProcessProbe`` over ``ps -o lstart= -p <pid>``; raises ``_ProcessTableError`` when
    ``ps`` cannot run, or exits non-zero and prints anything."""

    def __init__(self, ps: Ps) -> None:
        self._ps = ps

    def started(self, pid: int) -> str | None:
        try:
            reply = self._ps(["ps", "-o", "lstart=", "-p", str(pid)])
        except ChildTimedOutError, OSError:
            raise _ProcessTableError from None
        started = " ".join(reply.stdout.decode(errors="replace").split())
        if reply.returncode == 0:
            return started or None
        # For a pid that is not running, ``ps`` exits 1 and prints nothing.
        # Any text with a failing exit is ``ps`` itself failing (refused, a rejected option).
        if started or reply.stderr.strip():
            raise _ProcessTableError
        return None


def claude_process(ps: Ps, parent: int) -> tuple[int, str] | None:
    """The pid and ``lstart`` of the nearest Claude Code process from ``parent`` up (P5), or
    None when none is found within ``MAX_LEVELS`` or ``ps`` fails."""
    pid = parent
    for _ in range(MAX_LEVELS):
        if pid <= 0:
            return None
        row = _ps_row(ps, pid)
        if row is None:
            return None
        ppid, lstart, args = row
        if _is_claude(args):
            return pid, lstart
        pid = ppid
    return None


def _ps_row(ps: Ps, pid: int) -> tuple[int, str, str] | None:
    """``pid``'s parent, start time and command line, or None when ``ps`` gives none."""
    try:
        reply = ps(["ps", "-o", "ppid=,lstart=,args=", "-p", str(pid)])
    except ChildTimedOutError, OSError:
        return None
    lines = reply.stdout.decode(errors="replace").splitlines()
    if reply.returncode != 0 or not lines:
        return None
    words = lines[0].split(maxsplit=_LSTART_WORDS + 1)
    if len(words) <= _LSTART_WORDS or not words[0].isdigit():
        return None
    args = words[_LSTART_WORDS + 1] if len(words) > _LSTART_WORDS + 1 else ""
    return int(words[0]), " ".join(words[1 : _LSTART_WORDS + 1]), args[:MAX_ARGS_CHARS]


def _is_claude(args: str) -> bool:
    words = args.split(maxsplit=2)
    if not words:
        return False
    first = os.path.basename(words[0])
    if first == _CLAUDE:
        return True
    return first == _NODE and len(words) > 1 and os.path.basename(words[1]) == _CLAUDE


def _holder(claim: Claim) -> dict[str, object]:
    return {"session": claim.session, "pid": claim.pid, "hub": claim.hub}


def _print(verdict: str, ticket: str, **fields: object) -> None:
    typer.echo(json.dumps({"verdict": verdict, "ticket": ticket, **fields}))


@claim_app.command("take")
def take(ticket: Ticket, *, session: Session) -> None:
    """Claim the ticket for this session unless another live session holds it; print a JSON line."""
    _check(ticket, session)
    root = hub_root_or_exit(os.environ, command=COMMAND)
    ps = _ps_runner(root)
    clock = SystemClock()
    folder = root.joinpath(*CLAIMS_FOLDER)
    path = folder / f"{ticket}.json"
    with _locked(folder):
        held = _read_or_exit(path, ticket)
        now = clock.now()
        previous: Claim | None = None
        reason: str | None = None
        if held is not None and held.session != session:
            try:
                state: Live | Stale = claim_state(held, now, _PsProbe(ps))
            except _ProcessTableError:
                state = Live()
            if isinstance(state, Live):
                _print("live", ticket, holder=_holder(held))
                return
            previous, reason = held, state.reason
        found = claude_process(ps, getppid())
        claim = Claim(
            ticket=ticket,
            session=session,
            pid=None if found is None else found[0],
            started=None if found is None else found[1],
            hub=_hub_text(root),
            claimed_at=now if held is None or previous is not None else held.claimed_at,
            last_activity=now,
            # A refresh keeps the title and drops the question: the session works again.
            title=held.title if held is not None and previous is None else None,
        )
        _write_or_exit(folder, path, claim)
    if previous is not None:
        _print(
            "took_over",
            ticket,
            holder=_holder(claim),
            previous=_holder(previous),
            reason=reason,
        )
    else:
        _print("claimed" if held is None else "refreshed", ticket, holder=_holder(claim))


@claim_app.command("wait")
def wait(ticket: Ticket, *, session: Session, question: Question, title: Title = None) -> None:
    """Record the owner question this session waits on, when it holds the claim; print a line."""
    _check(ticket, session)
    if not _one_line(question, MAX_QUESTION):
        raise typer.BadParameter(_QUESTION_HINT, param_hint="--question")
    if title is not None and not _one_line(title, MAX_TEXT):
        raise typer.BadParameter(_TITLE_HINT, param_hint="--title")
    root = hub_root_or_exit(os.environ, command=COMMAND)
    folder = root.joinpath(*CLAIMS_FOLDER)
    path = folder / f"{ticket}.json"
    with _locked(folder):
        held = _read_or_exit(path, ticket)
        if held is None or held.session != session:
            _print("not_held", ticket)
            return
        asked = Claim.model_validate(
            {
                **held.model_dump(),
                "question": question,
                "asked_at": SystemClock().now(),
                "title": held.title if title is None else title,
            }
        )
        _write_or_exit(folder, path, asked)
    _print("waiting", ticket)


@claim_app.command("release")
def release(ticket: Ticket, *, session: Session) -> None:
    """Remove the ticket's claim when this session holds it; print one JSON line."""
    _check(ticket, session)
    root = hub_root_or_exit(os.environ, command=COMMAND)
    folder = root.joinpath(*CLAIMS_FOLDER)
    path = folder / f"{ticket}.json"
    with _locked(folder):
        held = _read_or_exit(path, ticket)
        if held is None or held.session != session:
            _print("not_held", ticket)
            return
        try:
            path.unlink()
        except OSError as error:
            fail(f"hub {COMMAND}: cannot remove the claim {shown_path(str(path))}: {_why(error)}")
    _print("released", ticket)


def _check(ticket: str, session: str) -> None:
    """Exit 2 when the ticket or the session id has the wrong shape, before any file access."""
    if _TICKET.fullmatch(ticket) is None:
        raise typer.BadParameter(_TICKET_HINT, param_hint="TICKET")
    if len(session) > MAX_TEXT or _SESSION.fullmatch(session) is None:
        raise typer.BadParameter(_SESSION_HINT, param_hint="--session")


def _one_line(text: str, limit: int) -> bool:
    """Whether ``text`` is one non-empty line of at most ``limit`` printable characters."""
    return 0 < len(text) <= limit and text.isprintable()


def _hub_text(root: Path) -> str:
    text = str(root)
    if len(text) > MAX_TEXT:
        fail(f"hub {COMMAND}: the hub path is longer than {MAX_TEXT} characters")
    return text


def _ps_runner(root: Path) -> Ps:
    # ``LC_ALL=C``: ``lstart`` is printed the same way by every ``hub claim``.
    env = {"PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C"}

    def ps(argv: Sequence[str]) -> ChildResult:
        return run_child(
            argv,
            cwd=root,
            env=env,
            timeout=PS_TIMEOUT,
            own_session=False,
            output_limit=_PS_OUTPUT_LIMIT,
        )

    return ps


@contextlib.contextmanager
def _locked(folder: Path) -> Iterator[None]:
    lock = folder / LOCK_FILE
    try:
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        handle = os.open(lock, os.O_RDWR | os.O_CREAT | _NO_LINK, 0o600)
    except OSError as error:
        fail(f"hub {COMMAND}: cannot open the claims lock {shown_path(str(lock))}: {_why(error)}")
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail(
                f"hub {COMMAND}: another hub claim holds the claims lock {shown_path(str(lock))};"
                " run it again"
            )
        yield
    finally:
        # Closing the descriptor releases the lock.
        os.close(handle)


def _read_or_exit(path: Path, ticket: str) -> Claim | None:
    """The claim at ``path``, or None when there is none; exit 2 when it cannot be read."""
    try:
        return _read(path, ticket)
    except _UnreadableClaimError as error:
        typer.echo(f"cannot read the claim {shown_path(str(path))}: {error}", err=True)
        raise typer.Exit(UNREADABLE_EXIT) from None


def _read(path: Path, ticket: str) -> Claim | None:
    try:
        handle = os.open(path, os.O_RDONLY | os.O_NONBLOCK | _NO_LINK)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise _UnreadableClaimError(_why(error)) from None
    try:
        with os.fdopen(handle, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise _UnreadableClaimError("it is not a regular file")
            raw = stream.read(MAX_CLAIM_BYTES + 1)
    except OSError as error:
        raise _UnreadableClaimError(_why(error)) from None
    if len(raw) > MAX_CLAIM_BYTES:
        raise _UnreadableClaimError(f"it is larger than {MAX_CLAIM_BYTES} bytes")
    try:
        claim = Claim.model_validate_json(raw)
    except ValidationError:
        raise _UnreadableClaimError(
            "it is not a claim with the fields hub claim writes; remove it if its session ended"
        ) from None
    if claim.ticket != ticket:
        raise _UnreadableClaimError(f"it names another ticket, {claim.ticket}")
    return claim


def _write_or_exit(folder: Path, path: Path, claim: Claim) -> None:
    # Not ``exclude_none``: ``pid`` and ``started`` have no default, so they stay as null.
    unset = {name for name in _OPTIONAL_FIELDS if getattr(claim, name) is None}
    raw = claim.model_dump_json(exclude=unset).encode()
    if len(raw) > MAX_CLAIM_BYTES:
        fail(f"hub {COMMAND}: the claim would be larger than {MAX_CLAIM_BYTES} bytes")
    temporary = folder / f".{claim.ticket}.{uuid.uuid4().hex}.tmp"
    try:
        handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NO_LINK, 0o600)
        with os.fdopen(handle, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        fail(f"hub {COMMAND}: cannot write the claim {shown_path(str(path))}: {_why(error)}")


def _why(error: OSError) -> str:
    return error.strerror or str(error)
