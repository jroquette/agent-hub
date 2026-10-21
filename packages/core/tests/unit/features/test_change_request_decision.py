"""The owner decides a plan change request from hub web (two-level-flows AC-2.7, AC-2.12,
AC-2.14, A5, P8): the open gate of the request's run answers it while the run lives; only a
request whose run is gone (lost, or ended, and held by no child) gets a decision file written by
the app, once, checked under the run commands' lock."""

import threading
from collections.abc import Mapping
from datetime import UTC, datetime

import pytest

from agent_hub.core.approvals.approval import ApprovalKind
from agent_hub.core.features.change_request_decision import (
    MAX_GATE_PAGES,
    ChangeRequestDecisionError,
    DecideChangeRequest,
    RequestRuns,
    decision_note,
    with_runs,
)
from agent_hub.core.features.feature_status import FeatureFolder, RecordHead
from agent_hub.core.features.feature_view import ChangeRequestView
from agent_hub.core.features.ticket_records import change_requests
from agent_hub.core.readmodels.filters import ApprovalFilter
from agent_hub.core.readmodels.page import Page
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.runs.workflow_run import WorkflowRun
from agent_hub.core.testing.read_model_builders import a_run, an_approval

DECIDED_AT = datetime(2026, 10, 21, 18, 0, tzinfo=UTC)


def a_request(n: int = 2, *, ticket: str = "DEM-8", run_id: str = "implement-8") -> RecordHead:
    text = (
        f"---\ntype: change-request\nticket: {ticket}\nstatus: open\nplan_from: 2\nplan_to: 3\n"
        f"affected: [DEM-9]\nopened_at: 2026-10-21T09:30:00Z\nrun_id: {run_id}\n---\n# Request\n"
    )
    return RecordHead(name=f"{n}.md", head=text.encode(), problem=None)


def a_decision(n: int = 2) -> RecordHead:
    text = (
        "---\ntype: change-request-decision\ndecision: approved\ndecided_by: Dana Owner\n"
        "decided_at: 2026-10-21T10:00:00Z\nnote: ok\n---\n"
    )
    return RecordHead(name=f"{n}.decision.md", head=text.encode(), problem=None)


class Hubs:
    def hub_path_of(self, project: str) -> str:
        if project != "demo":
            raise EntityNotFoundError(entity="project", entity_id=project)
        return "/hubs/demo"


class Folders:
    def __init__(self, *heads: RecordHead) -> None:
        self.heads = heads

    def feature_folder(self, hub_path: str, slug: str) -> FeatureFolder | None:
        if slug != "demo-feature":
            return None
        return FeatureFolder(slug=slug, files=("plan.md",), change_requests=self.heads)


class Writer:
    def __init__(self, *, exists: bool = False, linked: bool = False) -> None:
        self.exists, self.linked = exists, linked
        self.written: list[tuple[str, str, int, str]] = []

    def create_decision(self, hub_path: str, *, slug: str, n: int, text: str) -> None:
        if self.exists:
            raise FileExistsError(n)
        if self.linked:
            raise FileNotFoundError("change-requests")
        self.written.append((hub_path, slug, n, text))


def a_gate(run: str = "implement-8", **fields: object) -> object:
    values: dict[str, object] = {
        "id": f"{run}:approve-change:1",
        "kind": ApprovalKind.HUMAN_GATE,
        "gate_id": f"{run}:approve-change:1",
        "session_id": f"run:{run}",
    }
    return an_approval(**(values | fields))


class Events:
    """The event read models a request's run is looked up in: its runs and open approvals."""

    def __init__(self, *approvals: object, runs: tuple[WorkflowRun, ...] = ()) -> None:
        self.approvals = approvals
        self.runs = {run.id: run for run in runs}
        self.filters: list[ApprovalFilter] = []
        self.pages: dict[str | None, tuple[tuple[object, ...], str | None]] = {}

    def list_approvals(self, approval_filter: ApprovalFilter) -> Page[object]:
        self.filters.append(approval_filter)
        if self.pages:
            items, after = self.pages.get(approval_filter.cursor, ((), None))
            return Page(items=items, next_cursor=after, total_estimate=len(items))
        # As the read model does: an open filter lists the undecided ones.
        items = tuple(
            item
            for item in self.approvals
            if approval_filter.status != "open" or not getattr(item, "decided", False)
        )
        return Page(items=items, next_cursor=None, total_estimate=len(items))

    def get_run(self, run_id: str) -> WorkflowRun:
        if run_id not in self.runs:
            raise EntityNotFoundError(entity="workflow run", entity_id=run_id)
        return self.runs[run_id]


