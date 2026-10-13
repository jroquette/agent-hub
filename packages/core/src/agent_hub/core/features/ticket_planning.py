"""The planning of a feature's tickets (AGH-136 D2, S4, D5): a pure fold over plan and snapshot.

Each ticket of the plan (``features.json`` → ``tickets``) and each id of ``linear`` becomes one
row, named by its ``ref`` (its tracker id once created, else its draft key). A "blocked by" edge
comes from the plan's ``blocked_by``, from Linear's relations, or both, and says so. A ticket is
done when its Linear state type is ``completed``; a canceled (or duplicate) ticket never blocks
and is left out of the planning. Over the tickets neither done nor canceled: dependency cycles
(strongly connected components) are flagged and left out, and so is a ticket waiting on a
blocker outside the feature that is not done, canceled or known (it is listed under ``waiting``);
the rest are layered by Kahn's algorithm (each layer can run in parallel, the first is
``can_start``), and the recommended order is the layers in turn,
each by priority (1 urgent first, 0 none last), then plan ``order``, then ref. Blockers outside
the feature (named by Linear's relations, or only by the plan's ``blocked_by``) are listed with
the status Linear returned for them. Without a snapshot the readiness comes from the plan's edges
alone and every status is unknown. Linear's text is untrusted: titles, assignees and state names
are redacted (r1) and clipped, and a url is kept only under
``https://linear.app/``. Same input, same output, whatever the order of the input.
"""

import re
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Final
from urllib.parse import urlsplit

from agent_hub.core.features.feature_record import PlannedTicket, RecordAc
from agent_hub.core.features.ticket_view import (
    EdgeSource,
    ExternalBlocker,
    Readiness,
    TicketEdge,
    TicketPlan,
    TicketRow,
)
from agent_hub.core.redaction.redact import clip, redact_text
from agent_hub.core.tracker.tracker_client import ISSUE_ID_PATTERN
from agent_hub.core.tracker.tracker_reader import (
    MAX_RELATIONS,
    IssueState,
    IssueSummary,
    TicketSnapshot,
)

TITLE_CHARS: Final = 200
ASSIGNEE_CHARS: Final = 80
STATE_CHARS: Final = 80
LINEAR_HOST: Final = "linear.app"
DONE_TYPES: Final = frozenset({"completed"})
CANCELED_TYPES: Final = frozenset({"canceled", "duplicate"})
# Linear's priority 0 means "no priority": it sorts after 4 (low).
_NO_PRIORITY_RANK: Final = 5
_NO_ORDER: Final = 1 << 62
_DIGITS: Final = re.compile(r"(\d+)")
_UNSAFE_URL: Final = re.compile(r"[\s\x00-\x1f\x7f\\]")


@dataclass(frozen=True, kw_only=True, slots=True)
class TicketBoard:
    """The feature's ticket rows (by plan order, then ref) and their planning."""

    rows: tuple[TicketRow, ...]
    plan: TicketPlan


@dataclass(kw_only=True, slots=True)
class _Node:
    ref: str
    key: str | None
    id: str | None
    planned: PlannedTicket | None
    summary: IssueSummary | None
    rank: tuple[int, int, tuple[str | int, ...]] = (0, 0, ())
    edges: dict[str, set[EdgeSource]] = field(default_factory=dict)

    @property
    def state(self) -> IssueState | None:
        return None if self.summary is None else self.summary.state

    @property
    def done(self) -> bool:
        return self.state is not None and self.state.type in DONE_TYPES

    @property
    def canceled(self) -> bool:
        return self.state is not None and self.state.type in CANCELED_TYPES


