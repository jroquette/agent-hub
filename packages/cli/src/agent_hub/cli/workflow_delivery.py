"""The parent's side of the issue-to-pr workflow: ``hub run``'s tracker read, records and report.

``hub workflow run issue-to-pr --live`` is ``hub run`` as a graph (ADR 0032), so around the engine
it does what ``hub run`` does around its stages, with ``hub run``'s own code. Before the run: the
usage checks, the tracker key, the one issue read and the input brief (ADR 0026), then the
``picked`` record; the issue becomes the ``issue_text`` input. As nodes end, each stage's records
(``worktree_ready``, ``agent_finished`` per session, ``commits``, ``gate_ok``,
``title_unmatched``, ``pr_open`` or ``pr_exists``) go to ``.agent-runs/<date>.jsonl`` through
``RunLog``, so the retro, ``hub collect --runs`` and the events are ``hub run``'s; the engine's
node events are not sent for this workflow. After the run, ``LiveRun.finish`` makes ADR 0030's
tracker writes, the ``reported`` record and the inbox line from ``run.end``'s outcome (the
``report`` node's ``delivery``). A run that failed before ``report`` has no outcome: it failed at
the failed node's stage (``NODE_STAGES``), with that node's diagnosis. The exit is ``hub run``'s:
0 delivered or no changes, 3 blocked, 1 failed or a tracker write that failed.
"""

import contextlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import typer

from agent_hub.cli.errors import RunLogError
from agent_hub.cli.hub_config_reader import FILE_LABEL, load_hub_config_or_exit
from agent_hub.cli.run_children import RunOptions
from agent_hub.cli.run_command import begin_live_run, refuse_usage, run_setup
from agent_hub.cli.run_steps import (
    MAX_GATE_SHOWN_CHARS,
    MAX_LOGGED_REASON_CHARS,
    LiveRun,
    StageFailure,
)
from agent_hub.cli.workflow_executors import AGENT_EFFORT
from agent_hub.cli.workflow_runs import RecordedRun
from agent_hub.core.hub_config.model_tiers import RUN_TIER
from agent_hub.core.json_form import JsonValue
from agent_hub.core.runner.issue_block import issue_block
from agent_hub.core.runner.run_record import RunOutcome, Stage
from agent_hub.core.runner.verdict import SessionReply, session_outcome
from agent_hub.core.workflows.failures import RetryRecord
from agent_hub.core.workflows.nodes import AgentNode, Limits, LoopNode
from agent_hub.core.workflows.plan import WorkflowPlan
from agent_hub.core.workflows.ports import RunEnd, StepEnd, StepStart
from agent_hub.core.workflows.run_state import RunReport

# The workflow whose parent this is, named as the built-in names it (the smallest marker).
ISSUE_TO_PR: Final = "issue-to-pr"
ISSUE_TEXT: Final = "issue_text"
NODE_STAGES: Final[Mapping[str, Stage]] = {
    "worktree": Stage.WORKTREE,
    "implement": Stage.IMPLEMENTING,
    "commits": Stage.IMPLEMENTING,
    "verify": Stage.VERIFYING,
    "pr": Stage.PR_OPEN,
    "report": Stage.PR_OPEN,
}
_PREFIX: Final = "hub workflow run"
_IMPLEMENT: Final = "implement"
# A failed child's detail starts with "<program> exited <code>: "; a hub step's reason is its
# last stderr line, "hub step <name>: <reason>" (JSON-quoted when the reason held a line break).
_EXITED: Final = re.compile(r"^.+? exited -?[0-9]+: ?")
_STEP_LINE: Final = re.compile(r"^hub step [a-z]+: ")

type Output = Mapping[str, JsonValue]


def begin_delivery(
    context: typer.Context,
    hub: Path,
    *,
    plan: WorkflowPlan,
    inputs: Mapping[str, JsonValue],
    run_id: str,
) -> IssueToPr:
    """The checks, the issue read and the ``picked`` record, as ``hub run`` makes them."""
    hub_config = load_hub_config_or_exit(hub / FILE_LABEL)
    issue, repo = str(inputs["issue"]), str(inputs["repo"])
    refuse_usage(context, hub_config, issue=issue, repo=repo)
    children, client = run_setup(
        context, hub_config, hub=hub, issue=issue, repo=repo, command="workflow run"
    )
    # The session's caps as the picked record names them: the implement node's (its defaults
    # are hub run's), whatever a hub's own issue-to-pr holds.
    agents = (node for node in plan.document.nodes if isinstance(node, AgentNode | LoopNode))
    node = next((node for node in agents if node.id == _IMPLEMENT), None)
    limits, tier = (node.limits, node.model) if node is not None else (Limits(), RUN_TIER)
    options = RunOptions(
        live=True,
        max_turns=limits.max_turns,
        budget=limits.max_cost_usd,
        model=children.config.models.model_for(tier),
        start="implement",
        effort=AGENT_EFFORT,
    )
    return IssueToPr(begin_live_run(children, client, options=options, run_id=run_id))