class Guard:
    """``RunGuard``'s shape: the lock, the read models and the launcher's live children."""

    def __init__(self, events: Events, *, live: Mapping[str, str | None] | None = None) -> None:
        self.runs = events
        self.lock = threading.Lock()
        self.live = live or {}
        self.locked_when_checked: list[bool] = []

    @property
    def launcher(self) -> Guard:
        return self

    def live_runs(self, hub_path: str) -> Mapping[str, str | None]:
        self.locked_when_checked.append(self.lock.locked())
        return self.live


def a_running(run_id: str = "implement-8", **fields: object) -> WorkflowRun:
    return a_run(id=run_id, workflow="implement", **fields)


def decide(
    *heads: RecordHead,
    writer: Writer | None = None,
    events: Events | None = None,
    live: Mapping[str, str | None] | None = None,
    decider: str | None = "Dana Owner",
) -> tuple[DecideChangeRequest, Writer]:
    written = writer or Writer()
    guard = Guard(events or Events(), live=live)
    use = DecideChangeRequest(
        Hubs(),
        Folders(*(heads or (a_request(),))),
        writer=written,
        guard=guard,  # type: ignore[arg-type]
        decider=lambda project: decider,
        clock=lambda: DECIDED_AT,
    )
    return use, written


# AC-2.14: a request whose run is lost gets its decision file, read back as decided.
@pytest.mark.parametrize("decision", ["approved", "declined"])
def test_writes_decision_file_when_run_lost(decision: str) -> None:
    use, writer = decide()

    view = use("demo", "demo-feature", 2, decision=decision, note="Follow the current plan.")

    ((hub_path, slug, n, text),) = writer.written
    assert (hub_path, slug, n) == ("/hubs/demo", "demo-feature", 2)
    (request,) = change_requests(
        (a_request(), RecordHead(name="2.decision.md", head=text.encode(), problem=None)),
        skipped=0,
    ).requests
    assert (request.status, request.problem) == (decision, None)
    assert request.decision is not None
    assert (request.decision.decided_by, request.decision.note) == (
        "Dana Owner",
        "Follow the current plan.",
    )
    assert request.decision.decided_at == "2026-10-21T18:00:00+00:00"
    assert view.status == decision
    assert view.decision is not None
    assert view.decision.model_dump() == {
        "decision": decision,
        "decided_by": "Dana Owner",
        "decided_at": "2026-10-21T18:00:00+00:00",
        "note": "Follow the current plan.",
    }


# AC-2.12: a decline needs the owner's note, which the next preflight follows (D-2).
@pytest.mark.parametrize("note", [None, "", "   "])
def test_refuses_decline_when_note_missing(note: str | None) -> None:
    use, writer = decide()

    with pytest.raises(ChangeRequestDecisionError) as raised:
        use("demo", "demo-feature", 2, decision="declined", note=note)

    assert raised.value.code == "note_required"
    assert writer.written == []


def test_writes_approval_when_no_note_given() -> None:
    use, writer = decide()

    view = use("demo", "demo-feature", 2, decision="approved", note=None)

    assert view.status == "approved"
    assert len(writer.written) == 1


# P8, the invariant "hub web writes no record while a run is live": an open gate answers it.
def test_refuses_and_writes_nothing_when_run_gate_open() -> None:
    use, writer = decide(events=Events(a_gate(), runs=(a_running(),)))

    with pytest.raises(ChangeRequestDecisionError) as raised:
        use("demo", "demo-feature", 2, decision="approved", note=None)

    assert raised.value.code == "gate_open"
    assert "implement-8:approve-change:1" in raised.value.reason
    assert writer.written == []


