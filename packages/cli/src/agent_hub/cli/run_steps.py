"""The report of a live ``hub run``: its run state, ADR 0030's tracker writes, its records and exit.

The stages themselves are the ``issue-to-pr`` workflow's nodes, run through the engine
(``workflow_delivery``, AGH-224); this module keeps what they share with v0.14's stage machine:
the timeouts and output caps (read at call time by ``ship_steps``, ``step_command`` and
``workflow_executors``, where the tests patch them), the worktree's git runner, and ``LiveRun``,
which records the session and reports the run.

    PICKED -> WORKTREE -> IMPLEMENTING -> VERIFYING -> PR_OPEN -> REPORTED
    any stage can end in FAILED(stage, reason) -> REPORTED (failed label and diagnosis)

A run's outcome (AGH-140) is ``delivered`` with its PR, ``failed``, or one of two ends that are
not failures: ``no_changes`` (no commit on the branch) and ``blocked`` (the session stopped and
asked for a human). Those record ``not_delivered`` instead of ``failed`` and get a report of
their own (ADR 0030): ``no_changes`` a comment and no label, exit 0; ``blocked`` the blocked
label (``tracker.blocked_label``, else the failed label) and a comment with the session's
question, exit ``BLOCKED_EXIT`` (3). Every outcome but ``failed`` removes the outcome labels the
issue carries; a tracker write that fails makes the exit 1 whatever the outcome. A ``failed``
record names its stage, reason and, from the failed node, its ``failure_kind`` (AGH-179).

Residual risk: the implementing session and the gate run code as the user. Without the tokens
in their environment they can still read what the user's account can, such as gh's stored
token or the user's global git config, and change it. Only a sandbox closes that (the sandbox
follow-up, AGH-42); until then the guard checks the repo-side config right before each
token-bearing call (the fetch, the push). A process the session or the gate left running could
still change the config between that check and the call (a time-of-check gap, also AGH-42).
"""

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import typer

from agent_hub.cli.child_process import ChildResult, run_child
from agent_hub.cli.command_exits import FAILURE
from agent_hub.cli.errors import RunLogError
from agent_hub.cli.init_report import shown_text
from agent_hub.cli.run_children import (
    RunChildren,
    RunOptions,
)
from agent_hub.cli.run_log import RunLog
from agent_hub.cli.run_report import apply_writes
from agent_hub.core.json_form import JsonValue
from agent_hub.core.runner.report_writes import (
    TrackerWrite,
    blocked_writes,
    call_line,
    failure_writes,
    no_changes_writes,
    success_writes,
)
from agent_hub.core.runner.run_record import (
    NOT_DELIVERED,
    RunOutcome,
    Stage,
    not_delivered_data,
    reported_data,
)
from agent_hub.core.runner.run_texts import (
    blocked_comment,
    failure_comment,
    inbox_line,
    no_changes_comment,
    success_comment,
)
from agent_hub.core.runner.verdict import (
    Outcome,
    SessionReply,
    last_json_line,
    session_outcome,
)
from agent_hub.core.tracker.tracker_client import Issue, TrackerClient

WORKTREE_GIT_TIMEOUT: Final = 1_800.0
SESSION_TIMEOUT: Final = 3_600.0
GATE_TIMEOUT: Final = 1_800.0
PUSH_TIMEOUT: Final = 300.0
GH_TIMEOUT: Final = 120.0
GIT_TIMEOUT: Final = 120.0
MAX_LOGGED_REASON_CHARS: Final = 1_500
# The exit of a run whose session stopped for a human and whose report was made (ADR 0030);
# 0 is delivered or no changes, 1 (``FAILURE``) a failure or a report that failed.
BLOCKED_EXIT: Final = 3
MAX_GATE_SHOWN_CHARS: Final = 200
# The most of a child's output kept (its last bytes): the gate's and git's, and the session's,
# whose whole JSON result must fit.
CHILD_OUTPUT_LIMIT: Final = 64 * 1024
SESSION_OUTPUT_LIMIT: Final = 1 << 20
_PREFIX = "hub run"
# Given to the token-bearing fetch as its own -c, like the push's.
HOOKS_OFF: Final = ("-c", f"core.hooksPath={os.devnull}", "-c", "core.fsmonitor=false")


