"""``hub pr-watch GITHUB NUMBER --since TIME [--every SECONDS] [--for MINUTES]``: reads one pull
request until it changes and prints one JSON line (ADR 0063).

The session that opened a pull request runs it as a background command and starts it again
after each exit. It only reads: every call is ``gh api <path>`` with no method flag and no
field, so ``gh`` sends a GET. ``gh`` cannot reach GitHub from inside the sandbox, so the hub's
settings run the command outside it; since it only reads, they pre-allow it as
``./hub pr-watch``. It reads nothing from ``hub.json`` and needs no hub folder.

One read is three calls, in this order: the pull request (``repos/<github>/pulls/<number>``),
the check runs of its head commit (``repos/<github>/commits/<head>/check-runs?per_page=100``)
and its reviews (``repos/<github>/pulls/<number>/reviews?per_page=100``). Only the first page
of each is read, so at most 100 check runs and 100 reviews are counted and a change past them
is not seen. Only this snapshot is kept or printed: ``merged``, ``state``, ``head`` (the commit
id), ``mergeable_state``, ``checks`` (the runs counted by conclusion; a run with none counts
under ``pending``), ``comments``, ``review_comments`` and ``reviews`` (a count). No title,
body, comment or log text is kept.

The watch:

1. When 24 hours or more (``TOTAL_LIMIT``) have passed since ``--since``: ``expired``, with no
   read.
2. A read. The first good one ends the watch when the pull request is merged (``merged``) or
   closed (``closed``); else it is the baseline. A later good read that differs from the
   baseline in any snapshot field ends it (``changed``). A read fails when a call cannot
   start, runs past ``GH_TIMEOUT`` seconds, exits non-zero, answers ``GH_API_OUTPUT_LIMIT``
   bytes or more (it was cut), is not JSON or does not have the shape of GitHub's answer. The
   third failed read in a row (``MAX_FAILED_READS``) ends the watch (``unreadable``); a good
   read clears the count.
3. Then, when the 24 hours have passed: ``expired``. Else, when ``--for`` minutes have passed
   since the command started: ``quiet``. The window is 1 to 110 minutes, 100 by default: Claude
   Code stops a background command after 2 hours.
4. Else it waits ``--every`` seconds (60 to 1800, 300 by default), or less when the window or
   the 24 hours end sooner, and reads again.

The line holds ``event``, ``pr`` (the last good snapshot, or null), ``elapsed_minutes`` (whole
minutes since ``--since``) and, for ``unreadable``, a ``reason`` that names the failed call.
Exit codes: 0 for ``merged``, ``closed``, ``changed``, ``quiet`` and ``expired``; 3
(``UNREADABLE_EXIT``) for ``unreadable``; 2 for a bad argument, before any call. A ``--since``
more than 5 minutes (``SINCE_SKEW``) after the current time is a bad argument: the 24 hours
would count from a time still to come.
"""

import json
import os
import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Final, Literal, TypeGuard

import typer

from agent_hub.cli.child_process import ChildResult, run_child
from agent_hub.cli.errors import ChildTimedOutError
from agent_hub.cli.pr_steps import GH_API_OUTPUT_LIMIT
from agent_hub.cli.run_children import child_env
from agent_hub.cli.workflow_runs import SystemClock
from agent_hub.core.hub_config.text_shapes import SAFE_SEGMENT
from agent_hub.core.json_form import InvalidJsonError, JsonValue, load_json_bytes
from agent_hub.core.workflows.ports import Clock

# The watch of one pull request ends this long after ``--since``, however often it is started.
TOTAL_LIMIT: Final = timedelta(hours=24)
# A ``--since`` up to this long after the current time is taken: two clocks may differ.
SINCE_SKEW: Final = timedelta(minutes=5)
# One ``gh`` call is killed after this many seconds.
GH_TIMEOUT: Final = 30.0
# This many failed reads in a row end the watch.
MAX_FAILED_READS: Final = 3
UNREADABLE_EXIT: Final = 3
MAX_REASON_CHARS: Final = 300
# The key a check run with no conclusion is counted under.
PENDING: Final = "pending"
# ``owner/name``, each part of the shape ``hub.json`` accepts: it lands in the path of a call.
_GITHUB: Final = re.compile(f"{SAFE_SEGMENT}/{SAFE_SEGMENT}")
# A commit id, SHA-1 or SHA-256.
_COMMIT: Final = re.compile(r"[0-9a-f]{40,64}")
_MINUTE: Final = timedelta(minutes=1)
_GITHUB_HINT: Final = "give the repository as owner/name, such as acme/api"
_TIME_HINT: Final = "give an ISO 8601 time, such as 2026-10-26T09:00:00Z"
_AHEAD_HINT: Final = "this time is still to come; give the UTC time the watch first started"

type Event = Literal["merged", "closed", "changed", "quiet", "expired", "unreadable"]
# Runs one ``gh`` call; raises ``ChildTimedOutError`` or ``OSError`` when it gives no result.
type Gh = Callable[[Sequence[str]], ChildResult]


