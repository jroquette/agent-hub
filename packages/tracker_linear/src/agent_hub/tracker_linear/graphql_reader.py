"""The read-only ``TrackerReader`` port over Linear's GraphQL API (ADR 0025).

It shares ADR 0014's transport (``graphql_transport``): the fixed endpoint, no redirects, the
key from ``LINEAR_API_KEY`` read at call time and never in a message, answers of at most 4 MiB
checked field by field. It has no write method and never selects an issue's description,
comments or attachments.

The ids are grouped by team key and read with ``team.key`` plus ``number in`` (E6), at most
``BATCH_SIZE`` numbers per request, following a page cursor if Linear pages a batch. Ids Linear
does not return, and malformed ids (never sent), are ``missing``. "Blocks" are the issue's
``relations`` of type ``blocks``; "blocked by" its ``inverseRelations`` of that type. Blockers
that were not asked are ``external``, read from the same relation nodes (no second query). Each
direction reads at most ``MAX_RELATIONS``; more marks the summary ``relations_truncated`` (E10).

Each request waits at most ``timeout_s`` per blocking step; between requests, a read that has
taken ``deadline_s`` or more raises ``timeout``. Every failure is a ``TrackerError`` with its
``kind`` (``too_many`` beyond ``MAX_READ_IDS`` ids, before any request).
"""

import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Any, Final

from pydantic import ValidationError

from agent_hub.core.errors import TrackerError
from agent_hub.core.tracker.tracker_client import ISSUE_ID_PATTERN
from agent_hub.core.tracker.tracker_reader import (
    MAX_READ_IDS,
    MAX_RELATIONS,
    IssueState,
    IssueSummary,
    TicketSnapshot,
)
from agent_hub.tracker_linear.graphql_transport import (
    Nullable,
    Post,
    Shape,
    api_key,
    quoted,
    request_data,
    unexpected,
    urllib_post,
)

READ_OPERATION: Final = "issue_summaries"
DEFAULT_TIMEOUT_S: Final = 10.0
DEFAULT_DEADLINE_S: Final = 20.0
# Issue numbers per request (one team), and the page size asked for.
BATCH_SIZE: Final = 50
# The relation type that orders work: the relation's issue blocks its related issue.
BLOCKS: Final = "blocks"

_SUMMARY_FIELDS = (
    "identifier title url priority estimate state { name type } assignee { displayName }"
)
_RELATIONS = (
    f"relations(first: {MAX_RELATIONS}) {{ nodes {{ type relatedIssue {{ {_SUMMARY_FIELDS} }} }}"
    " pageInfo { hasNextPage } }"
)
_INVERSE_RELATIONS = (
    f"inverseRelations(first: {MAX_RELATIONS}) {{ nodes {{ type issue {{ {_SUMMARY_FIELDS} }} }}"
    " pageInfo { hasNextPage } }"
)
READ_ISSUE_SUMMARIES: Final = (
    "query ReadIssueSummaries($filter: IssueFilter!, $first: Int!, $after: String) {"
    " issues(filter: $filter, first: $first, after: $after) {"
    f" nodes {{ {_SUMMARY_FIELDS} {_RELATIONS} {_INVERSE_RELATIONS} }}"
    " pageInfo { hasNextPage endCursor } } }"
)

_NUMBER = (int, float)
_SUMMARY_SHAPE: dict[str, Shape] = {
    "identifier": str,
    "title": str,
    "url": str,
    "priority": _NUMBER,
    "estimate": (int, float, type(None)),
    "state": {"name": str, "type": str},
    "assignee": Nullable({"displayName": str}),
}


def _relations_shape(related: str) -> Shape:
    # A related issue the key cannot see may come back null: it is skipped, not an error.
    return {
        "nodes": [{"type": str, related: Nullable(_SUMMARY_SHAPE)}],
        "pageInfo": {"hasNextPage": bool},
    }


_ISSUE_SHAPE: Shape = _SUMMARY_SHAPE | {
    "relations": _relations_shape("relatedIssue"),
    "inverseRelations": _relations_shape("issue"),
}
_READ_SHAPE: Shape = {
    "issues": {
        "nodes": [_ISSUE_SHAPE],
        "pageInfo": {"hasNextPage": bool, "endCursor": (str, type(None))},
    }
}
_MAX_PRIORITY = 4