@dataclass
class IssueToPr:
    """One issue-to-pr run's ``hub run`` side; ``replies`` is shared with the executors."""

    live: LiveRun
    replies: dict[str, SessionReply] = field(default_factory=dict)
    outputs: dict[str, Output] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)
    session: SessionReply | None = None
    log_error: RunLogError | None = None

    @property
    def issue_text(self) -> str:
        return issue_block(self.live.issue)

    def recorder(self, inner: RecordedRun) -> DeliveryRecorder:
        return DeliveryRecorder(self, inner)

    def started(self, node: str) -> None:
        if node in NODE_STAGES and node != "report":
            self.live.log.state = NODE_STAGES[node]

    def ended(self, end: StepEnd) -> None:
        if end.status == "failed":
            self.failed.setdefault(end.node, end.detail)
        try:
            if end.node == _IMPLEMENT and (reply := self.replies.pop(_IMPLEMENT, None)):
                self.session = reply
                self.live.record_session(reply)
            if end.status == "ok":
                output = end.output if isinstance(end.output, dict) else {}
                self.outputs[end.node] = output
                self._record(end.node, output)
        except RunLogError as error:
            self.log_error = self.log_error or error

    def finish(self, report: RunReport) -> int:
        """ADR 0030's writes, the ``reported`` record and the inbox line; the run's exit."""
        if self.log_error is not None:
            return self.live.stop_on_log_error(self.log_error)
        outcome, delivery = report.outcome, self.outputs.get("report", {})
        if outcome == RunOutcome.DELIVERED:
            pr = self.outputs.get("pr", {})
            self.live.pr_url, self.live.summary = _text(pr, "url"), _text(pr, "summary")
            return self.live.finish(None)
        if isinstance(outcome, str) and outcome in set(RunOutcome) and delivery:
            stage = _text(delivery, "stage")
            failure = StageFailure(
                Stage(stage) if stage in set(Stage) else Stage.PR_OPEN,
                _text(delivery, "reason"),
                RunOutcome(outcome),
                question=_text(delivery, "question"),
            )
            return self.live.finish(failure)
        node = report.reason if report.reason in self.failed else next(iter(self.failed), "")
        stage = NODE_STAGES.get(node, Stage.PR_OPEN)
        return self.live.finish(StageFailure(stage, self._reason(node)))

    def _record(self, node: str, output: Output) -> None:
        log, children = self.live.log, self.live.children
        if node == "worktree":
            log.record("worktree_ready", {"path": _text(output, "path")})
        elif node == "commits" and (subjects := output.get("subjects")):
            log.record("commits", {"commits": subjects})
        elif node == "verify":
            log.record("gate_ok", {"gate": children.gate[:80]})
        elif node == "pr":
            unmatched = output.get("title_unmatched")
            if isinstance(unmatched, str):
                pattern = children.conventions.commit_title
                log.record("title_unmatched", {"subject": unmatched, "pattern": pattern})
            event = "pr_exists" if output.get("found") is True else "pr_open"
            log.record(event, {"url": _text(output, "url")})

    def _reason(self, node: str) -> str:
        """The failed node's diagnosis, as ``hub run`` words its stage's failure."""
        detail = self.failed.get(node, "")
        if node == _IMPLEMENT and self.session is not None and self.session.is_error:
            return session_outcome(self.session).text
        if node == "verify":
            header = f"gate failed: {self.live.children.gate[:MAX_GATE_SHOWN_CHARS]}\n"
            output = _EXITED.sub("", detail, count=1)
            return header + output[-(MAX_LOGGED_REASON_CHARS - len(header)) :]
        lines = detail.splitlines() or [""]
        last = _EXITED.sub("", lines[-1], count=1) if len(lines) == 1 else lines[-1]
        if last.startswith('"'):
            with contextlib.suppress(ValueError):
                last = str(json.loads(last))
        return _STEP_LINE.sub("", last, count=1) or "the run ended without a delivery"


@dataclass
class DeliveryRecorder:
    """The run's ``RunRecorder``: the workflow's record first, then ``hub run``'s."""

    parent: IssueToPr
    inner: RecordedRun

    def step_started(self, start: StepStart) -> None:
        self.inner.step_started(start)
        self.parent.started(start.node)

    def step_ended(self, end: StepEnd) -> None:
        self.inner.step_ended(end)
        self.parent.ended(end)

    def retry_scheduled(self, node: str, retry: RetryRecord) -> None:
        self.inner.retry_scheduled(node, retry)

    def run_ended(self, end: RunEnd) -> None:
        self.inner.run_ended(end)


def _text(output: Output, key: str) -> str:
    value = output.get(key)
    return value if isinstance(value, str) else ""
