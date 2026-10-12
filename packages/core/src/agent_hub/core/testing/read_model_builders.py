"""Builders of synthetic read models for API and screen tests; every value is made up."""

from datetime import UTC, datetime
from decimal import Decimal

from agent_hub.core.approvals.approval import Approval, ApprovalKind
from agent_hub.core.brain.brain_note import BrainEntry, BrainNote, BrainTree
from agent_hub.core.features.feature_view import AcCounts, FeatureView
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
        "sources_missing": ("github",),
    }
    return FeatureView.model_validate(fields | overrides)


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
