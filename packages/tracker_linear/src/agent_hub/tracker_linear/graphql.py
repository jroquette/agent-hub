"""The ``TrackerClient`` port over Linear's GraphQL API (ADR 0014).

The API key is read from ``environ`` on each call, never at construction, and is sent as the
bare ``Authorization`` value (a personal API key takes no ``Bearer``). Caller values (team,
label, issue id) travel only as GraphQL variables, never in the query text.

Every write resolves the identifier (``DEM-1``) to the issue's UUID once, with ``issue(id:)``,
and passes only UUIDs to the mutation (D-c). A write that would change nothing (the current
state, a present label added, an absent label removed) sends no mutation.

Every failure is a one-line ``TrackerError`` naming the operation, the issue id, the cause and
the fix: a missing or malformed key (before any request), a transport ``OSError`` or timeout,
an HTTP error status, a body that is not JSON, a GraphQL ``errors`` array at any status, and an
answer whose shape is not the one the query selects. Nothing is retried. The key is never part
of a message, a ``repr`` or a log record.

The default transport is ``urllib_post`` (standard library only, AC-9.6); tests pass their own.
"""

import http.client
import json
import re
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from email.message import Message
from typing import IO, Any, Protocol, override

from agent_hub.core.errors import TrackerError
from agent_hub.core.tracker.tracker_client import ISSUE_ID_PATTERN, UNSTARTED_STATE_TYPES, Issue

LINEAR_GRAPHQL_URL = "https://api.linear.app/graphql"
LINEAR_API_KEY_VARIABLE = "LINEAR_API_KEY"
DEFAULT_TIMEOUT_S = 30.0
# Issues per request; Linear's default page size (D-c).
PAGE_SIZE = 50
# WorkflowState.type values that count as done (D-a); list_ready leaves them out.
DONE_STATE_TYPES = ("completed", "canceled", "duplicate")
# Untrusted text (a Linear error message) quoted in an error is cut to this many characters.
MAX_QUOTED_CHARS = 200
# A key is sent as a header value as is: only printable ASCII, no space, is accepted.
_API_KEY_PATTERN = re.compile(r"[\x21-\x7e]+")
# A longer answer is refused (the default transport reads at most one byte more).
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
# list_ready reads at most this many pages (PAGE_SIZE issues each), then raises.
MAX_PAGES = 20
# Labels read per issue; an issue with more raises instead of being read in part.
MAX_LABELS = 50


# A response shape: a type (or types) for a leaf, a dict of exactly these fields, or a list of
# items of one shape.
type Shape = type | tuple[type, ...] | dict[str, Shape] | list[Shape]

_UNEXPECTED_FIX = "Linear's API may have changed; report it with the operation named here"