@dataclass(frozen=True, kw_only=True)
class WatchRequest:
    """One watch: the pull request, when its loop started, the interval and the window."""

    github: str
    number: int
    since: datetime
    every: timedelta
    window: timedelta


@dataclass(frozen=True, kw_only=True)
class Snapshot:
    """What one read keeps of a pull request: the fields two reads are compared on."""

    merged: bool
    state: str
    head: str
    mergeable_state: str
    checks: dict[str, int]
    comments: int
    review_comments: int
    reviews: int


@dataclass(frozen=True, kw_only=True)
class WatchEnd:
    """How a watch ended: its event, the last good snapshot and the whole minutes since the
    request's ``since``; ``reason`` names the failed call of an ``unreadable`` end."""

    event: Event
    pr: Snapshot | None
    elapsed_minutes: int
    reason: str | None = None

    @property
    def exit_code(self) -> int:
        return UNREADABLE_EXIT if self.event == "unreadable" else 0

    def line(self) -> str:
        """The JSON line the command prints, without its line break."""
        report: dict[str, object] = {
            "event": self.event,
            "pr": None if self.pr is None else asdict(self.pr),
            "elapsed_minutes": self.elapsed_minutes,
        }
        if self.reason is not None:
            report["reason"] = self.reason
        return json.dumps(report)


class _ReadError(Exception):
    """One call of a read failed; ``reason`` names the call and says why, on one line."""

    def __init__(self, path: str, why: str) -> None:
        self.reason = _one_line(f"gh api {path}: {why}")
        super().__init__(self.reason)


@dataclass
class _Seen:
    """What the reads showed so far: the baseline, the last good snapshot, and the failed reads
    in a row with the reason of the last one."""

    baseline: Snapshot | None = None
    last: Snapshot | None = None
    failed: int = 0
    reason: str | None = None

    def read(self, request: WatchRequest, gh: Gh) -> Event | None:
        """Read the pull request once; the event that ends the watch, or None when it goes on."""
        try:
            snapshot = _read(request, gh)
        except _ReadError as error:
            self.failed += 1
            self.reason = error.reason
            return "unreadable" if self.failed >= MAX_FAILED_READS else None
        self.failed, self.reason, self.last = 0, None, snapshot
        if self.baseline is not None:
            return "changed" if snapshot != self.baseline else None
        if snapshot.merged:
            return "merged"
        if snapshot.state == "closed":
            return "closed"
        self.baseline = snapshot
        return None


