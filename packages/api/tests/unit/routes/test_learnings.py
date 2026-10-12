from typing import Any

from agent_hub.core.learnings.learning import LearningStatus
from agent_hub.core.readmodels.filters import LearningFilter
from agent_hub.core.testing.read_model_builders import a_learning


def test_maps_filters_when_learnings_listed(wired: Any) -> None:
    wired.events.learnings.append(a_learning())

    response = wired.client.get("/api/v1/learnings", params={"status": "proposed"})

    assert response.json()["items"] == [a_learning().model_dump(mode="json")]
    assert wired.events.calls == [
        ("list_learnings", LearningFilter(status=LearningStatus.PROPOSED))
    ]


def test_maps_learning_when_learning_requested(wired: Any) -> None:
    wired.events.learnings.append(a_learning())

    assert wired.client.get("/api/v1/learnings/learning-1").json()["id"] == "learning-1"


def test_answers_not_found_when_learning_unknown(wired: Any) -> None:
    assert wired.client.get("/api/v1/learnings/nope").status_code == 404
