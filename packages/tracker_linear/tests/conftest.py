"""An in-process fake of Linear's GraphQL API over a ``FakeTrackerBackend``, and its fixtures.

``FakeLinearApi`` is the adapter's ``post`` transport: it serves the backend the contract suite
asserts on, reading it on every request (never a snapshot), so a write made through the
backend is seen by the next read, and a mutation changes the backend. It checks the request
document against the slice of Linear's schema it knows (research §6), serves only the fields
the query selects and fails the test on anything else. Issues, states and labels get stable
synthetic UUIDs; a mutation given anything but a UUID fails the test (D-c). An unknown issue is
answered as GraphQL answers a failed non-null root field: an ``errors`` array and ``data: null``
(Linear's exact error text and HTTP status for it are unverified; the live smoke confirms).
Every value here is synthetic: no recorded Linear response, no real key.
"""

import json
import re
import uuid
from collections.abc import Callable, Mapping
from typing import Any

import pytest

from agent_hub.core.testing.builders import a_seeded_tracker_backend
from agent_hub.core.testing.fakes import FakeTrackerBackend
from agent_hub.core.tracker.tracker_client import Issue

# Pinned here as literals, not imported from the adapter, so a wrong adapter constant fails.
LINEAR_ENDPOINT = "https://api.linear.app/graphql"
DEFAULT_TIMEOUT_S = 30.0
FAKE_PAGE_SIZE = 2

# Linear's WorkflowState.type of the seeded closed states; every open state reads "started".
_CLOSED_STATE_TYPES = {"Done": "completed", "Canceled": "canceled", "Duplicate": "duplicate"}
_OPEN_STATE_TYPE = "started"
_FILTER_KEYS = frozenset({"team", "labels", "state"})

_STATE_FILTER_KEYS = frozenset({"team", "name"})
_LABEL_FILTER_KEYS = frozenset({"name", "team"})
_UPDATE_INPUT_KEYS = frozenset({"stateId", "addedLabelIds", "removedLabelIds"})
_COMMENT_INPUT_KEYS = frozenset({"issueId", "body"})
_UUID_NAMESPACE = uuid.NAMESPACE_URL
NOT_FOUND_MESSAGE = "Entity not found: Issue"

# Each operation's kind and the root field it selects, and each root field's arguments with
# their schema types.
_OPERATIONS = {
    "ListReadyIssues": ("query", "issues"),
    "GetIssue": ("query", "issue"),
    "IssueRef": ("query", "issue"),
    "FindStates": ("query", "workflowStates"),
    "FindLabels": ("query", "issueLabels"),
    "UpdateIssue": ("mutation", "issueUpdate"),
    "CreateComment": ("mutation", "commentCreate"),
}
_ROOT_ARGUMENTS = {
    "issues": {"filter": "IssueFilter", "first": "Int", "after": "String"},
    "issue": {"id": "String!"},
    "workflowStates": {"filter": "WorkflowStateFilter"},
    "issueLabels": {"filter": "IssueLabelFilter"},
    "issueUpdate": {"id": "String!", "input": "IssueUpdateInput!"},
    "commentCreate": {"input": "CommentCreateInput!"},
}
_OPERATION = re.compile(r"\s*(query|mutation)\s+(\w+)\s*\(([^)]*)\)\s*(\{.*\})\s*", re.DOTALL)
_DECLARATION = re.compile(r"\$(\w+)\s*:\s*([\w!\[\]]+)")
_ARGUMENT = re.compile(r"(\w+)\s*:\s*\$(\w+)")
_TOKEN = re.compile(r"\([^()]*\)|[{}]|\w+|\S")

type Json = dict[str, Any]
# A parsed selection set: field name -> (its arguments text, its own selection or None).
type Selection = dict[str, tuple[str, "Selection | None"]]


class _NotFoundError(Exception):
    """Raised by a handler for an id Linear would not find; answered as a GraphQL error."""


