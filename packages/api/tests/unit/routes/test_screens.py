"""The screen routes over the read-model fakes, answered by a real ``ScreenReads``."""

from typing import Any

import pytest

from agent_hub.api.composition import COMPOSED_PROBLEMS
from agent_hub.core.features.feature_view import FeatureDetail
from agent_hub.core.projects.project_views import LiveTile, ProjectSummary
from agent_hub.core.readmodels.filters import Scope
from agent_hub.core.readmodels.page import Page
from agent_hub.core.screens.screen_reads import ScreenReads
from agent_hub.core.testing.read_model_builders import a_feature_view, a_hub_view, a_project_summary
from agent_hub.storage.errors import DatabaseAccessError
from agent_hub.storage.event_store import DatabaseBusyError

SHELL = "/api/v1/screens/shell"


# AC-374.7: the badge count still comes when the live sessions cannot be read. The store's own
# error, which /live-sessions answers as the database problem, leaves the shell read answering,
# its features counted without tiles: here the one NO-SHIP.
def test_answers_badge_count_when_store_cannot_read_live_sessions(
    wired: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    wired.hubs.hubs.append(a_hub_view())
    wired.hubs.projects.append(a_project_summary())
    refused = a_feature_view(slug="refused", issues=(), verdict="NO-SHIP")
    wired.hubs.features.append(FeatureDetail.model_validate(refused.model_dump() | {"ac_rows": ()}))
    tried: list[Scope] = []

    def unreadable(scope: Scope) -> Page[LiveTile]:
        tried.append(scope)
        raise DatabaseAccessError("the event database could not be read")

    monkeypatch.setattr(wired.events, "list_live_sessions", unreadable)
    wired.wire(screen_reads=ScreenReads(wired.events, wired.hubs))
    live = wired.client.get("/api/v1/live-sessions")
    assert (live.status_code, live.json()["title"]) == (503, "Collector database unavailable")

    response = wired.client.get(SHELL)

    assert response.status_code == 200, response.text
    assert response.json()["features_needing_you"] == 1
    assert tried == [Scope(project=None), Scope(project=None)]


# When the whole event store cannot be read, every event read the shell read makes raises the
# store's error at once (the projects' activity reads the same store), and the shell read answers
# the problem /live-sessions answers. On the shell's first read, the switcher, the Workflow runs
# item and the Features badge then hide together, the badge with them; a later poll's failure keeps
# the last facts. The app carries the composed error mapping, as hub web does.
@pytest.mark.parametrize(
    ("error", "title"),
    [
        (DatabaseAccessError("disk I/O error"), "Collector database unavailable"),
        (DatabaseBusyError("database is locked"), "Collector database busy"),
    ],
    ids=["unreadable", "busy"],
)
def test_answers_store_problem_when_event_store_cannot_be_read(
    wired: Any, open_client: Any, monkeypatch: pytest.MonkeyPatch, *, error: Exception, title: str
) -> None:
    wired.hubs.hubs.append(a_hub_view())
    wired.hubs.projects.append(a_project_summary())
    refused = a_feature_view(slug="refused", issues=(), verdict="NO-SHIP")
    wired.hubs.features.append(FeatureDetail.model_validate(refused.model_dump() | {"ac_rows": ()}))
    wired.wire(screen_reads=ScreenReads(wired.events, wired.hubs))

    def unreadable_projects() -> Page[ProjectSummary]:
        raise error

    with open_client(ports=wired.client.app.state.ports, problems=COMPOSED_PROBLEMS) as client:
        readable = client.get(SHELL)
        assert (readable.status_code, readable.json()["features_needing_you"]) == (200, 1)
        wired.events.failure = error
        monkeypatch.setattr(wired.hubs, "list_projects", unreadable_projects)
        live = client.get("/api/v1/live-sessions")
        assert (live.status_code, live.json()["title"]) == (503, title)

        response = client.get(SHELL)

    assert response.status_code == 503, response.text
    assert response.json() == live.json() | {"instance": SHELL}
