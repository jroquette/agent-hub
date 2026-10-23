"""Plan change requests in hub web (two-level-flows S2, AGH-405): the detail and the ticket route
carry each open request's gate (``approval_id``, AC-2.7, P8, A5), and the decision route answers a
request whose run is gone by creating its decision file once (AC-2.12, AC-2.14, D-10, D-11)."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from agent_hub.api.change_request_files import HubDecisionWriter
from agent_hub.api.owner_signoff_files import ProjectHubPaths
from agent_hub.core.approvals.approval import ApprovalKind
from agent_hub.core.features.change_request_decision import DecideChangeRequest
from agent_hub.core.features.feature_status import FeatureFolder
from agent_hub.core.features.feature_view import ChangeRequestView, FeatureDetail
from agent_hub.core.features.ticket_records import change_requests
from agent_hub.core.features.ticket_view import TicketRecords
from agent_hub.core.projects.project_views import ProjectDetail, TrackerView
from agent_hub.core.testing.read_model_builders import (
    HUB_ID,
    a_feature_view,
    a_run,
    an_approval,
)
from agent_hub.core.workflows.launch import RunGuard
from agent_hub.generator.feature_files import read_feature_folder

OWN = {"Origin": "http://127.0.0.1:7420"}
DECIDED_AT = datetime(2026, 10, 21, 18, 0, tzinfo=UTC)
GATE = "implement-8:approve-change:1"
DECISION = "/api/v1/features/demo/demo-feature/change-requests/2/decision"


def a_gate(run: str = "implement-8", **fields: object) -> Any:
    values: dict[str, object] = {
        "id": f"{run}:approve-change:1",
        "kind": ApprovalKind.HUMAN_GATE,
        "gate_id": f"{run}:approve-change:1",
        "session_id": f"run:{run}",
    }
    return an_approval(**(values | fields))


def a_request(n: int, *, run: str, status: str = "open") -> ChangeRequestView:
    return ChangeRequestView(
        n=n,
        ticket="DEM-8",
        status=status,  # type: ignore[arg-type]
        plan_from=2,
        plan_to=3,
        affected=("DEM-9",),
        opened_at="2026-10-21T09:30:00Z",
        run_id=run,
        decision=None,
        path=f"features/demo-feature/change-requests/{n}.md",
        problem=None,
    )


REQUESTS = (
    a_request(1, run="implement-8"),
    a_request(2, run="implement-9"),
    a_request(3, run="implement-8", status="approved"),
)


# AC-2.7 (web approve via the gate), P8, A5: an open request of a live run carries its gate's
# approval id; one whose run has no open gate, or one decided, carries none.
def test_detail_carries_open_gate_when_request_run_waits(tmp_path: Path, wired: Any) -> None:
    _decision_hub(tmp_path, wired)
    detail = FeatureDetail.model_validate(a_feature_view().model_dump())
    wired.hubs.features.append(detail.model_copy(update={"change_requests": REQUESTS}))
    wired.events.approvals.extend([a_gate(), a_gate("implement-9", decided=True)])

    body = wired.client.get("/api/v1/features/demo/demo-feature").json()

    assert [request["approval_id"] for request in body["change_requests"]] == [GATE, None, None]
    # Q1: implement-9's run is lost (no run folded): hub web decides it; the others it does not.
    assert [request["decidable_here"] for request in body["change_requests"]] == [
        False,
        True,
        False,
    ]


# Q11: with the decision route not wired (sessions off), the detail offers no decision here;
# spec F2: a run a child still holds is not gone either.
@pytest.mark.parametrize("wiring", ["not wired", "held by a child"])
def test_detail_decides_nothing_here_when_route_off_or_run_held(
    tmp_path: Path, wired: Any, wiring: str
) -> None:
    if wiring == "held by a child":
        _decision_hub(tmp_path, wired, live={"implement-9": "DEM-8"})
    detail = FeatureDetail.model_validate(a_feature_view().model_dump())
    wired.hubs.features.append(detail.model_copy(update={"change_requests": REQUESTS[1:2]}))

    body = wired.client.get("/api/v1/features/demo/demo-feature").json()

    assert body["change_requests"][0]["decidable_here"] is False


def test_detail_reads_no_approvals_when_no_request_open(wired: Any) -> None:
    detail = FeatureDetail.model_validate(a_feature_view().model_dump())
    wired.hubs.features.append(detail.model_copy(update={"change_requests": REQUESTS[2:]}))

    wired.client.get("/api/v1/features/demo/demo-feature")

    assert [name for name, _ in wired.events.calls] == ["feature_cost"]


# two-level-flows A7: the ticket panel's records, with the same gate resolution.
def test_ticket_route_carries_open_gate_when_ticket_asks(wired: Any) -> None:
    wired.hubs.ticket_views["demo/demo-feature/DEM-8"] = TicketRecords(
        project="demo",
        slug="demo-feature",
        ticket="DEM-8",
        preflight=None,
        change_requests=REQUESTS[:1],
    )
    wired.events.approvals.append(a_gate())

    response = wired.client.get("/api/v1/features/demo/demo-feature/tickets/DEM-8")

    assert response.status_code == 200, response.text
    assert response.json()["change_requests"][0]["approval_id"] == GATE


def test_ticket_route_answers_not_found_when_ticket_unknown(wired: Any) -> None:
    response = wired.client.get("/api/v1/features/demo/demo-feature/tickets/DEM-99")

    assert response.status_code == 404


class _DiskFolders:
    def feature_folder(self, hub_path: str, slug: str) -> FeatureFolder | None:
        return read_feature_folder(Path(hub_path), slug)


class _Launcher:
    """The launcher's live children (none): the guard's other calls never happen here."""

    def __init__(self) -> None:
        self.live: dict[str, str | None] = {}

    def live_runs(self, hub_path: str) -> dict[str, str | None]:
        return self.live


def _decision_hub(
    tmp_path: Path,
    wired: Any,
    *,
    person: str | None = "Dana Owner",
    live: dict[str, str | None] | None = None,
) -> Path:
    """A hub with request 2 of run implement-8, wired behind the decision route."""
    hub = tmp_path / "demo-hub"
    requests = hub / "brain" / "features" / "demo-feature" / "change-requests"
    requests.mkdir(parents=True)
    (requests / "2.md").write_text(
        "---\ntype: change-request\nticket: DEM-8\nstatus: open\nplan_from: 2\nplan_to: 3\n"
        "affected: [DEM-9]\nopened_at: 2026-10-21T09:30:00Z\nrun_id: implement-8\n---\n# Req\n",
        encoding="utf-8",
    )
    wired.hubs.details["demo"] = ProjectDetail(
        name="demo",
        hub_id=HUB_ID,
        hub_path=str(hub),
        hub_repo="acme/demo-hub",
        tracker=TrackerView(kind="linear", teams=("DEM",), ready_label=None, failed_label=None),
        default_branch="main",
        branch_prefix="jdoe/",
        platform_version="0.8.0",
        lock_version="0.8.0",
        lock_state="in_sync",
        modules=(),
    )
    launcher = _Launcher()
    launcher.live = dict(live or {})
    decide = DecideChangeRequest(
        ProjectHubPaths(wired.hubs),
        _DiskFolders(),
        writer=HubDecisionWriter(),
        guard=RunGuard(wired.events, launcher),  # type: ignore[arg-type]
        decider=lambda project: person,
        clock=lambda: DECIDED_AT,
    )
    wired.wire(change_request_decisions=decide)
    return requests


def _names(folder: Path) -> list[str]:
    return sorted(path.name for path in folder.iterdir())


# AC-2.14: answered in hub web, the decision is a new file; the request file is never edited.
@pytest.mark.parametrize("decision", ["approved", "declined"])
def test_creates_decision_file_when_run_has_no_open_gate(
    tmp_path: Path, wired: Any, decision: str
) -> None:
    requests = _decision_hub(tmp_path, wired)
    before = (requests / "2.md").read_bytes()

    response = wired.client.post(
        DECISION, json={"decision": decision, "note": "Follow the current plan."}, headers=OWN
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["status"], body["decision"]["decided_by"]) == (decision, "Dana Owner")
    assert body["decision"]["decided_at"] == "2026-10-21T18:00:00+00:00"
    assert _names(requests) == ["2.decision.md", "2.md"]
    assert (requests / "2.md").read_bytes() == before
    folder = read_feature_folder(requests.parents[3], "demo-feature")
    assert folder is not None
    (read,) = change_requests(folder.change_requests, skipped=0).requests
    assert (read.status, read.problem) == (decision, None)


# AC-2.12: a decline needs the owner's note (D-2); nothing is written without it.
@pytest.mark.parametrize("body", [{"decision": "declined"}, {"decision": "declined", "note": " "}])
def test_refuses_decline_and_writes_nothing_when_note_missing(
    tmp_path: Path, wired: Any, body: dict[str, str]
) -> None:
    requests = _decision_hub(tmp_path, wired)

    response = wired.client.post(DECISION, json=body, headers=OWN)

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "note_required"
    assert _names(requests) == ["2.md"]


# P8, the invariant "hub web writes no record while a run is live": the gate answers it.
def test_refuses_and_writes_nothing_when_run_gate_open(tmp_path: Path, wired: Any) -> None:
    requests = _decision_hub(tmp_path, wired)
    wired.events.approvals.append(a_gate())

    response = wired.client.post(DECISION, json={"decision": "approved"}, headers=OWN)

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "gate_open"
    assert GATE in response.json()["detail"]
    assert _names(requests) == ["2.md"]


# Q1: while the run lives (paused at a gate just decided, or running before it opens one), the
# run writes the records: hub web refuses and writes nothing.
@pytest.mark.parametrize(
    "gates",
    [(), (a_gate(decided=True, status="approved"),)],
    ids=["no gate yet", "gate just decided"],
)
def test_refuses_and_writes_nothing_when_run_live(
    tmp_path: Path, wired: Any, gates: tuple[Any, ...]
) -> None:
    requests = _decision_hub(tmp_path, wired)
    wired.events.runs.append(a_run(id="implement-8", workflow="implement"))
    wired.events.approvals.extend(gates)

    response = wired.client.post(DECISION, json={"decision": "approved"}, headers=OWN)

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "live_run"
    assert _names(requests) == ["2.md"]


# NFR Idempotency: decided once; a second decision is refused and the first kept.
def test_refuses_second_decision_when_request_decided(tmp_path: Path, wired: Any) -> None:
    requests = _decision_hub(tmp_path, wired)
    first = wired.client.post(DECISION, json={"decision": "approved"}, headers=OWN)
    written = (requests / "2.decision.md").read_bytes()

    second = wired.client.post(DECISION, json={"decision": "declined", "note": "no"}, headers=OWN)

    assert (first.status_code, second.status_code) == (201, 409)
    assert second.json()["code"] == "decided"
    assert (requests / "2.decision.md").read_bytes() == written


# D-11: created exclusively, no link followed: a link at the decision's name is never written
# through, and the request stays undecided.
def test_refuses_and_writes_nothing_when_decision_name_is_a_link(
    tmp_path: Path, wired: Any
) -> None:
    requests = _decision_hub(tmp_path, wired)
    target = tmp_path / "elsewhere.md"
    (requests / "2.decision.md").symlink_to(target)

    response = wired.client.post(DECISION, json={"decision": "approved"}, headers=OWN)

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "decided"
    assert not target.exists()


# A5: a decision names a person; with none to name, nothing is written.
@pytest.mark.parametrize("person", [None, "unknown"])
def test_refuses_and_writes_nothing_when_no_person(
    tmp_path: Path, wired: Any, person: str | None
) -> None:
    requests = _decision_hub(tmp_path, wired, person=person)

    response = wired.client.post(DECISION, json={"decision": "approved"}, headers=OWN)

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "no_person"
    assert _names(requests) == ["2.md"]


@pytest.mark.parametrize(
    "path",
    [DECISION.replace("/2/", "/3/"), DECISION.replace("demo-feature", "nope")],
    ids=["request", "feature"],
)
def test_answers_not_found_when_request_unknown(tmp_path: Path, wired: Any, path: str) -> None:
    _decision_hub(tmp_path, wired)

    assert wired.client.post(path, json={"decision": "approved"}, headers=OWN).status_code == 404


@pytest.mark.parametrize(
    "body", [{"decision": "maybe"}, {"decision": "approved", "decided_by": "x"}], ids=str
)
def test_answers_unprocessable_when_body_invalid(
    tmp_path: Path, wired: Any, body: dict[str, str]
) -> None:
    requests = _decision_hub(tmp_path, wired)

    assert wired.client.post(DECISION, json=body, headers=OWN).status_code == 422
    assert _names(requests) == ["2.md"]
