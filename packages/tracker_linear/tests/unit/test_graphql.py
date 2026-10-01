"""The Linear GraphQL adapter's reads and writes, over the in-process fake Linear API."""

import copy
import json
import logging
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
    MAX_QUOTED_CHARS,
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
    assert MAX_QUOTED_CHARS == 200


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


# Each operation, the issue id it names in an error, and a call that reaches the transport.
_SIX_OPERATIONS: dict[str, tuple[str | None, Callable[[LinearGraphqlTrackerClient], object]]] = {
    "list_ready": (None, lambda client: client.list_ready("DEM", "agent-ready")),
    "get_issue": ("DEM-1", lambda client: client.get_issue("DEM-1")),
    "move_state": ("DEM-1", lambda client: client.move_state("DEM-1", "Done")),
    "add_label": ("DEM-1", lambda client: client.add_label("DEM-1", "bug")),
    "remove_label": ("DEM-1", lambda client: client.remove_label("DEM-1", "agent-ready")),
    "comment": ("DEM-1", lambda client: client.comment("DEM-1", "A synthetic comment.")),
}


class _Answering:
    """A transport that answers every request with one reply, or raises it; counts the calls."""

    def __init__(self, reply: tuple[int, bytes] | BaseException) -> None:
        self._reply = reply
        self.calls = 0

    def __call__(
        self, url: str, headers: Mapping[str, str], body: bytes, *, timeout_s: float
    ) -> tuple[int, bytes]:
        self.calls += 1
        if isinstance(self._reply, BaseException):
            raise self._reply
        return self._reply


def _errors(message: str, **extensions: str) -> bytes:
    error: dict[str, Any] = {"message": message}
    if extensions:
        error["extensions"] = extensions
    return json.dumps({"errors": [error], "data": None}).encode()


_KEY_FIX = r"check that LINEAR_API_KEY"
_RETRY = r"retry later"

# AC-9.4: (reply, cause pattern, fix pattern).
_FAILURES: dict[str, tuple[tuple[int, bytes] | BaseException, str, str]] = {
    "http-401": ((401, _errors("Authentication required")), r"HTTP 401", _KEY_FIX),
    "http-403": ((403, b"Forbidden"), r"HTTP 403", _KEY_FIX),
    "http-429": ((429, b""), r"rate-limited .*HTTP 429", _RETRY),
    "http-500": ((500, b"<html>oops</html>"), r"unavailable .*HTTP 500", _RETRY),
    "http-503": ((503, b""), r"unavailable .*HTTP 503", _RETRY),
    "http-400-plain": ((400, b'{"data": null}'), r"HTTP 400", r"check"),
    "non-json": ((200, b"<html>not json</html>"), r"not JSON", _RETRY),
    "errors-200": (
        (200, _errors("Something failed")),
        r"Linear answered with an error: 'Something failed'",
        r"check (that DEM-1 exists|the team key and the label name)",
    ),
    "errors-400-ratelimited": (
        (400, _errors("Too many requests", code="RATELIMITED")),
        r"'Too many requests'",
        _RETRY,
    ),
    "errors-authentication": (
        (200, _errors("Invalid key", type="authentication error")),
        r"'Invalid key'",
        _KEY_FIX,
    ),
    "oserror": (OSError("connection refused"), r"could not reach Linear", r"check the network"),
    "timeout": (TimeoutError(), r"no answer from Linear within 30", _RETRY),
}


@pytest.mark.parametrize("operation", list(_SIX_OPERATIONS))
@pytest.mark.parametrize("failure", list(_FAILURES))
def test_raises_with_fix_when_response_fails(
    *, caplog: pytest.LogCaptureFixture, synthetic_key: str, failure: str, operation: str
) -> None:
    caplog.set_level(logging.DEBUG)
    reply, cause, fix = _FAILURES[failure]
    issue_id, call = _SIX_OPERATIONS[operation]
    post = _Answering(reply)
    client = LinearGraphqlTrackerClient(environ={LINEAR_API_KEY_VARIABLE: synthetic_key}, post=post)

    with pytest.raises(TrackerError) as raised:
        call(client)

    message = str(raised.value)
    subject = operation if issue_id is None else f"{operation} {issue_id}"
    assert message.startswith(f"{subject}: ")
    assert "\n" not in message
    cause_text, _, fix_text = message.removeprefix(f"{subject}: ").rpartition("; ")
    assert re.search(cause, cause_text), message
    assert re.search(fix, fix_text), message
    assert (raised.value.operation, raised.value.issue_id) == (operation, issue_id)
    assert post.calls == 1  # never retried
    for text in (message, repr(raised.value), str(client), repr(client), caplog.text):
        assert synthetic_key not in text