def watch(request: WatchRequest, *, gh: Gh, clock: Clock) -> WatchEnd:
    """Read the pull request until it changes, the window ends or the total limit passes."""
    started = clock.now()
    seen = _Seen()
    event: Event | None = "expired" if started - request.since >= TOTAL_LIMIT else None
    while event is None:
        event = seen.read(request, gh)
        now = clock.now()
        if event is None:
            event = _time_event(request, started=started, now=now)
        if event is None:
            clock.sleep(_wait(request, started=started, now=now))
    return WatchEnd(
        event=event,
        pr=seen.last,
        elapsed_minutes=max(0, (clock.now() - request.since) // _MINUTE),
        reason=seen.reason if event == "unreadable" else None,
    )


def _time_event(request: WatchRequest, *, started: datetime, now: datetime) -> Event | None:
    """``expired`` once the total limit has passed since the request's ``since``, else
    ``quiet`` once its window has passed since ``started``; None before both."""
    if now - request.since >= TOTAL_LIMIT:
        return "expired"
    if now - started >= request.window:
        return "quiet"
    return None


def _wait(request: WatchRequest, *, started: datetime, now: datetime) -> timedelta:
    """The wait before the next read: the interval, cut to what is left of the window and of
    the total limit."""
    window_left = request.window - (now - started)
    limit_left = TOTAL_LIMIT - (now - request.since)
    return min(request.every, window_left, limit_left)


def _read(request: WatchRequest, gh: Gh) -> Snapshot:
    """One read: the pull request, the check runs of its head commit and its reviews, in that
    order. Raises ``_ReadError`` at the first call that fails or answers another shape."""
    pull_path = f"repos/{request.github}/pulls/{request.number}"
    pull = _pull_snapshot(_get(gh, pull_path), pull_path)
    checks_path = f"repos/{request.github}/commits/{pull.head}/check-runs?per_page=100"
    checks = _check_counts(_get(gh, checks_path), checks_path)
    reviews_path = f"{pull_path}/reviews?per_page=100"
    reviews = _get(gh, reviews_path)
    if not isinstance(reviews, list):
        raise _ReadError(reviews_path, "the reply is not a list of reviews")
    return replace(pull, checks=checks, reviews=len(reviews))


def _get(gh: Gh, path: str) -> JsonValue:
    """The JSON value ``gh api <path>`` answers; raises ``_ReadError`` when there is none."""
    try:
        reply = gh(["gh", "api", path])
    except ChildTimedOutError as error:
        raise _ReadError(path, str(error)) from None
    except OSError as error:
        raise _ReadError(path, f"gh cannot start: {error}") from None
    if reply.returncode != 0:
        lines = reply.stderr.decode(errors="replace").strip().splitlines()
        raise _ReadError(path, lines[-1] if lines else f"gh exited with code {reply.returncode}")
    if len(reply.stdout) >= GH_API_OUTPUT_LIMIT:
        raise _ReadError(path, f"the reply holds {GH_API_OUTPUT_LIMIT} bytes or more and was cut")
    try:
        return load_json_bytes(reply.stdout)
    except InvalidJsonError as error:
        raise _ReadError(path, f"the reply is {error.message}") from None


def _pull_snapshot(reply: JsonValue, path: str) -> Snapshot:
    """The snapshot of the pull request ``reply`` holds, its checks and reviews not yet counted.

    The head's commit id is checked here, before the path of the next call is built from it.
    """
    pull = reply if isinstance(reply, dict) else {}
    head = pull.get("head")
    sha = head.get("sha") if isinstance(head, dict) else None
    merged, state, mergeable_state = (
        pull.get("merged"),
        pull.get("state"),
        pull.get("mergeable_state"),
    )
    comments, review_comments = pull.get("comments"), pull.get("review_comments")
    if (
        not isinstance(merged, bool)
        or not isinstance(state, str)
        or not isinstance(mergeable_state, str)
        or not _is_count(comments)
        or not _is_count(review_comments)
        or not isinstance(sha, str)
        or _COMMIT.fullmatch(sha) is None
    ):
        raise _ReadError(path, "the reply is not a pull request with the fields the watch reads")
    return Snapshot(
        merged=merged,
        state=state,
        head=sha,
        mergeable_state=mergeable_state,
        checks={},
        comments=comments,
        review_comments=review_comments,
        reviews=0,
    )


def _check_counts(reply: JsonValue, path: str) -> dict[str, int]:
    """The check runs of ``reply`` counted by conclusion, in name order; a run with no
    conclusion counts under ``PENDING``, whatever its status."""
    runs = reply.get("check_runs") if isinstance(reply, dict) else None
    if not isinstance(runs, list):
        raise _ReadError(path, "the reply holds no check_runs list")
    counts: Counter[str] = Counter()
    for run in runs:
        conclusion = run.get("conclusion") if isinstance(run, dict) else None
        counts[conclusion if isinstance(conclusion, str) else PENDING] += 1
    return dict(sorted(counts.items()))


def _is_count(value: JsonValue) -> TypeGuard[int]:
    """Whether ``value`` is a JSON integer (a boolean is not one)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _one_line(text: str) -> str:
    """``text`` as one printable line of ``MAX_REASON_CHARS`` characters at most."""
    printable = "".join(char if char.isprintable() else " " for char in text)
    return " ".join(printable.split())[:MAX_REASON_CHARS]


def parse_since(text: str) -> datetime | None:
    """The instant ``text`` names (UTC when it has no offset), or None when it is no ISO time."""
    try:
        moment = datetime.fromisoformat(text)
        return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)
    except ValueError, OverflowError:
        return None


def pr_watch(
    github: Annotated[
        str, typer.Argument(metavar="GITHUB", help="The repository on GitHub, as owner/name.")
    ],
    number: Annotated[
        int, typer.Argument(metavar="NUMBER", min=1, help="The pull request's number.")
    ],
    *,
    since: Annotated[
        str,
        typer.Option(
            "--since",
            metavar="TIME",
            help="When the watch of this pull request first started (ISO 8601, UTC when it"
            " has no offset); the command ends once 24 hours have passed since then.",
        ),
    ],
    every: Annotated[
        int,
        typer.Option(
            "--every", metavar="SECONDS", min=60, max=1800, help="Seconds between two reads."
        ),
    ] = 300,
    window: Annotated[
        int,
        typer.Option(
            "--for",
            metavar="MINUTES",
            min=1,
            max=110,
            help="Minutes after which the command ends when nothing changed.",
        ),
    ] = 100,
) -> None:
    """Read one pull request until it changes, with GET calls only; print one JSON line."""
    if _GITHUB.fullmatch(github) is None:
        raise typer.BadParameter(_GITHUB_HINT, param_hint="GITHUB")
    started = parse_since(since)
    if started is None:
        raise typer.BadParameter(_TIME_HINT, param_hint="--since")
    clock = SystemClock()
    if started - clock.now() > SINCE_SKEW:
        raise typer.BadParameter(_AHEAD_HINT, param_hint="--since")
    env = child_env(os.environ)

    def gh(argv: Sequence[str]) -> ChildResult:
        # gh stays in this command's process group, so what stops the command stops gh too.
        return run_child(
            argv,
            cwd=Path.cwd(),
            env=env,
            timeout=GH_TIMEOUT,
            own_session=False,
            output_limit=GH_API_OUTPUT_LIMIT,
        )

    request = WatchRequest(
        github=github,
        number=number,
        since=started,
        every=timedelta(seconds=every),
        window=timedelta(minutes=window),
    )
    end = watch(request, gh=gh, clock=clock)
    typer.echo(end.line())
    raise typer.Exit(end.exit_code)
