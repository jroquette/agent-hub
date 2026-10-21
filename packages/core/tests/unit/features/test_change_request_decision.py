"""The owner decides a plan change request from hub web (two-level-flows AC-2.7, AC-2.12,
AC-2.14, A5, P8): the open gate of the request's run answers it while the run lives; only a
request whose run has no open gate gets a decision file written by the app, once."""

from datetime import UTC, datetime

import pytest

from agent_hub.core.approvals.approval import ApprovalKind
from agent_hub.core.features.change_request_decision import (
    ChangeRequestDecisionError,
    DecideChangeRequest,
    OpenRunGates,
    decision_note,
    with_open_gates,
)
from agent_hub.core.features.feature_status import FeatureFolder, RecordHead
from agent_hub.core.features.feature_view import ChangeRequestView
from agent_hub.core.features.ticket_records import change_requests
from agent_hub.core.readmodels.filters import ApprovalFilter
from agent_hub.core.readmodels.page import Page
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.testing.read_model_builders import an_approval

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
    def __init__(self, *, exists: bool = False) -> None:
        self.exists = exists
        self.written: list[tuple[str, str, int, str]] = []

    def create_decision(self, hub_path: str, *, slug: str, n: int, text: str) -> None:
        if self.exists:
            raise FileExistsError(n)
        self.written.append((hub_path, slug, n, text))


class Gates:
    def __init__(self, gates: dict[str, str] | None = None) -> None:
        self.gates = gates or {}

    def of(self, project: str) -> dict[str, str]:
        return self.gates


def decide(
    *heads: RecordHead,
    writer: Writer | None = None,
    gates: dict[str, str] | None = None,
    decider: str | None = "Dana Owner",
) -> tuple[DecideChangeRequest, Writer]:
    written = writer or Writer()
    use = DecideChangeRequest(
        Hubs(),
        Folders(*(heads or (a_request(),))),
        writer=written,
        gates=Gates(gates),
        decider=lambda project: decider,
        clock=lambda: DECIDED_AT,
    )
    return use, written


# AC-2.14: a request whose run has no open gate gets its decision file, read back as decided.
@pytest.mark.parametrize("decision", ["approved", "declined"])
def test_writes_decision_file_when_run_has_no_open_gate(decision: str) -> None:
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
    use, writer = decide(gates={"implement-8": "implement-8:approve-change:1"})

    with pytest.raises(ChangeRequestDecisionError) as raised:
        use("demo", "demo-feature", 2, decision="approved", note=None)

    assert raised.value.code == "gate_open"
    assert "implement-8:approve-change:1" in raised.value.reason
    assert writer.written == []


def test_writes_decision_when_only_other_runs_have_gates() -> None:
    use, writer = decide(gates={"implement-9": "implement-9:approve-change:1"})

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


class Events:
    def __init__(self, *approvals: object) -> None:
        self.approvals = approvals
        self.filters: list[ApprovalFilter] = []

    def list_approvals(self, approval_filter: ApprovalFilter) -> Page[object]:
        self.filters.append(approval_filter)
        return Page(items=self.approvals, next_cursor=None, total_estimate=len(self.approvals))


def a_gate(**fields: object) -> object:
    values: dict[str, object] = {
        "id": "implement-8:approve-change:1",
        "kind": ApprovalKind.HUMAN_GATE,
        "gate_id": "implement-8:approve-change:1",
        "session_id": "run:implement-8",
    }
    return an_approval(**(values | fields))


# P8: an open person gate of the request's run, in the project.
def test_finds_open_gate_by_run_when_approvals_listed() -> None:
    events = Events(a_gate())

    assert OpenRunGates(events).of("demo") == {"implement-8": "implement-8:approve-change:1"}  # type: ignore[arg-type]
    (asked,) = events.filters
    assert (asked.project, asked.kind, asked.status) == ("demo", ApprovalKind.HUMAN_GATE, "open")


@pytest.mark.parametrize(
    "fields",
    [
        {"decided": True, "status": "approved"},
        {"kind": ApprovalKind.GUARD_ASK},
        {"session_id": "session-1"},
        {"project": "other"},
    ],
    ids=["decided", "not a gate", "not a run", "other project"],
)
def test_finds_no_gate_when_approval_is_not_an_open_run_gate(fields: dict[str, object]) -> None:
    assert OpenRunGates(Events(a_gate(**fields))).of("demo") == {}  # type: ignore[arg-type]


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


# P8, A5: an open request carries its run's open gate; a decided one, or one of another run, none.
def test_sets_approval_id_when_open_request_run_has_gate() -> None:
    gates = {"implement-8": "implement-8:approve-change:1"}

    found = with_open_gates(
        (a_view(), a_view(n=3, status="approved"), a_view(n=4, run_id="implement-9")), gates
    )

    assert [view.approval_id for view in found] == ["implement-8:approve-change:1", None, None]