class FakeLinearApi:
    """A ``post(url, headers, body, *, timeout_s)`` callable that plays Linear's GraphQL API.

    The transport only ever POSTs, so the method is the callable itself. Each call asserts the
    endpoint, ``timeout_s == expected_timeout_s``, the JSON content type and body,
    ``Authorization`` equal to the bare key (no ``Bearer``) and the query document, then
    dispatches on ``operationName``. ``page_size`` caps the issues per page; a nested connection
    selected with ``(first: N)`` (an issue's labels) serves its first ``N`` nodes and a
    ``pageInfo``. ``requests``, ``timeouts`` and ``responses`` record each call
    (``responses`` holds each answer's ``data``). ``mutation_success = False`` answers every
    mutation with ``success: false`` and changes nothing. ``issue_teams`` maps an identifier to
    the team the issue belongs to now (after a move between teams); the identifier's prefix
    otherwise.
    """

    def __init__(
        self, backend: FakeTrackerBackend, *, key: str, page_size: int = FAKE_PAGE_SIZE
    ) -> None:
        self._backend = backend
        self._key = key
        self.page_size = page_size
        self.expected_timeout_s = DEFAULT_TIMEOUT_S
        self.requests: list[Json] = []
        self.timeouts: list[float] = []
        self.responses: list[Json | None] = []
        self.mutation_success = True
        self.issue_teams: dict[str, str] = {}

    def __call__(
        self, url: str, headers: Mapping[str, str], body: bytes, *, timeout_s: float
    ) -> tuple[int, bytes]:
        assert url == LINEAR_ENDPOINT
        assert timeout_s == self.expected_timeout_s
        assert headers["Content-Type"] == "application/json"
        assert headers["Authorization"] == self._key
        request = json.loads(body)
        assert isinstance(request, dict)
        self.requests.append(request)
        self.timeouts.append(timeout_s)
        root, selection = _checked_document(request)
        handlers: dict[str, Callable[[Json], Json]] = {
            "ListReadyIssues": self._issues,
            "GetIssue": self._issue,
            "IssueRef": self._issue,
            "FindStates": self._states,
            "FindLabels": self._labels,
            "UpdateIssue": self._update_issue,
            "CreateComment": self._create_comment,
        }
        try:
            full = handlers[request["operationName"]](request["variables"])
        except _NotFoundError:
            self.responses.append(None)
            error = {"message": NOT_FOUND_MESSAGE, "path": [root]}
            return 200, json.dumps({"errors": [error], "data": None}).encode()
        data = {root: _project(full[root], selection)}
        self.responses.append(data)
        return 200, json.dumps({"data": data}).encode()

    def _issues(self, variables: Json) -> Json:
        assert variables["first"] >= 1
        matches = [
            issue for issue in self._backend.issues.values() if self._matches(issue, variables)
        ]
        start = int(variables["after"]) if variables.get("after") is not None else 0
        end = start + min(variables["first"], self.page_size)
        has_next_page = end < len(matches)
        return {
            "issues": {
                "nodes": [self._node(issue) for issue in matches[start:end]],
                "pageInfo": {
                    "hasNextPage": has_next_page,
                    "endCursor": str(end) if has_next_page else None,
                },
            }
        }

    def _issue(self, variables: Json) -> Json:
        # Linear's issue(id:) takes the identifier or the UUID.
        reference = variables["id"]
        issue = (
            self._issue_by_uuid(reference)
            if _is_uuid(reference)
            else self._backend.issues.get(reference)
        )
        if issue is None:
            raise _NotFoundError
        return {"issue": self._node(issue)}

    def _states(self, variables: Json) -> Json:
        state_filter: Json = variables["filter"]
        assert set(state_filter) == _STATE_FILTER_KEYS, state_filter
        assert set(state_filter["team"]) == {"key"}, state_filter
        team, name = _eq(state_filter["team"]["key"]), _eq(state_filter["name"])
        states = self._backend.states.get(team, ())
        nodes = [{"id": _state_uuid(team, state.name)} for state in states if state.name == name]
        return {"workflowStates": {"nodes": nodes}}

    def _labels(self, variables: Json) -> Json:
        label_filter: Json = variables["filter"]
        assert set(label_filter) == _LABEL_FILTER_KEYS, label_filter
        name, team_filter = _eq(label_filter["name"]), label_filter["team"]
        team: str | None
        if team_filter == {"null": True}:
            team, names = None, self._backend.workspace_labels
        else:
            assert set(team_filter) == {"key"}, team_filter
            team = _eq(team_filter["key"])
            names = self._backend.team_labels.get(team, ())
        nodes = [{"id": _label_uuid(team, name)}] if name in names else []
        return {"issueLabels": {"nodes": nodes}}

    def _update_issue(self, variables: Json) -> Json:
        _assert_uuid(variables["id"], "issueUpdate(id:)")
        issue = self._issue_by_uuid(variables["id"])
        if issue is None:
            raise _NotFoundError
        update_input: Json = variables["input"]
        assert len(update_input) == 1, update_input
        assert set(update_input) <= _UPDATE_INPUT_KEYS, update_input
        if not self.mutation_success:
            return {"issueUpdate": {"success": False}}
        team = self._team(issue)
        if "stateId" in update_input:
            states = {
                _state_uuid(team, state.name): state.name for state in self._backend.states[team]
            }
            state_id = _assert_uuid(update_input["stateId"], "stateId")
            assert state_id in states, f"stateId {state_id} is not a state of team {team}"
            changes: Json = {"state": states[state_id]}
        else:
            labels = self._labels_of_team(team)
            ids = update_input.get("addedLabelIds", update_input.get("removedLabelIds"))
            assert isinstance(ids, list), update_input
            for label_id in ids:
                assert _assert_uuid(label_id, "a label id") in labels, f"{label_id} not in {team}"
            names = [labels[label_id] for label_id in ids]
            if "addedLabelIds" in update_input:
                kept = (*issue.labels, *(name for name in names if name not in issue.labels))
            else:
                kept = tuple(name for name in issue.labels if name not in names)
            changes = {"labels": kept}
        self._backend.issues[issue.id] = issue.model_copy(update=changes)
        return {"issueUpdate": {"success": True}}

    def _create_comment(self, variables: Json) -> Json:
        comment_input: Json = variables["input"]
        assert set(comment_input) == _COMMENT_INPUT_KEYS, comment_input
        _assert_uuid(comment_input["issueId"], "commentCreate(input: {issueId})")
        assert isinstance(comment_input["body"], str), comment_input
        issue = self._issue_by_uuid(comment_input["issueId"])
        if issue is None:
            raise _NotFoundError
        if not self.mutation_success:
            return {"commentCreate": {"success": False}}
        self._backend.comments.append((issue.id, comment_input["body"]))
        return {"commentCreate": {"success": True}}

    def _team(self, issue: Issue) -> str:
        return self.issue_teams.get(issue.id, _team_of(issue))

    def _issue_by_uuid(self, issue_uuid: str) -> Issue | None:
        matches = [
            issue for issue in self._backend.issues.values() if _issue_uuid(issue) == issue_uuid
        ]
        return matches[0] if matches else None

    def _labels_of_team(self, team: str) -> dict[str, str]:
        # The labels an issue of the team may carry, by UUID: the team's, then the workspace's.
        labels = {_label_uuid(None, name): name for name in self._backend.workspace_labels}
        team_labels = self._backend.team_labels.get(team, ())
        labels |= {_label_uuid(team, name): name for name in team_labels}
        return labels

    def _label_node(self, issue: Issue, name: str) -> Json:
        team = self._team(issue)
        owner = team if name in self._backend.team_labels.get(team, ()) else None
        return {"id": _label_uuid(owner, name), "name": name}

    def _matches(self, issue: Issue, variables: Json) -> bool:
        # The IssueFilter subset the adapter sends; any other key fails the test.
        issue_filter: Json = variables["filter"]
        assert set(issue_filter) <= _FILTER_KEYS, issue_filter
        if "team" in issue_filter and self._team(issue) != issue_filter["team"]["key"]["eq"]:
            return False
        if "labels" in issue_filter and (
            issue_filter["labels"]["some"]["name"]["eq"] not in issue.labels
        ):
            return False
        return "state" not in issue_filter or (
            self._state_type(issue) not in issue_filter["state"]["type"]["nin"]
        )

    def _node(self, issue: Issue) -> Json:
        team = self._team(issue)
        return {
            "id": _issue_uuid(issue),
            "identifier": issue.id,
            "title": issue.title,
            "description": issue.description or None,  # Linear answers null for none.
            "url": issue.url,
            "team": {"key": team},
            "state": {
                "id": _state_uuid(team, issue.state),
                "name": issue.state,
                "type": self._state_type(issue),
            },
            "labels": {"nodes": [self._label_node(issue, name) for name in issue.labels]},
        }

    def _state_type(self, issue: Issue) -> str:
        states = {state.name: state for state in self._backend.states[self._team(issue)]}
        if not states[issue.state].closed:
            return _OPEN_STATE_TYPE
        return _CLOSED_STATE_TYPES[issue.state]


