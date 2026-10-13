import type { Stage as ChipStage, Status } from "../../components";
import { STAGES } from "../../components";
import { toNumber } from "../../lib/format";
import type { RunStep, Stage, WorkflowRun } from "./queries";

/* View models of workflow runs, shared by the Runs list, Run detail and Project overview. */

export type RunOutcome = "failed" | "running" | "done";

export function runOutcome(run: WorkflowRun): RunOutcome {
  if (run.stage === "FAILED") return "failed";
  return run.stage === "REPORTED" ? "done" : "running";
}

export const OUTCOME_BADGE: Record<RunOutcome, { status: Status; label: string }> = {
  failed: { status: "failed", label: "Failed" },
  running: { status: "running", label: "Running" },
  done: { status: "done", label: "Done" },
};

/** A run that ended without a PR yet did not fail (AGH-140): what it delivered instead. */
const NOT_DELIVERED_BADGE = {
  no_changes: { status: "ended", label: "No changes" },
  blocked: { status: "blocked", label: "Blocked" },
} as const satisfies Record<string, { status: Status; label: string }>;

/** The run's badge: its outcome, or for a done run that opened no PR, why not. */
export function runBadge(run: WorkflowRun): { status: Status; label: string } {
  const outcome = runOutcome(run);
  if (outcome === "done" && (run.delivery === "no_changes" || run.delivery === "blocked")) {
    return NOT_DELIVERED_BADGE[run.delivery];
  }
  return OUTCOME_BADGE[outcome];
}

const ATTENTION: Record<RunOutcome, number> = { failed: 0, running: 1, done: 2 };

/** Failed and in-progress runs first, then the latest started (spec 13, `sort=attention`). */
export function byAttention(runs: readonly WorkflowRun[]): WorkflowRun[] {
  return [...runs].sort(
    (a, b) =>
      ATTENTION[runOutcome(a)] - ATTENTION[runOutcome(b)] ||
      Date.parse(b.started_at) - Date.parse(a.started_at),
  );
}

export function stageLabel(stage: Stage): string {
  if (stage === "FAILED") return "Failed";
  return STAGES.find((s) => s.id === stage)?.label ?? stage;
}

/** The stage a chip shows: where it is, or where it failed. */
export function chipStage(run: WorkflowRun): ChipStage {
  const stage = run.stage === "FAILED" ? (run.failure?.stage ?? "PICKED") : run.stage;
  return stage === "FAILED" ? "PICKED" : stage;
}

/** The step key each stage runs; Reported has none. */
export const STEP_OF: Record<ChipStage, RunStep["key"] | null> = {
  PICKED: "pick",
  WORKTREE: "worktree",
  IMPLEMENTING: "implement",
  VERIFYING: "verify",
  PR_OPEN: "pr",
  REPORTED: null,
};

/** The latest step attempt (the current one while running). */
export function lastStep(run: WorkflowRun): RunStep | undefined {
  return [...run.steps].sort(
    (a, b) => Date.parse(a.started_at) - Date.parse(b.started_at) || a.attempt - b.attempt,
  )[run.steps.length - 1];
}

/** "attempt 2 of 2" of the current (or failing) step. */
export function attemptText(run: WorkflowRun): string {
  const step = lastStep(run);
  if (!step) return "attempt 1 of 1";
  return `attempt ${String(step.attempt)} of ${String(step.max_attempts)}`;
}

/** Seconds from start to end, or to now while it runs. */
export function durationSeconds(
  startedAt: string,
  endedAt: string | null | undefined,
  now: number,
): number {
  const end = endedAt ? Date.parse(endedAt) : now;
  return Math.max(0, (end - Date.parse(startedAt)) / 1000);
}

export function budgetOf(run: WorkflowRun): number | null {
  return toNumber(run.caps?.budget_usd);
}

/** The middle value of the costs runs report; null with none. */
export function median(values: readonly number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  const upper = sorted[mid] ?? 0;
  return sorted.length % 2 ? upper : ((sorted[mid - 1] ?? 0) + upper) / 2;
}

export function finishedCosts(runs: readonly WorkflowRun[]): number[] {
  return runs
    .filter((run) => runOutcome(run) !== "running")
    .map((run) => toNumber(run.cost_usd))
    .filter((cost): cost is number => cost !== null);
}

export function shortRunId(id: string): string {
  return id.replace(/-/g, "").slice(0, 8);
}
