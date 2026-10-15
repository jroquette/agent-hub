"""The parent's side of the issue-to-pr workflow: ``hub run``'s tracker read, records and report.

``hub run --live`` runs ``issue-to-pr`` through the engine (AGH-224), and ``hub workflow run
issue-to-pr --live`` is the same run (ADR 0032), so around the engine this parent does what
v0.14's ``hub run`` did around its stages, with its code. Before the run: the
usage checks, the tracker key, the one issue read and the input brief (ADR 0026), then the
``picked`` record; the issue becomes the ``issue_text`` input. As nodes end, each stage's records
(``worktree_ready``, ``agent_finished`` per session, ``commits``, ``gate_ok``,
``title_unmatched``, ``pr_open`` or ``pr_exists``) go to ``.agent-runs/<date>.jsonl`` through
``RunLog``, so the retro, ``hub collect --runs`` and the events are ``hub run``'s; the engine's
node events are not sent for this workflow. After the run, ``LiveRun.finish`` makes ADR 0030's
tracker writes, the ``reported`` record and the inbox line from ``run.end``'s outcome (the
``report`` node's ``delivery``). A run that failed before ``report`` has no outcome: it failed at
the failed node's stage (``NODE_STAGES``), with that node's diagnosis (its last attempt's) and
failure kind (AGH-179, on the ``failed`` record and so on its ``step.end`` event). Its children
run as ``hub run``'s (``executor_options``): the ``hub step`` nodes in process, the others in the
caller's group, the ``implement`` node with the run's model, effort and caps; with the input
``start`` set to ``verify`` (``--from verify``) the session is skipped and recorded so. The
exit is ``hub run``'s: 0 delivered or no changes, 3 blocked, 1 failed or a tracker write that
failed; a record that cannot be written stops the run, naming what is left undone. The run's
folder and snapshot are made before the issue is read and removed if the read fails; such a
run is never resumed nor abandoned (``hub workflow run`` exits 2 for either).
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import typer

from agent_hub.cli import child_process
from agent_hub.cli.hub_config_reader import FILE_LABEL, load_hub_config_or_exit
from agent_hub.cli.run_children import RunOptions
from agent_hub.cli.run_command import RunStart, begin_live_run, refuse_usage, run_setup
from agent_hub.cli.run_steps import (
    MAX_GATE_SHOWN_CHARS,
    MAX_LOGGED_REASON_CHARS,
    LiveRun,
    StageFailure,
)
from agent_hub.cli.step_command import run_in_process
from agent_hub.cli.workflow_executors import AGENT_EFFORT
from agent_hub.cli.workflow_runs import RecordedRun
from agent_hub.core.hub_config.model import HubConfig
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
START: Final = "start"
DELIVERY_INPUTS: Final = frozenset({"issue", "repo", ISSUE_TEXT})
NODE_STAGES: Final[Mapping[str, Stage]] = {
    "worktree": Stage.WORKTREE,
    "implement": Stage.IMPLEMENTING,
    "verdict": Stage.IMPLEMENTING,
    "commits": Stage.IMPLEMENTING,
    "verify": Stage.VERIFYING,
    "pr": Stage.PR_OPEN,
    "report": Stage.PR_OPEN,
}
_IMPLEMENT: Final = "implement"
_PREFIX: Final = "hub workflow run"
# A failed child's detail starts with "<program> exited <code>: " (an in-process hub step's is
# its reason, as written).
_EXITED: Final = re.compile(r"^.+? exited -?[0-9]+: ?")

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
    start = RunStart.VERIFY if inputs.get(START) == RunStart.VERIFY else RunStart.IMPLEMENT
    options = session_options(plan, children.config, start=start, given={})
    live = begin_live_run(children, client, options=options, run_id=run_id)
    return IssueToPr(live, prefix=_PREFIX)


def session_options(
    plan: WorkflowPlan, config: HubConfig, *, start: RunStart, given: Mapping[str, Any]
) -> RunOptions:
    """The implementing session's caps, as the picked record names them and the ``implement``
    node runs with: each of ``given`` (``hub run``'s flags typed on its command line), else the
    node's own (whose defaults are ``hub run``'s), whatever a hub's own issue-to-pr holds."""
    agents = (node for node in plan.document.nodes if isinstance(node, AgentNode | LoopNode))
    node = next((node for node in agents if node.id == _IMPLEMENT), None)
    limits, tier = (node.limits, node.model) if node is not None else (Limits(), RUN_TIER)
    return RunOptions(
        live=True,
        max_turns=given.get("max_turns", limits.max_turns),
        budget=given.get("budget", limits.max_cost_usd),
        model=given.get("model", config.models.model_for(tier)),
        start=start,
        effort=given.get("effort", AGENT_EFFORT),
    )


