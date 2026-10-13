import threading
from datetime import UTC, datetime

import pytest

from agent_hub.core.errors import TrackerError
from agent_hub.core.features.ticket_snapshots import SnapshotRequest
from agent_hub.core.testing.tracker_reader_fakes import (
    CountingTrackerReader,
    FailingTrackerReader,
    InMemoryTicketSnapshots,
    InMemoryTrackerReader,
    a_seeded_issue_board,
)
from agent_hub.core.tracker.tracker_reader import MAX_RELATIONS

AS_OF = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)


def _request(transport: str = "api") -> SnapshotRequest:
    return SnapshotRequest.of(project="demo", transport=transport, ids=("DEM-2", "DEM-1", "DEM-2"))


def test_sorts_ids_once_when_request_built() -> None:
    assert _request().ids == ("DEM-1", "DEM-2")


def test_truncates_relations_when_board_over_limit() -> None:
    board = a_seeded_issue_board()
    blocker = board.issues["DEM-1"]
    for number in range(100, 100 + MAX_RELATIONS + 1):
        board.put(blocker.model_copy(update={"id": f"DEM-{number}"}))
        board.block("DEM-1", f"DEM-{number}")

    summary = board.summary("DEM-1")

    assert len(summary.blocks) == MAX_RELATIONS
    assert summary.relations_truncated is True


def test_reads_external_blockers_without_people_or_numbers_when_not_asked() -> None:
    board = a_seeded_issue_board()

    snapshot = InMemoryTrackerReader(board).issue_summaries(["DEM-3"])

    assert snapshot.external == (board.external("DEM-2"), board.external("OPS-1"))
    ops_1 = snapshot.external[1]
    assert (ops_1.title, ops_1.state.type) == ("Synthetic issue OPS-1", "completed")
    assert (ops_1.assignee, ops_1.priority, ops_1.estimate) == (None, None, None)


def test_counts_calls_when_reader_wrapped() -> None:
    gate = threading.Event()
    gate.set()
    reader = CountingTrackerReader(InMemoryTrackerReader(a_seeded_issue_board()), before=gate.wait)

    reader.issue_summaries(["DEM-1"])
    reader.issue_summaries(["DEM-2", "DEM-1"])

    assert (reader.count, reader.calls) == (2, [("DEM-1",), ("DEM-2", "DEM-1")])


def test_raises_kind_when_failing_reader_read() -> None:
    reader = FailingTrackerReader("rate_limited", http_status=429)

    with pytest.raises(TrackerError) as raised:
        reader.issue_summaries(["DEM-1"])

    assert (raised.value.kind, raised.value.http_status, reader.count) == ("rate_limited", 429, 1)


def test_serves_linear_then_stale_when_snapshots_fetched_and_reader_fails() -> None:
    board = a_seeded_issue_board()
    snapshots = InMemoryTicketSnapshots(InMemoryTrackerReader(board), clock=lambda: AS_OF)

    cold = snapshots.cached(_request())
    fresh = snapshots.fetch(_request())
    snapshots.reader = FailingTrackerReader("unavailable", http_status=500)
    stale = snapshots.fetch(_request())

    assert (cold.source, cold.snapshot, cold.failure) == ("plan", None, None)
    assert (fresh.source, fresh.stale, fresh.as_of) == ("linear", False, AS_OF)
    assert fresh.snapshot is not None
    assert [summary.id for summary in fresh.snapshot.summaries] == ["DEM-1", "DEM-2"]
    assert (stale.source, stale.stale, stale.failure, stale.http_status) == (
        "linear",
        True,
        "unavailable",
        500,
    )
    assert snapshots.cached(_request()).snapshot == fresh.snapshot
    assert [name for name, _ in snapshots.calls] == ["cached", "fetch", "fetch", "cached"]


@pytest.mark.parametrize("transport", ["api", "mcp"])
def test_says_not_connected_when_no_reader_or_mcp(transport: str) -> None:
    reader = None if transport == "api" else InMemoryTrackerReader(a_seeded_issue_board())
    snapshots = InMemoryTicketSnapshots(reader)

    for read in (snapshots.fetch(_request(transport)), snapshots.cached(_request(transport))):
        assert (read.source, read.snapshot, read.failure) == ("plan", None, "not_connected")


def test_falls_back_to_plan_when_first_fetch_fails() -> None:
    snapshots = InMemoryTicketSnapshots(FailingTrackerReader("unauthorized", http_status=401))

    read = snapshots.fetch(_request())

    assert (read.source, read.stale, read.failure, read.http_status) == (
        "plan",
        False,
        "unauthorized",
        401,
    )
    assert read.detail is not None
