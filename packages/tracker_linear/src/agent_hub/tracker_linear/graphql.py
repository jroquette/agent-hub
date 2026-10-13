"""The ``TrackerClient`` port over Linear's GraphQL API (ADR 0014).

The transport (the key, the request, the checks on the answer) is ``graphql_transport``.

Every write resolves the identifier (``DEM-1``) to the issue's UUID once, with ``issue(id:)``,
and passes only UUIDs to the mutation (D-c). A write that would change nothing (the current
state, a present label added, an absent label removed) sends no mutation.

Every failure is a one-line ``TrackerError`` naming the operation, the issue id, the cause and
the fix (``graphql_transport`` lists the transport's). Nothing is retried. The key is never part
of a message, a ``repr`` or a log record.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from agent_hub.core.errors import TrackerError
from agent_hub.core.tracker.tracker_client import ISSUE_ID_PATTERN, UNSTARTED_STATE_TYPES, Issue
from agent_hub.tracker_linear.graphql_transport import (
    LINEAR_API_KEY_VARIABLE as LINEAR_API_KEY_VARIABLE,
)
from agent_hub.tracker_linear.graphql_transport import LINEAR_GRAPHQL_URL as LINEAR_GRAPHQL_URL
from agent_hub.tracker_linear.graphql_transport import MAX_QUOTED_CHARS as MAX_QUOTED_CHARS
from agent_hub.tracker_linear.graphql_transport import MAX_RESPONSE_BYTES as MAX_RESPONSE_BYTES
from agent_hub.tracker_linear.graphql_transport import (
    Post,
    Shape,
    quoted,
    request_data,
    unexpected,
)
from agent_hub.tracker_linear.graphql_transport import urllib_post as urllib_post

DEFAULT_TIMEOUT_S = 30.0
# Issues per request; Linear's default page size (D-c).
PAGE_SIZE = 50
# WorkflowState.type values that count as done (D-a); list_ready leaves them out.
DONE_STATE_TYPES = ("completed", "canceled", "duplicate")
# list_ready reads at most this many pages (PAGE_SIZE issues each), then raises.
MAX_PAGES = 20
# Labels read per issue; an issue with more raises instead of being read in part.
MAX_LABELS = 50


def _labels_selection(fields: str) -> str:
    """An issue's labels, at most ``MAX_LABELS``, with whether there are more."""
    return f"labels(first: {MAX_LABELS}) {{ nodes {{ {fields} }} pageInfo {{ hasNextPage }} }}"


_ISSUE_FIELDS = f"identifier title description url state {{ name }} {_labels_selection('name')}"
_ISSUE_SHAPE: Shape = {
    "identifier": str,
    "title": str,
    "description": (str, type(None)),
    "url": str,
    "state": {"name": str},
    "labels": {"nodes": [{"name": str}], "pageInfo": {"hasNextPage": bool}},
}

_LIST_READY_ISSUES = (
    "query ListReadyIssues($filter: IssueFilter!, $first: Int!, $after: String) {"
    " issues(filter: $filter, first: $first, after: $after) {"
    f" nodes {{ {_ISSUE_FIELDS} }} pageInfo {{ hasNextPage endCursor }} }} }}"
)

_LIST_READY_SHAPE: Shape = {
    "issues": {
        "nodes": [_ISSUE_SHAPE],
        "pageInfo": {"hasNextPage": bool, "endCursor": (str, type(None))},
    }
}

_GET_ISSUE = f"query GetIssue($id: String!) {{ issue(id: $id) {{ {_ISSUE_FIELDS} }} }}"

_ISSUE_REF = (
    "query IssueRef($id: String!) {"
    " issue(id: $id) { id team { key } state { name type }"
    f" {_labels_selection('id name')} }} }}"
)
_ISSUE_REF_SHAPE: Shape = {
    "issue": {
        "id": str,
        "team": {"key": str},
        "state": {"name": str, "type": str},
        "labels": {"nodes": [{"id": str, "name": str}], "pageInfo": {"hasNextPage": bool}},
    }
}

_FIND_STATES = (
    "query FindStates($filter: WorkflowStateFilter!) {"
    " workflowStates(filter: $filter) { nodes { id } } }"
)

_FIND_LABELS = (
    "query FindLabels($filter: IssueLabelFilter!) { issueLabels(filter: $filter) { nodes { id } } }"
)

