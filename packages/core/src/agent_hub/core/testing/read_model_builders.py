"""Builders of synthetic read models for API and screen tests; every value is made up."""

from datetime import UTC, datetime
from decimal import Decimal

from pydantic import JsonValue

from agent_hub.core.agent_sessions.agent_session import (
    AgentSession,
    AgentSessionStatus,
    CloudSession,
    OpenPermission,
    Workdir,
)
from agent_hub.core.agent_sessions.driver import PermissionRequest, PermissionSuggestion
from agent_hub.core.agent_sessions.records import LogRecord, RecordKind
from agent_hub.core.approvals.approval import Approval, ApprovalKind
from agent_hub.core.brain.brain_note import BrainEntry, BrainNote, BrainTree
from agent_hub.core.features.feature_view import (
    AcCounts,
    EvalRecord,
    FeatureView,
    GoldenPath,
    GoldenStep,
)
from agent_hub.core.features.ticket_view import (
    FeatureTickets,
    TicketEdge,
    TicketPlan,
    TicketRow,
)
from agent_hub.core.hub_config.doctor_rules import Severity
from agent_hub.core.hubs.finding_view import FindingView
from agent_hub.core.hubs.registered_hub import HubView
from agent_hub.core.learnings.learning import (
    Learning,
    LearningDetail,
    LearningState,
    LearningStatus,
    LearningTarget,
)
from agent_hub.core.projects.project_views import ProjectSummary
from agent_hub.core.runner.run_record import Stage
from agent_hub.core.runs.workflow_run import IssueRef, RunCaps, RunStep, WorkflowRun
from agent_hub.core.sessions.problem import Problem, ProblemKind, Resolution, SessionProblems
from agent_hub.core.sessions.session import (
    Actor,
    Session,
    SessionLabel,
    SessionSegment,
    SessionStatus,
    SummaryLine,
    TokenUsage,
)
from agent_hub.core.tracker.tracker_reader import IssueState, IssueSummary, TicketSnapshot

STARTED = datetime(2026, 10, 9, 14, 0, 0, 123000, tzinfo=UTC)
LAST_ACTIVITY = datetime(2026, 10, 9, 14, 5, 41, 882000, tzinfo=UTC)
EVENT_ID = "01929a4e-6c1d-7f3a-9b2e-5d1c0a8e4f17"
HUB_ID = "01929a40-5091-7b98-8a6e-3f20c1d4a7b2"


def a_session(**overrides: object) -> Session:
    """A live synthetic session of project ``demo``."""
    fields: dict[str, object] = {
        "id": "session-1",
        "project": "demo",
        "repo": "demo-api",
        "agent": "main",
        "started_at": STARTED,
        "ended_at": None,
        "last_activity_at": LAST_ACTIVITY,
        "segments": (SessionSegment(index=1, started_at=STARTED, ended_at=None, end_reason=None),),
        "status": SessionStatus.LIVE,
        "outcome": None,
        "end_reason": None,
        "turns": 3,
        "tool_counts": {"Read": 4, "Bash": 1},
        "files_touched": 2,
        "errors": 0,
        "guard_denials": 0,
        "gates": 0,
        "learnings_proposed": 0,
        "model": "claude-opus-4-1",
        "tokens": TokenUsage(input=1200, output=340, cache_read=0, cache_write=0),
        "cost_usd": Decimal("0.0412"),
        "has_transcript": True,
        "sources_missing": ("otel", "github"),
    }
    return Session.model_validate(fields | overrides)