@pytest.mark.parametrize("operation", list(_SIX_OPERATIONS))
@pytest.mark.parametrize("environ", [{}, {LINEAR_API_KEY_VARIABLE: ""}], ids=["unset", "empty"])
def test_raises_naming_key_when_key_missing(environ: dict[str, str], operation: str) -> None:
    issue_id, call = _SIX_OPERATIONS[operation]
    post = _Answering((200, b"{}"))

    client = LinearGraphqlTrackerClient(environ=environ, post=post)
    assert post.calls == 0

    with pytest.raises(TrackerError, match=r"LINEAR_API_KEY is not set") as raised:
        call(client)
    assert (raised.value.operation, raised.value.issue_id) == (operation, issue_id)
    assert post.calls == 0


@pytest.mark.parametrize("control", ["\n", "\r", "\x00", "\x1b", "\x7f"])
def test_raises_naming_key_when_key_has_control_character(synthetic_key: str, control: str) -> None:
    key = f"{synthetic_key}{control}injected"
    post = _Answering((200, b"{}"))
    client = LinearGraphqlTrackerClient(environ={LINEAR_API_KEY_VARIABLE: key}, post=post)

    with pytest.raises(TrackerError, match=r"LINEAR_API_KEY has a control character") as raised:
        client.get_issue("DEM-1")

    assert post.calls == 0
    for text in (str(raised.value), repr(raised.value), repr(client)):
        assert synthetic_key not in text
        assert "injected" not in text


def _altered(fake_linear_api: Any, alter: Callable[[Any], Any]) -> Callable[..., tuple[int, bytes]]:
    """A transport that lets the fake answer, then rewrites the decoded answer with ``alter``."""

    def post(
        url: str, headers: Mapping[str, str], body: bytes, *, timeout_s: float
    ) -> tuple[int, bytes]:
        status, answer = fake_linear_api(url, headers, body, timeout_s=timeout_s)
        return status, json.dumps(alter(json.loads(answer))).encode()

    return post


def _set(path: tuple[str, ...], value: Any) -> Callable[[Any], Any]:
    def alter(answer: Any) -> Any:
        node = answer
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
        return answer

    return alter


def _drop(path: tuple[str, ...]) -> Callable[[Any], Any]:
    def alter(answer: Any) -> Any:
        node = answer
        for key in path[:-1]:
            node = node[key]
        del node[path[-1]]
        return answer

    return alter


_ISSUE = ("data", "issue")
_SHAPE_CHANGES: dict[str, tuple[str, Callable[[Any], Any]]] = {
    "not-an-object": ("get_issue", lambda answer: [answer]),
    "data-null-no-errors": ("get_issue", _set(("data",), None)),
    "root-missing": ("get_issue", _drop(_ISSUE)),
    "field-missing": ("get_issue", _drop((*_ISSUE, "title"))),
    "field-wrong-type": ("get_issue", _set((*_ISSUE, "title"), 5)),
    "field-unexpected": ("get_issue", _set((*_ISSUE, "secret"), "x")),
    "nodes-not-a-list": ("get_issue", _set((*_ISSUE, "labels", "nodes"), "agent-ready")),
    "cursor-missing": (
        "list_ready",
        _set(("data", "issues", "pageInfo"), {"hasNextPage": True, "endCursor": None}),
    ),
    "success-missing": ("comment", lambda answer: _drop_success(answer)),
}


def _drop_success(answer: Any) -> Any:
    # Only the mutation's answer: the lookup before it stays intact.
    if "commentCreate" in (answer.get("data") or {}):
        del answer["data"]["commentCreate"]["success"]
    return answer


@pytest.mark.parametrize("change", list(_SHAPE_CHANGES))
def test_raises_when_response_shape_unexpected(
    fake_linear_api: Any, synthetic_key: str, change: str
) -> None:
    operation, alter = _SHAPE_CHANGES[change]
    issue_id, call = _SIX_OPERATIONS[operation]
    client = LinearGraphqlTrackerClient(
        environ={LINEAR_API_KEY_VARIABLE: synthetic_key}, post=_altered(fake_linear_api, alter)
    )
    subject = operation if issue_id is None else f"{operation} {issue_id}"

    with pytest.raises(TrackerError, match=rf"^{subject}: unexpected response from Linear"):
        call(client)


def test_quotes_linear_message_cut_when_message_long(synthetic_key: str) -> None:
    long_message = "x" * (MAX_QUOTED_CHARS + 50) + "\nsecond line"
    post = _Answering((200, _errors(long_message)))
    client = LinearGraphqlTrackerClient(environ={LINEAR_API_KEY_VARIABLE: synthetic_key}, post=post)

    with pytest.raises(TrackerError) as raised:
        client.get_issue("DEM-1")

    message = str(raised.value)
    assert f"'{'x' * MAX_QUOTED_CHARS}'" in message
    assert "x" * (MAX_QUOTED_CHARS + 1) not in message
    assert "second line" not in message
    assert "\n" not in message
