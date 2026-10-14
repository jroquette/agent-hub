from agent_hub.core.hub_config.model import TrackerStates
from agent_hub.core.hub_config.schema import read_shipped_schema
from agent_hub.core.runner.report_writes import (
    REVIEW_STATE,
    TrackerWrite,
    blocked_writes,
    call_line,
    failure_writes,
    no_changes_writes,
    success_writes,
)
from agent_hub.core.testing.builders import an_issue

COMMENT = "Run ab12cd34 opened https://github.com/acme/demo-api/pull/99. Adds the parser."
NO_CHANGES = "Run ab12cd34 ended with no changes at IMPLEMENTING: no commit on the branch"
BLOCKED = "Run ab12cd34 stopped at IMPLEMENTING and needs a human. The session asked: which API?"


def test_pins_review_state_when_module_loaded() -> None:
    assert REVIEW_STATE == "In Review"


def test_defaults_review_state_to_review_state_when_states_not_set() -> None:
    shipped = read_shipped_schema()["$defs"]["TrackerStates"]["properties"]["review"]

    # One source (Q-6): the model's default, the shipped schema's and REVIEW_STATE agree.
    assert TrackerStates().review == REVIEW_STATE
    assert TrackerStates.model_fields["review"].default is REVIEW_STATE
    assert shipped["default"] == REVIEW_STATE


def test_orders_success_writes_when_run_succeeds() -> None:
    issue = an_issue(id="DEM-1", labels=("agent-ready", "agent-failed", "demo-api"))

    writes = success_writes(
        issue,
        review_state=REVIEW_STATE,
        failed_label="agent-failed",
        blocked_label="agent-failed",
        comment=COMMENT,
    )

    assert writes == (
        TrackerWrite(operation="move_state", arguments=("DEM-1", "In Review")),
        TrackerWrite(operation="remove_label", arguments=("DEM-1", "agent-failed")),
        TrackerWrite(operation="comment", arguments=("DEM-1", COMMENT)),
    )


def test_skips_remove_when_issue_lacks_failed_label() -> None:
    issue = an_issue(id="DEM-1", labels=("agent-ready", "demo-api"))

    writes = success_writes(
        issue,
        review_state=REVIEW_STATE,
        failed_label="agent-failed",
        blocked_label="agent-failed",
        comment=COMMENT,
    )

    assert [write.operation for write in writes] == ["move_state", "comment"]


def test_removes_both_outcome_labels_when_delivered_issue_carries_them() -> None:
    issue = an_issue(id="DEM-1", labels=("agent-blocked", "agent-failed", "demo-api"))

    writes = success_writes(
        issue,
        review_state=REVIEW_STATE,
        failed_label="agent-failed",
        blocked_label="agent-blocked",
        comment=COMMENT,
    )

    assert writes == (
        TrackerWrite(operation="move_state", arguments=("DEM-1", "In Review")),
        TrackerWrite(operation="remove_label", arguments=("DEM-1", "agent-failed")),
        TrackerWrite(operation="remove_label", arguments=("DEM-1", "agent-blocked")),
        TrackerWrite(operation="comment", arguments=("DEM-1", COMMENT)),
    )


def test_writes_only_comment_when_no_changes_issue_carries_no_outcome_label() -> None:
    issue = an_issue(id="DEM-1", labels=("agent-ready", "demo-api"))

    writes = no_changes_writes(
        issue, failed_label="agent-failed", blocked_label="agent-blocked", comment=NO_CHANGES
    )

    assert writes == (TrackerWrite(operation="comment", arguments=("DEM-1", NO_CHANGES)),)


def test_removes_carried_labels_when_no_changes() -> None:
    issue = an_issue(id="DEM-1", labels=("agent-blocked", "agent-failed"))

    writes = no_changes_writes(
        issue, failed_label="agent-failed", blocked_label="agent-blocked", comment=NO_CHANGES
    )

    assert writes == (
        TrackerWrite(operation="remove_label", arguments=("DEM-1", "agent-failed")),
        TrackerWrite(operation="remove_label", arguments=("DEM-1", "agent-blocked")),
        TrackerWrite(operation="comment", arguments=("DEM-1", NO_CHANGES)),
    )


def test_removes_failed_label_once_when_no_changes_and_labels_fall_back() -> None:
    issue = an_issue(id="DEM-1", labels=("agent-failed",))

    writes = no_changes_writes(
        issue, failed_label="agent-failed", blocked_label="agent-failed", comment=NO_CHANGES
    )

    assert [write.operation for write in writes] == ["remove_label", "comment"]


def test_orders_blocked_writes_when_issue_carries_failed_label() -> None:
    issue = an_issue(id="DEM-1", labels=("agent-failed", "demo-api"))

    writes = blocked_writes(
        issue, failed_label="agent-failed", blocked_label="agent-blocked", comment=BLOCKED
    )

    assert writes == (
        TrackerWrite(operation="add_label", arguments=("DEM-1", "agent-blocked")),
        TrackerWrite(operation="remove_label", arguments=("DEM-1", "agent-failed")),
        TrackerWrite(operation="comment", arguments=("DEM-1", BLOCKED)),
    )


def test_adds_failed_label_alone_when_blocked_label_falls_back() -> None:
    issue = an_issue(id="DEM-1", labels=("agent-failed", "demo-api"))

    writes = blocked_writes(
        issue, failed_label="agent-failed", blocked_label="agent-failed", comment=BLOCKED
    )

    assert writes == (
        TrackerWrite(operation="add_label", arguments=("DEM-1", "agent-failed")),
        TrackerWrite(operation="comment", arguments=("DEM-1", BLOCKED)),
    )


def test_skips_remove_when_blocked_issue_lacks_failed_label() -> None:
    issue = an_issue(id="DEM-1", labels=("demo-api",))

    writes = blocked_writes(
        issue, failed_label="agent-failed", blocked_label="agent-blocked", comment=BLOCKED
    )

    assert [write.operation for write in writes] == ["add_label", "comment"]


def test_orders_failure_writes_when_run_fails() -> None:
    comment = "Run ab12cd34 failed at VERIFYING. Diagnosis: gate failed"

    writes = failure_writes(issue_id="DEM-1", failed_label="agent-failed", comment=comment)

    assert writes == (
        TrackerWrite(operation="add_label", arguments=("DEM-1", "agent-failed")),
        TrackerWrite(operation="comment", arguments=("DEM-1", comment)),
    )


def test_formats_call_line_when_write_shown() -> None:
    assert call_line(TrackerWrite(operation="move_state", arguments=("DEM-1", "In Review"))) == (
        "move_state(DEM-1, In Review)"
    )
    assert call_line(TrackerWrite(operation="comment", arguments=("DEM-1", COMMENT))) == (
        f"comment(DEM-1, {COMMENT})"
    )
