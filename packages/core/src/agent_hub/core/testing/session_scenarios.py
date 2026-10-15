"""Synthetic event scenarios for the fold tests: sessions, runs and learnings, made up end to end.

Payload keys follow the spec's "Payload kept" table and the mappers' field tables, so the folds
are tested against the shapes the collector writes. ``as_stored`` numbers events the way the
store does (append sequence from 1, a UUID per event); ``shuffled`` permutes them to prove a
fold does not depend on arrival order.
"""

import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from agent_hub.core.events.event import Event
from agent_hub.core.events.stored_event import StoredEvent
from agent_hub.core.json_form import JsonValue
from agent_hub.core.workflows.events import WorkflowEvents
from agent_hub.core.workflows.failures import FailureKind
from agent_hub.core.workflows.ports import RunEnd, RunStatus, SkipCause, StepEnd, StepStart

SCENARIO_START = datetime(2026, 10, 9, 14, 0, 0, tzinfo=UTC)
SCENARIO_MODEL = "claude-opus-5-5"
RUN_WORKFLOW = "issue-to-pr"
WORKFLOW_HASH = "sha256:" + "ab" * 32

type ToolUse = tuple[str, dict[str, JsonValue]]

DEFAULT_TOOLS: tuple[ToolUse, ...] = (
    ("Read", {"path": "src/app.py"}),
    ("Edit", {"path": "src/app.py", "lines_added": 3, "lines_removed": 1, "new_file": False}),
    ("Bash", {"command": "make check-fast"}),
)


def _event(**fields: object) -> Event:
    return Event.model_validate(fields)


def _stamp(at: datetime) -> str:
    return at.isoformat()


def a_session_events(
    session: str = "session-1",
    *,
    project: str = "demo",
    repo: str | None = "demo-api",
    start: datetime = SCENARIO_START,
    tools: Sequence[ToolUse] = DEFAULT_TOOLS,
    failed_tools: frozenset[int] = frozenset(),
    run: str | None = None,
    step: str | None = None,
    attempt: int | None = None,
    ended: bool = True,
    model: str = SCENARIO_MODEL,
    cwd: str = "/work/demo-api",
    git_branch: str | None = None,
    slash_commands: Sequence[str] = (),
) -> list[Event]:
    """Hook events of one session: start, a prompt, one call and result per tool, an end.

    Each event is one minute after the previous. ``failed_tools`` holds the positions in
    ``tools`` whose result is an error. ``run``/``step``/``attempt`` mimic a session started by
    ``hub run`` (the sensor's ``AGENT_HUB_RUN_*`` variables). ``slash_commands`` adds one user
    prompt per command after the first prompt; ``git_branch`` is put on every event, as the
    transcript mapper writes it on each event of a line.
    """
    common: dict[str, object] = {
        "project": project,
        "session": session,
        "source": "claude_code",
        "repo": repo,
        "agent": "main",
    }
    extra: dict[str, JsonValue] = {}
    if git_branch is not None:
        extra["git_branch"] = git_branch
    if run is not None:
        common |= {"workflow": RUN_WORKFLOW, "step": step}
        extra["run"] = run
        if attempt is not None:
            extra["attempt"] = attempt
    clock = iter(
        start + timedelta(minutes=n) for n in range(2 * len(tools) + len(slash_commands) + 3)
    )
    at = next(clock)
    events = [
        _event(
            **common,
            type="session.start",
            timestamp=at,
            source_id=f"{session}:SessionStart:{_stamp(at)}:0000000000000000",
            payload={"trigger": "startup", "cwd": cwd, "model": model} | extra,
        )
    ]
    at = next(clock)
    events.append(
        _event(
            **common,
            type="message",
            timestamp=at,
            source_id=f"{session}:UserPromptSubmit:{_stamp(at)}:0000000000000001",
            payload={"role": "user", "chars": 42} | extra,
        )
    )
    for command in slash_commands:
        at = next(clock)
        events.append(
            _event(
                **common,
                type="message",
                timestamp=at,
                source_id=f"{session}:UserPromptSubmit:{_stamp(at)}:0000000000000003",
                payload={"role": "user", "chars": 42, "slash_command": command} | extra,
            )
        )
    for position, (tool, metadata) in enumerate(tools):
        tool_use_id = f"toolu_{session}_{position}"
        at = next(clock)
        events.append(
            _event(
                **common,
                type="tool.call",
                timestamp=at,
                source_id=f"{session}:PreToolUse:{tool_use_id}",
                payload={"tool": tool, "tool_use_id": tool_use_id} | metadata | extra,
            )
        )
        failed = position in failed_tools
        hook = "PostToolUseFailure" if failed else "PostToolUse"
        result: dict[str, JsonValue] = {
            "tool": tool,
            "tool_use_id": tool_use_id,
            "status": "error" if failed else "ok",
            "duration_ms": 120,
        }
        if failed:
            result["error_line"] = "exit status 2"
        at = next(clock)
        events.append(
            _event(
                **common,
                type="tool.result",
                timestamp=at,
                source_id=f"{session}:{hook}:{tool_use_id}",
                payload=result | extra,
            )
        )
    if ended:
        at = next(clock)
        events.append(
            _event(
                **common,
                type="session.end",
                timestamp=at,
                source_id=f"{session}:SessionEnd:{_stamp(at)}:0000000000000002",
                payload={"end_reason": "prompt_input_exit", "outcome": "stopped"} | extra,
            )
        )
    return events


