"""The owner decides a plan change request from hub web (two-level-flows AC-2.7, AC-2.12,
AC-2.14; D-10, D-11, A5, P8): pure, no I/O but the ports.

While the request's ``implement`` run lives, hub web answers its gate through the approvals
route, and the run writes the records: ``RequestRuns`` finds the gate (an open ``human_gate``
approval in the run's session ``run:<run>``) and whether the run is gone (no run folded under
that id, or one that ended), and ``with_runs`` sets each open request's ``approval_id`` and
``decidable_here``. Only a request whose run is gone is decided here: ``DecideChangeRequest``
creates ``change-requests/<n>.decision.md`` once, never editing the request, and the next
``/implement`` of its ticket reads it. Under the run commands' lock (``RunGuard``, as a gate's
decision is), it refuses, writing nothing: a request that cannot be read or is already decided,
a run whose gate is open, a run that still lives (folded ``running``, a paused one included, or
held by a child hub web started), a decline without the owner's note (D-2) and a decision with
no person to name (``decided_by`` empty or ``unknown``, A5).
"""

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Final, Literal, Protocol

from agent_hub.core.approvals.approval import ApprovalKind
from agent_hub.core.brain.frontmatter import with_frontmatter
from agent_hub.core.errors import AgentHubError
from agent_hub.core.features.feature_view import ChangeDecisionView, ChangeRequestView
from agent_hub.core.features.owner_signoff import FeatureFolders, ProjectHubs
from agent_hub.core.features.ticket_records import (
    CHANGE_REQUESTS_FOLDER,
    ChangeRequest,
    change_requests,
    request_view,
)
from agent_hub.core.readmodels.filters import MAX_PAGE_LIMIT, ApprovalFilter
from agent_hub.core.readmodels.read_ports import EntityNotFoundError, EventReadModels
from agent_hub.core.workflows.gate_decisions import RUN_SESSION_PREFIX
from agent_hub.core.workflows.launch import RunGuard

MAX_NOTE_CHARS: Final = 2_000
# The open gates read for a project, at most this many pages (as RunGuard's live runs are).
MAX_GATE_PAGES: Final = 10

type ChangeDecision = Literal["approved", "declined"]


class ChangeRequestDecisionError(AgentHubError):
    """The decision is refused, nothing written; ``code`` names why (``note_required`` is the
    owner's input, the others the request's or its run's state) and ``reason`` says it."""

    def __init__(self, code: str, reason: str) -> None:
        self.code, self.reason = code, reason
        super().__init__(reason)


class DecisionWriter(Protocol):
    def create_decision(self, hub_path: str, *, slug: str, n: int, text: str) -> None:
        """Create ``brain/features/<slug>/change-requests/<n>.decision.md``; ``FileExistsError``
        when it exists."""
        ...


class RequestRuns:
    """The runs of change requests, as the event read models fold them."""

    def __init__(self, events: EventReadModels) -> None:
        self._events = events

    def gates(self, project: str) -> Mapping[str, str]:
        """The project's open person gates of runs: approval id by run id."""
        found: dict[str, str] = {}
        cursor: str | None = None
        for _ in range(MAX_GATE_PAGES):
            page = self._events.list_approvals(
                ApprovalFilter(
                    project=project,
                    kind=ApprovalKind.HUMAN_GATE,
                    status="open",
                    cursor=cursor,
                    limit=MAX_PAGE_LIMIT,
                )
            )
            for approval in page.items:
                run = approval.session_id.removeprefix(RUN_SESSION_PREFIX)
                if run != approval.session_id:
                    found.setdefault(run, approval.id)
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        return found

    def gone(self, run_id: str) -> bool:
        """Whether the run can no longer decide: none is folded under ``run_id``, or it ended."""
        try:
            return self._events.get_run(run_id).status != "running"
        except EntityNotFoundError:
            return True


def with_runs(
    requests: tuple[ChangeRequestView, ...], runs: RequestRuns, *, project: str
) -> tuple[ChangeRequestView, ...]:
    """Each open request with its run's open gate (``approval_id``) and, with none, whether its
    run is gone (``decidable_here``); the gates are read only when a request is open."""
    if not any(request.status == "open" for request in requests):
        return requests
    gates = runs.gates(project)
    annotated = []
    for request in requests:
        if request.status == "open":
            gate = gates.get(request.run_id) if request.run_id else None
            gone = gate is None and (request.run_id is None or runs.gone(request.run_id))
            request = request.model_copy(update={"approval_id": gate, "decidable_here": gone})
        annotated.append(request)
    return tuple(annotated)


