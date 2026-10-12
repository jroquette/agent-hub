from datetime import timedelta

import pytest

from agent_hub.core.approvals.approval import ApprovalKind
from agent_hub.core.approvals.fold_approvals import fold_approvals, open_gate_ids
from agent_hub.core.events.event import Event
from agent_hub.core.testing.builders import an_event
from agent_hub.core.testing.session_scenarios import (
    SCENARIO_START,
    as_stored,
    shuffled,
    stored_event_id,
)

TOOL_USE_ID = "toolu_ask_1"


def _at(minutes: float) -> object:
    return SCENARIO_START + timedelta(minutes=minutes)


def _guard_ask() -> Event:
    return an_event(
        type="gate.request",
        timestamp=_at(0),
        source_id=f"session-1:guard_ask:{TOOL_USE_ID}",
        repo="demo-api",
        agent="main",
        payload={
            "gate_id": TOOL_USE_ID,
            "kind": "guard_ask",
            "path": "docs/adr/0001-demo.md",
            "rule": "guard.ask_before_edit",
        },
    )


def _tool_result(source: str, status: str, minutes: float = 1) -> Event:
    hook = {"ok": "PostToolUse", "error": "PostToolUseFailure"}.get(status, "guard")
    return an_event(
        type="tool.result",
        source=source,
        timestamp=_at(minutes),
        source_id=f"session-1:{hook}:{source}:{TOOL_USE_ID}",
        payload={"tool": "Edit", "tool_use_id": TOOL_USE_ID, "status": status},
    )


def _prompt(minutes: float) -> Event:
    return an_event(type="message", timestamp=_at(minutes), payload={"role": "user", "chars": 12})


def _session_end(minutes: float) -> Event:
    return an_event(
        type="session.end",
        timestamp=_at(minutes),
        payload={"end_reason": "other", "outcome": None},
    )


def test_opens_approval_when_guard_ask_has_no_follow_up() -> None:
    approvals = fold_approvals(as_stored([_guard_ask()]), hub_paths={"demo": "/home/demo/demo-hub"})

    approval = approvals[TOOL_USE_ID]
    assert approval.kind == ApprovalKind.GUARD_ASK
    assert approval.status == "open"
    assert approval.decided is False
    assert approval.session_id == "session-1"
    assert approval.path == "docs/adr/0001-demo.md"
    assert approval.rule == "guard.ask_before_edit"
    assert approval.request_event_id == stored_event_id(1)
    assert approval.how_to_decide == "cd /home/demo/demo-hub && claude --resume session-1"
    assert approval.title == "Edit docs/adr/0001-demo.md needs approval"


@pytest.mark.parametrize("status", ["ok", "error"])
def test_approves_guard_ask_when_hook_result_has_same_tool_use_id(status: str) -> None:
    approval = fold_approvals(as_stored([_guard_ask(), _tool_result("claude_code", status)]))[
        TOOL_USE_ID
    ]

    assert (approval.status, approval.decided, approval.inferred) == ("approved", True, False)
    assert approval.decision_event_id == stored_event_id(2)
    assert approval.decided_at == _at(1)


@pytest.mark.parametrize("follow_up", [_prompt(2), _session_end(2)])
def test_declines_inferred_when_turn_ends_without_tool_run(follow_up: Event) -> None:
    approval = fold_approvals(as_stored([_guard_ask(), follow_up]))[TOOL_USE_ID]

    assert (approval.status, approval.decided, approval.inferred) == ("declined", True, True)
    assert approval.decided_at == _at(2)


def test_declines_inferred_when_only_transcript_reports_error_after_stop() -> None:
    # Stop yields no event (E4); the transcript tail it triggers carries the refused result.
    approval = fold_approvals(as_stored([_guard_ask(), _tool_result("transcript", "error")]))[
        TOOL_USE_ID
    ]

    assert (approval.status, approval.inferred) == ("declined", True)


def test_approves_when_hook_result_follows_inferred_decline_signal() -> None:
    events = [
        _guard_ask(),
        _tool_result("transcript", "error"),
        _tool_result("claude_code", "ok", 3),
    ]

    approval = fold_approvals(as_stored(events))[TOOL_USE_ID]

    assert (approval.status, approval.inferred) == ("approved", False)


def test_ignores_follow_up_when_it_belongs_to_other_session() -> None:
    other = _prompt(2).model_copy(update={"session": "session-2"})

    approval = fold_approvals(as_stored([_guard_ask(), other]))[TOOL_USE_ID]

    assert approval.status == "open"


def test_ignores_follow_up_when_it_happened_before_request() -> None:
    approval = fold_approvals(as_stored([_prompt(-1), _guard_ask()]))[TOOL_USE_ID]

    assert approval.status == "open"


def test_decides_by_gate_result_when_gate_id_matches() -> None:
    plan = an_event(
        type="gate.request",
        timestamp=_at(0),
        payload={"gate_id": "gate-plan-1", "kind": "plan", "feature": "control-plane"},
    )
    result = an_event(
        type="gate.result",
        source="executor",
        timestamp=_at(5),
        payload={"gate_id": "gate-plan-1", "kind": "plan", "result": "changes_requested"},
    )

    approvals = fold_approvals(as_stored([plan, result]))

    assert approvals["gate-plan-1"].status == "changes_requested"
    assert approvals["gate-plan-1"].title == "Approve plan for control-plane"
    assert approvals["gate-plan-1"].feature == "control-plane"


def test_opens_permission_approval_when_notification_asks() -> None:
    permission = an_event(
        type="gate.request",
        timestamp=_at(0),
        payload={"gate_id": "perm-1", "kind": "permission"},
    )

    approvals = fold_approvals(as_stored([permission]))

    assert approvals["perm-1"].kind == ApprovalKind.PERMISSION
    assert approvals["perm-1"].how_to_decide == "claude --resume session-1"
    assert open_gate_ids(as_stored([permission])) == frozenset({"perm-1"})


def test_approves_permission_inferred_when_tool_runs_before_turn_ends() -> None:
    permission = an_event(
        type="gate.request", timestamp=_at(0), payload={"gate_id": "perm-1", "kind": "permission"}
    )
    ran = an_event(
        type="tool.result",
        timestamp=_at(1),
        payload={"tool": "Bash", "tool_use_id": "toolu_x", "status": "ok"},
    )

    approval = fold_approvals(as_stored([permission, ran, _prompt(2)]))["perm-1"]

    assert (approval.status, approval.inferred) == ("approved", True)


def test_skips_request_when_kind_is_not_an_approval() -> None:
    stop_gate = an_event(type="gate.request", payload={"gate_id": "g-1", "kind": "stop_gate"})

    assert fold_approvals(as_stored([stop_gate])) == {}


def test_folds_same_approvals_when_events_shuffled() -> None:
    events = as_stored([_prompt(-1), _guard_ask(), _tool_result("transcript", "error"), _prompt(4)])
    expected = fold_approvals(events)

    for seed in range(30):
        assert fold_approvals(shuffled([*events, events[1]], seed)) == expected