def an_agent_call(
    tool_use_id: str,
    *,
    session: str = "session-1",
    subagent_type: str = "Explore",
    description: str = "Find the session folds",
    at: datetime = SCENARIO_START,
    done_at: datetime | None = None,
) -> list[Event]:
    """The main agent's Agent tool call (and its result at ``done_at``, when given)."""
    common: dict[str, object] = {
        "project": "demo",
        "session": session,
        "source": "claude_code",
        "repo": "demo-api",
        "agent": "main",
    }
    events = [
        _event(
            **common,
            type="tool.call",
            timestamp=at,
            source_id=f"{session}:PreToolUse:{tool_use_id}",
            payload={
                "tool": "Agent",
                "tool_use_id": tool_use_id,
                "subagent_type": subagent_type,
                "description": description,
            },
        )
    ]
    if done_at is not None:
        events.append(
            _event(
                **common,
                type="tool.result",
                timestamp=done_at,
                source_id=f"{session}:PostToolUse:{tool_use_id}",
                payload={"tool": "Agent", "tool_use_id": tool_use_id, "status": "ok"},
            )
        )
    return events


def a_subagent_events(
    agent_id: str,
    *,
    session: str = "session-1",
    subagent_type: str = "Explore",
    start: datetime = SCENARIO_START,
    tools: Sequence[ToolUse] = (("Read", {"path": "src/app.py"}),),
    failed_tools: frozenset[int] = frozenset(),
) -> list[Event]:
    """Hook events of one subagent: a call and a result per tool, a minute apart from ``start``.

    The events carry the subagent's type as ``agent`` and its ``agent_id`` in the payload, as
    the hook mapper writes them.
    """
    common: dict[str, object] = {
        "project": "demo",
        "session": session,
        "source": "claude_code",
        "repo": "demo-api",
        "agent": subagent_type,
    }
    events: list[Event] = []
    for position, (tool, metadata) in enumerate(tools):
        tool_use_id = f"toolu_{agent_id}_{position}"
        call_at = start + timedelta(minutes=2 * position)
        events.append(
            _event(
                **common,
                type="tool.call",
                timestamp=call_at,
                source_id=f"{session}:PreToolUse:{tool_use_id}",
                payload={"tool": tool, "tool_use_id": tool_use_id, "agent_id": agent_id} | metadata,
            )
        )
        failed = position in failed_tools
        result: dict[str, JsonValue] = {
            "tool": tool,
            "tool_use_id": tool_use_id,
            "status": "error" if failed else "ok",
            "agent_id": agent_id,
        }
        if failed:
            result["error_line"] = "exit status 2"
        events.append(
            _event(
                **common,
                type="tool.result",
                timestamp=call_at + timedelta(minutes=1),
                source_id=f"{session}:PostToolUse:{tool_use_id}",
                payload=result,
            )
        )
    return events


def with_transcript_copies(events: Iterable[Event]) -> list[Event]:
    """``events`` plus a transcript copy of each tool call and result, a second later.

    The copies carry the same ``tool_use_id`` (the fact key) and a transcript ``source_id``.
    """
    result: list[Event] = []
    for position, event in enumerate(events):
        result.append(event)
        if event.type not in {"tool.call", "tool.result"}:
            continue
        payload = dict(event.payload) | {"turn": 1}
        result.append(
            event.model_copy(
                update={
                    "source": "transcript",
                    "source_id": f"{event.session}:uuid-{position:04d}:0",
                    "timestamp": event.timestamp + timedelta(seconds=1),
                    "payload": payload,
                }
            )
        )
    return result


