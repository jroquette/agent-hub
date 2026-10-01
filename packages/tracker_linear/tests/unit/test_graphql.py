"""The Linear GraphQL adapter's reads and writes, over the in-process fake Linear API."""

import copy
import json
import re
from collections.abc import Callable, Iterator, Mapping
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
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


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


def _operation_names(fake_linear_api: Any) -> list[str]:
    return [request["operationName"] for request in fake_linear_api.requests]


def _is_uuid(value: object) -> bool:
    return isinstance(value, str) and _UUID.fullmatch(value) is not None


def test_resolves_identifier_once_when_issue_moved(
    fake_linear_api: Any, synthetic_key: str, tracker_backend: FakeTrackerBackend
) -> None:
    _client(fake_linear_api, synthetic_key).move_state("DEM-1", "In Progress")

    assert _operation_names(fake_linear_api) == ["IssueRef", "FindStates", "UpdateIssue"]
    lookup, states, update = fake_linear_api.requests
    issue_uuid = fake_linear_api.responses[0]["issue"]["id"]
    assert lookup["variables"] == {"id": "DEM-1"}
    assert states["variables"]["filter"] == {
        "team": {"key": {"eq": "DEM"}},
        "name": {"eq": "In Progress"},
    }
    assert "In Progress" not in states["query"]
    assert _is_uuid(issue_uuid)
    assert update["variables"]["id"] == issue_uuid
    (state_id,) = update["variables"]["input"].values()
    assert set(update["variables"]["input"]) == {"stateId"}
    assert _is_uuid(state_id)
    assert tracker_backend.issues["DEM-1"].state == "In Progress"


def test_sends_no_mutation_when_moved_to_current_state(
    fake_linear_api: Any, synthetic_key: str
) -> None:
    _client(fake_linear_api, synthetic_key).move_state("DEM-1", "Todo")

    assert _operation_names(fake_linear_api) == ["IssueRef"]


def test_sends_no_mutation_when_present_label_added(
    fake_linear_api: Any, synthetic_key: str
) -> None:
    _client(fake_linear_api, synthetic_key).add_label("DEM-1", "demo-api")

    assert _operation_names(fake_linear_api) == ["IssueRef"]


def test_sends_no_mutation_when_absent_label_removed(
    fake_linear_api: Any, synthetic_key: str
) -> None:
    # agent-failed is a workspace label: the team lookup misses, the workspace one finds it.
    _client(fake_linear_api, synthetic_key).remove_label("DEM-1", "agent-failed")

    assert _operation_names(fake_linear_api) == ["IssueRef", "FindLabels", "FindLabels"]


def test_looks_up_team_label_only_when_team_has_it(
    fake_linear_api: Any, synthetic_key: str
) -> None:
    _client(fake_linear_api, synthetic_key).add_label("DEM-1", "bug")

    assert _operation_names(fake_linear_api) == ["IssueRef", "FindLabels", "UpdateIssue"]
    assert fake_linear_api.requests[1]["variables"]["filter"] == {
        "name": {"eq": "bug"},
        "team": {"key": {"eq": "DEM"}},
    }
    update = fake_linear_api.requests[2]["variables"]
    assert set(update["input"]) == {"addedLabelIds"}
    assert all(_is_uuid(label_id) for label_id in update["input"]["addedLabelIds"])


def test_looks_up_workspace_label_when_team_has_none(
    fake_linear_api: Any, synthetic_key: str
) -> None:
    _client(fake_linear_api, synthetic_key).add_label("DEM-7", "agent-failed")

    assert _operation_names(fake_linear_api) == [
        "IssueRef",
        "FindLabels",
        "FindLabels",
        "UpdateIssue",
    ]
    team_lookup, workspace_lookup = fake_linear_api.requests[1:3]
    assert team_lookup["variables"]["filter"]["team"] == {"key": {"eq": "DEM"}}
    assert workspace_lookup["variables"]["filter"] == {
        "name": {"eq": "agent-failed"},
        "team": {"null": True},
    }


def test_removes_label_by_its_id_when_label_present(
    fake_linear_api: Any, synthetic_key: str
) -> None:
    _client(fake_linear_api, synthetic_key).remove_label("DEM-1", "agent-ready")

    assert _operation_names(fake_linear_api) == ["IssueRef", "UpdateIssue"]
    update = fake_linear_api.requests[1]["variables"]
    assert update["id"] == fake_linear_api.responses[0]["issue"]["id"]
    assert set(update["input"]) == {"removedLabelIds"}


def test_comments_with_issue_uuid_when_issue_commented(
    fake_linear_api: Any, synthetic_key: str, tracker_backend: FakeTrackerBackend
) -> None:
    body = 'A "quoted" body } with braces'

    _client(fake_linear_api, synthetic_key).comment("DEM-2", body)

    assert _operation_names(fake_linear_api) == ["IssueRef", "CreateComment"]
    comment = fake_linear_api.requests[1]
    assert comment["variables"] == {
        "input": {"issueId": fake_linear_api.responses[0]["issue"]["id"], "body": body}
    }
    assert body not in comment["query"]
    assert tracker_backend.comments == [("DEM-2", body)]


