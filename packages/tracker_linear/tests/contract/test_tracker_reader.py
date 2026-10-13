"""The TrackerReader contract suite, run against the Linear GraphQL reader (AC-136.1, AC-136.2).

The reader's transport is ``FakeLinearApi`` over the suite's ``issue_board`` (both from
``tests/conftest.py``), paging by 50 as Linear does, so every summary the suite checks went
through the ``ReadIssueSummaries`` query.
"""

from typing import Any

import pytest

from agent_hub.core.testing.tracker_reader_contract import WIDE_READ, TrackerReaderContract
from agent_hub.core.testing.tracker_reader_fakes import FakeIssueBoard
from agent_hub.core.tracker.tracker_reader import TrackerReader
from agent_hub.tracker_linear.graphql_reader import BATCH_SIZE, LinearGraphqlTrackerReader
from agent_hub.tracker_linear.graphql_transport import LINEAR_API_KEY_VARIABLE


@pytest.fixture
def tracker_reader(fake_linear_reader_api: Any, synthetic_key: str) -> TrackerReader:
    return LinearGraphqlTrackerReader(
        environ={LINEAR_API_KEY_VARIABLE: synthetic_key}, post=fake_linear_reader_api
    )


class TestGraphqlTrackerReader(TrackerReaderContract):
    """The TrackerReader contract suite, run against the GraphQL reader over the fake API."""

    def test_sends_full_batches_when_hundred_twenty_read(
        self,
        tracker_reader: TrackerReader,
        issue_board: FakeIssueBoard,
        fake_linear_reader_api: Any,
    ) -> None:
        # AC-136.2: the fake API serves this test's issue_board, so the suite's wide read
        # reaches it in batches of BATCH_SIZE (five requests of 25, 25, 25, 25 and 20).
        self.test_reads_every_id_when_hundred_twenty_asked(tracker_reader, issue_board)

        sizes = [
            len(request["variables"]["filter"]["number"]["in"])
            for request in fake_linear_reader_api.requests
        ]
        full, rest = divmod(WIDE_READ, BATCH_SIZE)
        assert sizes == [BATCH_SIZE] * full + [rest]