def a_run(**overrides: object) -> WorkflowRun:
    """A synthetic ``hub run`` in IMPLEMENTING."""
    fields: dict[str, object] = {
        "id": "1a2b3c4d",
        "project": "demo",
        "repo": "demo-api",
        "issue": IssueRef(key="DEM-7"),
        "workflow": "issue-to-pr",
        "stage": Stage.IMPLEMENTING,
        "mode": "live",
        "started_at": STARTED,
        "ended_at": None,
        "last_activity_at": LAST_ACTIVITY,
        "steps": (
            RunStep(
                key="implement",
                attempt=1,
                max_attempts=1,
                status="running",
                started_at=STARTED,
                ended_at=None,
            ),
        ),
        "failure": None,
        "caps": RunCaps(
            budget_usd=Decimal(10), max_turns=80, model="opus", tracker_transport="api"
        ),
        "cost_usd": None,
        "sources_missing": ("linear", "github"),
    }
    return WorkflowRun.model_validate(fields | overrides)


def an_approval(**overrides: object) -> Approval:
    """An open synthetic guard ask."""
    fields: dict[str, object] = {
        "id": "toolu_demo_1",
        "project": "demo",
        "repo": "demo-api",
        "kind": ApprovalKind.GUARD_ASK,
        "title": "Edit under docs/adr needs approval",
        "status": "open",
        "decided": False,
        "gate_id": "toolu_demo_1",
        "session_id": "session-1",
        "requested_by": "main",
        "requested_at": STARTED,
        "path": "docs/adr/0001-demo.md",
        "rule": "guard.ask_before_edit",
        "hub_path": "/home/demo/demo-hub",
        "how_to_decide": "cd /home/demo/demo-hub && claude --resume session-1",
        "request_event_id": EVENT_ID,
    }
    return Approval.model_validate(fields | overrides)


def a_learning(**overrides: object) -> Learning:
    """A proposed synthetic learning."""
    fields: dict[str, object] = {
        "id": "learning-1",
        "project": "demo",
        "text": "Run the migrations check before the PR",
        "target": LearningTarget(kind="team", path="brain/learnings/gotchas/testing.md"),
        "author": "main",
        "provenance": "agent",
        "status": LearningStatus.PROPOSED,
        "source_session_id": "session-1",
        "source_event_id": EVENT_ID,
        "proposed_at": STARTED,
    }
    return Learning.model_validate(fields | overrides)


def a_project_summary(**overrides: object) -> ProjectSummary:
    """A Portfolio card of the synthetic project ``demo``."""
    fields: dict[str, object] = {
        "name": "demo",
        "hub_id": HUB_ID,
        "hub_repo": "acme/demo-hub",
        "tracker_teams": ("DEM",),
        "platform_version": "0.8.0",
        "lock_version": "0.8.0",
        "lock_state": "in_sync",
        "repos": ("demo-api",),
        "hub_health": "ok",
        "live_sessions": 1,
        "runs_in_flight_by_stage": {Stage.IMPLEMENTING: 1},
        "failed_runs_7d": 0,
        "cost_period": Decimal("1.2734"),
        "cost_previous_period": None,
        "sources_missing": ("github", "linear"),
    }
    return ProjectSummary.model_validate(fields | overrides)


def a_feature_view(**overrides: object) -> FeatureView:
    """A synthetic feature in implementation."""
    fields: dict[str, object] = {
        "project": "demo",
        "slug": "demo-feature",
        "issues": ("DEM-7",),
        "size": "bounded",
        "phase": "implement",
        "files": ("spec.md", "plan.md", "features.json"),
        "acs": AcCounts(passing=2, total=5, owner_steps=1),
        "verdict": None,
        "verdict_line": None,
        "repos": ("demo-api",),
        "golden_path": a_golden_path(),
        "tickets_source": "plan",
        "sources_missing": ("github",),
    }
    return FeatureView.model_validate(fields | overrides)