_NODE_IDS_SHAPE: Shape = {"nodes": [{"id": str}]}

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
    """What a write needs to know about an issue: its UUID, team, state (name and type) and
    labels by name."""

    issue_id: str
    uuid: str
    team: str
    state: str
    state_type: str
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
        self._post: Post = urllib_post if post is None else post
        self._timeout_s = timeout_s

    def __repr__(self) -> str:
        # Names no environment value: the key lives in ``environ``.
        return f"LinearGraphqlTrackerClient(timeout_s={self._timeout_s})"

    def list_ready(self, team: str, label: str) -> list[Issue]:
        """Return the team's issues with the label whose state is not done, following pages."""
        issue_filter = {
            "team": {"key": {"eq": team}},
            "labels": {"some": {"name": {"eq": label}}},
            "state": {"type": {"nin": list(DONE_STATE_TYPES)}},
        }
        issues: list[Issue] = []
        after: str | None = None
        for _page in range(MAX_PAGES):
            data = self._request(
                operation="list_ready",
                issue_id=None,
                operation_name="ListReadyIssues",
                query=_LIST_READY_ISSUES,
                variables={"filter": issue_filter, "first": PAGE_SIZE, "after": after},
                shape=_LIST_READY_SHAPE,
            )
            connection = data["issues"]
            issues.extend(
                _issue_from_node("list_ready", None, node) for node in connection["nodes"]
            )
            if not connection["pageInfo"]["hasNextPage"]:
                return issues
            after = connection["pageInfo"]["endCursor"]
            if after is None:
                raise unexpected("list_ready", None, "a next page without a cursor")
        raise TrackerError(
            operation="list_ready",
            cause=f"more than {MAX_PAGES} pages of {PAGE_SIZE} issues match",
            fix="close or unlabel issues in Linear, or list a narrower label",
        )

    def get_issue(self, issue_id: str) -> Issue:
        """Return the issue with the identifier ``issue_id``."""
        _check_issue_id("get_issue", issue_id)
        data = self._request(
            operation="get_issue",
            issue_id=issue_id,
            operation_name="GetIssue",
            query=_GET_ISSUE,
            variables={"id": issue_id},
            shape={"issue": _ISSUE_SHAPE},
        )
        return _issue_from_node("get_issue", issue_id, data["issue"])

    def move_state(
        self, issue_id: str, state_name: str, *, only_if_unstarted: bool = False
    ) -> bool:
        """Move the issue to its team's state ``state_name``; the current state is a no-op.

        With ``only_if_unstarted``, an issue whose state type is not unstarted is left alone
        after ``IssueRef``, before the state is looked up. True when the issue moved.
        """
        ref = self._issue_ref("move_state", issue_id)
        if only_if_unstarted and ref.state_type not in UNSTARTED_STATE_TYPES:
            return False
        if ref.state == state_name:
            return False
        states = self._node_ids(
            operation="move_state",
            issue_id=issue_id,
            operation_name="FindStates",
            query=_FIND_STATES,
            root="workflowStates",
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
        return True

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
            shape={"commentCreate": {"success": bool}},
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
            shape=_ISSUE_REF_SHAPE,
        )
        node = data["issue"]
        return _IssueRef(
            issue_id=issue_id,
            uuid=node["id"],
            team=node["team"]["key"],
            state=node["state"]["name"],
            state_type=node["state"]["type"],
            label_ids={
                label["name"]: label["id"] for label in _label_nodes(operation, issue_id, node)
            },
        )

    def _label_id(self, operation: str, ref: _IssueRef, name: str) -> str:
        """Return the id of the team's label ``name``, else the workspace's; raise when neither."""
        for team_filter in ({"key": {"eq": ref.team}}, {"null": True}):
            labels = self._node_ids(
                operation=operation,
                issue_id=ref.issue_id,
                operation_name="FindLabels",
                query=_FIND_LABELS,
                root="issueLabels",
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
        root: str,
        issue_filter: dict[str, Any],
    ) -> list[str]:
        data = self._request(
            operation=operation,
            issue_id=issue_id,
            operation_name=operation_name,
            query=query,
            variables={"filter": issue_filter},
            shape={root: _NODE_IDS_SHAPE},
        )
        return [node["id"] for node in data[root]["nodes"]]

    def _update(self, operation: str, ref: _IssueRef, update_input: dict[str, Any]) -> None:
        data = self._request(
            operation=operation,
            issue_id=ref.issue_id,
            operation_name="UpdateIssue",
            query=_UPDATE_ISSUE,
            variables={"id": ref.uuid, "input": update_input},
            shape={"issueUpdate": {"success": bool}},
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
        shape: Shape,
    ) -> Any:
        """POST the query named ``operation_name``; return its ``data``, of the given ``shape``."""
        return request_data(
            post=self._post,
            environ=self._environ,
            timeout_s=self._timeout_s,
            operation=operation,
            issue_id=issue_id,
            operation_name=operation_name,
            query=query,
            variables=variables,
            shape=shape,
        )


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


def _issue_from_node(operation: str, issue_id: str | None, node: Mapping[str, Any]) -> Issue:
    # The identifier is untrusted: only an issue id's shape is passed on (callers sort by it).
    if not ISSUE_ID_PATTERN.fullmatch(node["identifier"]):
        raise unexpected(operation, issue_id, f"an issue identifier {quoted(node['identifier'])}")
    return Issue(
        id=node["identifier"],
        title=node["title"],
        description=node["description"] or "",
        state=node["state"]["name"],
        labels=tuple(label["name"] for label in _label_nodes(operation, issue_id, node)),
        url=node["url"],
    )


def _label_nodes(operation: str, issue_id: str | None, node: Mapping[str, Any]) -> list[Any]:
    """The issue's label nodes; more than ``MAX_LABELS`` raises (an issue is never read in part)."""
    labels = node["labels"]
    if labels["pageInfo"]["hasNextPage"] or len(labels["nodes"]) > MAX_LABELS:
        subject = "the issue" if "identifier" not in node else f"issue {node['identifier']}"
        raise TrackerError(
            operation=operation,
            issue_id=issue_id,
            cause=f"{subject} has more than {MAX_LABELS} labels",
            fix=f"remove labels from it in Linear (at most {MAX_LABELS} are read)",
        )
    nodes: list[Any] = labels["nodes"]
    return nodes
