from agent_hub.core.runner.report_writes import (
    REVIEW_STATE,
    TrackerWrite,
    call_line,
    failure_writes,
    success_writes,
)
from agent_hub.core.testing.builders import an_issue

COMMENT = "Run ab12cd34 opened https://github.com/acme/demo-api/pull/99. Adds the parser."


def test_pins_review_state_when_module_loaded() -> None:
    assert REVIEW_STATE == "In Review"


def test_orders_success_writes_when_run_succeeds() -> None:
    issue = an_issue(id="DEM-1", labels=("agent-ready", "agent-failed", "demo-api"))

    writes = success_writes(
        issue, review_state=REVIEW_STATE, failed_label="agent-failed", comment=COMMENT
    )

    assert writes == (
        TrackerWrite(operation="move_state", arguments=("DEM-1", "In Review")),
        TrackerWrite(operation="remove_label", arguments=("DEM-1", "agent-failed")),
        TrackerWrite(operation="comment", arguments=("DEM-1", COMMENT)),
    )


def test_skips_remove_when_issue_lacks_failed_label() -> None:
    issue = an_issue(id="DEM-1", labels=("agent-ready", "demo-api"))

    writes = success_writes(
        issue, review_state=REVIEW_STATE, failed_label="agent-failed", comment=COMMENT
    )

    assert [write.operation for write in writes] == ["move_state", "comment"]


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
