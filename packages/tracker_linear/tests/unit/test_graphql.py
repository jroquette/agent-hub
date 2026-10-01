"""The Linear GraphQL adapter's reads, over the in-process fake Linear API (no socket)."""

import json
from collections.abc import Iterator, Mapping
from typing import Any

import pytest

from agent_hub.core.errors import TrackerError
from agent_hub.core.testing.builders import an_issue
from agent_hub.core.testing.fakes import FakeTrackerBackend
from agent_hub.core.tracker.tracker_client import Issue
from agent_hub.tracker_linear.graphql import (
    DEFAULT_TIMEOUT_S,
    DONE_STATE_TYPES,
    LINEAR_API_KEY_VARIABLE,
    LINEAR_GRAPHQL_URL,
    PAGE_SIZE,
    LinearGraphqlTrackerClient,
)

_READY_IN_DEM = {"DEM-1", "DEM-2", "DEM-3"}


class _RecordingEnviron(Mapping[str, str]):
    """An environment that records every name read from it."""

    def __init__(self, values: dict[str, str]) -> None:
        self._values = values
        self.reads: list[str] = []

    def __getitem__(self, name: str) -> str:
        self.reads.append(name)
        return self._values[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


def _client(fake_linear_api: Any, synthetic_key: str) -> LinearGraphqlTrackerClient:
    return LinearGraphqlTrackerClient(
        environ={LINEAR_API_KEY_VARIABLE: synthetic_key}, post=fake_linear_api
    )


def _with_sorted_labels(issue: Issue) -> Issue:
    return issue.model_copy(update={"labels": tuple(sorted(issue.labels))})


def test_pins_constants_when_module_loaded() -> None:
    assert LINEAR_GRAPHQL_URL == "https://api.linear.app/graphql"
    assert LINEAR_API_KEY_VARIABLE == "LINEAR_API_KEY"
    assert PAGE_SIZE == 50
    assert DONE_STATE_TYPES == ("completed", "canceled", "duplicate")
    assert DEFAULT_TIMEOUT_S == 30.0


def test_passes_default_timeout_when_no_timeout_given(
    fake_linear_api: Any, synthetic_key: str
) -> None:
    _client(fake_linear_api, synthetic_key).get_issue("DEM-1")

    assert fake_linear_api.timeouts == [30.0]


def test_passes_timeout_to_transport_when_custom_timeout_given(
    fake_linear_api: Any, synthetic_key: str
) -> None:
    fake_linear_api.expected_timeout_s = 7.5
    client = LinearGraphqlTrackerClient(
        environ={LINEAR_API_KEY_VARIABLE: synthetic_key}, post=fake_linear_api, timeout_s=7.5
    )

    client.list_ready("DEM", "agent-ready")

    assert fake_linear_api.timeouts == [7.5, 7.5]


def test_follows_pages_when_matches_exceed_fake_page_size(
    fake_linear_api: Any, synthetic_key: str, tracker_backend: FakeTrackerBackend
) -> None:
    ready = _client(fake_linear_api, synthetic_key).list_ready("DEM", "agent-ready")

    assert {issue.id for issue in ready} == _READY_IN_DEM
    assert len(ready) == len(_READY_IN_DEM)
    assert {_with_sorted_labels(issue) for issue in ready} == {
        _with_sorted_labels(tracker_backend.issues[issue_id]) for issue_id in _READY_IN_DEM
    }
    assert len(fake_linear_api.requests) == 2
    first, second = fake_linear_api.requests
    first_cursor = fake_linear_api.responses[0]["issues"]["pageInfo"]["endCursor"]
    assert first["variables"]["after"] is None
    assert first_cursor is not None
    assert second["variables"]["after"] == first_cursor
    assert first["variables"]["first"] == second["variables"]["first"] == PAGE_SIZE


def test_sends_filter_as_variables_when_ready_issues_listed(
    fake_linear_api: Any, synthetic_key: str
) -> None:
    # Quotes and braces would break a query that interpolated the name; as a variable they
    # are plain data and match no label.
    hostile_label = 'agent-ready"}} } issues { nodes { title'

    client = _client(fake_linear_api, synthetic_key)
    client.list_ready("DEM", "agent-ready")
    assert client.list_ready("DEM", hostile_label) == []

    plain, hostile = fake_linear_api.requests[0], fake_linear_api.requests[-1]
    assert plain["query"] == hostile["query"]
    assert "DEM" not in plain["query"]
    assert "agent-ready" not in plain["query"]
    assert plain["operationName"] == "ListReadyIssues"
    assert hostile["variables"]["filter"] == {
        "team": {"key": {"eq": "DEM"}},
        "labels": {"some": {"name": {"eq": hostile_label}}},
        "state": {"type": {"nin": ["completed", "canceled", "duplicate"]}},
    }


def test_returns_backend_changes_when_backend_changes_after_construction(
    fake_linear_api: Any, synthetic_key: str, tracker_backend: FakeTrackerBackend
) -> None:
    client = _client(fake_linear_api, synthetic_key)
    tracker_backend.issues["DEM-8"] = an_issue(id="DEM-8", state="In Progress")

    ready = client.list_ready("DEM", "agent-ready")

    assert {issue.id for issue in ready} == {*_READY_IN_DEM, "DEM-8"}


def test_maps_response_to_issue_when_issue_fetched(
    fake_linear_api: Any, synthetic_key: str, tracker_backend: FakeTrackerBackend
) -> None:
    issue = _client(fake_linear_api, synthetic_key).get_issue("DEM-1")

    assert _with_sorted_labels(issue) == _with_sorted_labels(tracker_backend.issues["DEM-1"])
    (request,) = fake_linear_api.requests
    assert request["operationName"] == "GetIssue"
    assert request["variables"] == {"id": "DEM-1"}
    assert "DEM-1" not in request["query"]


def test_raises_before_any_request_when_issue_id_malformed(
    fake_linear_api: Any, synthetic_key: str
) -> None:
    with pytest.raises(TrackerError, match=r"^get_issue dem-1: malformed issue id"):
        _client(fake_linear_api, synthetic_key).get_issue("dem-1")

    assert fake_linear_api.requests == []


def test_reads_key_only_at_call_time_when_client_constructed(
    fake_linear_api: Any, synthetic_key: str
) -> None:
    environ = _RecordingEnviron({LINEAR_API_KEY_VARIABLE: synthetic_key})

    client = LinearGraphqlTrackerClient(environ=environ, post=fake_linear_api)
    assert environ.reads == []

    client.get_issue("DEM-1")
    assert LINEAR_API_KEY_VARIABLE in environ.reads


def test_fake_rejects_identifier_when_mutation_needs_uuid(
    fake_linear_api: Any, synthetic_key: str
) -> None:
    # Pins D-c: mutations take the issue's UUID; the fake fails the test on an identifier.
    update = {
        "query": (
            "mutation UpdateIssue($id: String!, $input: IssueUpdateInput!) {"
            " issueUpdate(id: $id, input: $input) { success } }"
        ),
        "operationName": "UpdateIssue",
        "variables": {"id": "DEM-1", "input": {"removedLabelIds": []}},
    }
    comment = {
        "query": (
            "mutation CreateComment($input: CommentCreateInput!) {"
            " commentCreate(input: $input) { success } }"
        ),
        "operationName": "CreateComment",
        "variables": {"input": {"issueId": "DEM-1", "body": "A synthetic comment."}},
    }
    headers = {"Content-Type": "application/json", "Authorization": synthetic_key}

    for request in (update, comment):
        with pytest.raises(AssertionError, match="UUID"):
            fake_linear_api(
                LINEAR_GRAPHQL_URL, headers, json.dumps(request).encode(), timeout_s=30.0
            )


def test_fake_answers_errors_when_issue_unknown(fake_linear_api: Any, synthetic_key: str) -> None:
    lookup = {
        "query": "query GetIssue($id: String!) { issue(id: $id) { title } }",
        "operationName": "GetIssue",
        "variables": {"id": "DEM-999"},
    }
    headers = {"Content-Type": "application/json", "Authorization": synthetic_key}

    status, body = fake_linear_api(
        LINEAR_GRAPHQL_URL, headers, json.dumps(lookup).encode(), timeout_s=30.0
    )

    answer = json.loads(body)
    assert status == 200
    assert answer["data"] is None
    assert answer["errors"][0]["message"] == "Entity not found: Issue"