def ticket_board(
    planned: Sequence[PlannedTicket],
    acs: Sequence[RecordAc],
    snapshot: TicketSnapshot | None,
    *,
    linear: Sequence[str] = (),
    approved: Collection[str] = (),
) -> TicketBoard:
    """The rows and planning of a feature's tickets.

    ``planned`` is the plan's tickets and ``linear`` the record's issue ids (an id no planned
    ticket has becomes a row with no key); ``acs`` gives each row the ACs whose ``ticket`` names
    it (withdrawn ones left out). ``snapshot`` is Linear's read of the ids, None when Linear was
    not read. ``approved`` names the tickets (key or id, any case) with an approved review
    record; a row is reviewed when Linear has it ``completed`` or it is approved, unknown
    (None) without a snapshot and a record.
    """
    warnings: list[str] = []
    summaries = {} if snapshot is None else {item.id: item for item in snapshot.summaries}
    nodes = _nodes(planned, linear, summaries=summaries, warnings=warnings)
    by_ref = {node.ref: node for node in nodes}
    resolve = _resolver(nodes)
    externals = _outside(nodes, summaries, () if snapshot is None else snapshot.external)
    _link(nodes, resolve=resolve, warnings=warnings)
    if snapshot is not None:
        warnings.extend(
            f"Linear does not know {missing}; it is shown from the plan."
            for missing in sorted(snapshot.missing, key=_natural)
        )

    def settled(ref: str) -> bool:
        node = by_ref.get(ref)
        if node is not None:
            return node.done or node.canceled
        summary = externals.get(ref)
        return summary is not None and summary.state.type in DONE_TYPES | CANCELED_TYPES

    active = {node.ref for node in nodes if not (node.done or node.canceled)}
    graph = {ref: sorted(b for b in by_ref[ref].edges if b in active) for ref in sorted(active)}
    cycles = _cycles(graph, by_ref)
    in_cycle = {ref for cycle in cycles for ref in cycle}
    # A ticket behind an open (or unread) blocker outside the feature cannot start: it and the
    # tickets after it get no layer, so every layer's blockers are in earlier layers or settled.
    held = {
        ref for ref in active if any(b not in by_ref and not settled(b) for b in by_ref[ref].edges)
    }
    layers = _layers(graph, in_cycle | held, by_ref)
    order = tuple(ref for layer in layers for ref in layer)
    readiness: dict[str, Readiness] = {}
    waiting_on: dict[str, tuple[str, ...]] = {}
    for node in nodes:
        waiting_on[node.ref] = tuple(b for b in sorted(node.edges, key=_natural) if not settled(b))
        readiness[node.ref] = _readiness(node, in_cycle=in_cycle, waiting=waiting_on[node.ref])
    blocks = _blocks(nodes)
    approved_names = {name.lower() for name in approved}
    rows = tuple(
        _row(
            node,
            acs=_acs_of(node, acs, resolve),
            blocks=blocks.get(node.ref, ()),
            readiness=readiness[node.ref],
            waiting_on=waiting_on[node.ref],
            reviewed=_reviewed(node, approved_names, read=snapshot is not None),
        )
        for node in nodes
    )
    waiting = [ref for ref in order if readiness[ref] == "waiting"]
    waiting += sorted(
        (n.ref for n in nodes if readiness[n.ref] == "waiting" and n.ref not in order),
        key=lambda ref: by_ref[ref].rank,
    )
    plan = TicketPlan(
        layers=layers,
        can_start=tuple(ref for ref in order if readiness[ref] == "can_start"),
        order=order,
        waiting=tuple(waiting),
        cycles=cycles,
        external_blockers=_external_blockers(nodes, by_ref, externals),
        critical_path=_critical_path(order, graph, by_ref),
        warnings=tuple(warnings),
    )
    return TicketBoard(rows=rows, plan=plan)


def safe_linear_url(url: str | None) -> str | None:
    """``url`` when it is an ``https://linear.app/`` address with no credentials, else None."""
    if url is None or _UNSAFE_URL.search(url) is not None:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme != "https" or parts.netloc != LINEAR_HOST:
        return None
    return url


def _natural(text: str) -> tuple[str | int, ...]:
    """A sort key that puts ``DEM-9`` before ``DEM-10``: text and numbers alternate."""
    return tuple(int(part) if index % 2 else part for index, part in enumerate(_DIGITS.split(text)))


def _is_issue_id(text: str) -> bool:
    return ISSUE_ID_PATTERN.fullmatch(text) is not None


def _outside(
    nodes: Sequence[_Node], summaries: dict[str, IssueSummary], external: Iterable[IssueSummary]
) -> dict[str, IssueSummary]:
    """Linear's summaries of issues that are no row: the blockers outside the feature, whether
    the snapshot asked for them (a plan-only ``blocked_by``) or Linear's relations named them."""
    rows = {node.id for node in nodes if node.id is not None}
    outside = {item.id: item for item in external}
    outside.update((issue, item) for issue, item in summaries.items() if issue not in rows)
    return outside


def _nodes(
    planned: Sequence[PlannedTicket],
    linear: Sequence[str],
    *,
    summaries: dict[str, IssueSummary],
    warnings: list[str],
) -> list[_Node]:
    nodes: list[_Node] = []
    keys: set[str] = set()
    ids: set[str] = set()
    for ticket in sorted(planned, key=_plan_sort_key):
        if ticket.key in keys:
            warnings.append(f"Ticket key {ticket.key} is planned twice; the first is used.")
            continue
        if ticket.id is not None and ticket.id in ids:
            warnings.append(f"Issue {ticket.id} is planned twice; the first is used.")
            continue
        keys.add(ticket.key)
        if ticket.id is not None:
            ids.add(ticket.id)
        nodes.append(
            _Node(
                ref=ticket.id or ticket.key,
                key=ticket.key,
                id=ticket.id,
                planned=ticket,
                summary=summaries.get(ticket.id) if ticket.id is not None else None,
            )
        )
    for issue in sorted(set(linear), key=_natural):
        if _is_issue_id(issue) and issue not in ids and issue not in keys:
            ids.add(issue)
            nodes.append(
                _Node(ref=issue, key=None, id=issue, planned=None, summary=summaries.get(issue))
            )
    for node in nodes:
        node.rank = _rank(node)
    return nodes


