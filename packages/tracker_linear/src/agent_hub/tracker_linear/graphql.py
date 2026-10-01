"""The ``TrackerClient`` port over Linear's GraphQL API (ADR 0014).

The API key is read from ``environ`` on each call, never at construction, and is sent as the
bare ``Authorization`` value (a personal API key takes no ``Bearer``). Caller values (team,
label, issue id) travel only as GraphQL variables, never in the query text.
"""

import json
from collections.abc import Mapping
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
        return json.loads(response)["data"]


def _check_issue_id(operation: str, issue_id: str) -> None:
    if not ISSUE_ID_PATTERN.fullmatch(issue_id):
        raise TrackerError(
            operation=operation,
            issue_id=issue_id,
            cause="malformed issue id",
            fix="pass an identifier such as DEM-1",
        )


def _issue_from_node(node: Mapping[str, Any]) -> Issue:
    return Issue(
        id=node["identifier"],
        title=node["title"],
        state=node["state"]["name"],
        labels=tuple(label["name"] for label in node["labels"]["nodes"]),
        url=node["url"],
    )
