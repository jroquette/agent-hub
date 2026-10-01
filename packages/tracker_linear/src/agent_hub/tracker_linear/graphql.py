"""The ``TrackerClient`` port over Linear's GraphQL API (ADR 0014).

The API key is read from ``environ`` on each call, never at construction, and is sent as the
bare ``Authorization`` value (a personal API key takes no ``Bearer``). Caller values (team,
label, issue id) travel only as GraphQL variables, never in the query text.

Every write resolves the identifier (``DEM-1``) to the issue's UUID once, with ``issue(id:)``,
and passes only UUIDs to the mutation (D-c). A write that would change nothing (the current
state, a present label added, an absent label removed) sends no mutation.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from agent_hub.core.errors import TrackerError
from agent_hub.core.tracker.tracker_client import ISSUE_ID_PATTERN, Issue

LINEAR_GRAPHQL_URL = "https://api.linear.app/graphql"
LINEAR_API_KEY_VARIABLE = "LINEAR_API_KEY"
DEFAULT_TIMEOUT_S = 30.0
# Issues per request; Linear's default page size (D-c).
PAGE_SIZE = 50
# WorkflowState.type values that count as done (D-a); list_ready leaves them out.
DONE_STATE_TYPES = ("completed", "canceled", "duplicate")
# Untrusted text (a Linear error message) quoted in an error is cut to this many characters.
MAX_QUOTED_CHARS = 200


class Post(Protocol):
    """The HTTP transport: POST ``body`` to ``url`` and return ``(status, response body)``."""

    def __call__(
        self, url: str, headers: Mapping[str, str], body: bytes, *, timeout_s: float
    ) -> tuple[int, bytes]:
        """Send one request, giving up after ``timeout_s`` seconds."""
        ...


_ISSUE_FIELDS = "identifier title url state { name } labels { nodes { name } }"

_LIST_READY_ISSUES = (
    "query ListReadyIssues($filter: IssueFilter!, $first: Int!, $after: String) {"
    " issues(filter: $filter, first: $first, after: $after) {"
    f" nodes {{ {_ISSUE_FIELDS} }} pageInfo {{ hasNextPage endCursor }} }} }}"
)

_GET_ISSUE = f"query GetIssue($id: String!) {{ issue(id: $id) {{ {_ISSUE_FIELDS} }} }}"

_ISSUE_REF = (
    "query IssueRef($id: String!) {"
    " issue(id: $id) { id team { key } state { name } labels { nodes { id name } } } }"
)

_FIND_STATES = (
    "query FindStates($filter: WorkflowStateFilter!) {"
    " workflowStates(filter: $filter) { nodes { id } } }"
)

_FIND_LABELS = (
    "query FindLabels($filter: IssueLabelFilter!) { issueLabels(filter: $filter) { nodes { id } } }"
)

_UPDATE_ISSUE = (
    "mutation UpdateIssue($id: String!, $input: IssueUpdateInput!) {"
    " issueUpdate(id: $id, input: $input) { success } }"
)

_CREATE_COMMENT = (
    "mutation CreateComment($input: CommentCreateInput!) {"
    " commentCreate(input: $input) { success } }"
)


@dataclass(frozen=True, kw_only=True, slots=True)
class _IssueRef:
    """What a write needs to know about an issue: its UUID, team, state and labels by name."""

    issue_id: str
    uuid: str
    team: str
    state: str
    label_ids: dict[str, str]


class LinearGraphqlTrackerClient:
    """A ``TrackerClient`` that calls Linear's GraphQL API through ``post``."""

    def __init__(
        self,
        *,
        environ: Mapping[str, str],
        post: Post | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._environ = environ
        self._post = post
        self._timeout_s = timeout_s

    def list_ready(self, team: str, label: str) -> list[Issue]:
        """Return the team's issues with the label whose state is not done, following pages."""
        issue_filter = {
            "team": {"key": {"eq": team}},
            "labels": {"some": {"name": {"eq": label}}},
            "state": {"type": {"nin": list(DONE_STATE_TYPES)}},
        }
        issues: list[Issue] = []
        after: str | None = None
        while True:
            data = self._request(
                operation="list_ready",
                issue_id=None,
                operation_name="ListReadyIssues",
                query=_LIST_READY_ISSUES,
                variables={"filter": issue_filter, "first": PAGE_SIZE, "after": after},
            )
            connection = data["issues"]
            issues.extend(_issue_from_node(node) for node in connection["nodes"])
            if not connection["pageInfo"]["hasNextPage"]:
                return issues
            after = connection["pageInfo"]["endCursor"]

    def get_issue(self, issue_id: str) -> Issue:
        """Return the issue with the identifier ``issue_id``."""
        _check_issue_id("get_issue", issue_id)
        data = self._request(
            operation="get_issue",
            issue_id=issue_id,
            operation_name="GetIssue",
            query=_GET_ISSUE,
            variables={"id": issue_id},
        )
        return _issue_from_node(data["issue"])

    def move_state(self, issue_id: str, state_name: str) -> None:
        """Move the issue to its team's state ``state_name``; the current state is a no-op."""
        ref = self._issue_ref("move_state", issue_id)
        if ref.state == state_name:
            return
        states = self._node_ids(
            operation="move_state",
            issue_id=issue_id,
            operation_name="FindStates",
            query=_FIND_STATES,
            issue_filter={"team": {"key": {"eq": ref.team}}, "name": {"eq": state_name}},
        )
        if not states:
            raise TrackerError(
                operation="move_state",
                issue_id=issue_id,
                cause=f"state {state_name!r} not found in team {ref.team}",
                fix=f"use the name of a workflow state of team {ref.team}",
            )
        self._update("move_state", ref, {"stateId": states[0]})

    def add_label(self, issue_id: str, name: str) -> None:
        """Add a label of the issue's team or the workspace; a present label is a no-op."""
        ref = self._issue_ref("add_label", issue_id)
        if name in ref.label_ids:
            return
        label_id = self._label_id("add_label", ref, name)
        self._update("add_label", ref, {"addedLabelIds": [label_id]})

    def remove_label(self, issue_id: str, name: str) -> None:
        """Remove a label; a known label the issue does not carry is a no-op."""
        ref = self._issue_ref("remove_label", issue_id)
        label_id = ref.label_ids.get(name)
        if label_id is None:
            # Absent from the issue: nothing to change, but an unknown name is still an error.
            self._label_id("remove_label", ref, name)
            return
        self._update("remove_label", ref, {"removedLabelIds": [label_id]})

    def comment(self, issue_id: str, body: str) -> None:
        """Add one comment with ``body`` to the issue."""
        ref = self._issue_ref("comment", issue_id)
        data = self._request(
            operation="comment",
            issue_id=issue_id,
            operation_name="CreateComment",
            query=_CREATE_COMMENT,
            variables={"input": {"issueId": ref.uuid, "body": body}},
        )
        _check_success("comment", issue_id, data["commentCreate"])

    def _issue_ref(self, operation: str, issue_id: str) -> _IssueRef:
        """Resolve the identifier to the issue's UUID, team, state and labels (one request)."""
        _check_issue_id(operation, issue_id)
        data = self._request(
            operation=operation,
            issue_id=issue_id,
            operation_name="IssueRef",
            query=_ISSUE_REF,
            variables={"id": issue_id},
        )
        node = data["issue"]
        return _IssueRef(
            issue_id=issue_id,
            uuid=node["id"],
            team=node["team"]["key"],
            state=node["state"]["name"],
            label_ids={label["name"]: label["id"] for label in node["labels"]["nodes"]},
        )

    def _label_id(self, operation: str, ref: _IssueRef, name: str) -> str:
        """Return the id of the team's label ``name``, else the workspace's; raise when neither."""
        for team_filter in ({"key": {"eq": ref.team}}, {"null": True}):
            labels = self._node_ids(
                operation=operation,
                issue_id=ref.issue_id,
                operation_name="FindLabels",
                query=_FIND_LABELS,
                issue_filter={"name": {"eq": name}, "team": team_filter},
            )
            if labels:
                return labels[0]
        raise TrackerError(
            operation=operation,
            issue_id=ref.issue_id,
            cause=f"label {name!r} not found in team {ref.team} or the workspace",
            fix="create the label in Linear first",
        )

    def _node_ids(
        self,
        *,
        operation: str,
        issue_id: str,
        operation_name: str,
        query: str,
        issue_filter: dict[str, Any],
    ) -> list[str]:
        data = self._request(
            operation=operation,
            issue_id=issue_id,
            operation_name=operation_name,
            query=query,
            variables={"filter": issue_filter},
        )
        (connection,) = data.values()
        return [node["id"] for node in connection["nodes"]]

    def _update(self, operation: str, ref: _IssueRef, update_input: dict[str, Any]) -> None:
        data = self._request(
            operation=operation,
            issue_id=ref.issue_id,
            operation_name="UpdateIssue",
            query=_UPDATE_ISSUE,
            variables={"id": ref.uuid, "input": update_input},
        )
        _check_success(operation, ref.issue_id, data["issueUpdate"])

    def _request(
        self,
        *,
        operation: str,
        issue_id: str | None,
        operation_name: str,
        query: str,
        variables: dict[str, Any],
    ) -> Any:
        """POST the query, named ``operation_name`` in its text, and return its ``data``."""
        if self._post is None:
            raise TrackerError(
                operation=operation,
                issue_id=issue_id,
                cause="no HTTP transport",
                fix="pass post= to LinearGraphqlTrackerClient",
            )
        headers = {
            "Content-Type": "application/json",
            "Authorization": self._environ[LINEAR_API_KEY_VARIABLE],
        }
        body = json.dumps(
            {"query": query, "operationName": operation_name, "variables": variables}
        ).encode()
        _status, response = self._post(LINEAR_GRAPHQL_URL, headers, body, timeout_s=self._timeout_s)
        payload = json.loads(response)
        errors = payload.get("errors")
        if errors:
            raise TrackerError(
                operation=operation,
                issue_id=issue_id,
                cause=f"Linear answered with an error: {_first_message(errors)}",
                fix="check the issue id and the names passed",
            )
        return payload["data"]


def _check_issue_id(operation: str, issue_id: str) -> None:
    if not ISSUE_ID_PATTERN.fullmatch(issue_id):
        raise TrackerError(
            operation=operation,
            issue_id=issue_id,
            cause="malformed issue id",
            fix="pass an identifier such as DEM-1",
        )


def _check_success(operation: str, issue_id: str, payload: Mapping[str, Any]) -> None:
    if payload["success"] is not True:
        raise TrackerError(
            operation=operation,
            issue_id=issue_id,
            cause="Linear reported no success",
            fix="check the issue in Linear, then try again",
        )


def _first_message(errors: Any) -> str:
    """The first GraphQL error's message, quoted and cut: it is untrusted text."""
    first = errors[0] if isinstance(errors, list) else None
    message = first.get("message") if isinstance(first, dict) else None
    return repr(str(message)[:MAX_QUOTED_CHARS])


def _issue_from_node(node: Mapping[str, Any]) -> Issue:
    return Issue(
        id=node["identifier"],
        title=node["title"],
        state=node["state"]["name"],
        labels=tuple(label["name"] for label in node["labels"]["nodes"]),
        url=node["url"],
    )