@pytest.mark.parametrize(
    ("operation", "call", "mutation"),
    [
        ("move_state", lambda client: client.move_state("DEM-1", "In Progress"), "UpdateIssue"),
        ("add_label", lambda client: client.add_label("DEM-1", "bug"), "UpdateIssue"),
        ("remove_label", lambda client: client.remove_label("DEM-1", "agent-ready"), "UpdateIssue"),
        ("comment", lambda client: client.comment("DEM-1", "A comment."), "CreateComment"),
    ],
)
def test_raises_naming_id_when_mutation_not_successful(
    *,
    fake_linear_api: Any,
    synthetic_key: str,
    tracker_backend: FakeTrackerBackend,
    operation: str,
    call: Callable[[LinearGraphqlTrackerClient], None],
    mutation: str,
) -> None:
    fake_linear_api.mutation_success = False
    before = copy.deepcopy(tracker_backend)

    with pytest.raises(TrackerError, match=rf"^{operation} DEM-1: Linear reported no success"):
        call(_client(fake_linear_api, synthetic_key))

    assert tracker_backend == before
    # Never retried: exactly one mutation was sent.
    assert _operation_names(fake_linear_api).count(mutation) == 1


def test_raises_without_retry_when_comment_answers_errors(
    fake_linear_api: Any, synthetic_key: str, tracker_backend: FakeTrackerBackend
) -> None:
    # The issue is deleted between the lookup and the mutation: Linear answers with errors.
    def deleting_post(
        url: str, headers: Mapping[str, str], body: bytes, *, timeout_s: float
    ) -> tuple[int, bytes]:
        answer = fake_linear_api(url, headers, body, timeout_s=timeout_s)
        tracker_backend.issues.pop("DEM-1", None)
        return answer

    client = LinearGraphqlTrackerClient(
        environ={LINEAR_API_KEY_VARIABLE: synthetic_key}, post=deleting_post
    )

    with pytest.raises(TrackerError, match=r"^comment DEM-1: Linear answered with an error"):
        client.comment("DEM-1", "A synthetic comment.")

    assert _operation_names(fake_linear_api) == ["IssueRef", "CreateComment"]
    assert tracker_backend.comments == []


def test_scopes_states_by_served_team_when_issue_moved_to_other_team(
    fake_linear_api: Any, synthetic_key: str, tracker_backend: FakeTrackerBackend
) -> None:
    # DEM-9 now belongs to OPS (moved between teams; the identifier keeps its old prefix).
    tracker_backend.issues["DEM-9"] = an_issue(id="DEM-9", state="Todo")
    fake_linear_api.issue_teams["DEM-9"] = "OPS"
    client = _client(fake_linear_api, synthetic_key)

    client.move_state("DEM-9", "Done")

    assert fake_linear_api.requests[1]["variables"]["filter"]["team"] == {"key": {"eq": "OPS"}}
    assert tracker_backend.issues["DEM-9"].state == "Done"
    # Duplicate is a DEM state only: OPS refuses it.
    with pytest.raises(TrackerError, match=r"^move_state DEM-9: state 'Duplicate' not found"):
        client.move_state("DEM-9", "Duplicate")


def test_raises_quoting_linear_error_when_issue_answers_errors(
    fake_linear_api: Any, synthetic_key: str
) -> None:
    with pytest.raises(TrackerError, match=r"^move_state DEM-999: .*Entity not found: Issue"):
        _client(fake_linear_api, synthetic_key).move_state("DEM-999", "Todo")

    assert _operation_names(fake_linear_api) == ["IssueRef"]


def test_lets_transport_assertion_through_when_fake_fails(synthetic_key: str) -> None:
    # A failing fake (or a bug) must surface as itself, never as a TrackerError.
    def failing_post(
        url: str, headers: Mapping[str, str], body: bytes, *, timeout_s: float
    ) -> tuple[int, bytes]:
        raise AssertionError("fake rejected the request")

    client = LinearGraphqlTrackerClient(
        environ={LINEAR_API_KEY_VARIABLE: synthetic_key}, post=failing_post
    )

    with pytest.raises(AssertionError, match="fake rejected"):
        client.add_label("DEM-1", "bug")


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


def test_serves_stable_uuids_when_issue_read_twice(
    fake_linear_api: Any, synthetic_key: str
) -> None:
    client = _client(fake_linear_api, synthetic_key)
    client.comment("DEM-1", "first")
    client.comment("DEM-1", "second")
    client.comment("DEM-2", "third")

    first, second, third = (fake_linear_api.responses[index]["issue"]["id"] for index in (0, 2, 4))
    assert first == second != third