def _plan_sort_key(ticket: PlannedTicket) -> tuple[int, tuple[str | int, ...], str]:
    order = _NO_ORDER if ticket.order is None else ticket.order
    return order, _natural(ticket.key), ticket.id or ""


def _rank(node: _Node) -> tuple[int, int, tuple[str | int, ...]]:
    priority = None if node.summary is None else node.summary.priority
    order = None if node.planned is None else node.planned.order
    return (
        priority if priority is not None and priority > 0 else _NO_PRIORITY_RANK,
        _NO_ORDER if order is None else order,
        _natural(node.ref),
    )


type _Resolve = dict[str, str]


def _resolver(nodes: Iterable[_Node]) -> _Resolve:
    """Each key and id of a row, to the row's ref."""
    names: dict[str, str] = {}
    for node in nodes:
        if node.id is not None:
            names[node.id] = node.ref
    for node in nodes:
        if node.key is not None:
            names.setdefault(node.key, node.ref)
    return names


def _link(nodes: Sequence[_Node], *, resolve: _Resolve, warnings: list[str]) -> None:
    """Fills each row's ``edges``: blocker ref → the sources that name the edge."""
    by_ref = {node.ref: node for node in nodes}
    for node in nodes:
        _plan_edges(node, resolve=resolve, warnings=warnings)
        _linear_edges(node, by_ref=by_ref, resolve=resolve, warnings=warnings)


def _plan_edges(node: _Node, *, resolve: _Resolve, warnings: list[str]) -> None:
    for name in () if node.planned is None else node.planned.blocked_by:
        blocker = resolve.get(name, name if _is_issue_id(name) else None)
        if blocker is None:
            warnings.append(f"{node.ref} is blocked by {name}, which the plan does not list.")
        elif blocker == node.ref:
            warnings.append(f"{node.ref} is blocked by itself; the edge is ignored.")
        else:
            node.edges.setdefault(blocker, set()).add("plan")


def _linear_edges(
    node: _Node, *, by_ref: dict[str, _Node], resolve: _Resolve, warnings: list[str]
) -> None:
    if node.summary is None:
        return
    if node.summary.relations_truncated:
        warnings.append(
            f"Linear returned only the first {MAX_RELATIONS} relations of {node.ref}; "
            "some blockers may be missing."
        )
    for issue in node.summary.blocked_by:
        blocker = resolve.get(issue, issue)
        if blocker != node.ref:
            node.edges.setdefault(blocker, set()).add("linear")
    for issue in node.summary.blocks:
        blocked = resolve.get(issue)
        if blocked is not None and blocked != node.ref:
            by_ref[blocked].edges.setdefault(node.ref, set()).add("linear")


def _source(sources: set[EdgeSource]) -> EdgeSource:
    return "both" if len(sources) > 1 else next(iter(sources))


def _readiness(node: _Node, *, in_cycle: set[str], waiting: tuple[str, ...]) -> Readiness:
    if node.done:
        return "done"
    if node.canceled:
        return "canceled"
    if node.ref in in_cycle:
        return "in_cycle"
    return "waiting" if waiting else "can_start"


def _cycles(graph: dict[str, list[str]], by_ref: dict[str, _Node]) -> tuple[tuple[str, ...], ...]:
    """The strongly connected components of more than one ticket: the tickets each reaches
    and that reach it back (a few hundred tickets at most, so reachability is cheap)."""
    reach = {ref: _reachable(graph, ref) for ref in graph}
    found: set[tuple[str, ...]] = set()
    for ref in graph:
        component = {other for other in reach[ref] if ref in reach[other]} | {ref}
        if len(component) > 1:
            found.add(tuple(sorted(component, key=lambda r: by_ref[r].rank)))
    return tuple(sorted(found, key=lambda cycle: by_ref[cycle[0]].rank))


def _reachable(graph: dict[str, list[str]], start: str) -> set[str]:
    seen: set[str] = set()
    todo = list(graph[start])
    while todo:
        ref = todo.pop()
        if ref not in seen:
            seen.add(ref)
            todo.extend(graph[ref])
    return seen