def a_golden_path(**overrides: object) -> GoldenPath:
    """The golden path of a synthetic feature in implementation: 1 of 3 tickets, 2 of 5 ACs."""
    states = (
        ("spec", "done", None, None),
        ("research", "skipped", None, None),
        ("plan", "done", None, None),
        ("tickets", "done", "3 of 3 created", None),
        ("implement", "current", "1/3 tickets · 2/5 ACs", None),
        ("review", "pending", "0/3 reviewed", "Implement is not done"),
        ("evaluate", "pending", None, "Implement is not done"),
        ("shipped", "pending", None, "Implement is not done"),
    )
    progress = {
        "tickets": {"done": 3, "total": 3},
        "implement": {"done": 1, "total": 3},
        "review": {"done": 0, "total": 3},
    }
    fields: dict[str, object] = {
        "steps": tuple(
            GoldenStep.model_validate(
                {
                    "name": name,
                    "state": state,
                    "meta": meta,
                    "reason": reason,
                    "progress": progress.get(name),
                }
            )
            for name, state, meta, reason in states
        ),
        "phase": "implement",
    }
    return GoldenPath.model_validate(fields | overrides)


def a_hub_view(**overrides: object) -> HubView:
    """A valid synthetic registered hub."""
    fields: dict[str, object] = {
        "id": HUB_ID,
        "path": "/home/demo/demo-hub",
        "added_at": STARTED,
        "project": "demo",
        "platform_pin": "0.8.0",
        "running_version": "0.8.0",
        "lock_version": "0.8.0",
        "lock_state": "in_sync",
        "modules": ("cloud",),
        "guard_ask_before_edit": ("demo-api/docs/adr",),
        "repos": ("demo-api",),
        "valid": True,
    }
    return HubView.model_validate(fields | overrides)


def a_finding_view(**overrides: object) -> FindingView:
    """A synthetic warning of the doctor."""
    fields: dict[str, object] = {
        "project": "demo",
        "rule": "instructions.size",
        "severity": Severity.WARNING,
        "path": "AGENTS.md",
        "line": 1,
        "message": "132 lines, limit 100",
        "fix": "Keep it a map, not a manual",
    }
    return FindingView.model_validate(fields | overrides)


def a_session_label(**overrides: object) -> SessionLabel:
    """The label of a synthetic ``/feature`` session on issue ``DEM-7``."""
    fields: dict[str, object] = {
        "issue": "DEM-7",
        "workflow": "/feature",
        "workflows": ("/feature", "/create-plan"),
        "repo": "demo-api",
        "branch": "jdoe/dem-7-login",
        "worktree": "dem-7-login",
    }
    return SessionLabel.model_validate(fields | overrides)


def a_problem(**overrides: object) -> Problem:
    """A failed Bash of the main agent that still needs the owner."""
    fields: dict[str, object] = {
        "event_id": EVENT_ID,
        "kind": ProblemKind.COMMAND_EXIT,
        "tool": "Bash",
        "where": "make check-fast",
        "message": "1 failed, 12 passed",
        "at": LAST_ACTIVITY,
        "actor": Actor(kind="main"),
        "resolution": Resolution.NEEDS_YOU,
    }
    return Problem.model_validate(fields | overrides)


def a_session_problems(**overrides: object) -> SessionProblems:
    """The problems of ``session-1``: one that needs the owner, with its summary line."""
    problem = a_problem()
    fields: dict[str, object] = {
        "session_id": "session-1",
        "summary": (
            SummaryLine(text="Needs you: command_exit in make check-fast", event_id=EVENT_ID),
        ),
        "items": (problem,),
    }
    return SessionProblems.model_validate(fields | overrides)


def a_brain_tree(**overrides: object) -> BrainTree:
    """The brain of the synthetic project ``demo``."""
    fields: dict[str, object] = {
        "project": "demo",
        "entries": (
            BrainEntry(path="_inbox/testing-x.md", size=96),
            BrainEntry(path="decisions/index.md", size=210),
            BrainEntry(path="index.md", size=180),
            BrainEntry(path="now.md", size=140),
        ),
    }
    return BrainTree.model_validate(fields | overrides)


def a_brain_note(**overrides: object) -> BrainNote:
    """The synthetic inbox note ``_inbox/testing-x.md``."""
    fields: dict[str, object] = {
        "project": "demo",
        "path": "_inbox/testing-x.md",
        "frontmatter": {"type": "learning", "provenance": "agent", "tags": ["testing"]},
        "markdown": "# Run the migrations check\n\nRun `make migrations` before the PR.\n",
        "size": 96,
    }
    return BrainNote.model_validate(fields | overrides)


