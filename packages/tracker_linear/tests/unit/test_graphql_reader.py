"""The Linear GraphQL tracker reader, over the in-process fake Linear API and its issue board."""

import json
from collections.abc import Callable, Iterator, Mapping
from typing import Any

import pytest

from agent_hub.core.errors import TrackerError
from agent_hub.core.testing.tracker_reader_fakes import FakeIssueBoard, a_board_issue
from agent_hub.core.tracker.tracker_reader import (
    MAX_READ_IDS,
    MAX_RELATIONS,
    IssueState,
    IssueSummary,
)
from agent_hub.tracker_linear.graphql_reader import (
    BATCH_SIZE,
    DEFAULT_DEADLINE_S,
    DEFAULT_TIMEOUT_S,
    READ_ISSUE_SUMMARIES,
    READ_OPERATION,
    LinearGraphqlTrackerReader,
)
from agent_hub.tracker_linear.graphql_transport import LINEAR_API_KEY_VARIABLE

type Post = Callable[..., tuple[int, bytes]]
type Complexity = Callable[[str, Mapping[str, int]], int]

# Half of Linear's 10,000-point cap on one query, so the read keeps a margin.
COMPLEXITY_BUDGET = 5_000


def _reader(
    post: Post, synthetic_key: str, *, clock: Callable[[], float] | None = None
) -> LinearGraphqlTrackerReader:
    if clock is None:
        return LinearGraphqlTrackerReader(
            environ={LINEAR_API_KEY_VARIABLE: synthetic_key}, post=post
        )
    return LinearGraphqlTrackerReader(
        environ={LINEAR_API_KEY_VARIABLE: synthetic_key}, post=post, clock=clock
    )


def _sorted(summary: IssueSummary) -> IssueSummary:
    return summary.model_copy(
        update={
            "blocks": tuple(sorted(summary.blocks)),
            "blocked_by": tuple(sorted(summary.blocked_by)),
        }
    )


def _numbers(api: Any) -> list[list[int]]:
    return [request["variables"]["filter"]["number"]["in"] for request in api.requests]


def _altered(api: Any, alter: Callable[[Any], None]) -> Post:
    """The fake's answers with ``alter`` applied to each answer's ``data`` before it is sent."""

    def post(
        url: str, headers: Mapping[str, str], body: bytes, *, timeout_s: float
    ) -> tuple[int, bytes]:
        status, response = api(url, headers, body, timeout_s=timeout_s)
        payload = json.loads(response)
        alter(payload["data"])
        return status, json.dumps(payload).encode()

    return post


def test_pins_constants_when_module_loaded() -> None:
    assert (DEFAULT_TIMEOUT_S, DEFAULT_DEADLINE_S, BATCH_SIZE) == (10.0, 20.0, 25)
    assert READ_OPERATION == "issue_summaries"


@pytest.mark.parametrize(
    ("query", "points"),
    [
        ('{ user(id: "u") { name } }', 2),
        ('{ user(id: "u") { createdIssues { nodes { id title url } } } }', 66),
        ('{ user(id: "u") { createdIssues(first: 10) { nodes { id title url } } } }', 14),
    ],
)
def test_scores_linear_examples_when_complexity_computed(
    complexity_of: Complexity, query: str, points: int
) -> None:
    # The worked examples of linear.app/developers/rate-limiting.
    assert complexity_of(query, {}) == points


def test_keeps_query_within_linear_complexity_when_batch_is_full(
    complexity_of: Complexity,
) -> None:
    # Linear rejects any query over 10,000 points; ``$first`` is at its largest, BATCH_SIZE.
    points = complexity_of(READ_ISSUE_SUMMARIES, {"first": BATCH_SIZE})

    assert points <= COMPLEXITY_BUDGET
    assert points == 4_679  # noqa: PLR2004 - the score stated next to the query