# Q1: the gate was just decided, or not opened yet: the run is live and writes the records.
@pytest.mark.parametrize(
    "gates",
    [(), (a_gate(decided=True, status="approved"),)],
    ids=["gate not opened yet", "gate just decided"],
)
def test_refuses_and_writes_nothing_when_run_still_running(gates: tuple[object, ...]) -> None:
    use, writer = decide(events=Events(*gates, runs=(a_running(),)))

    with pytest.raises(ChangeRequestDecisionError) as raised:
        use("demo", "demo-feature", 2, decision="approved", note=None)

    assert raised.value.code == "live_run"
    assert writer.written == []


# Q1: a child hub web started still holds the run, whatever its events say.
def test_refuses_when_launcher_holds_the_run() -> None:
    ended = a_running(status="cancelled")
    use, writer = decide(events=Events(runs=(ended,)), live={"implement-8": "DEM-8"})

    with pytest.raises(ChangeRequestDecisionError) as raised:
        use("demo", "demo-feature", 2, decision="approved", note=None)

    assert raised.value.code == "live_run"
    assert writer.written == []


# Q1: a run that ended (cancelled when abandoned, failed, done) is gone: hub web decides.
@pytest.mark.parametrize("status", ["cancelled", "failed", "done"])
def test_writes_decision_when_run_ended(status: str) -> None:
    use, writer = decide(events=Events(runs=(a_running(status=status),)))

    use("demo", "demo-feature", 2, decision="approved", note=None)

    assert len(writer.written) == 1


# Q1: the check and the write hold the run commands' lock, as the gate route does.
def test_checks_the_run_when_holding_the_run_commands_lock() -> None:
    events = Events()
    guard = Guard(events)
    use = DecideChangeRequest(
        Hubs(),
        Folders(a_request()),
        writer=Writer(),
        guard=guard,  # type: ignore[arg-type]
        decider=lambda project: "Dana Owner",
        clock=lambda: DECIDED_AT,
    )

    use("demo", "demo-feature", 2, decision="approved", note=None)

    assert guard.locked_when_checked == [True]


def test_writes_decision_when_only_other_runs_have_gates() -> None:
    use, writer = decide(events=Events(a_gate("implement-9")))

    use("demo", "demo-feature", 2, decision="approved", note=None)

    assert len(writer.written) == 1


# NFR Idempotency: a request is decided once.
def test_refuses_when_request_already_decided() -> None:
    use, writer = decide(a_request(), a_decision())

    with pytest.raises(ChangeRequestDecisionError) as raised:
        use("demo", "demo-feature", 2, decision="declined", note="no")

    assert (raised.value.code, raised.value.reason) == (
        "decided",
        "change request 2 is already approved",
    )
    assert writer.written == []


# D-11: the file is created exclusively; one written meanwhile is never overwritten.
def test_refuses_when_decision_file_appears_meanwhile() -> None:
    use, _ = decide(writer=Writer(exists=True))

    with pytest.raises(ChangeRequestDecisionError) as raised:
        use("demo", "demo-feature", 2, decision="approved", note=None)

    assert raised.value.code == "decided"


# A folder that became a link since the read: refused, never followed.
def test_refuses_when_folder_cannot_be_written() -> None:
    use, _ = decide(writer=Writer(linked=True))

    with pytest.raises(ChangeRequestDecisionError) as raised:
        use("demo", "demo-feature", 2, decision="approved", note=None)

    assert (raised.value.code, raised.value.reason) == (
        "unwritable",
        "change-requests/2.decision.md could not be created",
    )


# A5: who decided is a person, never empty or unknown.
@pytest.mark.parametrize("decider", [None, "", "  ", "unknown", " Unknown "])
def test_refuses_when_no_person_to_record(decider: str | None) -> None:
    use, writer = decide(decider=decider)

    with pytest.raises(ChangeRequestDecisionError) as raised:
        use("demo", "demo-feature", 2, decision="approved", note=None)

    assert raised.value.code == "no_person"
    assert writer.written == []