def a_learning_detail(**overrides: object) -> LearningDetail:
    """A proposed learning read with its inbox note."""
    fields: dict[str, object] = a_learning().model_dump() | {
        "target": LearningTarget(kind="team", path="brain/_inbox/testing-x.md"),
        "note_path": "brain/_inbox/testing-x.md",
        "state": LearningState.PROPOSED,
        "summary": "Run `make migrations` before the PR.",
        "note": a_brain_note(),
        "suggested_target": "learnings/",
        "target_choices": ("learnings/", "playbooks/"),
    }
    return LearningDetail.model_validate(fields | overrides)


def an_issue_summary(**overrides: object) -> IssueSummary:
    """Linear's summary of synthetic issue ``DEM-8``: in progress, blocked by ``DEM-7``."""
    fields: dict[str, object] = {
        "id": "DEM-8",
        "title": "Read the ticket summaries",
        "state": IssueState(name="In Progress", type="started"),
        "assignee": "Ada Example",
        "url": "https://linear.app/demo/issue/DEM-8",
        "priority": 2,
        "estimate": 3.0,
        "blocks": ("DEM-9",),
        "blocked_by": ("DEM-7",),
    }
    return IssueSummary.model_validate(fields | overrides)


def a_ticket_snapshot(**overrides: object) -> TicketSnapshot:
    """A read of ``DEM-8``, with ``DEM-404`` unknown and the done blocker ``DEM-7`` external."""
    fields: dict[str, object] = {
        "summaries": (an_issue_summary(),),
        "missing": ("DEM-404",),
        "external": (
            an_issue_summary(
                id="DEM-7",
                title="Add the collector",
                state=IssueState(name="Done", type="completed"),
                url="https://linear.app/demo/issue/DEM-7",
                blocks=(),
                blocked_by=(),
            ),
        ),
    }
    return TicketSnapshot.model_validate(fields | overrides)


def a_ticket_row(**overrides: object) -> TicketRow:
    """Ticket ``T2`` (``DEM-8``) of the synthetic feature: in progress, its blocker done."""
    fields: dict[str, object] = {
        "ref": "DEM-8",
        "key": "T2",
        "id": "DEM-8",
        "title": "Read the ticket summaries",
        "state": IssueState(name="In Progress", type="started"),
        "assignee": "Ada Example",
        "url": "https://linear.app/demo/issue/DEM-8",
        "priority": 2,
        "estimate": 3.0,
        "repo": "demo-api",
        "order": 2,
        "acs": ("AC-7.2", "AC-7.3"),
        "blocked_by": (TicketEdge(ref="DEM-7", source="both"),),
        "blocks": ("DEM-9",),
        "readiness": "can_start",
        "waiting_on": (),
        "reviewed": False,
    }
    return TicketRow.model_validate(fields | overrides)


def a_ticket_plan(**overrides: object) -> TicketPlan:
    """The planning of the synthetic feature's three tickets (``DEM-7`` done)."""
    fields: dict[str, object] = {
        "layers": (("DEM-8",), ("DEM-9",)),
        "can_start": ("DEM-8",),
        "order": ("DEM-8", "DEM-9"),
        "waiting": ("DEM-9",),
        "cycles": (),
        "external_blockers": (),
        "critical_path": ("DEM-8", "DEM-9"),
        "warnings": (),
    }
    return TicketPlan.model_validate(fields | overrides)


