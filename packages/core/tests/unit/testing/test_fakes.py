import copy

import pytest

from agent_hub.core.errors import TrackerError
from agent_hub.core.testing.builders import a_seeded_tracker_backend, an_event, an_issue
from agent_hub.core.testing.fakes import InMemoryEventStore, InMemoryTrackerClient


def test_keeps_stored_event_when_caller_mutates_appended_payload() -> None:
    event_store = InMemoryEventStore()
    event = an_event(payload={"items": [1, 2]})
    original = event.model_copy(deep=True)
    event_store.append([event])

    event.payload["items"].append(3)  # type: ignore[union-attr]
    event.payload["added"] = True

    assert event_store.read_all() == [original]


def test_keeps_stored_event_when_caller_mutates_read_payload() -> None:
    event_store = InMemoryEventStore()
    event = an_event(payload={"items": [1, 2]})
    original = event.model_copy(deep=True)
    event_store.append([event])

    read = event_store.read_all()[0]
    read.payload["items"].append(3)  # type: ignore[union-attr]
    read.payload["added"] = True

    assert event_store.read_all() == [original]


def test_lists_open_issues_with_label_when_ready_issues_listed() -> None:
    client = InMemoryTrackerClient(a_seeded_tracker_backend())

    ready = client.list_ready("DEM", "agent-ready")

    assert {issue.id for issue in ready} == {"DEM-1", "DEM-2", "DEM-3"}


def test_lists_nothing_when_team_or_label_unknown() -> None:
    client = InMemoryTrackerClient(a_seeded_tracker_backend())

    assert client.list_ready("NOPE", "agent-ready") == []
    assert client.list_ready("DEM", "no-such-label") == []


def test_returns_stored_issue_when_issue_read() -> None:
    backend = a_seeded_tracker_backend()

    issue = InMemoryTrackerClient(backend).get_issue("DEM-1")

    assert issue == backend.issues["DEM-1"]


def test_raises_naming_id_when_issue_unknown() -> None:
    client = InMemoryTrackerClient(a_seeded_tracker_backend())

    with pytest.raises(TrackerError) as raised:
        client.get_issue("DEM-999")

    assert str(raised.value).startswith("get_issue DEM-999: ")


def test_raises_naming_id_when_id_malformed() -> None:
    client = InMemoryTrackerClient(a_seeded_tracker_backend())

    with pytest.raises(TrackerError) as raised:
        client.get_issue("dem-1\n")

    assert str(raised.value).startswith("get_issue dem-1\\n: ")
    assert "\n" not in str(raised.value)


def test_moves_issue_when_state_known() -> None:
    backend = a_seeded_tracker_backend()

    InMemoryTrackerClient(backend).move_state("DEM-1", "In Progress")

    assert backend.issues["DEM-1"].state == "In Progress"


def test_keeps_backend_when_moved_to_current_state() -> None:
    backend = a_seeded_tracker_backend()
    before = copy.deepcopy(backend)

    InMemoryTrackerClient(backend).move_state("DEM-1", "Todo")

    assert backend == before


def test_raises_naming_state_when_state_unknown() -> None:
    backend = a_seeded_tracker_backend()
    before = copy.deepcopy(backend)

    with pytest.raises(TrackerError) as raised:
        InMemoryTrackerClient(backend).move_state("DEM-1", "Shipped")

    assert "Shipped" in str(raised.value)
    assert backend == before


def test_raises_when_state_belongs_to_other_team() -> None:
    backend = a_seeded_tracker_backend()

    with pytest.raises(TrackerError) as raised:
        InMemoryTrackerClient(backend).move_state("OPS-1", "Duplicate")

    assert "Duplicate" in str(raised.value)
    assert backend.issues["OPS-1"].state == "Todo"


def test_adds_label_keeping_others_when_label_known() -> None:
    backend = a_seeded_tracker_backend()

    InMemoryTrackerClient(backend).add_label("DEM-1", "agent-failed")

    assert backend.issues["DEM-1"].labels == ("agent-ready", "demo-api", "agent-failed")


def test_keeps_backend_when_present_label_added() -> None:
    backend = a_seeded_tracker_backend()
    before = copy.deepcopy(backend)

    InMemoryTrackerClient(backend).add_label("DEM-1", "demo-api")

    assert backend == before


def test_raises_naming_label_when_added_label_unknown() -> None:
    backend = a_seeded_tracker_backend()
    before = copy.deepcopy(backend)

    with pytest.raises(TrackerError) as raised:
        InMemoryTrackerClient(backend).add_label("DEM-1", "urgent")

    assert "urgent" in str(raised.value)
    assert backend == before


def test_raises_when_team_label_added_to_other_team() -> None:
    backend = a_seeded_tracker_backend()
    before = copy.deepcopy(backend)

    with pytest.raises(TrackerError) as raised:
        InMemoryTrackerClient(backend).add_label("OPS-1", "bug")

    assert "bug" in str(raised.value)
    assert backend == before


def test_removes_label_keeping_others_when_label_present() -> None:
    backend = a_seeded_tracker_backend()

    InMemoryTrackerClient(backend).remove_label("DEM-1", "agent-ready")

    assert backend.issues["DEM-1"].labels == ("demo-api",)


def test_keeps_backend_when_absent_label_removed() -> None:
    backend = a_seeded_tracker_backend()
    before = copy.deepcopy(backend)

    InMemoryTrackerClient(backend).remove_label("DEM-1", "bug")

    assert backend == before


def test_raises_naming_label_when_removed_label_unknown() -> None:
    backend = a_seeded_tracker_backend()
    before = copy.deepcopy(backend)

    with pytest.raises(TrackerError) as raised:
        InMemoryTrackerClient(backend).remove_label("DEM-1", "urgent")

    assert "urgent" in str(raised.value)
    assert backend == before


def test_records_one_comment_when_issue_commented() -> None:
    backend = a_seeded_tracker_backend()

    InMemoryTrackerClient(backend).comment("DEM-2", "Run failed: check the log.")

    assert backend.comments == [("DEM-2", "Run failed: check the log.")]


def test_raises_naming_id_when_commented_issue_unknown() -> None:
    backend = a_seeded_tracker_backend()
    before = copy.deepcopy(backend)

    with pytest.raises(TrackerError) as raised:
        InMemoryTrackerClient(backend).comment("DEM-999", "hello")

    assert str(raised.value).startswith("comment DEM-999: ")
    assert backend == before


def test_raises_naming_team_when_issue_of_unknown_team_moved() -> None:
    backend = a_seeded_tracker_backend()
    backend.issues["XYZ-1"] = an_issue(id="XYZ-1")
    before = copy.deepcopy(backend)

    with pytest.raises(TrackerError) as raised:
        InMemoryTrackerClient(backend).move_state("XYZ-1", "Done")

    assert "team XYZ not found" in str(raised.value)
    assert backend == before


def test_raises_naming_team_when_issue_of_unknown_team_labelled() -> None:
    backend = a_seeded_tracker_backend()
    backend.issues["XYZ-1"] = an_issue(id="XYZ-1")
    before = copy.deepcopy(backend)

    with pytest.raises(TrackerError) as raised:
        InMemoryTrackerClient(backend).add_label("XYZ-1", "agent-failed")

    assert "team XYZ not found" in str(raised.value)
    assert backend == before


def test_lists_nothing_when_team_has_issues_but_no_states() -> None:
    backend = a_seeded_tracker_backend()
    backend.issues["XYZ-1"] = an_issue(id="XYZ-1")

    assert InMemoryTrackerClient(backend).list_ready("XYZ", "agent-ready") == []