def test_reads_summaries_when_three_issues_and_one_unknown(
    fake_linear_reader_api: Any, issue_board: FakeIssueBoard, synthetic_key: str
) -> None:
    # AC-136.1: every field, the unknown id missing, and no description ever selected. On the
    # seeded board DEM-1 (assigned, estimated) blocks DEM-2 (no assignee, priority or estimate).
    api = fake_linear_reader_api

    snapshot = _reader(api, synthetic_key).issue_summaries(["DEM-1", "DEM-404", "OPS-1", "DEM-2"])

    assert [summary.id for summary in snapshot.summaries] == ["DEM-1", "OPS-1", "DEM-2"]
    assert [_sorted(summary) for summary in snapshot.summaries] == [
        issue_board.summary("DEM-1"),
        issue_board.summary("OPS-1"),
        issue_board.summary("DEM-2"),
    ]
    dem_1, ops_1, dem_2 = snapshot.summaries
    assert (dem_1.title, dem_1.state, dem_1.assignee) == (
        "Synthetic issue DEM-1",
        IssueState(name="In Progress", type="started"),
        "Ada Example",
    )
    assert (dem_1.url, dem_1.priority, dem_1.estimate) == (
        "https://linear.app/demo/issue/DEM-1",
        2,
        3.0,
    )
    assert dem_1.blocks == ("DEM-2",)
    assert dem_2.blocked_by == ("DEM-1",)
    assert (dem_2.assignee, dem_2.priority, dem_2.estimate) == (None, 0, None)
    assert ops_1.blocks == ("DEM-3",)
    assert snapshot.missing == ("DEM-404",)
    assert snapshot.external == ()
    assert api.requests
    assert all("description" not in request["query"] for request in api.requests)
    assert all(request["operationName"] == "ReadIssueSummaries" for request in api.requests)


def test_groups_ids_by_team_when_teams_mixed(
    fake_linear_reader_api: Any, synthetic_key: str
) -> None:
    _reader(fake_linear_reader_api, synthetic_key).issue_summaries(
        ["DEM-2", "OPS-1", "DEM-1", "DEM-2"]
    )

    filters = [request["variables"]["filter"] for request in fake_linear_reader_api.requests]
    assert filters == [
        {"team": {"key": {"eq": "DEM"}}, "number": {"in": [2, 1]}},
        {"team": {"key": {"eq": "OPS"}}, "number": {"in": [1]}},
    ]
    assert all(
        request["variables"]["first"] == BATCH_SIZE for request in fake_linear_reader_api.requests
    )


def test_sends_five_batches_when_reading_hundred_twenty_ids(
    fake_linear_reader_api: Any, issue_board: FakeIssueBoard, synthetic_key: str
) -> None:
    asked = [f"DEM-{number}" for number in range(100, 220)]
    for issue_id in asked:
        issue_board.put(a_board_issue(id=issue_id, url=f"https://linear.app/demo/issue/{issue_id}"))

    snapshot = _reader(fake_linear_reader_api, synthetic_key).issue_summaries(asked)

    assert [len(numbers) for numbers in _numbers(fake_linear_reader_api)] == [25, 25, 25, 25, 20]
    assert sorted(number for numbers in _numbers(fake_linear_reader_api) for number in numbers) == (
        list(range(100, 220))
    )
    assert [summary.id for summary in snapshot.summaries] == asked


def test_follows_next_page_when_linear_pages_a_batch(
    fake_linear_reader_api: Any, synthetic_key: str
) -> None:
    api = fake_linear_reader_api
    api.page_size = 2

    snapshot = _reader(api, synthetic_key).issue_summaries(["DEM-1", "DEM-2", "DEM-3", "DEM-4"])

    assert [request["variables"]["after"] for request in api.requests] == [None, "2"]
    assert [summary.id for summary in snapshot.summaries] == ["DEM-1", "DEM-2", "DEM-3", "DEM-4"]