def _layers(
    graph: dict[str, list[str]], held: set[str], by_ref: dict[str, _Node]
) -> tuple[tuple[str, ...], ...]:
    """Kahn's layers over the tickets not ``held`` (in a cycle, or behind an open blocker outside
    the feature); a ticket after a held one never gets one."""
    pending = {ref: set(blockers) for ref, blockers in graph.items() if ref not in held}
    layers: list[tuple[str, ...]] = []
    while True:
        layer = sorted(
            (ref for ref, left in pending.items() if not left), key=lambda r: by_ref[r].rank
        )
        if not layer:
            return tuple(layers)
        layers.append(tuple(layer))
        for ref in layer:
            del pending[ref]
        for left in pending.values():
            left.difference_update(layer)


def _critical_path(
    order: tuple[str, ...], graph: dict[str, list[str]], by_ref: dict[str, _Node]
) -> tuple[str, ...]:
    """The longest chain of tickets in ``order`` by count; ties go to the better ranked."""
    length: dict[str, int] = {}
    previous: dict[str, str | None] = {}
    for ref in order:
        blockers = [b for b in graph[ref] if b in length]
        best = min(blockers, key=lambda b: (-length[b], by_ref[b].rank), default=None)
        previous[ref] = best
        length[ref] = 1 if best is None else length[best] + 1
    if not order:
        return ()
    end: str | None = min(order, key=lambda r: (-length[r], by_ref[r].rank))
    chain: list[str] = []
    while end is not None:
        chain.append(end)
        end = previous[end]
    return tuple(reversed(chain))


def _blocks(nodes: Sequence[_Node]) -> dict[str, tuple[str, ...]]:
    blocked: dict[str, list[str]] = {}
    refs = {node.ref for node in nodes}
    for node in nodes:
        for blocker in node.edges:
            if blocker in refs:
                blocked.setdefault(blocker, []).append(node.ref)
    return {ref: tuple(sorted(items, key=_natural)) for ref, items in blocked.items()}


def _acs_of(node: _Node, acs: Sequence[RecordAc], resolve: _Resolve) -> tuple[str, ...]:
    named = (
        ac.id
        for ac in acs
        if not ac.withdrawn and ac.ticket is not None and resolve.get(ac.ticket) == node.ref
    )
    return tuple(sorted(set(named), key=_natural))


def _reviewed(node: _Node, approved: set[str], *, read: bool) -> bool | None:
    if node.done:
        return True
    names = {name.lower() for name in (node.key, node.id) if name is not None}
    if names & approved:
        return True
    return False if read else None


def _text(text: str | None, limit: int) -> str | None:
    return None if text is None else clip(redact_text(text), limit)


def _state(state: IssueState | None) -> IssueState | None:
    """Linear's state with its name redacted and clipped like a title; the type is a closed set."""
    if state is None:
        return None
    return IssueState(name=_text(state.name, STATE_CHARS) or "", type=state.type)


def _row(
    node: _Node,
    *,
    acs: tuple[str, ...],
    blocks: tuple[str, ...],
    readiness: Readiness,
    waiting_on: tuple[str, ...],
    reviewed: bool | None,
) -> TicketRow:
    summary = node.summary
    planned = node.planned
    title = summary.title if summary is not None else None if planned is None else planned.title
    return TicketRow(
        ref=node.ref,
        key=node.key,
        id=node.id,
        title=_text(title, TITLE_CHARS),
        state=_state(node.state),
        assignee=None if summary is None else _text(summary.assignee, ASSIGNEE_CHARS),
        url=None if summary is None else safe_linear_url(summary.url),
        priority=None if summary is None else summary.priority,
        estimate=None if summary is None else summary.estimate,
        repo=None if planned is None else planned.repo,
        order=None if planned is None else planned.order,
        acs=acs,
        blocked_by=tuple(
            TicketEdge(ref=ref, source=_source(node.edges[ref]))
            for ref in sorted(node.edges, key=_natural)
        ),
        blocks=blocks,
        readiness=readiness,
        waiting_on=waiting_on,
        reviewed=reviewed,
    )


def _external_blockers(
    nodes: Sequence[_Node], by_ref: dict[str, _Node], externals: dict[str, IssueSummary]
) -> tuple[ExternalBlocker, ...]:
    outside = {blocker for node in nodes for blocker in node.edges if blocker not in by_ref}
    blockers: list[ExternalBlocker] = []
    for issue in sorted(outside, key=_natural):
        summary = externals.get(issue)
        blockers.append(
            ExternalBlocker(
                id=issue,
                title=None if summary is None else _text(summary.title, TITLE_CHARS),
                state=None if summary is None else _state(summary.state),
                url=None if summary is None else safe_linear_url(summary.url),
                done=summary is not None and summary.state.type in DONE_TYPES,
            )
        )
    return tuple(blockers)
