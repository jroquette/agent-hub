import pytest
from pydantic import ValidationError

from agent_hub.core.events.event import Event, EventType
from agent_hub.core.testing.builders import (
    a_hub_document,
    a_seeded_tracker_backend,
    an_event,
    an_issue,
    events_to_jsonl,
)
from agent_hub.core.testing.fakes import TrackerState


def test_gives_unique_source_id_when_called_twice() -> None:
    assert an_event().source_id != an_event().source_id


def test_applies_overrides_when_fields_given() -> None:
    event = an_event(project="other", type="message", payload={"text": "hi"})

    assert event.project == "other"
    assert event.type == EventType.MESSAGE
    assert event.payload == {"text": "hi"}


def test_round_trips_when_events_written_as_jsonl() -> None:
    events = [an_event(), an_event(repo="org/a")]

    text = events_to_jsonl(events)

    assert text.endswith("\n")
    lines = text.splitlines()
    assert len(lines) == len(events)
    assert [Event.model_validate_json(line) for line in lines] == events


def test_returns_fresh_copy_when_hub_document_built() -> None:
    first = a_hub_document()
    first["project"]["name"] = "changed"
    first["repos"].append({"dir": "extra"})

    second = a_hub_document()

    assert second["project"]["name"] == "demo"
    assert [repo["dir"] for repo in second["repos"]] == ["demo-api"]


def test_builds_issue_with_url_of_id_when_id_overridden() -> None:
    issue = an_issue(id="DEM-42", labels=("bug",))

    assert issue.id == "DEM-42"
    assert issue.labels == ("bug",)
    assert issue.url == "https://linear.app/demo/issue/DEM-42"


def test_raises_when_issue_override_names_unknown_field() -> None:
    with pytest.raises(ValidationError):
        an_issue(lables=("x",))


def test_keeps_given_url_when_url_overridden() -> None:
    assert an_issue(url="https://example.com/x").url == "https://example.com/x"


def test_seeds_teams_states_and_labels_when_tracker_backend_built() -> None:
    backend = a_seeded_tracker_backend()

    states = (
        TrackerState(name="Todo", closed=False),
        TrackerState(name="In Progress", closed=False),
        TrackerState(name="Done", closed=True),
        TrackerState(name="Canceled", closed=True),
    )
    assert backend.states == {
        "DEM": (*states, TrackerState(name="Duplicate", closed=True)),
        "OPS": states,
    }
    assert backend.team_labels == {"DEM": ("demo-api", "bug"), "OPS": ()}
    assert backend.workspace_labels == ("agent-ready", "agent-failed")
    assert backend.comments == []


def test_seeds_issues_in_every_state_when_tracker_backend_built() -> None:
    backend = a_seeded_tracker_backend()

    seeded = {issue_id: (issue.state, issue.labels) for issue_id, issue in backend.issues.items()}
    assert seeded == {
        "DEM-1": ("Todo", ("agent-ready", "demo-api")),
        "DEM-2": ("In Progress", ("agent-ready",)),
        "DEM-3": ("Todo", ("agent-ready", "bug")),
        "DEM-4": ("Done", ("agent-ready",)),
        "DEM-5": ("Canceled", ("agent-ready",)),
        "DEM-6": ("Duplicate", ("agent-ready",)),
        "DEM-7": ("Todo", ()),
        "OPS-1": ("Todo", ("agent-ready",)),
    }
    assert all(issue.id == issue_id for issue_id, issue in backend.issues.items())


def test_returns_fresh_backend_when_tracker_backend_built_twice() -> None:
    first = a_seeded_tracker_backend()
    first.comments.append(("DEM-1", "changed"))
    del first.issues["DEM-1"]

    second = a_seeded_tracker_backend()

    assert second.comments == []
    assert "DEM-1" in second.issues