def test_lists_malformed_ids_as_missing_when_never_sent(
    fake_linear_reader_api: Any, synthetic_key: str
) -> None:
    snapshot = _reader(fake_linear_reader_api, synthetic_key).issue_summaries(
        ["dem-1", "DEM-0", "DEM 1", "DEM-1"]
    )

    assert snapshot.missing == ("dem-1", "DEM-0", "DEM 1")
    assert _numbers(fake_linear_reader_api) == [[1]]


def test_sends_nothing_when_no_id_well_formed(
    fake_linear_reader_api: Any, synthetic_key: str
) -> None:
    snapshot = _reader(fake_linear_reader_api, synthetic_key).issue_summaries(["x", "DEM-"])

    assert (snapshot.summaries, snapshot.missing, snapshot.external) == ((), ("x", "DEM-"), ())
    assert fake_linear_reader_api.requests == []


def test_lists_external_blockers_when_blocker_not_asked(
    fake_linear_reader_api: Any, issue_board: FakeIssueBoard, synthetic_key: str
) -> None:
    snapshot = _reader(fake_linear_reader_api, synthetic_key).issue_summaries(["DEM-3", "DEM-1"])

    assert snapshot.external == (issue_board.external("DEM-2"), issue_board.external("OPS-1"))
    # DEM-1 blocks DEM-2, which is not asked either: only blockers are external.
    assert _sorted(snapshot.summaries[1]).blocks == ("DEM-2",)


def _answering(answer: Any) -> Post:
    def post(
        url: str, headers: Mapping[str, str], body: bytes, *, timeout_s: float
    ) -> tuple[int, bytes]:
        del url, headers, body, timeout_s
        return 200, json.dumps(answer).encode()

    return post


def test_accepts_recorded_answer_when_shape_checked(
    synthetic_summaries_answer: Any, synthetic_key: str
) -> None:
    # Q7: a hand-written answer in Linear's schema passes the strict shape check.
    post = _answering(synthetic_summaries_answer)

    snapshot = _reader(post, synthetic_key).issue_summaries(["DEM-11", "DEM-12"])

    eleven, twelve = snapshot.summaries
    assert eleven == IssueSummary(
        id="DEM-11",
        title="Synthetic issue eleven",
        state=IssueState(name="In Progress", type="started"),
        assignee="ada.example",
        url="https://linear.app/demo/issue/DEM-11/synthetic-issue-eleven",
        priority=2,
        estimate=3.0,
        blocks=("DEM-12",),
        blocked_by=(),
    )
    assert (twelve.assignee, twelve.priority, twelve.estimate) == (None, 0, None)
    assert twelve.blocked_by == ("DEM-11", "OPS-4")
    assert twelve.parent == "DEM-11"
    assert snapshot.missing == ()
    assert snapshot.external == (
        IssueSummary(
            id="OPS-4",
            title="Synthetic ops issue",
            state=IssueState(name="In Review", type="started"),
            assignee=None,
            url="https://linear.app/demo/issue/OPS-4/synthetic-ops-issue",
            priority=None,
            estimate=None,
            blocks=(),
            blocked_by=(),
        ),
    )


def _drop_estimate(data: Any) -> None:
    del data["issues"]["nodes"][0]["estimate"]


def _add_description(data: Any) -> None:
    data["issues"]["nodes"][0]["description"] = "a body the query never selects"


def _null_title(data: Any) -> None:
    data["issues"]["nodes"][0]["title"] = None


def _state_type_unknown(data: Any) -> None:
    data["issues"]["nodes"][0]["state"]["type"] = "archived"


def _priority_out_of_range(data: Any) -> None:
    data["issues"]["nodes"][0]["priority"] = 7.0


def _priority_fraction(data: Any) -> None:
    data["issues"]["nodes"][0]["priority"] = 1.5


def _priority_boolean(data: Any) -> None:
    data["issues"]["nodes"][0]["priority"] = True