def a_feature_tickets(**overrides: object) -> FeatureTickets:
    """The tickets of the synthetic feature as Linear answered them: one done, one can start,
    one waiting."""
    done = a_ticket_row(
        ref="DEM-7",
        key="T1",
        id="DEM-7",
        title="Add the collector",
        state=IssueState(name="Done", type="completed"),
        url="https://linear.app/demo/issue/DEM-7",
        order=1,
        acs=("AC-7.1",),
        blocked_by=(),
        blocks=("DEM-8",),
        readiness="done",
        reviewed=True,
    )
    waiting = a_ticket_row(
        ref="DEM-9",
        key="T3",
        id="DEM-9",
        title="Show the planning view",
        state=IssueState(name="Todo", type="unstarted"),
        assignee=None,
        url="https://linear.app/demo/issue/DEM-9",
        priority=0,
        estimate=None,
        order=3,
        acs=("AC-7.4", "AC-7.5"),
        blocked_by=(TicketEdge(ref="DEM-8", source="plan"),),
        blocks=(),
        readiness="waiting",
        waiting_on=("DEM-8",),
    )
    fields: dict[str, object] = {
        "project": "demo",
        "slug": "demo-feature",
        "source": "linear",
        "stale": False,
        "as_of": LAST_ACTIVITY,
        "notice": None,
        "tracker_problem": None,
        "tickets": (done, a_ticket_row(), waiting),
        "planning": a_ticket_plan(),
        "golden_path": a_golden_path(),
        "sources_missing": ("github",),
    }
    return FeatureTickets.model_validate(fields | overrides)


def an_eval_record(**overrides: object) -> EvalRecord:
    """The SHIP eval of the synthetic feature's first delivery, ``evals/dem-7.md``."""
    fields: dict[str, object] = {
        "delivery": "dem-7",
        "path": "features/demo-feature/evals/dem-7.md",
        "verdict": "SHIP",
        "tickets": ("DEM-7",),
        "acs": ("AC-7.1",),
        "prs": ("demo-api#12",),
        "commit": "0a1b2c3",
        "evaluated_at": "2026-10-09",
        "legacy": False,
        "problem": None,
    }
    return EvalRecord.model_validate(fields | overrides)


AGENT_SESSION_ID = "01929a4e-7a11-7c00-8a00-00000000a001"
CLAUDE_SESSION_ID = "5091b986-0000-4000-8000-000000000001"
WORKDIR_ID = "3f2a9c1d4b5e6f70"
SUGGESTIONS = (
    PermissionSuggestion(
        index=0,
        destination="localSettings",
        rule={
            "type": "addRules",
            "rules": [{"toolName": "Bash", "ruleContent": "git status"}],
            "behavior": "allow",
            "destination": "localSettings",
        },
    ),
    PermissionSuggestion(
        index=1,
        destination="session",
        rule={"type": "setMode", "mode": "acceptEdits", "destination": "session"},
    ),
)

# The body of a record of each kind; synthetic text only.
RECORD_BODIES: dict[str, dict[str, JsonValue]] = {
    "init": {"session_id": CLAUDE_SESSION_ID, "model": "sonnet", "slash_commands": ["/feature"]},
    "text": {"block": 0, "text": "The tests pass."},
    "thinking": {"text": "Check the failing test first."},
    "tool.call": {
        "tool_use_id": "toolu_01",
        "name": "Edit",
        "input": {"file_path": "src/app.py", "old_string": "a = 1", "new_string": "a = 2"},
        "parent_tool_use_id": None,
    },
    "tool.result": {"tool_use_id": "toolu_01", "content": "edited", "is_error": False},
    "todos": {"items": [{"content": "Fix the test", "status": "in_progress", "active_form": None}]},
    "permission.request": {
        "request_id": "req-1",
        "tool": "Bash",
        "request_kind": "tool",
        "summary": "git status",
        "suggestions": [suggestion.model_dump(mode="json") for suggestion in SUGGESTIONS],
    },
    "result": {
        "subtype": "success",
        "terminal_reason": "completed",
        "cost_usd": "0.0012",
        "usage": {"input": 12, "output": 5, "cache_read": 0, "cache_write": 0},
        "model_usage": None,
        "duration_ms": 40,
        "num_turns": 1,
    },
    "error": {"message": "claude exited with code 1"},
    "exited": {"code": 0},
    "user.message": {"text": "Run the tests."},
    "permission.decision": {"request_id": "req-1", "decision": "allow"},
    "interrupt": {},
    "settings": {"mode": "plan"},
    "close": {},
    "log.truncated": {"cap": "records", "limit": 50000},
    "cloud.start": {"cloud_id": "cse_01synthetic"},
    "cloud.followup": {"cloud_id": "cse_01synthetic"},
}
RECORD_BY: dict[str, str | None] = {
    "user.message": "web",
    "permission.decision": "web",
    "interrupt": "web",
    "settings": "web",
    "close": "web",
    "log.truncated": "server",
    "cloud.start": "web",
    "cloud.followup": "web",
}


