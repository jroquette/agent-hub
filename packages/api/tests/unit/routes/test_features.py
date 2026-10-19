import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_hub.api.owner_signoff_files import HubEvalWriter, ProjectHubPaths
from agent_hub.api.rfc9457 import owner_signoff_problem
from agent_hub.core.features.feature_status import FeatureFolder
from agent_hub.core.features.feature_view import AcRow, FeatureDetail
from agent_hub.core.features.owner_signoff import OwnerSignOffError, SignOffOwnerSteps
from agent_hub.core.projects.project_views import ProjectDetail, TrackerView
from agent_hub.core.readmodels.filters import Scope
from agent_hub.core.testing.read_model_builders import HUB_ID, a_feature_tickets, a_feature_view
from agent_hub.generator.feature_files import read_feature_folder

SIGNED_AT = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


def _detail() -> FeatureDetail:
    row = AcRow(id="AC-1", description="does it", repo="demo-api", passes=True)
    return FeatureDetail.model_validate(a_feature_view().model_dump() | {"ac_rows": (row,)})


def test_maps_scope_when_features_listed(wired: Any) -> None:
    wired.hubs.features.append(_detail())

    response = wired.client.get("/api/v1/features", params={"project": "demo"})

    assert response.json()["items"] == [a_feature_view().model_dump(mode="json")]
    assert wired.hubs.calls == [("list_features", Scope(project="demo"))]


def test_maps_detail_when_feature_requested(wired: Any) -> None:
    wired.hubs.features.append(_detail())

    response = wired.client.get("/api/v1/features/demo/demo-feature")

    assert response.json()["ac_rows"][0]["id"] == "AC-1"


def test_answers_not_found_when_feature_unknown(wired: Any) -> None:
    response = wired.client.get("/api/v1/features/demo/nope")

    assert response.status_code == 404
    assert response.json()["detail"] == "No feature with id 'demo/nope'."


def test_returns_tickets_when_port_answers(wired: Any) -> None:
    wired.hubs.tickets["demo/demo-feature"] = a_feature_tickets()

    response = wired.client.get("/api/v1/features/demo/demo-feature/tickets")

    assert response.status_code == 200
    assert response.json() == a_feature_tickets().model_dump(mode="json")
    assert wired.hubs.calls == [("feature_tickets", ("demo", "demo-feature"))]


def test_answers_not_found_when_tickets_feature_unknown(wired: Any) -> None:
    response = wired.client.get("/api/v1/features/demo/nope/tickets")

    assert response.status_code == 404
    assert response.json()["detail"] == "No feature with id 'demo/nope'."


def test_refuses_slug_when_tickets_path_too_long(wired: Any) -> None:
    response = wired.client.get(f"/api/v1/features/demo/{'x' * 201}/tickets")

    assert response.status_code == 400
    assert wired.hubs.calls == []


class _DiskFolders:
    def feature_folder(self, hub_path: str, slug: str) -> FeatureFolder | None:
        return read_feature_folder(Path(hub_path), slug)


def _signoff_hub(tmp_path: Path, wired: Any, verdict: str) -> Path:
    """A hub with one feature whose only eval has ``verdict``, wired behind the sign-off route."""
    hub = tmp_path / "demo-hub"
    evals = hub / "brain" / "features" / "demo-feature" / "evals"
    evals.mkdir(parents=True)
    acs = [
        {"id": f"AC-7.{n}", "description": "Given x, when y, then z", "passes": True}
        for n in (1, 2)
    ]
    (evals.parent / "features.json").write_text(json.dumps({"acs": acs}), encoding="utf-8")
    (evals / "dem-7.md").write_text(
        f"---\ntype: eval\nverdict: {verdict}\nacs: all\nevaluated_at: 2026-10-08\n---\n", "utf-8"
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
    sign_off = SignOffOwnerSteps(
        ProjectHubPaths(wired.hubs), _DiskFolders(), HubEvalWriter(), clock=lambda: SIGNED_AT
    )
    wired.wire(owner_signoff=sign_off)
    return evals


# AC-PG-10.1: the sign-off answers 201 with the new SHIP record and writes owner-signoff.md.
def test_answers_created_with_record_when_owner_signs_off(tmp_path: Path, wired: Any) -> None:
    evals = _signoff_hub(tmp_path, wired, "SHIP-WITH-OWNER-STEPS")

    response = wired.client.post("/api/v1/features/demo/demo-feature/owner-signoff")

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["delivery"], body["verdict"], body["acs"]) == (
        "owner-signoff",
        "SHIP",
        ["AC-7.1", "AC-7.2"],
    )
    assert body["path"] == "features/demo-feature/evals/owner-signoff.md"
    assert body["evaluated_at"] == "2026-10-17T12:00:00+00:00"
    text = (evals / "owner-signoff.md").read_text(encoding="utf-8")
    assert "verdict: SHIP\n" in text
    assert "provenance: owner\n" in text
    assert "acs: [AC-7.1, AC-7.2]\n" in text


# AC-PG-10.1 (and its refusal, AC-PG-10.2): nothing waits on owner steps, 409 and no file;
# the app carries the composed error mapping for the sign-off's refusal.
def test_answers_conflict_and_writes_nothing_when_no_owner_steps(
    tmp_path: Path, wired: Any, open_client: Any
) -> None:
    evals = _signoff_hub(tmp_path, wired, "SHIP")
    ports = wired.client.app.state.ports
    problems = {OwnerSignOffError: owner_signoff_problem}

    with open_client(ports=ports, problems=problems) as client:
        response = client.post("/api/v1/features/demo/demo-feature/owner-signoff")

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "no AC waits on owner steps"
    assert sorted(path.name for path in evals.iterdir()) == ["dem-7.md"]


# AC-PG-10.1: an unknown feature answers 404.
def test_answers_not_found_when_signoff_feature_unknown(tmp_path: Path, wired: Any) -> None:
    _signoff_hub(tmp_path, wired, "SHIP-WITH-OWNER-STEPS")

    response = wired.client.post("/api/v1/features/demo/nope/owner-signoff")

    assert response.status_code == 404
