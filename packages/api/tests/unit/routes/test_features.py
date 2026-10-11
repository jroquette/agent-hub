from typing import Any

from agent_hub.core.features.feature_view import AcRow, FeatureDetail
from agent_hub.core.readmodels.filters import Scope
from agent_hub.core.testing.read_model_builders import a_feature_view


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