class StageFailure(Exception):  # noqa: N818 - a stage's outcome, read as "the stage failed"
    """A stage ended the run: the stage, why, and the run's outcome (``failed`` unless the run
    ended without a PR yet without failing); ``question`` is what a blocked session asked,
    ``failure_kind`` the failed node's kind (AGH-179), recorded on ``failed``."""

    def __init__(
        self,
        stage: Stage,
        reason: str,
        outcome: RunOutcome = RunOutcome.FAILED,
        *,
        question: str = "",
        failure_kind: str | None = None,
    ) -> None:
        super().__init__(reason)
        self.stage = stage
        self.reason = reason
        self.outcome = outcome
        self.question = question
        self.failure_kind = failure_kind


@dataclass(kw_only=True, slots=True)
class LiveRun:
    """One live run's state: what it was given and what it learned on the way."""

    children: RunChildren
    options: RunOptions
    issue: Issue
    client: TrackerClient
    log: RunLog
    cost_usd: float = 0.0
    summary: str = ""
    pr_url: str = ""
    # The report's writes not made yet; None until the report starts.
    pending: tuple[TrackerWrite, ...] | None = None

    def finish(self, failure: StageFailure | None) -> int:
        """Report the run its stages (the issue-to-pr workflow's nodes) made: delivered with
        ``pr_url`` and ``summary`` set, else ``failure``; its exit.

        A record that cannot be written stops the run: what is left undone is named.
        """
        try:
            return self._report_success() if failure is None else self._report_failure(failure)
        except RunLogError as error:
            return self.stop_on_log_error(error)

    def record_session(self, reply: SessionReply) -> Outcome:
        """Count the session's cost and record ``agent_finished``; its outcome."""
        self.cost_usd += reply.cost_usd
        # The old runner's event and fields (the retro contract, AC-27.21 "as today").
        verdict: JsonValue = json.loads(json.dumps(last_json_line(reply.result)))
        self.log.record(
            "agent_finished",
            {
                "cost_usd": round(self.cost_usd, 4),
                "turns": reply.turns,
                "subtype": reply.subtype,
                "verdict": verdict,
            },
        )
        return session_outcome(reply)

    # report

    def _success_writes(self) -> tuple[TrackerWrite, ...]:
        comment = success_comment(
            run_id=self.log.run_id,
            pr_url=self.pr_url,
            summary=self.summary,
            workspace=self._workspace,
        )
        return success_writes(
            self.issue,
            review_state=self.children.config.tracker.states.review,
            failed_label=self.children.config.tracker.failed_label,
            blocked_label=self.children.config.tracker.effective_blocked_label,
            comment=comment,
        )

    def _report_success(self) -> int:
        made = self._report(
            self._success_writes(), failed_stage=None, run_outcome=RunOutcome.DELIVERED
        )
        outcome = f"PR {self.pr_url}" if made else f"PR {self.pr_url}; report failed"
        self._inbox(outcome)
        return 0 if made else FAILURE

    def _report_failure(self, failure: StageFailure) -> int:
        self.log.state = failure.stage
        reason = failure.reason[:MAX_LOGGED_REASON_CHARS]
        is_failed = failure.outcome not in NOT_DELIVERED
        if is_failed:
            data: dict[str, JsonValue] = {"stage": failure.stage.value, "reason": reason}
            if failure.failure_kind is not None:
                data["failure_kind"] = failure.failure_kind
            self.log.record("failed", data)
            ended = "FAILED"
        else:
            data = not_delivered_data(outcome=failure.outcome, stage=failure.stage, reason=reason)
            self.log.record("not_delivered", data)
            ended = f"NOT DELIVERED ({failure.outcome})"
        typer.echo(f"{ended} at {failure.stage}: {shown_text(failure.reason)}", err=True)
        writes, exit_code = self._outcome_report(failure)
        if is_failed:
            self.log.state = Stage.FAILED
        made = self._report(
            writes,
            failed_stage=failure.stage if is_failed else None,
            run_outcome=failure.outcome,
        )
        self._inbox(f"{ended} at {failure.stage}")
        return exit_code if made else FAILURE

    def _outcome_report(self, failure: StageFailure) -> tuple[tuple[TrackerWrite, ...], int]:
        """The tracker writes of a run that ended without a PR, and its exit once they are made
        (ADR 0030)."""
        tracker = self.children.config.tracker
        failed, blocked = tracker.failed_label, tracker.effective_blocked_label
        run_id, stage, workspace = self.log.run_id, failure.stage.value, self._workspace
        if failure.outcome is RunOutcome.NO_CHANGES:
            comment = no_changes_comment(
                run_id=run_id, stage=stage, reason=failure.reason, workspace=workspace
            )
            writes = no_changes_writes(
                self.issue, failed_label=failed, blocked_label=blocked, comment=comment
            )
            return writes, 0
        if failure.outcome is RunOutcome.BLOCKED:
            comment = blocked_comment(
                run_id=run_id, stage=stage, question=failure.question, workspace=workspace
            )
            writes = blocked_writes(
                self.issue, failed_label=failed, blocked_label=blocked, comment=comment
            )
            return writes, BLOCKED_EXIT
        comment = failure_comment(
            run_id=run_id, stage=stage, reason=failure.reason, workspace=workspace
        )
        return failure_writes(issue_id=self.issue.id, failed_label=failed, comment=comment), FAILURE

    def _report(
        self, writes: Sequence[TrackerWrite], *, failed_stage: Stage | None, run_outcome: RunOutcome
    ) -> bool:
        """Make the writes; on a tracker failure name the PR and the writes not made."""
        self.pending = tuple(writes)
        outcome = apply_writes(self.client, writes)
        self.cost_usd += outcome.cost_usd
        self.pending = tuple(writes[outcome.done :])
        if outcome.error is not None:
            typer.echo(f"{_PREFIX}: {shown_text(str(outcome.error))}", err=True)
            if self.pr_url:
                typer.echo(f"{_PREFIX}: the PR is open: {self.pr_url}", err=True)
            for write in writes[outcome.done :]:
                typer.echo(f"not done: {shown_text(call_line(write))}", err=True)
        self.log.state = Stage.REPORTED
        data: dict[str, JsonValue] = reported_data(
            ok=outcome.error is None,
            failed_stage=failed_stage,
            total_cost_usd=round(self.cost_usd, 4),
            pr=self.pr_url,
            outcome=run_outcome,
        )
        self.log.record("reported", data)
        return outcome.error is None

    def _inbox(self, outcome: str) -> None:
        self.log.inbox(
            inbox_line(
                issue_id=self.issue.id,
                repo=self.children.repo,
                run_id=self.log.run_id,
                outcome=outcome,
                cost_usd=self.cost_usd,
            )
        )

    @property
    def _workspace(self) -> str:
        return str(self.children.workspace)

    def stop_on_log_error(self, error: RunLogError) -> int:
        """Name the open PR and the report's writes not made; the tracker is left as it is."""
        typer.echo(f"{_PREFIX}: {error}", err=True)
        pending = self.pending
        if self.pr_url:
            typer.echo(f"{_PREFIX}: the PR is open: {self.pr_url}", err=True)
            if pending is None:
                pending = self._success_writes()
        for write in pending or ():
            typer.echo(f"not done: {shown_text(call_line(write))}", err=True)
        return FAILURE


def bounded_child(
    argv: Sequence[str],
    *,
    cwd: Path | str,
    env: Mapping[str, str],
    timeout: float | None,
    own_session: bool | None = None,
) -> ChildResult:
    """``run_child`` keeping the last ``CHILD_OUTPUT_LIMIT`` bytes of each stream."""
    return run_child(
        argv,
        cwd=cwd,
        env=env,
        timeout=timeout,
        own_session=own_session,
        output_limit=CHILD_OUTPUT_LIMIT,
    )