def usage_events(
    session: str = "session-1",
    *,
    project: str = "demo",
    turns: Sequence[tuple[int, int, int, int]] = ((1000, 200, 0, 0),),
    model: str = SCENARIO_MODEL,
    start: datetime = SCENARIO_START,
    split_blocks: int = 1,
) -> list[Event]:
    """Transcript assistant messages carrying usage, one message id per turn.

    Each entry of ``turns`` is ``(input, output, cache_read, cache_write)`` tokens for turn
    ``n + 1``. ``split_blocks`` > 1 repeats the usage on several blocks of the same message id,
    as a transcript does when one API response is split per content block.
    """
    events: list[Event] = []
    for index, (input_tokens, output_tokens, cache_read, cache_write) in enumerate(turns):
        message_id = f"msg_{session}_{index + 1}"
        for block in range(split_blocks):
            at = start + timedelta(minutes=index, seconds=30 + block)
            events.append(
                _event(
                    project=project,
                    session=session,
                    type="message",
                    timestamp=at,
                    source="transcript",
                    source_id=f"{session}:uuid-usage-{index:04d}:{block}",
                    agent="main",
                    payload={
                        "role": "assistant",
                        "chars": 120,
                        "turn": index + 1,
                        "message_id": message_id,
                        "model": model,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "cache_read_tokens": cache_read,
                        "cache_write_tokens": cache_write,
                    },
                )
            )
    return events


def a_run_events(
    run: str = "1a2b3c4d",
    *,
    project: str = "demo",
    issue: str = "DEM-7",
    loops: int = 0,
    fails: bool = False,
    start: datetime = SCENARIO_START,
    cost_usd: float = 1.25,
) -> list[Event]:
    """Executor events of one ``hub run``: pick to pr, ``loops`` extra verify attempts.

    A loop is a verify failure followed by implement and verify again. With ``fails`` the last
    verify fails and the run ends ``failed`` in VERIFYING; otherwise it ends ``done``.
    """
    clock = iter(start + timedelta(minutes=n) for n in range(200))
    common: dict[str, object] = {
        "project": project,
        "session": f"run:{run}",
        "source": "executor",
        "repo": "demo-api",
        "workflow": RUN_WORKFLOW,
    }
    attempts: dict[str, int] = {}
    events: list[Event] = []

    def emit(type_: str, step: str | None, payload: dict[str, JsonValue]) -> None:
        at = next(clock)
        events.append(
            _event(
                **common,
                type=type_,
                step=step,
                timestamp=at,
                source_id=f"{run}:{payload.get('stage', 'REPORTED')}:{type_}:{_stamp(at)}:{type_}",
                payload={"run": run, "issue": issue} | payload,
            )
        )

    def stage(key: str, name: str, *, status: str = "ok", reason: str | None = None) -> None:
        attempts[key] = attempts.get(key, 0) + 1
        start_payload: dict[str, JsonValue] = {"stage": name, "attempt": attempts[key]}
        if key == "pick":
            start_payload |= {
                "mode": "live",
                "caps": {"budget": 10.0, "max_turns": 80, "model": "opus", "transport": "api"},
            }
        emit("step.start", key, start_payload)
        end_payload: dict[str, JsonValue] = {
            "stage": name,
            "attempt": attempts[key],
            "status": status,
        }
        if reason is not None:
            end_payload["reason"] = reason
        emit("step.end", key, end_payload)

    stage("pick", "PICKED")
    stage("worktree", "WORKTREE")
    stage("implement", "IMPLEMENTING")
    for _ in range(loops):
        stage("verify", "VERIFYING", status="failed", reason="check failed: make check")
        stage("implement", "IMPLEMENTING")
    if fails:
        stage("verify", "VERIFYING", status="failed", reason="check failed: make check")
        emit(
            "run.end",
            None,
            {
                "stage": "VERIFYING",
                "status": "failed",
                "reason": "check failed: make check",
                "cost_usd": cost_usd,
            },
        )
    else:
        stage("verify", "VERIFYING")
        stage("pr", "PR_OPEN")
        emit(
            "run.end",
            None,
            {
                "status": "done",
                "pr_url": "https://github.com/acme/demo-api/pull/7",
                "cost_usd": cost_usd,
            },
        )
    return events


