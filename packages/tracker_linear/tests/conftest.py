"""An in-process fake of Linear's GraphQL API over a ``FakeTrackerBackend``, and its fixtures.

``FakeLinearApi`` is the adapter's ``post`` transport: it serves the backend the contract suite
asserts on, reading it on every request (never a snapshot), so a write made through the
backend is seen by the next read. It checks the request document against the slice of Linear's
schema it knows (research §6), serves only the fields the query selects and fails the test on
anything else. Every value here is synthetic: no recorded Linear response, no real key.
"""

import json
import re
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

# The root field each operation queries, and that field's arguments with their schema types.
_OPERATION_ROOTS = {"ListReadyIssues": "issues", "GetIssue": "issue"}
_ROOT_ARGUMENTS = {
    "issues": {"filter": "IssueFilter", "first": "Int", "after": "String"},
    "issue": {"id": "String!"},
}
_OPERATION = re.compile(r"\s*query\s+(\w+)\s*\(([^)]*)\)\s*(\{.*\})\s*", re.DOTALL)
_DECLARATION = re.compile(r"\$(\w+)\s*:\s*([\w!\[\]]+)")
_ARGUMENT = re.compile(r"(\w+)\s*:\s*\$(\w+)")
_TOKEN = re.compile(r"\([^()]*\)|[{}]|\w+|\S")

type Json = dict[str, Any]
# A parsed selection set: field name -> (its arguments text, its own selection or None).
type Selection = dict[str, tuple[str, "Selection | None"]]


class FakeLinearApi:
    """A ``post(url, headers, body, *, timeout_s)`` callable that plays Linear's GraphQL API.

    The transport only ever POSTs, so the method is the callable itself. Each call asserts the
    endpoint, ``timeout_s == expected_timeout_s``, the JSON content type and body,
    ``Authorization`` equal to the bare key (no ``Bearer``) and the query document, then
    dispatches on ``operationName``. ``requests``, ``timeouts`` and ``responses`` record each call.
    """

    def __init__(
        self, backend: FakeTrackerBackend, *, key: str, page_size: int = FAKE_PAGE_SIZE
    ) -> None:
        self._backend = backend
        self._key = key
        self._page_size = page_size
        self.expected_timeout_s = DEFAULT_TIMEOUT_S
        self.requests: list[Json] = []
        self.timeouts: list[float] = []
        self.responses: list[Json] = []

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
        }
        full = handlers[request["operationName"]](request["variables"])
        data = {root: _project(full[root], selection)}
        self.responses.append(data)
        return 200, json.dumps({"data": data}).encode()

    def _issues(self, variables: Json) -> Json:
        assert variables["first"] >= 1
        matches = [
            issue for issue in self._backend.issues.values() if self._matches(issue, variables)
        ]
        start = int(variables["after"]) if variables.get("after") is not None else 0
        end = start + min(variables["first"], self._page_size)
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
        return {"issue": self._node(self._backend.issues[variables["id"]])}

    def _matches(self, issue: Issue, variables: Json) -> bool:
        # The IssueFilter subset the adapter sends; any other key fails the test.
        issue_filter: Json = variables["filter"]
        assert set(issue_filter) <= _FILTER_KEYS, issue_filter
        if "team" in issue_filter and _team_of(issue) != issue_filter["team"]["key"]["eq"]:
            return False
        if "labels" in issue_filter and (
            issue_filter["labels"]["some"]["name"]["eq"] not in issue.labels
        ):
            return False
        return "state" not in issue_filter or (
            self._state_type(issue) not in issue_filter["state"]["type"]["nin"]
        )

    def _node(self, issue: Issue) -> Json:
        return {
            "identifier": issue.id,
            "title": issue.title,
            "url": issue.url,
            "state": {"name": issue.state, "type": self._state_type(issue)},
            "labels": {"nodes": [{"name": name} for name in issue.labels]},
        }

    def _state_type(self, issue: Issue) -> str:
        states = {state.name: state for state in self._backend.states[_team_of(issue)]}
        if not states[issue.state].closed:
            return _OPEN_STATE_TYPE
        return _CLOSED_STATE_TYPES[issue.state]


def _checked_document(request: Json) -> tuple[str, Selection | None]:
    """Check the query against the operation name and the schema; return its root selection."""
    query, variables = request["query"], request["variables"]
    assert isinstance(query, str)
    match = _OPERATION.fullmatch(query)
    assert match is not None, f"not a single named query: {query!r}"
    name, declarations, selection_text = match.groups()
    assert name == request["operationName"]
    declared = dict(_DECLARATION.findall(declarations))
    assert set(declared) == set(variables), (declared, variables)
    selection = _parse_selection(_TOKEN.findall(selection_text))
    assert list(selection) == [_OPERATION_ROOTS[name]], selection
    root = _OPERATION_ROOTS[name]
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
        assert arguments == "", f"arguments on {name!r} are not supported"
        projected[name] = _project(value[name], child)
    return projected


def _team_of(issue: Issue) -> str:
    return issue.id.partition("-")[0]


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