def _identifier_not_asked(data: Any) -> None:
    data["issues"]["nodes"][0]["identifier"] = "DEM-99"


def _identifier_malformed(data: Any) -> None:
    data["issues"]["nodes"][0]["identifier"] = "not an id"


def _related_identifier_malformed(data: Any) -> None:
    data["issues"]["nodes"][0]["relations"]["nodes"][0]["relatedIssue"]["identifier"] = "x\ny"


def _next_page_without_cursor(data: Any) -> None:
    data["issues"]["pageInfo"] = {"hasNextPage": True, "endCursor": None}


@pytest.mark.parametrize(
    "alter",
    [
        _drop_estimate,
        _add_description,
        _null_title,
        _state_type_unknown,
        _priority_out_of_range,
        _priority_fraction,
        _priority_boolean,
        _identifier_not_asked,
        _identifier_malformed,
        _related_identifier_malformed,
        _next_page_without_cursor,
    ],
)
def test_raises_unexpected_when_answer_has_other_shape(
    fake_linear_reader_api: Any, synthetic_key: str, alter: Callable[[Any], None]
) -> None:
    # DEM-1 blocks DEM-2: its node has a relation to alter.
    reader = _reader(_altered(fake_linear_reader_api, alter), synthetic_key)

    with pytest.raises(TrackerError, match=r"^issue_summaries: unexpected response") as raised:
        reader.issue_summaries(["DEM-1"])

    assert raised.value.kind == "unexpected"


def test_raises_unexpected_when_next_page_brings_nothing(
    fake_linear_reader_api: Any, synthetic_key: str
) -> None:
    def endless(data: Any) -> None:
        data["issues"]["nodes"] = []
        data["issues"]["pageInfo"] = {"hasNextPage": True, "endCursor": "more"}

    reader = _reader(_altered(fake_linear_reader_api, endless), synthetic_key)

    with pytest.raises(TrackerError) as raised:
        reader.issue_summaries(["DEM-1"])

    assert raised.value.kind == "unexpected"
    assert len(fake_linear_reader_api.requests) == 1


def test_marks_truncated_when_relations_over_limit(
    fake_linear_reader_api: Any, issue_board: FakeIssueBoard, synthetic_key: str
) -> None:
    blockers = [f"OPS-{number}" for number in range(100, 100 + MAX_RELATIONS + 1)]
    for blocker in blockers:
        issue_board.put(a_board_issue(id=blocker, url=f"https://linear.app/demo/issue/{blocker}"))
        issue_board.block(blocker, "DEM-4")

    snapshot = _reader(fake_linear_reader_api, synthetic_key).issue_summaries(["DEM-4", "DEM-1"])

    busy, calm = snapshot.summaries
    assert busy.relations_truncated is True
    assert len(busy.blocked_by) == MAX_RELATIONS
    assert _sorted(busy) == issue_board.summary("DEM-4")
    assert calm.relations_truncated is False
    assert len(snapshot.external) == MAX_RELATIONS


def _ticking(values: list[float]) -> Callable[[], float]:
    times: Iterator[float] = iter(values)
    return lambda: next(times)


def test_raises_timeout_when_deadline_passes_between_pages(
    fake_linear_reader_api: Any, synthetic_key: str
) -> None:
    clock = _ticking([0.0, DEFAULT_DEADLINE_S + 0.1, DEFAULT_DEADLINE_S + 0.2])
    reader = _reader(fake_linear_reader_api, synthetic_key, clock=clock)

    with pytest.raises(TrackerError, match=r"over 20 s") as raised:
        reader.issue_summaries(["DEM-1", "OPS-1"])

    assert (raised.value.kind, raised.value.http_status) == ("timeout", None)
    assert len(fake_linear_reader_api.requests) == 1