class LinearGraphqlTrackerReader:
    """A ``TrackerReader`` that reads Linear's GraphQL API through ``post``."""

    def __init__(
        self,
        *,
        environ: Mapping[str, str],
        post: Post | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        deadline_s: float = DEFAULT_DEADLINE_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._environ = environ
        self._post: Post = urllib_post if post is None else post
        self._timeout_s = timeout_s
        self._deadline_s = deadline_s
        self._clock = clock

    def __repr__(self) -> str:
        # Names no environment value: the key lives in ``environ``.
        return (
            f"LinearGraphqlTrackerReader(timeout_s={self._timeout_s},"
            f" deadline_s={self._deadline_s})"
        )

    def issue_summaries(self, ids: Sequence[str]) -> TicketSnapshot:
        """The summaries of ``ids`` (duplicates read once), at most ``MAX_READ_IDS`` of them."""
        unique = tuple(dict.fromkeys(ids))
        if len(unique) > MAX_READ_IDS:
            raise TrackerError(
                operation=READ_OPERATION,
                cause=f"{len(unique)} issue ids asked, at most {MAX_READ_IDS} per read",
                fix="read fewer ids at a time",
                kind="too_many",
            )
        api_key(self._environ, READ_OPERATION, None)
        nodes = self._read_nodes(_by_team(unique))
        summaries = tuple(_summary(nodes[issue_id]) for issue_id in unique if issue_id in nodes)
        found = {summary.id for summary in summaries}
        external: dict[str, IssueSummary] = {}
        for issue_id in unique:
            if issue_id in nodes:
                for blocker in _related(nodes[issue_id], "inverseRelations", "issue"):
                    if blocker["identifier"] not in found:
                        external.setdefault(blocker["identifier"], _bare_summary(blocker))
        return TicketSnapshot(
            summaries=summaries,
            missing=tuple(issue_id for issue_id in unique if issue_id not in found),
            external=tuple(external[issue_id] for issue_id in sorted(external)),
        )

    def _read_nodes(self, teams: dict[str, list[int]]) -> dict[str, Any]:
        """Every issue node Linear returns for ``teams``' numbers, by identifier."""
        nodes: dict[str, Any] = {}
        started = self._clock()
        requests = 0
        for team, numbers in teams.items():
            for start in range(0, len(numbers), BATCH_SIZE):
                batch = numbers[start : start + BATCH_SIZE]
                asked = {f"{team}-{number}" for number in batch}
                after: str | None = None
                while True:
                    if requests:
                        self._check_deadline(started)
                    requests += 1
                    connection = self._page(team, batch, after)["issues"]
                    page = [_checked_node(node, asked) for node in connection["nodes"]]
                    nodes.update((node["identifier"], node) for node in page)
                    if not connection["pageInfo"]["hasNextPage"]:
                        break
                    after = connection["pageInfo"]["endCursor"]
                    if after is None or not page:
                        raise unexpected(READ_OPERATION, None, "a next page without issues")
        return nodes

    def _page(self, team: str, batch: list[int], after: str | None) -> Any:
        return request_data(
            post=self._post,
            environ=self._environ,
            timeout_s=self._timeout_s,
            operation=READ_OPERATION,
            issue_id=None,
            operation_name="ReadIssueSummaries",
            query=READ_ISSUE_SUMMARIES,
            variables={
                "filter": {"team": {"key": {"eq": team}}, "number": {"in": batch}},
                "first": BATCH_SIZE,
                "after": after,
            },
            shape=_READ_SHAPE,
        )

    def _check_deadline(self, started: float) -> None:
        if self._clock() - started >= self._deadline_s:
            raise TrackerError(
                operation=READ_OPERATION,
                cause=f"reading from Linear took over {self._deadline_s:g} s",
                fix="retry later, or read fewer issues",
                kind="timeout",
            )


def _by_team(ids: Sequence[str]) -> dict[str, list[int]]:
    """The well-formed ids' numbers by team key, both in first-asked order."""
    teams: dict[str, list[int]] = {}
    for issue_id in ids:
        if ISSUE_ID_PATTERN.fullmatch(issue_id):
            team, _, number = issue_id.partition("-")
            teams.setdefault(team, []).append(int(number))
    return teams


def _checked_node(node: Any, asked: set[str]) -> Any:
    if node["identifier"] not in asked:
        raise unexpected(
            READ_OPERATION, None, f"an issue not asked for, {quoted(node['identifier'])}"
        )
    return node


def _related(node: Any, direction: str, related: str) -> Iterator[Any]:
    """The issues of the node's ``blocks`` relations in ``direction``, at most MAX_RELATIONS."""
    for relation in node[direction]["nodes"][:MAX_RELATIONS]:
        if relation["type"] == BLOCKS and relation[related] is not None:
            _check_identifier(relation[related]["identifier"])
            yield relation[related]


def _truncated(node: Any, direction: str) -> bool:
    relations = node[direction]
    return bool(relations["pageInfo"]["hasNextPage"]) or len(relations["nodes"]) > MAX_RELATIONS


def _summary(node: Any) -> IssueSummary:
    blocks = [issue["identifier"] for issue in _related(node, "relations", "relatedIssue")]
    blocked_by = [issue["identifier"] for issue in _related(node, "inverseRelations", "issue")]
    return _bare_summary(node).model_copy(
        update={
            "blocks": tuple(dict.fromkeys(blocks)),
            "blocked_by": tuple(dict.fromkeys(blocked_by)),
            "relations_truncated": _truncated(node, "relations")
            or _truncated(node, "inverseRelations"),
        }
    )


def _bare_summary(node: Any) -> IssueSummary:
    """The node's own fields as a summary without relations; a value out of range raises."""
    identifier = _check_identifier(node["identifier"])
    priority, estimate = node["priority"], node["estimate"]
    if (
        isinstance(priority, bool)
        or priority not in range(_MAX_PRIORITY + 1)
        or isinstance(estimate, bool)
    ):
        raise unexpected(READ_OPERATION, None, f"issue {identifier} has a number out of range")
    try:
        return IssueSummary(
            id=identifier,
            title=node["title"],
            state=IssueState.model_validate(node["state"]),
            assignee=None if node["assignee"] is None else node["assignee"]["displayName"],
            url=node["url"],
            priority=int(priority),
            estimate=None if estimate is None else float(estimate),
            blocks=(),
            blocked_by=(),
        )
    except ValidationError as error:
        # The validation message would quote untrusted values: name the issue only.
        raise unexpected(
            READ_OPERATION, None, f"issue {identifier} has a field Linear should not answer"
        ) from error


def _check_identifier(identifier: str) -> str:
    # The identifier is untrusted: only an issue id's shape is passed on.
    if not ISSUE_ID_PATTERN.fullmatch(identifier):
        raise unexpected(READ_OPERATION, None, f"an issue identifier {quoted(identifier)}")
    return identifier