def _checked_document(request: Json) -> tuple[str, Selection | None]:
    """Check the query against the operation name and the schema; return its root selection."""
    query, variables = request["query"], request["variables"]
    assert isinstance(query, str)
    match = _OPERATION.fullmatch(query)
    assert match is not None, f"not a single named query: {query!r}"
    kind, name, declarations, selection_text = match.groups()
    assert name == request["operationName"]
    assert kind == _OPERATIONS[name][0], (kind, name)
    declared = dict(_DECLARATION.findall(declarations))
    assert set(declared) == set(variables), (declared, variables)
    selection = _parse_selection(_TOKEN.findall(selection_text))
    root = _OPERATIONS[name][1]
    assert list(selection) == [root], selection
    arguments_text, root_selection = selection[root]
    for argument, variable in _ARGUMENT.findall(arguments_text):
        _check_variable_type(declared[variable], _ROOT_ARGUMENTS[root][argument])
        assert variables[variable] is not None or not declared[variable].endswith("!")
    return root, root_selection


def _check_variable_type(declared: str, argument_type: str) -> None:
    # GraphQL: a variable fits an argument of its type, or a nullable one when non-null.
    if argument_type.endswith("!"):
        allowed = {argument_type}
    else:
        allowed = {argument_type, f"{argument_type}!"}
    assert declared in allowed, (declared, argument_type)