def delivery_problem(plan: WorkflowPlan, *, start: str = RunStart.IMPLEMENT) -> str | None:
    """Why the parent cannot run ``plan`` (a hub's own issue-to-pr may lack an input it fills)."""
    declared = set(plan.document.inputs)
    if not declared >= DELIVERY_INPUTS:
        return f"{ISSUE_TO_PR} must declare the inputs issue, repo and {ISSUE_TEXT}"
    if start == RunStart.VERIFY and START not in declared:
        return f"--from verify needs the input {START} in {ISSUE_TO_PR}"
    return None


@dataclass
class IssueToPr:
    """One issue-to-pr run's ``hub run`` side; ``replies`` is shared with the executors."""

    live: LiveRun
    # The command a warning names: the entry point's.
    prefix: str = "hub run"
    replies: dict[str, SessionReply] = field(default_factory=dict)
    outputs: dict[str, Output] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)
    kinds: dict[str, str | None] = field(default_factory=dict)
    session: SessionReply | None = None

    @property
    def issue_text(self) -> str:
        return issue_block(self.live.issue)

    def recorder(self, inner: RecordedRun | None) -> DeliveryRecorder:
        return DeliveryRecorder(self, inner)

    def executor_options(self) -> dict[str, Any]:
        """``WorkflowExecutors``' options for a run with ``hub run``'s children and caps; the
        child is looked up now, not at import (the tests spy on ``run_child``)."""
        return {
            "replies": self.replies,
            "hub_steps": self._step,
            "in_session": False,
            "session": self.live.options,
            "child": child_process.run_child,
        }

    def _step(self, arguments: Sequence[str], stdin: bytes) -> str:
        return run_in_process(arguments, stdin=stdin, echo=typer.echo, prefix=self.prefix)

    def started(self, node: str) -> None:
        if node in NODE_STAGES and node != "report":
            self.live.log.state = NODE_STAGES[node]

    def ended(self, end: StepEnd) -> None:
        """Record the stage as ``hub run`` does; a ``RunLogError`` stops the run, as there."""
        if end.status == "failed":
            # The last failed attempt's detail and kind, under the node that failed first.
            self.failed[end.node] = end.detail
            self.kinds[end.node] = end.failure_kind
        if end.node == _IMPLEMENT and end.status == "skipped" and self._from_verify:
            self.live.log.state = Stage.IMPLEMENTING
            self.live.log.record("skip_implement", {"reason": "--from verify"})
        if end.node == _IMPLEMENT and (reply := self.replies.pop(_IMPLEMENT, None)):
            self.session = reply
            self.live.record_session(reply)
        if end.status == "ok":
            output = end.output if isinstance(end.output, dict) else {}
            self.outputs[end.node] = output
            self._record(end.node, output)

    def finish(self, report: RunReport) -> int:
        """ADR 0030's writes, the ``reported`` record and the inbox line; the run's exit."""
        outcome, delivery = report.outcome, self.outputs.get("report", {})
        if outcome == RunOutcome.DELIVERED:
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
        kind = self.kinds.get(node)
        return self.live.finish(StageFailure(stage, self._reason(node), failure_kind=kind))

    @property
    def _from_verify(self) -> bool:
        return self.live.options.start == RunStart.VERIFY

    def _record(self, node: str, output: Output) -> None:
        log, children = self.live.log, self.live.children
        if node == "worktree":
            log.record("worktree_ready", {"path": _text(output, "path")})
        elif node == "commits" and (subjects := output.get("subjects")):
            log.record("commits", {"commits": subjects})
        elif node == "verify":
            log.record("gate_ok", {"gate": children.gate[:80]})
        elif node == "pr":
            # The PR is open: a record that fails from here on names it and the writes left.
            self.live.pr_url, self.live.summary = _text(output, "url"), _text(output, "summary")
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
        if node == "verify" and self.kinds.get(node) == "exec_failed":
            header = f"gate failed: {self.live.children.gate[:MAX_GATE_SHOWN_CHARS]}\n"
            output = _EXITED.sub("", detail, count=1)
            return header + output[-(MAX_LOGGED_REASON_CHARS - len(header)) :]
        return detail or "the run ended without a delivery"


@dataclass
class DeliveryRecorder:
    """The run's ``RunRecorder``: the workflow's record first, then ``hub run``'s."""

    parent: IssueToPr
    # None for hub run's own run: its RunLog records are its only record.
    inner: RecordedRun | None

    def step_started(self, start: StepStart) -> None:
        if self.inner is not None:
            self.inner.step_started(start)
        self.parent.started(start.node)

    def step_ended(self, end: StepEnd) -> None:
        if self.inner is not None:
            self.inner.step_ended(end)
        self.parent.ended(end)

    def retry_scheduled(self, node: str, retry: RetryRecord) -> None:
        if self.inner is not None:
            self.inner.retry_scheduled(node, retry)

    def run_ended(self, end: RunEnd) -> None:
        if self.inner is not None:
            self.inner.run_ended(end)


def _text(output: Output, key: str) -> str:
    value = output.get(key)
    return value if isinstance(value, str) else ""