class Post(Protocol):
    """The HTTP transport: POST ``body`` to ``url`` and return ``(status, response body)``.

    ``timeout_s`` bounds each blocking step (connecting, each read), not the whole call.
    """

    def __call__(
        self, url: str, headers: Mapping[str, str], body: bytes, *, timeout_s: float
    ) -> tuple[int, bytes]:
        """Send one request; a step that waits longer than ``timeout_s`` seconds gives up."""
        ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuses every redirect: a followed one would resend ``Authorization`` to its host."""

    @override
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: Message,
        newurl: str,
    ) -> None:
        # None makes urllib raise HTTPError for the 3xx, which urllib_post returns as an answer.
        return None


def opener_with(*handlers: urllib.request.BaseHandler) -> urllib.request.OpenerDirector:
    """urllib's default opener (proxies from the environment, verified HTTPS) minus redirects.

    ``handlers`` replace or add to the defaults, as in ``urllib.request.build_opener``.
    """
    return urllib.request.build_opener(_NoRedirect, *handlers)


_OPENER = opener_with()


def urllib_post(
    url: str, headers: Mapping[str, str], body: bytes, *, timeout_s: float
) -> tuple[int, bytes]:
    """The default ``Post``: one ``urllib`` POST, reading at most ``MAX_RESPONSE_BYTES + 1``.

    An HTTP error status, a redirect included (never followed), is an answer, returned as
    ``(status, body)``. ``timeout_s`` applies to each socket operation (connect, each read), so
    a slow trickle can take longer in total, and the DNS lookup has no bound. A timeout raises
    ``TimeoutError``; any other failure raises an ``OSError`` (a malformed HTTP answer becomes a
    ``ConnectionError``). No message names the headers, so the key never reaches one.
    """
    request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")  # noqa: S310 - fixed https endpoint
    try:
        try:
            response = _OPENER.open(request, timeout=timeout_s)
        except urllib.error.HTTPError as error:
            with error:
                return error.code, error.read(MAX_RESPONSE_BYTES + 1)
        with response:
            return response.status, response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.URLError as error:
        if isinstance(error.reason, TimeoutError):
            raise TimeoutError(f"no answer within {timeout_s:g} s") from error
        raise
    except http.client.HTTPException as error:
        raise ConnectionError(f"malformed HTTP answer ({type(error).__name__})") from error


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
                raise _unexpected("list_ready", None, "a next page without a cursor")
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
        key = self._api_key(operation, issue_id)
        headers = {"Content-Type": "application/json", "Authorization": key}
        body = json.dumps(
            {"query": query, "operationName": operation_name, "variables": variables}
        ).encode()
        try:
            status, response = self._post(
                LINEAR_GRAPHQL_URL, headers, body, timeout_s=self._timeout_s
            )
        except TimeoutError as error:
            raise TrackerError(
                operation=operation,
                issue_id=issue_id,
                cause=f"no answer from Linear within {self._timeout_s:g} s",
                fix="retry later",
            ) from error
        except OSError as error:
            raise TrackerError(
                operation=operation,
                issue_id=issue_id,
                cause=f"could not reach Linear: {_quoted(error)}",
                fix="check the network connection to api.linear.app, then retry",
            ) from error
        return _data(
            operation=operation,
            issue_id=issue_id,
            operation_name=operation_name,
            answer=(status, response),
            shape=shape,
        )

    def _api_key(self, operation: str, issue_id: str | None) -> str:
        """The key from ``environ``, checked before any request; its value is never quoted."""
        key = self._environ.get(LINEAR_API_KEY_VARIABLE, "")
        if not key:
            raise TrackerError(
                operation=operation,
                issue_id=issue_id,
                cause=f"{LINEAR_API_KEY_VARIABLE} is not set",
                fix=f"export {LINEAR_API_KEY_VARIABLE} with a Linear personal API key",
            )
        if not _API_KEY_PATTERN.fullmatch(key):
            raise TrackerError(
                operation=operation,
                issue_id=issue_id,
                cause=f"{LINEAR_API_KEY_VARIABLE} has a character outside printable ASCII",
                fix=f"set {LINEAR_API_KEY_VARIABLE} to the key alone, without spaces or newlines",
            )
        return key


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


def _data(
    *,
    operation: str,
    issue_id: str | None,
    operation_name: str,
    answer: tuple[int, bytes],
    shape: Shape,
) -> Any:
    """The answer's ``data``, of ``shape``; any failure the answer reports raises."""
    status, response = answer
    _check_status(operation, issue_id, status)
    payload = _decoded(operation, issue_id, answer)
    errors = payload.get("errors") if isinstance(payload, dict) else None
    if errors:
        raise TrackerError(
            operation=operation,
            issue_id=issue_id,
            cause=f"Linear answered with an error: {_first_message(errors)}",
            fix=_errors_fix(errors, issue_id),
        )
    if not 200 <= status < 300:  # noqa: PLR2004 - the HTTP success range
        raise TrackerError(
            operation=operation,
            issue_id=issue_id,
            cause=f"Linear rejected the request (HTTP {status})",
            fix=(
                "check the issue id and the state or label names passed"
                " (if they are right, Linear's API may have changed)"
            ),
        )
    data = payload.get("data") if isinstance(payload, dict) else None
    if not _fits(data, shape):
        raise _unexpected(operation, issue_id, f"{operation_name} answered another shape")
    return data


