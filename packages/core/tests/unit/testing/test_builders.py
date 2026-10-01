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

SEEDED_DEM_1_DESCRIPTION = """Add a synthetic feature.

Steps:

- read the synthetic input
- write the synthetic output

```sh
make check
```
"""


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


def test_defaults_description_when_issue_built() -> None:
    assert an_issue().description == "A synthetic description."


def test_applies_description_when_description_overridden() -> None:
    assert an_issue(description="").description == ""


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

    seeded = {
        issue_id: (issue.state, issue.labels, issue.description)
        for issue_id, issue in backend.issues.items()
    }
    assert seeded == {
        "DEM-1": ("Todo", ("agent-ready", "demo-api"), SEEDED_DEM_1_DESCRIPTION),
        "DEM-2": ("In Progress", ("agent-ready",), ""),
        "DEM-3": ("Todo", ("agent-ready", "bug"), "Fix the synthetic bug in DEM-3."),
        "DEM-4": ("Done", ("agent-ready",), "Synthetic work already done in DEM-4."),
        "DEM-5": ("Canceled", ("agent-ready",), "Synthetic work dropped in DEM-5."),
        "DEM-6": ("Duplicate", ("agent-ready",), "Synthetic duplicate of DEM-5."),
        "DEM-7": ("Todo", (), "Synthetic issue DEM-7 with no label."),
        "OPS-1": ("Todo", ("agent-ready",), "Synthetic issue of another team."),
    }
    assert all(issue.id == issue_id for issue_id, issue in backend.issues.items())


def test_gives_each_seeded_issue_own_description_when_backend_built() -> None:
    issues = a_seeded_tracker_backend().issues
    descriptions = [issue.description for issue in issues.values()]

    assert len(set(descriptions)) == len(descriptions)
    assert issues["DEM-2"].description == ""
    dem_1 = issues["DEM-1"].description.splitlines()
    assert len(dem_1) > 3
    assert any(line.startswith("- ") for line in dem_1)
    assert any(line.startswith("```") and line != "```" for line in dem_1)
    assert dem_1.count("```") == 1


def test_returns_fresh_backend_when_tracker_backend_built_twice() -> None:
    first = a_seeded_tracker_backend()
    first.comments.append(("DEM-1", "changed"))
    del first.issues["DEM-1"]

    second = a_seeded_tracker_backend()

    assert second.comments == []
    assert "DEM-1" in second.issues
