"""The live stages of ``hub run``: worktree, implementing session, gate, PR, then the report.

    PICKED -> WORKTREE -> IMPLEMENTING -> VERIFYING -> PR_OPEN -> REPORTED
    any stage can end in FAILED(stage, reason) -> REPORTED (failed label and diagnosis)

Each stage raises ``StageFailure`` naming itself and the reason; the report then runs through
the tracker port. The worktree is made in process with ``hub worktree``'s steps (D7, E18), each
git call capped at ``WORKTREE_GIT_TIMEOUT``. Every child runs in the caller's process group
(``own_session=False``) with the environments of ``run_children``: none holds
``LINEAR_API_KEY`` (D10). A timeout kills the timed-out child alone; its own children are left
to the caller's group kill (the residual of E6). The session's verdict is a hint: the commits on
the branch and the command's own gate decide (the old runner's rule).

Residual risk: the implementing session and the gate run code as the user. Without the tokens
in their environment they can still read what the user's account can, such as gh's stored
token or the user's global git config, and change it. Only a sandbox closes that (the sandbox
follow-up, AGH-42); until then the guard checks the repo-side config right before each
token-bearing call (the fetch, the push). A process the session or the gate left running could
still change the config between that check and the call (a time-of-check gap, also AGH-42).
"""

import json
import os
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import typer

