from typing import Any

from agent_hub.core.readmodels.filters import Scope
from agent_hub.core.testing.read_model_builders import a_finding_view


def test_maps_scope_when_findings_listed(wired: Any) -> None:
    wired.hubs.findings.append(a_finding_view())

    response = wired.client.get("/api/v1/doctor/findings", params={"project": "demo"})

    assert response.json()["items"] == [a_finding_view().model_dump(mode="json")]
    assert wired.hubs.calls == [("doctor_findings", Scope(project="demo"))]
