"""The ``TrackerReader`` contract suite (ADR 0025): the in-memory fake and the Linear GraphQL
adapter honour it.

An implementation's ``tests/contract/`` provides two fixtures: ``issue_board``, a
``FakeIssueBoard`` seeded with ``a_seeded_issue_board()``, and ``tracker_reader``, the
implementation reading that board (the adapter through a fake server over it); then it declares
``class Test<Implementation>(TrackerReaderContract)``. The suite may add issues to the board
before reading. ``blocks`` and ``blocked_by`` have no defined order, so they are compared
sorted. Checks raise ``AssertionError`` by hand: core ships this suite without pytest.
"""

from typing import Final

from agent_hub.core.errors import TrackerError
from agent_hub.core.testing.tracker_reader_fakes import FakeIssueBoard, a_board_issue
from agent_hub.core.tracker.tracker_reader import (
    MAX_READ_IDS,
    IssueSummary,
    TicketSnapshot,
    TrackerReader,
)

# The ids read in full in one call: more than two pages of 50.
WIDE_READ: Final = 120


def _check(condition: bool, message: str) -> None:  # noqa: FBT001 -- an assertion's condition
    if not condition:
        raise AssertionError(message)


def _sorted(summary: IssueSummary) -> IssueSummary:
    return summary.model_copy(
        update={
            "blocks": tuple(sorted(summary.blocks)),
            "blocked_by": tuple(sorted(summary.blocked_by)),
        }
    )


def _by_id(snapshot: TicketSnapshot) -> dict[str, IssueSummary]:
    return {summary.id: _sorted(summary) for summary in snapshot.summaries}


def _ids(snapshot: TicketSnapshot) -> list[str]:
    return [summary.id for summary in snapshot.summaries]


class TrackerReaderContract:
    """What every ``TrackerReader`` returns for the ``issue_board`` it reads."""

    def test_reads_every_field_when_summaries_read(
        self, tracker_reader: TrackerReader, issue_board: FakeIssueBoard
    ) -> None:
        asked = ("DEM-1", "DEM-2", "DEM-3", "DEM-4")

        snapshot = tracker_reader.issue_summaries(asked)

        _check(_ids(snapshot) == list(asked), f"summaries in the asked order: {_ids(snapshot)}")
        expected = {issue_id: issue_board.summary(issue_id) for issue_id in asked}
        _check(_by_id(snapshot) == expected, f"every field as the board holds it: {snapshot}")
        _check(snapshot.missing == (), f"nothing missing: {snapshot.missing}")

    def test_lists_missing_when_ids_unknown_or_malformed(
        self, tracker_reader: TrackerReader
    ) -> None:
        snapshot = tracker_reader.issue_summaries(["DEM-1", "DEM-404", "not an id", "OPS-77"])

        _check(_ids(snapshot) == ["DEM-1"], f"only the known id is read: {_ids(snapshot)}")
        _check(
            snapshot.missing == ("DEM-404", "not an id", "OPS-77"),
            f"unknown and malformed ids are missing, in order: {snapshot.missing}",
        )

    def test_keeps_relations_symmetric_when_both_ends_read(
        self, tracker_reader: TrackerReader
    ) -> None:
        summaries = _by_id(tracker_reader.issue_summaries(["DEM-1", "DEM-2", "DEM-3"]))

        _check(summaries["DEM-1"].blocks == ("DEM-2",), "DEM-1 blocks DEM-2")
        _check(summaries["DEM-2"].blocked_by == ("DEM-1",), "DEM-2 is blocked by DEM-1")
        _check(summaries["DEM-2"].blocks == ("DEM-3",), "DEM-2 blocks DEM-3")
        for left in summaries.values():
            for right in summaries.values():
                _check(
                    (right.id in left.blocks) == (left.id in right.blocked_by),
                    f"{left.id} and {right.id} disagree on their relation",
                )

    def test_lists_external_blockers_when_blocker_not_asked(
        self, tracker_reader: TrackerReader, issue_board: FakeIssueBoard
    ) -> None:
        snapshot = tracker_reader.issue_summaries(["DEM-3"])

        _check(
            _by_id(snapshot)["DEM-3"].blocked_by == ("DEM-2", "OPS-1"),
            "DEM-3 is blocked by DEM-2 and OPS-1",
        )
        _check(
            snapshot.external == (issue_board.bare("DEM-2"), issue_board.bare("OPS-1")),
            f"blockers not asked are external, sorted, without relations: {snapshot.external}",
        )

    def test_reads_every_id_when_hundred_twenty_asked(
        self, tracker_reader: TrackerReader, issue_board: FakeIssueBoard
    ) -> None:
        asked = tuple(f"DEM-{number}" for number in range(100, 100 + WIDE_READ))
        for issue_id in asked:
            issue_board.put(
                a_board_issue(id=issue_id, url=f"https://linear.app/demo/issue/{issue_id}")
            )

        snapshot = tracker_reader.issue_summaries(asked)

        _check(_ids(snapshot) == list(asked), f"all {WIDE_READ} ids read, in order")
        _check(snapshot.missing == (), f"nothing missing: {snapshot.missing}")

    def test_reads_once_when_ids_repeat(self, tracker_reader: TrackerReader) -> None:
        snapshot = tracker_reader.issue_summaries(["DEM-2", "DEM-1", "DEM-2", "DEM-404", "DEM-404"])

        _check(_ids(snapshot) == ["DEM-2", "DEM-1"], f"each id once: {_ids(snapshot)}")
        _check(snapshot.missing == ("DEM-404",), f"each missing id once: {snapshot.missing}")

    def test_raises_too_many_when_ids_over_limit(self, tracker_reader: TrackerReader) -> None:
        asked = [f"DEM-{number}" for number in range(1, MAX_READ_IDS + 2)]

        try:
            tracker_reader.issue_summaries(asked)
        except TrackerError as error:
            _check(error.kind == "too_many", f"kind too_many, got {error.kind}")
        else:
            raise AssertionError("a read over MAX_READ_IDS did not raise")

    def test_holds_no_description_when_summaries_read(self, tracker_reader: TrackerReader) -> None:
        snapshot = tracker_reader.issue_summaries(["DEM-1", "DEM-3"])

        _check("description" not in IssueSummary.model_fields, "no description field")
        _check("description" not in snapshot.model_dump_json(), "no description in the read")