def an_agent_session(**overrides: object) -> AgentSession:
    """An idle local agent session of project ``demo`` in the hub's workdir."""
    fields: dict[str, object] = {
        "id": AGENT_SESSION_ID,
        "kind": "local",
        "project": "demo",
        "workdir_id": WORKDIR_ID,
        "workdir_label": "demo-hub",
        "claude_session_id": CLAUDE_SESSION_ID,
        "status": AgentSessionStatus.IDLE,
        "mode": "default",
        "model": "sonnet",
        "title": "Run the tests",
        "created_at": STARTED,
        "updated_at": LAST_ACTIVITY,
        "cost_usd": Decimal("0.0012"),
        "usage": TokenUsage(input=12, output=5, cache_read=0, cache_write=0),
        "last_seq": 4,
    }
    return AgentSession.model_validate(fields | overrides)


def a_log_record(kind: RecordKind = "text", seq: int = 1, **overrides: object) -> LogRecord:
    """A record of ``kind`` at ``seq`` with that kind's synthetic body."""
    body = RECORD_BODIES[kind]
    fields: dict[str, object] = {
        "seq": seq,
        "at": STARTED,
        "kind": kind,
        "by": RECORD_BY.get(kind, "driver"),
        "body": body,
        "text_bytes": len(str(body).encode()),
    }
    return LogRecord.model_validate(fields | overrides)


def a_permission_request(**overrides: object) -> PermissionRequest:
    """A ``Bash`` permission request with a ``localSettings`` and a ``session`` suggestion."""
    fields: dict[str, object] = {
        "request_id": "req-1",
        "tool": "Bash",
        "input": {"command": "git status", "description": "Show the working tree"},
        "suggestions": SUGGESTIONS,
        "request_kind": "tool",
    }
    return PermissionRequest.model_validate(fields | overrides)


def an_open_permission(**overrides: object) -> OpenPermission:
    """The open request a live session waits on, as ``GET /{id}`` shows it."""
    fields: dict[str, object] = {
        "request_id": "req-1",
        "tool": "Bash",
        "request_kind": "tool",
        "summary": "git status",
        "suggestions": SUGGESTIONS,
        "asked_at": LAST_ACTIVITY,
        "deadline_at": datetime(2026, 10, 9, 14, 15, 41, 882000, tzinfo=UTC),
    }
    return OpenPermission.model_validate(fields | overrides)


def a_workdir(**overrides: object) -> Workdir:
    """The hub's own folder, with one skill."""
    fields: dict[str, object] = {
        "workdir_id": WORKDIR_ID,
        "kind": "hub",
        "label": "demo-hub",
        "repo": None,
        "worktree": None,
        "skills": ("feature",),
    }
    return Workdir.model_validate(fields | overrides)


def a_cloud_session(**overrides: object) -> CloudSession:
    """A cloud start with its claude.ai/code link and teleport command."""
    fields: dict[str, object] = {
        "id": "01929a4e-7a11-7c00-8a00-00000000c001",
        "project": "demo",
        "workdir_id": WORKDIR_ID,
        "cloud_id": "cse_01synthetic",
        "url": "https://claude.ai/code/cse_01synthetic",
        "teleport_command": "claude --teleport cse_01synthetic",
        "title": "Upgrade the linter",
        "created_at": STARTED,
        "followups": 0,
    }
    return CloudSession.model_validate(fields | overrides)