from agent_hub.cli.child_process import ChildResult, run_child
from agent_hub.cli.command_exits import FAILURE
from agent_hub.cli.errors import ChildTimedOutError, RunLogError, WorktreeError
from agent_hub.cli.init_report import shown_text
from agent_hub.cli.push_guard import REMOTE_URL, names_github_repo, parse_scoped_list, risky_keys
from agent_hub.cli.run_children import (
    RunChildren,
    RunOptions,
    push_env,
    session_env,
    untrusted_env,
)
from agent_hub.cli.run_log import RunLog
from agent_hub.cli.run_report import apply_writes
from agent_hub.cli.worktree_steps import check_branches, create_worktree, worktree_task
from agent_hub.core.json_form import JsonValue
from agent_hub.core.runner.report_writes import (
    REVIEW_STATE,
    TrackerWrite,
    call_line,
    failure_writes,
    success_writes,
)
from agent_hub.core.runner.run_record import Stage, reported_data
from agent_hub.core.runner.run_texts import (
    commit_summary,
    failure_comment,
    inbox_line,
    pr_body,
    pr_title,
    success_comment,
)
from agent_hub.core.runner.verdict import (
    OutcomeKind,
    last_json_line,
    parse_session_output,
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
MAX_GATE_SHOWN_CHARS: Final = 200
MAX_ERROR_TAIL_CHARS: Final = 500
MAX_PR_URL_CHARS: Final = 2_048
# The most of a child's output kept (its last bytes): the gate's and git's, and the session's,
# whose whole JSON result must fit.
CHILD_OUTPUT_LIMIT: Final = 64 * 1024
SESSION_OUTPUT_LIMIT: Final = 1 << 20
_URL_SCHEME = "https://"
_PREFIX = "hub run"
# Given to the token-bearing fetch as its own -c, like the push's.
_HOOKS_OFF = ("-c", f"core.hooksPath={os.devnull}", "-c", "core.fsmonitor=false")


class StageFailure(Exception):  # noqa: N818 - a stage's outcome, read as "the stage failed"
    """A stage ended the run: the stage and why."""

    def __init__(self, stage: Stage, reason: str) -> None:
        super().__init__(reason)
        self.stage = stage
        self.reason = reason


@dataclass(kw_only=True, slots=True)
class LiveRun:
    """One live run's state: what it was given and what it learned on the way."""

    children: RunChildren
    options: RunOptions
    issue: Issue
    client: TrackerClient
    log: RunLog
    environ: Mapping[str, str]
    cost_usd: float = 0.0
    summary: str = ""
    pr_url: str = ""
    worktree: Path = field(init=False)
    # The report's writes not made yet; None until the report starts.
    pending: tuple[TrackerWrite, ...] | None = None

    def __post_init__(self) -> None:
        self.worktree = self.children.worktree

    def run(self) -> int:
        """Run every stage, then report; 0 when the PR opened and the report was made.

        A record that cannot be written stops the run: what is left undone is named.
        """
        try:
            return self._run_stages()
        except RunLogError as error:
            return self._stop_on_log_error(error)

    def _run_stages(self) -> int:
        try:
            self._make_worktree()
            self._implement()
            self._verify()
            self._open_pr()
        except StageFailure as failure:
            return self._report_failure(failure)
        return self._report_success()

    # stages

    def _make_worktree(self) -> None:
        self._enter(Stage.WORKTREE)
        git = shutil.which("git", path=self.environ.get("PATH", ""))
        if git is None:
            raise StageFailure(Stage.WORKTREE, "git is not on PATH; install git")
        git = os.path.abspath(git)
        if os.path.lexists(self.children.repo_path / ".git"):
            # The fetch is the run's first call with the GitHub tokens: the clone's config is
            # checked first (a missing clone is the worktree step's own error).
            self._refuse_risky_config(
                stage=Stage.WORKTREE,
                cwd=self.children.repo_path,
                use="a fetch would use",
                outcome="nothing was fetched",
            )
        try:
            task = worktree_task(
                self.children.config,
                name=self.children.slug,
                branch_prefix=self.children.branch_prefix,
                only=self.children.repo,
                hub=self.children.hub,
                git=git,
                # Only the fetch may need the GitHub tokens, and it runs as the push does: hooks
                # and fsmonitor off (a hook planted in the clone would see the tokens). The add
                # and the repo's setup script run without them, every hook off for the add.
                env=untrusted_env(self.environ),
                fetch_env=push_env(self.environ),
                fetch_options=_HOOKS_OFF,
                add_options=("-c", f"core.hooksPath={os.devnull}"),
                git_timeout=WORKTREE_GIT_TIMEOUT,
                runner=_bounded_child,
            )
            check_branches(task)
            self.worktree = create_worktree(task, self.children.repo, echo=typer.echo)
        except (WorktreeError, ChildTimedOutError) as error:
            raise StageFailure(Stage.WORKTREE, str(error).replace(git, "git")) from None
        except OSError as error:
            reason = f"git could not run: {error.strerror or error}"
            raise StageFailure(Stage.WORKTREE, reason) from None
        self.log.record("worktree_ready", {"path": str(self.worktree)})

    def _implement(self) -> None:
        self._enter(Stage.IMPLEMENTING)
        if self.options.start == "verify":
            self.log.record("skip_implement", {"reason": "--from verify"})
        else:
            self._run_session()
        commits = self._git_output("log", "--format=%s", f"{self.children.base}..HEAD")
        subjects = [line for line in commits.splitlines() if line]
        if not subjects:
            reason = "no commit on the branch (the session reported done or gave no verdict)"
            raise StageFailure(Stage.IMPLEMENTING, reason)
        if not self.summary:
            messages = self._git_output("log", "--format=%B", f"{self.children.base}..HEAD")
            self.summary = commit_summary(messages, workspace=self._workspace)
        self.log.record("commits", {"commits": list(subjects)})

    def _run_session(self) -> None:
        env = session_env(
            self.environ,
            repo=self.children.repo,
            issue_id=self.issue.id,
            run_id=self.log.run_id,
        )
        argv = self.children.session_argv(self.issue, self.options)
        result = self._child(
            argv, env=env, timeout=SESSION_TIMEOUT, output_limit=SESSION_OUTPUT_LIMIT
        )
        reply = parse_session_output(result.stdout.decode(errors="replace"))
        self.cost_usd += reply.cost_usd
        outcome = session_outcome(reply)
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
        if outcome.kind is not OutcomeKind.DONE:
            raise StageFailure(Stage.IMPLEMENTING, outcome.text)
        self.summary = outcome.text

    def _verify(self) -> None:
        self._enter(Stage.VERIFYING)
        # The gate checks what the PR will hold: the commits, no tracked change beside them
        # (untracked files never reach the PR; owner decision, 2026-10-02).
        if self._git_output("status", "--porcelain", "--untracked-files=no").strip():
            raise StageFailure(Stage.VERIFYING, "uncommitted changes in the worktree")
        gate = self.children.gate
        result = self._child(
            self.children.gate_argv(), env=untrusted_env(self.environ), timeout=GATE_TIMEOUT
        )
        if result.returncode != 0:
            output = (result.stdout + result.stderr).decode(errors="replace")
            # The output's end says why; with the header the reason fits the logged length.
            header = f"gate failed: {gate[:MAX_GATE_SHOWN_CHARS]}\n"
            reason = header + output[-(MAX_LOGGED_REASON_CHARS - len(header)) :]
            raise StageFailure(Stage.VERIFYING, reason)
        self.log.record("gate_ok", {"gate": gate[:80]})

    def _open_pr(self) -> None:
        self._enter(Stage.PR_OPEN)
        self._refuse_risky_config(
            stage=Stage.PR_OPEN,
            cwd=self.worktree,
            use="a push would use",
            outcome="the branch was not pushed",
        )
        env = push_env(self.environ)
        pushed = self._child(self.children.push_argv(), env=env, timeout=PUSH_TIMEOUT)
        if pushed.returncode != 0:
            raise StageFailure(Stage.PR_OPEN, f"push failed: {_tail(pushed.stderr)}")
        title = pr_title(
            self._git_output("log", "-1", "--format=%s"),
            workspace=self._workspace,
            fallback=self.issue.id,
        )
        body = pr_body(
            issue_id=self.issue.id,
            summary=self.summary,
            gate=self.children.gate,
            workspace=self._workspace,
        )
        created = self._child(
            self.children.pr_argv(title=title, body=body), env=env, timeout=GH_TIMEOUT
        )
        if created.returncode != 0:
            # A rerun: the branch's PR is already open, and the push updated it.
            existing = self._open_pr_url(env)
            if existing is None:
                reason = f"gh pr create failed: {_tail(created.stderr)}"
                raise StageFailure(Stage.PR_OPEN, reason)
            self.pr_url = existing
            self.log.record("pr_exists", {"url": existing})
            return
        url = _pr_url(created.stdout)
        if url is None:
            raise StageFailure(Stage.PR_OPEN, "gh printed no PR url")
        self.pr_url = url
        self.log.record("pr_open", {"url": url})

    def _refuse_risky_config(self, *, stage: Stage, cwd: Path, use: str, outcome: str) -> None:
        """No token-bearing call (the fetch, the push) when the repo's config in ``cwd`` holds
        a key it would act on, or origin is not the repo's GitHub url (push_guard)."""
        listed = self._git_output("config", "--list", "--show-scope", "--includes", "-z", cwd=cwd)
        held = risky_keys(parse_scoped_list(listed))
        if held:
            reason = f"git config holds keys {use} ({', '.join(held)})"
            raise StageFailure(stage, f"{reason}; {outcome}")
        urls = self._git_output(
            "config", "--get-all", REMOTE_URL, accept=(0, 1), cwd=cwd
        ).splitlines()
        github = self.children.github
        if not names_github_repo(urls, github=github):
            raise StageFailure(stage, f"{REMOTE_URL} is not the GitHub url of {github}; {outcome}")

    def _open_pr_url(self, env: dict[str, str]) -> str | None:
        """The url of the branch's open PR, from ``gh pr view``; None when there is none."""
        viewed = self._child(self.children.pr_view_argv(), env=env, timeout=GH_TIMEOUT)
        if viewed.returncode != 0:
            return None
        try:
            found = json.loads(viewed.stdout)
        except ValueError:
            return None
        if not isinstance(found, dict) or found.get("state") != "OPEN":
            return None
        url = found.get("url")
        return _pr_url(url.encode()) if isinstance(url, str) else None

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
            review_state=REVIEW_STATE,
            failed_label=self.children.config.tracker.failed_label,
            comment=comment,
        )

    def _report_success(self) -> int:
        made = self._report(self._success_writes(), failed_stage=None)
        outcome = f"PR {self.pr_url}" if made else f"PR {self.pr_url}; report failed"
        self._inbox(outcome)
        return 0 if made else FAILURE

    def _report_failure(self, failure: StageFailure) -> int:
        self.log.state = failure.stage
        self.log.record(
            "failed",
            {"stage": failure.stage.value, "reason": failure.reason[:MAX_LOGGED_REASON_CHARS]},
        )
        typer.echo(f"FAILED at {failure.stage}: {shown_text(failure.reason)}", err=True)
        comment = failure_comment(
            run_id=self.log.run_id,
            stage=failure.stage.value,
            reason=failure.reason,
            workspace=self._workspace,
        )
        writes = failure_writes(
            issue_id=self.issue.id,
            failed_label=self.children.config.tracker.failed_label,
            comment=comment,
        )
        self.log.state = Stage.FAILED
        self._report(writes, failed_stage=failure.stage)
        self._inbox(f"FAILED at {failure.stage}")
        return FAILURE

    def _report(self, writes: Sequence[TrackerWrite], *, failed_stage: Stage | None) -> bool:
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

    # children

    def _enter(self, stage: Stage) -> None:
        self.log.state = stage

    @property
    def _workspace(self) -> str:
        return str(self.children.workspace)

    def _git_output(
        self, *arguments: str, accept: tuple[int, ...] = (0,), cwd: Path | None = None
    ) -> str:
        """git's stdout in the worktree (or ``cwd``), with the untrusted environment; an exit
        code outside ``accept`` fails the stage."""
        result = self._child(
            ["git", *arguments], env=untrusted_env(self.environ), timeout=GIT_TIMEOUT, cwd=cwd
        )
        if result.returncode not in accept:
            reason = f"git {arguments[0]} failed: {_tail(result.stderr).strip()}"
            raise StageFailure(self.log.state, reason)
        return result.stdout.decode(errors="replace")

    def _stop_on_log_error(self, error: RunLogError) -> int:
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

    def _child(
        self,
        argv: Sequence[str],
        *,
        env: dict[str, str],
        timeout: float,
        output_limit: int = CHILD_OUTPUT_LIMIT,
        cwd: Path | None = None,
    ) -> ChildResult:
        """Run ``argv`` in the worktree, in the caller's group; a problem fails the stage.

        In the caller's group (E6), a timeout kills the direct child only: a process it started
        survives until the caller's own group is killed (Ctrl-C, a supervisor). The run reports
        the stage as FAILED either way.
        """
        stage = self.log.state
        name = argv[0]
        program = shutil.which(name, path=env.get("PATH", ""))
        if program is None:
            raise StageFailure(stage, f"{name} is not on PATH")
        try:
            return run_child(
                [os.path.abspath(program), *argv[1:]],
                cwd=self.worktree if cwd is None else cwd,
                env=env,
                timeout=timeout,
                own_session=False,
                output_limit=output_limit,
            )
        except ChildTimedOutError:
            raise StageFailure(stage, f"{name} timed out after {timeout:g} s") from None
        except OSError as error:
            raise StageFailure(stage, f"{name} could not run: {error.strerror or error}") from None


def _bounded_child(
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


def _tail(data: bytes) -> str:
    return data.decode(errors="replace")[-MAX_ERROR_TAIL_CHARS:]


def _pr_url(stdout: bytes) -> str | None:
    """The last line of ``gh``'s output when it is one printable ``https://`` url (E21)."""
    lines = stdout.decode(errors="replace").strip().splitlines()
    last = lines[-1].strip() if lines else ""
    if last.startswith(_URL_SCHEME) and last.isprintable() and " " not in last:
        return last if len(last) <= MAX_PR_URL_CHARS else None
    return None
