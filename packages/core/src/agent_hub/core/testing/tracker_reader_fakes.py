"""Fakes of the ``TrackerReader`` and ``TicketSnapshots`` ports (AGH-136), over synthetic issues.

``FakeIssueBoard`` is the tracker's data, shared by ``InMemoryTrackerReader`` and an adapter's
fake server (``tracker_linear``'s ``FakeLinearApi``), so the contract suite runs the same on
both. ``CountingTrackerReader`` and ``FailingTrackerReader`` let cache tests count and fail
reads; ``InMemoryTicketSnapshots`` is a cache without expiry for use-case tests.
"""

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final

from agent_hub.core.errors import TrackerError, TrackerFailure
from agent_hub.core.features.ticket_snapshots import SnapshotRead, SnapshotRequest
from agent_hub.core.tracker.tracker_reader import (
    MAX_READ_IDS,
    MAX_RELATIONS,
    IssueState,
    IssueSummary,
    TicketSnapshot,
    TrackerReader,
)

READ_OPERATION: Final = "issue_summaries"
SNAPSHOT_TIME: Final = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)


@dataclass(kw_only=True, slots=True)
class FakeIssueBoard:
    """Issues and their "blocks" edges; tests seed it with ``put`` and ``block``.

    ``issues`` holds each issue without relations; ``edges`` holds ``(blocker, blocked)`` pairs,
    so ``blocks`` and ``blocked_by`` are always symmetric.
    """

    issues: dict[str, IssueSummary] = field(default_factory=dict)
    edges: set[tuple[str, str]] = field(default_factory=set)

    def put(self, summary: IssueSummary) -> None:
        """Store the issue; its own ``blocks`` and ``blocked_by`` are ignored (use ``block``)."""
        self.issues[summary.id] = _bare(summary)

    def block(self, blocker: str, blocked: str) -> None:
        """Record that ``blocker`` blocks ``blocked``; both must be on the board."""
        if blocker not in self.issues or blocked not in self.issues:
            raise KeyError(f"put {blocker} and {blocked} on the board first")
        self.edges.add((blocker, blocked))

    def summary(self, issue_id: str) -> IssueSummary:
        """The issue with its relations, sorted, at most ``MAX_RELATIONS`` per direction."""
        blocks = sorted(blocked for blocker, blocked in self.edges if blocker == issue_id)
        blocked_by = sorted(blocker for blocker, blocked in self.edges if blocked == issue_id)
        return self.issues[issue_id].model_copy(
            update={
                "blocks": tuple(blocks[:MAX_RELATIONS]),
                "blocked_by": tuple(blocked_by[:MAX_RELATIONS]),
                "relations_truncated": max(len(blocks), len(blocked_by)) > MAX_RELATIONS,
            }
        )

    def bare(self, issue_id: str) -> IssueSummary:
        """The issue without relations."""
        return self.issues[issue_id]

    def external(self, issue_id: str) -> IssueSummary:
        """The issue as a blocker not asked is read (``external``): no relations, assignee,
        priority, estimate or parent."""
        return self.issues[issue_id].model_copy(
            update={"assignee": None, "priority": None, "estimate": None, "parent": None}
        )


def _bare(summary: IssueSummary) -> IssueSummary:
    return summary.model_copy(update={"blocks": (), "blocked_by": (), "relations_truncated": False})


def a_board_issue(**overrides: object) -> IssueSummary:
    """A synthetic issue to put on a board: ``DEM-1``, started, assigned, priority 2."""
    fields: dict[str, object] = {
        "id": "DEM-1",
        "title": "Add the collector",
        "state": IssueState(name="In Progress", type="started"),
        "assignee": "Ada Example",
        "url": "https://linear.app/demo/issue/DEM-1",
        "priority": 2,
        "estimate": 3.0,
        "blocks": (),
        "blocked_by": (),
    }
    return IssueSummary.model_validate(fields | overrides)


def a_seeded_issue_board() -> FakeIssueBoard:
    """The synthetic board the contract suite runs on; a fresh board per call.

    ``DEM-1`` (started) blocks ``DEM-2`` (unstarted, unassigned, no priority or estimate);
    ``DEM-2`` and ``OPS-1`` (another team, done) block ``DEM-3`` (completed); ``DEM-4`` is
    canceled and alone.
    """
    board = FakeIssueBoard()
    for issue_id, name, state_type, assignee, priority, estimate in (
        ("DEM-1", "In Progress", "started", "Ada Example", 2, 3.0),
        ("DEM-2", "Todo", "unstarted", None, 0, None),
        ("DEM-3", "Done", "completed", "Grace Example", 1, 1.0),
        ("DEM-4", "Canceled", "canceled", None, 4, 2.0),
        ("OPS-1", "Done", "completed", "Linus Example", 3, None),
    ):
        board.put(
            a_board_issue(
                id=issue_id,
                title=f"Synthetic issue {issue_id}",
                state=IssueState.model_validate({"name": name, "type": state_type}),
                assignee=assignee,
                url=f"https://linear.app/demo/issue/{issue_id}",
                priority=priority,
                estimate=estimate,
            )
        )
    board.block("DEM-1", "DEM-2")
    board.block("DEM-2", "DEM-3")
    board.block("OPS-1", "DEM-3")
    return board