def test_refuses_when_request_unreadable() -> None:
    broken = RecordHead(name="2.md", head=b"---\nticket: DEM-8\n---\n", problem=None)
    use, writer = decide(broken)

    with pytest.raises(ChangeRequestDecisionError) as raised:
        use("demo", "demo-feature", 2, decision="approved", note=None)

    assert raised.value.code == "unreadable"
    assert writer.written == []


@pytest.mark.parametrize(
    ("project", "slug", "n"),
    [("nope", "demo-feature", 2), ("demo", "nope", 2), ("demo", "demo-feature", 3)],
    ids=["project", "feature", "request"],
)
def test_answers_not_found_when_unknown(project: str, slug: str, n: int) -> None:
    use, _ = decide()

    with pytest.raises(EntityNotFoundError):
        use(project, slug, n, decision="approved", note=None)


def test_note_keeps_frontmatter_on_one_line_when_note_spans_lines() -> None:
    text = decision_note(
        n=2, decision="declined", decided_by="Dana Owner", at=DECIDED_AT, note="a: b\nc # d"
    )

    (request,) = change_requests(
        (a_request(), RecordHead(name="2.decision.md", head=text.encode(), problem=None)),
        skipped=0,
    ).requests
    assert request.decision is not None
    assert request.decision.note == "a: b c # d"


# P8: the open person gates of the project's runs, asked of the read model as such (Q2).
def test_finds_open_gate_by_run_when_approvals_listed() -> None:
    events = Events(a_gate())

    assert RequestRuns(events).gates("demo") == {"implement-8": "implement-8:approve-change:1"}  # type: ignore[arg-type]
    (asked,) = events.filters
    assert (asked.project, asked.kind, asked.status) == ("demo", ApprovalKind.HUMAN_GATE, "open")


def test_finds_no_gate_when_approval_is_no_run_session() -> None:
    assert RequestRuns(Events(a_gate(session_id="session-1"))).gates("demo") == {}  # type: ignore[arg-type]


# Q2: a gate on a later page is found; the pages read are capped.
def test_finds_gate_on_second_page_when_first_page_full() -> None:
    events = Events()
    events.pages = {None: ((a_gate("implement-1"),), "c1"), "c1": ((a_gate(),), None)}

    assert RequestRuns(events).gates("demo")["implement-8"] == "implement-8:approve-change:1"  # type: ignore[arg-type]


def test_stops_after_page_cap_when_pages_never_end() -> None:
    events = Events()
    events.pages = {
        None if n == 0 else f"c{n}": ((a_gate(f"implement-{n}"),), f"c{n + 1}") for n in range(50)
    }

    RequestRuns(events).gates("demo")  # type: ignore[arg-type]

    assert len(events.filters) == MAX_GATE_PAGES


def a_view(**fields: object) -> ChangeRequestView:
    values: dict[str, object] = {
        "n": 2,
        "ticket": "DEM-8",
        "status": "open",
        "plan_from": 2,
        "plan_to": 3,
        "affected": ("DEM-9",),
        "opened_at": None,
        "run_id": "implement-8",
        "decision": None,
        "path": "features/demo-feature/change-requests/2.md",
        "problem": None,
    }
    return ChangeRequestView.model_validate(values | fields)


# P8, A5, Q1: an open request carries its run's open gate; a decided one, or one of another run,
# none; hub web decides only a request whose run is gone.
def test_sets_gate_and_decidable_here_when_requests_annotated() -> None:
    events = Events(
        a_gate(), runs=(a_running("implement-9"), a_running("implement-7", status="failed"))
    )

    found = with_runs(
        (
            a_view(),
            a_view(n=3, status="approved"),
            a_view(n=4, run_id="implement-9"),
            a_view(n=5, run_id="implement-7"),
            a_view(n=6, run_id="implement-lost"),
        ),
        RequestRuns(events),  # type: ignore[arg-type]
        project="demo",
    )

    assert [(view.approval_id, view.decidable_here) for view in found] == [
        ("implement-8:approve-change:1", False),
        (None, False),
        (None, False),
        (None, True),
        (None, True),
    ]