def decision_note(
    *, n: int, decision: ChangeDecision, decided_by: str, at: datetime, note: str | None
) -> str:
    """The decision file's text: its frontmatter (each value on one line) and a title."""
    body = f"\n# Change request {n}: {decision}\n\nRecorded in hub web by {decided_by}.\n"
    return with_frontmatter(
        body,
        {
            "type": "change-request-decision",
            "decision": decision,
            "decided_by": decided_by,
            "decided_at": at.isoformat(timespec="seconds"),
            "note": note or "",
        },
    )


class DecideChangeRequest:
    """``(project, slug, n, decision, note)`` → the request, decided by the hub's person."""

    def __init__(  # noqa: PLR0913 -- the use case's ports, keyword-only after the folders
        self,
        hubs: ProjectHubs,
        folders: FeatureFolders,
        *,
        writer: DecisionWriter,
        guard: RunGuard,
        decider: Callable[[str], str | None],
        clock: Callable[[], datetime],
    ) -> None:
        self._hubs, self._folders, self._writer, self._guard = hubs, folders, writer, guard
        self._decider, self._clock = decider, clock

    def __call__(
        self, project: str, slug: str, n: int, *, decision: ChangeDecision, note: str | None
    ) -> ChangeRequestView:
        hub_path, folder_slug, request = self._open_request(project, slug, n)
        text = " ".join((note or "").split())[:MAX_NOTE_CHARS] or None
        if decision == "declined" and text is None:
            reason = "a decline needs your note: the next preflight follows it"
            raise ChangeRequestDecisionError("note_required", reason)
        person = (self._decider(project) or "").strip()
        if not person or person.lower() == "unknown":
            reason = "no person to record as decided_by: set author_name in hub.json"
            raise ChangeRequestDecisionError("no_person", reason)
        at = self._clock().replace(microsecond=0)
        content = decision_note(n=n, decision=decision, decided_by=person, at=at, note=text)
        with self._guard.lock:
            self._refuse_live(project, hub_path, request.run_id)
            self._write(hub_path, slug=folder_slug, n=n, text=content)
        decided = ChangeDecisionView(
            decision=decision,
            decided_by=person,
            decided_at=at.isoformat(timespec="seconds"),
            note=text,
        )
        return request_view(request, slug=folder_slug).model_copy(
            update={"status": decision, "decision": decided}
        )

    def _refuse_live(self, project: str, hub_path: str, run_id: str | None) -> None:
        """Refuse while the request's run can still decide it: its gate is open, it is folded
        running (paused at a gate, or not there yet), or a child hub web started holds it."""
        if run_id is None:
            return
        runs = RequestRuns(self._guard.runs)
        gate = runs.gates(project).get(run_id)
        if gate is not None:
            reason = f"run {run_id} waits at its gate: answer approval {gate} instead"
            raise ChangeRequestDecisionError("gate_open", reason)
        if not runs.gone(run_id) or run_id in self._guard.launcher.live_runs(hub_path):
            reason = f"run {run_id} is live: it records the decision itself"
            raise ChangeRequestDecisionError("live_run", reason)

    def _write(self, hub_path: str, *, slug: str, n: int, text: str) -> None:
        try:
            self._writer.create_decision(hub_path, slug=slug, n=n, text=text)
        except FileExistsError:
            raise ChangeRequestDecisionError(
                "decided", f"change request {n} was just decided; reload the feature"
            ) from None
        except OSError:
            # A folder turned into a link, or went away, since the read: nothing written.
            reason = f"{CHANGE_REQUESTS_FOLDER}/{n}.decision.md could not be created"
            raise ChangeRequestDecisionError("unwritable", reason) from None

    def _open_request(self, project: str, slug: str, n: int) -> tuple[str, str, ChangeRequest]:
        """The hub folder, the feature's slug and request ``n``, still open and readable."""
        missing = EntityNotFoundError(entity="feature", entity_id=f"{project}/{slug}")
        try:
            hub_path = self._hubs.hub_path_of(project)
        except EntityNotFoundError:
            raise missing from None
        folder = self._folders.feature_folder(hub_path, slug)
        if folder is None:
            raise missing
        requests = change_requests(folder.change_requests, skipped=0).requests
        request = next((found for found in requests if found.n == n), None)
        if request is None:
            raise EntityNotFoundError(entity="change request", entity_id=f"{slug}/{n}")
        if request.status is None:
            raise ChangeRequestDecisionError("unreadable", request.problem or "unreadable")
        if request.status != "open":
            raise ChangeRequestDecisionError(
                "decided", f"change request {n} is already {request.status}"
            )
        return hub_path, folder.slug, request