def too_many_ids_error(count: int) -> TrackerError:
    """The ``too_many`` failure of a read of ``count`` distinct ids."""
    return TrackerError(
        operation=READ_OPERATION,
        cause=f"{count} issue ids asked, at most {MAX_READ_IDS} per read",
        fix="read fewer ids at a time",
        kind="too_many",
    )


class InMemoryTrackerReader:
    """A ``TrackerReader`` over a ``FakeIssueBoard``."""

    def __init__(self, board: FakeIssueBoard) -> None:
        self._board = board

    def issue_summaries(self, ids: Sequence[str]) -> TicketSnapshot:
        """The board's summaries of ``ids``; unknown ids are missing, blockers not asked are
        external."""
        unique = tuple(dict.fromkeys(ids))
        if len(unique) > MAX_READ_IDS:
            raise too_many_ids_error(len(unique))
        found = tuple(issue_id for issue_id in unique if issue_id in self._board.issues)
        summaries = tuple(self._board.summary(issue_id) for issue_id in found)
        external = sorted(
            {blocker for summary in summaries for blocker in summary.blocked_by} - set(found)
        )
        return TicketSnapshot(
            summaries=summaries,
            missing=tuple(issue_id for issue_id in unique if issue_id not in found),
            external=tuple(self._board.external(issue_id) for issue_id in external),
        )


class CountingTrackerReader:
    """A ``TrackerReader`` that records each call's ids, then reads ``inner``.

    ``before`` runs first on every call (a test can block on an ``Event`` there to hold readers
    in flight). Safe to call from several threads.
    """

    def __init__(self, inner: TrackerReader, *, before: Callable[[], object] | None = None) -> None:
        self._inner = inner
        self._before = before
        self._lock = threading.Lock()
        self.calls: list[tuple[str, ...]] = []

    @property
    def count(self) -> int:
        """How many calls were made."""
        with self._lock:
            return len(self.calls)

    def issue_summaries(self, ids: Sequence[str]) -> TicketSnapshot:
        """Record the call, run ``before``, then read ``inner``."""
        with self._lock:
            self.calls.append(tuple(ids))
        if self._before is not None:
            self._before()
        return self._inner.issue_summaries(ids)


class FailingTrackerReader:
    """A ``TrackerReader`` whose every read fails with ``kind`` (and ``http_status``)."""

    def __init__(self, kind: TrackerFailure, *, http_status: int | None = None) -> None:
        self.kind: TrackerFailure = kind
        self.http_status = http_status
        self.count = 0

    def issue_summaries(self, ids: Sequence[str]) -> TicketSnapshot:
        """Raise ``TrackerError`` with the configured kind."""
        self.count += 1
        raise TrackerError(
            operation=READ_OPERATION,
            cause=f"synthetic {self.kind} failure",
            fix="nothing to fix: a test fake",
            kind=self.kind,
            http_status=self.http_status,
        )


class InMemoryTicketSnapshots:
    """A ``TicketSnapshots`` that keeps each request's last good snapshot forever.

    ``reader`` (settable) is read on every ``fetch``; None, or a request whose transport is
    ``mcp``, is ``not_connected`` without a read. ``calls`` records ``("fetch" | "cached",
    request)`` in order.
    """

    def __init__(
        self,
        reader: TrackerReader | None = None,
        *,
        clock: Callable[[], datetime] = lambda: SNAPSHOT_TIME,
    ) -> None:
        self.reader = reader
        self._clock = clock
        self._kept: dict[SnapshotRequest, SnapshotRead] = {}
        self.calls: list[tuple[str, SnapshotRequest]] = []

    def fetch(self, request: SnapshotRequest) -> SnapshotRead:
        """Read ``reader``; on a failure serve the kept snapshot as stale, else the plan."""
        self.calls.append(("fetch", request))
        if self.reader is None or request.transport != "api":
            return _not_connected()
        try:
            snapshot = self.reader.issue_summaries(request.ids)
        except TrackerError as error:
            kept = self._kept.get(request)
            failed = SnapshotRead(
                snapshot=None,
                source="plan",
                stale=False,
                as_of=None,
                failure=error.kind,
                detail=error.cause,
                http_status=error.http_status,
            )
            if kept is None:
                return failed
            return SnapshotRead(
                snapshot=kept.snapshot,
                source="linear",
                stale=True,
                as_of=kept.as_of,
                failure=error.kind,
                detail=error.cause,
                http_status=error.http_status,
            )
        read = SnapshotRead(
            snapshot=snapshot,
            source="linear",
            stale=False,
            as_of=self._clock(),
            failure=None,
            detail=None,
            http_status=None,
        )
        self._kept[request] = read
        return read

    def cached(self, request: SnapshotRequest) -> SnapshotRead:
        """The kept snapshot, else a cold read (or ``not_connected``)."""
        self.calls.append(("cached", request))
        if self.reader is None or request.transport != "api":
            return _not_connected()
        kept = self._kept.get(request)
        if kept is not None:
            return kept
        return SnapshotRead(
            snapshot=None,
            source="plan",
            stale=False,
            as_of=None,
            failure=None,
            detail=None,
            http_status=None,
        )


def _not_connected() -> SnapshotRead:
    return SnapshotRead(
        snapshot=None,
        source="plan",
        stale=False,
        as_of=None,
        failure="not_connected",
        detail="Linear is not connected for hub web",
        http_status=None,
    )
