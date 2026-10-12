from typing import Any

from agent_hub.core.readmodels.filters import RunFilter
from agent_hub.core.runner.run_record import Stage
from agent_hub.core.testing.read_model_builders import a_run


def test_maps_filters_when_runs_listed(wired: Any) -> None:
    wired.events.runs.append(a_run())

    response = wired.client.get(
        "/api/v1/workflow-runs",
        params={"project": "demo", "stage": "IMPLEMENTING", "mode": "live", "issue": "DEM-7"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["id"] == "1a2b3c4d"
    assert wired.events.calls == [
        (
            "list_runs",
            RunFilter(project="demo", stage=Stage.IMPLEMENTING, mode="live", issue="DEM-7"),
        )
    ]


def test_maps_run_when_run_requested(wired: Any) -> None:
    wired.events.runs.append(a_run())

    response = wired.client.get("/api/v1/workflow-runs/1a2b3c4d")

    assert response.json() == a_run().model_dump(mode="json")


def test_answers_not_found_when_run_unknown(wired: Any) -> None:
    response = wired.client.get("/api/v1/workflow-runs/ffffffff")

    assert response.status_code == 404
    assert response.json()["detail"] == "No run with id 'ffffffff'."