def _parse_selection(tokens: list[str]) -> Selection:
    selection, rest = _selection_set(tokens)
    assert rest == [], rest
    return selection


def _selection_set(tokens: list[str]) -> tuple[Selection, list[str]]:
    assert tokens[0] == "{", tokens
    selection: Selection = {}
    rest = tokens[1:]
    while rest[0] != "}":
        name, rest = rest[0], rest[1:]
        assert re.fullmatch(r"\w+", name), f"unsupported syntax at {name!r}"
        arguments = ""
        if rest[0].startswith("("):
            arguments, rest = rest[0], rest[1:]
        child: Selection | None = None
        if rest[0] == "{":
            child, rest = _selection_set(rest)
        selection[name] = (arguments, child)
    return selection, rest[1:]


def _project(value: Any, selection: Selection | None) -> Any:
    """Keep only the selected fields of ``value``; a field the fake does not serve fails."""
    if isinstance(value, list):
        return [_project(item, selection) for item in value]
    if selection is None:
        assert not isinstance(value, dict), "an object field needs a selection"
        return value
    assert isinstance(value, dict), f"{value!r} has no fields to select"
    projected: Json = {}
    for name, (arguments, child) in selection.items():
        assert name in value, f"field {name!r} is not served here"
        field = _first_page(value[name], arguments) if arguments else value[name]
        projected[name] = _project(field, child)
    return projected


def _first_page(connection: Any, arguments: str) -> Json:
    # The only argument served on a nested field: a literal first: N on a connection.
    match = re.fullmatch(r"\(\s*first\s*:\s*(\d+)\s*\)", arguments)
    assert match is not None, f"unsupported arguments {arguments!r}"
    first, nodes = int(match.group(1)), connection["nodes"]
    return {"nodes": nodes[:first], "pageInfo": {"hasNextPage": len(nodes) > first}}


def _team_of(issue: Issue) -> str:
    return issue.id.partition("-")[0]


def _eq(comparator: Json) -> str:
    # The StringComparator subset the adapter sends: exactly {"eq": <string>}.
    assert set(comparator) == {"eq"}, comparator
    value = comparator["eq"]
    assert isinstance(value, str), comparator
    return value


def _issue_uuid(issue: Issue) -> str:
    return str(uuid.uuid5(_UUID_NAMESPACE, f"agent-hub-fake:issue:{issue.id}"))


def _state_uuid(team: str, name: str) -> str:
    return str(uuid.uuid5(_UUID_NAMESPACE, f"agent-hub-fake:state:{team}:{name}"))


def _label_uuid(team: str | None, name: str) -> str:
    # A workspace label (team None) and a team label of the same name are different labels.
    owner = "" if team is None else team
    return str(uuid.uuid5(_UUID_NAMESPACE, f"agent-hub-fake:label:{owner}:{name}"))


def _is_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _assert_uuid(value: object, where: str) -> str:
    assert _is_uuid(value), f"{where} must be a UUID (D-c), got {value!r}"
    assert isinstance(value, str)
    return value


@pytest.fixture
def synthetic_key() -> str:
    """A fake key shaped like a Linear one, assembled so no key-like literal is committed."""
    return "_".join(("lin", "api", "synthetic" + "0" * 31))


@pytest.fixture
def tracker_backend() -> FakeTrackerBackend:
    return a_seeded_tracker_backend()


@pytest.fixture
def fake_linear_api(tracker_backend: FakeTrackerBackend, synthetic_key: str) -> FakeLinearApi:
    return FakeLinearApi(tracker_backend, key=synthetic_key)