@dataclass(frozen=True)
class NodeVisit:
    """One node attempt of an engine run; ``running`` has a start and no end, ``skipped`` the
    reverse."""

    node: str
    status: Literal["ok", "failed", "skipped", "running"] = "ok"
    failure_kind: FailureKind | None = None
    skip_cause: SkipCause | None = None
    origin: str | None = None


def a_workflow_run_events(  # noqa: PLR0913 -- one keyword per part of a run a test varies
    visits: Sequence[NodeVisit],
    *,
    run: str = "5e6f7a8b",
    workflow: str = "ship",
    project: str = "demo",
    status: RunStatus | None = None,
    outcome: JsonValue = None,
    end_index: int = 0,
    start: datetime = SCENARIO_START,
) -> list[Event]:
    """The events the workflow engine emits for ``visits``, a minute apart, then a ``run.end``
    when ``status`` is given (its ``reason`` the last failed node)."""
    recorder = WorkflowEvents(
        project=project,
        run_id=run,
        workflow=workflow,
        revision=3,
        content_hash=WORKFLOW_HASH,
        end_index=end_index,
        repo="demo-api",
    )
    attempts: dict[str, int] = {}
    failed: str | None = None
    for minute, visit in enumerate(visits):
        at = start + timedelta(minutes=minute)
        attempt = attempts[visit.node] = attempts.get(visit.node, 0) + 1
        if visit.status != "skipped":
            recorder.step_started(StepStart(visit.node, attempt, at))
        if visit.status != "running":
            failed = visit.node if visit.status == "failed" else failed
            ended = StepEnd(
                visit.node,
                attempt,
                visit.status,
                at + timedelta(seconds=30),
                failure_kind=visit.failure_kind,
                skip_cause=visit.skip_cause,
                origin=visit.origin,
            )
            recorder.step_ended(ended)
    if status is not None:
        at = start + timedelta(minutes=len(visits))
        recorder.run_ended(RunEnd(status, at, outcome=outcome, reason=failed))
    return recorder.events


def learning_events(
    proposal: str = "learning-1",
    *,
    project: str = "demo",
    session: str = "session-1",
    start: datetime = SCENARIO_START,
    decisions: Sequence[tuple[str, int]] = (),
) -> list[Event]:
    """A ``learning.proposed`` and its decisions: ``(type, minutes after the proposal)``."""
    events = [
        _event(
            project=project,
            session=session,
            type="learning.proposed",
            timestamp=start,
            source="transcript",
            source_id=f"{session}:{proposal}:proposed",
            agent="main",
            payload={
                "proposal": proposal,
                "text": "Run the migrations check before the PR",
                "target": "brain/learnings/gotchas/testing.md",
                "author": "main",
            },
        )
    ]
    for type_, minutes in decisions:
        payload: dict[str, JsonValue] = {"proposal": proposal, "author": "owner"}
        if type_ == "learning.rejected":
            payload["reason"] = "already documented"
        else:
            payload |= {"brain_path": "brain/learnings/gotchas/testing.md", "commit": "abc1234"}
        events.append(
            _event(
                project=project,
                session=session,
                type=type_,
                timestamp=start + timedelta(minutes=minutes),
                source="claude_code",
                source_id=f"{session}:{proposal}:{type_}:{minutes}",
                payload=payload,
            )
        )
    return events


def as_stored(events: Iterable[Event], *, first_seq: int = 1) -> list[StoredEvent]:
    """``events`` as the store would return them, numbered from ``first_seq`` in order.

    The ``event_id`` is a fixed UUID built from the sequence, so tests can name it.
    """
    return [
        StoredEvent(
            seq=seq,
            event_id=stored_event_id(seq),
            received_at=event.timestamp + timedelta(milliseconds=250),
            event=event,
        )
        for seq, event in enumerate(events, start=first_seq)
    ]


def stored_event_id(seq: int) -> str:
    """The ``event_id`` ``as_stored`` gives the event at ``seq``."""
    return f"00000000-0000-7000-8000-{seq:012x}"


def shuffled[T](items: Sequence[T], seed: int) -> list[T]:
    """A permutation of ``items``, the same for the same seed."""
    copied = list(items)
    random.Random(seed).shuffle(copied)  # noqa: S311 - a test permutation, not a secret
    return copied