def _decoded(operation: str, issue_id: str | None, answer: tuple[int, bytes]) -> Any:
    """The answer's body as JSON, within ``MAX_RESPONSE_BYTES`` and the parser's nesting limit."""
    status, response = answer
    if len(response) > MAX_RESPONSE_BYTES:
        raise TrackerError(
            operation=operation,
            issue_id=issue_id,
            cause=f"Linear's answer is over {MAX_RESPONSE_BYTES // 1024**2} MiB",
            fix="list a narrower label, or report it with the operation named here",
        )
    try:
        return json.loads(response)
    except RecursionError as error:
        raise TrackerError(
            operation=operation,
            issue_id=issue_id,
            cause="Linear's answer is nested too deep to read",
            fix=_UNEXPECTED_FIX,
        ) from error
    except ValueError as error:
        raise TrackerError(
            operation=operation,
            issue_id=issue_id,
            cause=f"Linear answered a body that is not JSON (HTTP {status})",
            fix="retry later",
        ) from error


def _check_status(operation: str, issue_id: str | None, status: int) -> None:
    """Raise for the HTTP statuses whose fix does not depend on the body."""
    if status in {401, 403}:
        cause = f"Linear refused the key (HTTP {status})"
        fix = f"check that {LINEAR_API_KEY_VARIABLE} is a valid Linear API key with access"
    elif 300 <= status < 400:  # noqa: PLR2004 - HTTP redirects
        cause = f"Linear answered a redirect (HTTP {status})"
        fix = (
            "check for a proxy or network that redirects api.linear.app"
            " (redirects are not followed, so the key is never sent elsewhere)"
        )
    elif status == 429:  # noqa: PLR2004 - HTTP Too Many Requests
        cause, fix = f"Linear rate-limited the request (HTTP {status})", "retry later"
    elif status >= 500:  # noqa: PLR2004 - HTTP server errors
        cause, fix = f"Linear is unavailable (HTTP {status})", "retry later"
    else:
        return
    raise TrackerError(operation=operation, issue_id=issue_id, cause=cause, fix=fix)


def _errors_fix(errors: Any, issue_id: str | None) -> str:
    """The fix for a GraphQL ``errors`` array, from its ``extensions`` when they say more."""
    kinds = " ".join(
        value.lower()
        for error in (errors if isinstance(errors, list) else [])
        if isinstance(error, dict) and isinstance(error.get("extensions"), dict)
        for name, value in error["extensions"].items()
        if name in {"code", "type"} and isinstance(value, str)
    )
    if "ratelimited" in kinds:
        return "retry later"
    if "authentication" in kinds or "forbidden" in kinds:
        return f"check that {LINEAR_API_KEY_VARIABLE} is a valid Linear API key with access"
    if issue_id is not None:
        return f"check that {issue_id} exists in Linear and the key can read it"
    return "check the team key and the label name"


def _fits(value: Any, shape: Shape) -> bool:
    """Whether ``value`` has ``shape``: exactly the selected fields, each of its type."""
    if isinstance(shape, dict):
        return (
            isinstance(value, dict)
            and value.keys() == shape.keys()
            and all(_fits(value[name], field) for name, field in shape.items())
        )
    if isinstance(shape, list):
        (item,) = shape
        return isinstance(value, list) and all(_fits(element, item) for element in value)
    return isinstance(value, shape)


def _unexpected(operation: str, issue_id: str | None, detail: str) -> TrackerError:
    return TrackerError(
        operation=operation,
        issue_id=issue_id,
        cause=f"unexpected response from Linear: {detail}",
        fix=_UNEXPECTED_FIX,
    )


def _first_message(errors: Any) -> str:
    """The first GraphQL error's message, quoted and cut: it is untrusted text."""
    first = errors[0] if isinstance(errors, list) and errors else None
    message = first.get("message") if isinstance(first, dict) else None
    return _quoted(message)


def _quoted(text: object) -> str:
    """Untrusted text, cut to ``MAX_QUOTED_CHARS`` and quoted (escapes included)."""
    return repr(str(text)[:MAX_QUOTED_CHARS])


def _issue_from_node(operation: str, issue_id: str | None, node: Mapping[str, Any]) -> Issue:
    # The identifier is untrusted: only an issue id's shape is passed on (callers sort by it).
    if not ISSUE_ID_PATTERN.fullmatch(node["identifier"]):
        raise _unexpected(operation, issue_id, f"an issue identifier {_quoted(node['identifier'])}")
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