def test_reads_every_page_when_within_deadline(
    fake_linear_reader_api: Any, synthetic_key: str
) -> None:
    clock = _ticking([0.0, DEFAULT_DEADLINE_S - 0.1])
    reader = _reader(fake_linear_reader_api, synthetic_key, clock=clock)

    snapshot = reader.issue_summaries(["DEM-1", "OPS-1"])

    assert [summary.id for summary in snapshot.summaries] == ["DEM-1", "OPS-1"]


def test_reads_two_hundred_ids_when_each_batch_takes_two_seconds(
    fake_linear_reader_api: Any, synthetic_key: str
) -> None:
    # 200 ids of one team are 8 batches of 25: 7 deadline checks, the last at 14 s of 20.
    clock = _ticking([2.0 * tick for tick in range(MAX_READ_IDS // BATCH_SIZE)])
    asked = [f"DEM-{number}" for number in range(1, MAX_READ_IDS + 1)]

    snapshot = _reader(fake_linear_reader_api, synthetic_key, clock=clock).issue_summaries(asked)

    assert len(fake_linear_reader_api.requests) == MAX_READ_IDS // BATCH_SIZE == 8  # noqa: PLR2004
    assert len(snapshot.summaries) + len(snapshot.missing) == MAX_READ_IDS


def test_raises_too_many_when_ids_over_limit(
    fake_linear_reader_api: Any, synthetic_key: str
) -> None:
    asked = [f"DEM-{number}" for number in range(1, MAX_READ_IDS + 2)]

    with pytest.raises(TrackerError) as raised:
        _reader(fake_linear_reader_api, synthetic_key).issue_summaries([*asked, *asked])

    assert raised.value.kind == "too_many"
    assert fake_linear_reader_api.requests == []


def test_reads_limit_when_ids_repeat_up_to_limit(
    fake_linear_reader_api: Any, synthetic_key: str
) -> None:
    asked = [f"DEM-{number}" for number in range(1, MAX_READ_IDS + 1)]

    snapshot = _reader(fake_linear_reader_api, synthetic_key).issue_summaries([*asked, *asked])

    assert len(snapshot.summaries) + len(snapshot.missing) == MAX_READ_IDS
    assert len(fake_linear_reader_api.requests) == MAX_READ_IDS // BATCH_SIZE


def test_raises_not_connected_before_any_request_when_key_missing(
    fake_linear_reader_api: Any,
) -> None:
    reader = LinearGraphqlTrackerReader(environ={}, post=fake_linear_reader_api)

    with pytest.raises(TrackerError) as raised:
        reader.issue_summaries(["DEM-1"])

    assert raised.value.kind == "not_connected"
    assert fake_linear_reader_api.requests == []


@pytest.mark.parametrize(
    ("status", "kind"),
    [(401, "unauthorized"), (429, "rate_limited"), (500, "unavailable")],
)
def test_raises_with_kind_and_status_when_linear_fails(
    synthetic_key: str, status: int, kind: str
) -> None:
    def post(
        url: str, headers: Mapping[str, str], body: bytes, *, timeout_s: float
    ) -> tuple[int, bytes]:
        del url, headers, body, timeout_s
        return status, b"{}"

    with pytest.raises(TrackerError) as raised:
        _reader(post, synthetic_key).issue_summaries(["DEM-1"])

    assert (raised.value.kind, raised.value.http_status) == (kind, status)
    assert raised.value.operation == READ_OPERATION


def test_names_no_key_when_repr_read(synthetic_key: str) -> None:
    reader = LinearGraphqlTrackerReader(environ={LINEAR_API_KEY_VARIABLE: synthetic_key})

    assert synthetic_key not in repr(reader)


def test_lists_asked_order_when_answer_in_other_order(
    synthetic_summaries_answer: Any, synthetic_key: str
) -> None:
    snapshot = _reader(_answering(synthetic_summaries_answer), synthetic_key).issue_summaries(
        ["DEM-12", "DEM-11", "DEM-12"]
    )

    assert [summary.id for summary in snapshot.summaries] == ["DEM-12", "DEM-11"]
