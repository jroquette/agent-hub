"""The owner decides a plan change request from hub web (two-level-flows AC-2.7, AC-2.12,
AC-2.14; D-10, D-11, A5, P8): pure, no I/O but the ports.

While the request's ``implement`` run waits at its gate, hub web answers that gate through the
approvals route, and the run writes the records: ``OpenRunGates`` finds the gate (an open
``human_gate`` approval in the run's session ``run:<run>``) and ``with_open_gates`` sets each open
request's ``approval_id``. Only a request whose run has no open gate (abandoned, or its record
lost) is decided here: ``DecideChangeRequest`` creates ``change-requests/<n>.decision.md`` once,
never editing the request, and the next ``/implement`` of its ticket reads it. It refuses, writing
nothing: a request that cannot be read or is already decided, a run whose gate is open, a decline
without the owner's note (D-2) and a decision with no person to name (``decided_by`` empty or
``unknown``, A5).
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
    ChangeRequest,
    change_requests,
    request_view,
)
from agent_hub.core.readmodels.filters import MAX_PAGE_LIMIT, ApprovalFilter
from agent_hub.core.readmodels.read_ports import EntityNotFoundError, EventReadModels
from agent_hub.core.workflows.gate_decisions import RUN_SESSION_PREFIX

MAX_NOTE_CHARS: Final = 2_000

type ChangeDecision = Literal["approved", "declined"]


class ChangeRequestDecisionError(AgentHubError):
    """The decision is refused, nothing written; ``code`` names why (``note_required`` is the
    owner's input, the others the request's state) and ``reason`` says it in one line."""

    def __init__(self, code: str, reason: str) -> None:
        self.code, self.reason = code, reason
        super().__init__(reason)


class DecisionWriter(Protocol):
    def create_decision(self, hub_path: str, *, slug: str, n: int, text: str) -> None:
        """Create ``brain/features/<slug>/change-requests/<n>.decision.md``; ``FileExistsError``
        when it exists."""
        ...


class RunGates(Protocol):
    def of(self, project: str) -> Mapping[str, str]:
        """The open person gates of the project's runs: approval id by run id."""
        ...


class OpenRunGates:
    """``RunGates`` over the event read models' open approvals."""

    def __init__(self, events: EventReadModels) -> None:
        self._events = events

    def of(self, project: str) -> Mapping[str, str]:
        found: dict[str, str] = {}
        cursor: str | None = None
        while True:
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
                if (
                    approval.project == project
                    and approval.kind == ApprovalKind.HUMAN_GATE
                    and not approval.decided
                    and run != approval.session_id
                ):
                    found.setdefault(run, approval.id)
            if page.next_cursor is None:
                return found
            cursor = page.next_cursor


def with_open_gates(
    requests: tuple[ChangeRequestView, ...], gates: Mapping[str, str]
) -> tuple[ChangeRequestView, ...]:
    """Each open request with the ``approval_id`` of its run's open gate, when it has one."""
    return tuple(
        request.model_copy(update={"approval_id": gates.get(request.run_id)})
        if request.status == "open" and request.run_id
        else request
        for request in requests
    )


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
        gates: RunGates,
        decider: Callable[[str], str | None],
        clock: Callable[[], datetime],
    ) -> None:
        self._hubs, self._folders, self._writer, self._gates = hubs, folders, writer, gates
        self._decider, self._clock = decider, clock

    def __call__(
        self, project: str, slug: str, n: int, *, decision: ChangeDecision, note: str | None
    ) -> ChangeRequestView:
        hub_path, folder_slug, request = self._open_request(project, slug, n)
        text = " ".join((note or "").split())[:MAX_NOTE_CHARS] or None
        if decision == "declined" and text is None:
            reason = "a decline needs your note: the next preflight follows it"
            raise ChangeRequestDecisionError("note_required", reason)
        gate = None if request.run_id is None else self._gates.of(project).get(request.run_id)
        if gate is not None:
            reason = f"run {request.run_id} waits at its gate: answer approval {gate} instead"
            raise ChangeRequestDecisionError("gate_open", reason)
        person = (self._decider(project) or "").strip()
        if not person or person.lower() == "unknown":
            reason = "no person to record as decided_by: set author_name in hub.json"
            raise ChangeRequestDecisionError("no_person", reason)
        at = self._clock().replace(microsecond=0)
        content = decision_note(n=n, decision=decision, decided_by=person, at=at, note=text)
        try:
            self._writer.create_decision(hub_path, slug=folder_slug, n=n, text=content)
        except FileExistsError:
            raise ChangeRequestDecisionError(
                "decided", f"change request {n} was just decided; reload the feature"
            ) from None
        decided = ChangeDecisionView(
            decision=decision,
            decided_by=person,
            decided_at=at.isoformat(timespec="seconds"),
            note=text,
        )
        return request_view(request, slug=folder_slug).model_copy(
            update={"status": decision, "decision": decided}
        )

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
