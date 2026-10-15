import type { PipelineStep, Stage as ChipStage } from "../../components";
import { STAGES } from "../../components";
import type { RunStep, Stage, WorkflowRun } from "../runs-list/queries";
import { durationSeconds, STEP_OF } from "../runs-list/model";

/* View models of Run detail (spec 13, screen 2): pipeline, failure banner and Gantt lanes. */

export const STEP_LABEL: Record<RunStep["key"], string> = {
  pick: "Picked",
  worktree: "Worktree",
  implement: "Implement",
  verify: "Verify",
  pr: "PR open",
};

function attemptsOf(run: WorkflowRun, key: RunStep["key"]): RunStep[] {
  return run.steps.filter((step) => step.key === key).sort((a, b) => a.attempt - b.attempt);
}

/** The latest attempt of the step a stage runs. */
export function latestAttempt(run: WorkflowRun, stage: Stage): RunStep | undefined {
  const key = stage === "FAILED" || stage === "REPORTED" ? null : STEP_OF[stage];
  if (key === null) return undefined;
  const attempts = attemptsOf(run, key);
  return attempts[attempts.length - 1];
}

/** Six nodes, one per stage; attempts show where a step may loop (max attempts above 1). */
export function pipeline(run: WorkflowRun, now: number): PipelineStep[] {
  const nodes = STAGES.map(({ id, label }): PipelineStep => {
    if (id === "REPORTED") {
      return { id, label, state: run.stage === "REPORTED" ? "done" : "pending" };
    }
    const key = STEP_OF[id];
    const attempts = key ? attemptsOf(run, key) : [];
    const last = attempts[attempts.length - 1];
    if (!last) return { id, label, state: "pending" };
    const state =
      last.status === "running" ? "active" : last.status === "failed" ? "failed" : "done";
    return {
      id,
      label,
      state,
      duration: attempts.reduce(
        (sum, step) => sum + durationSeconds(step.started_at, step.ended_at, now),
        0,
      ),
      attempts: attempts.length,
      attempt: last.max_attempts > 1 ? last.attempt : undefined,
      maxAttempts: last.max_attempts,
      note: state === "failed" ? (last.reason ?? undefined) : undefined,
    };
  });
  return nodes;
}

/**
 * The loop back-edge: the last stage run more than once (Verifying back to Implementing), as
 * "on fail: back to Implementing · attempt 2 of 2 · cap reached"; null when nothing looped.
 */
export function loopLabel(nodes: readonly PipelineStep[]): string | null {
  const looped = nodes
    .map((node, i) => ({ node, i }))
    .filter(({ node }) => (node.attempt ?? 1) > 1);
  const last = looped[looped.length - 1];
  if (!last) return null;
  const back = nodes[last.i - 1];
  const { attempt = 1, maxAttempts = attempt } = last.node;
  const capped = attempt >= maxAttempts && last.node.state === "failed";
  return `${back ? `on fail: back to ${back.label} · ` : ""}attempt ${String(attempt)} of ${String(maxAttempts)}${capped ? " · cap reached" : ""}`;
}

/** The session holding the failing moment: the failing step's, else the latest implement one. */
export function failingSession(run: WorkflowRun): string | null {
  const stage = run.failure?.stage;
  const failing = stage ? latestAttempt(run, stage) : undefined;
  const implement = attemptsOf(run, "implement");
  const candidates = [
    failing?.session_ids,
    implement[implement.length - 1]?.session_ids,
    run.session_ids,
  ];
  for (const ids of candidates) {
    const id = ids?.[ids.length - 1];
    if (id) return id;
  }
  return null;
}

/** "Failed at Verifying · attempt 2 of 2". */
export function failureTitle(run: WorkflowRun, label: string): string {
  const stage = run.failure?.stage ?? "PICKED";
  const step = latestAttempt(run, stage);
  const attempt = step ? ` · attempt ${String(step.attempt)} of ${String(step.max_attempts)}` : "";
  return `Failed at ${label}${attempt}`;
}

/** The plain reason: the run's, else the last failed gate's command and exit code. */
export function failureReason(run: WorkflowRun): string {
  if (run.failure?.reason) return run.failure.reason;
  const gate = [...run.gate_results].reverse().find((g) => g.result === "failed");
  if (gate?.command) {
    return `${gate.command} exited ${gate.exit_code === null || gate.exit_code === undefined ? "with an error" : String(gate.exit_code)}`;
  }
  return "No reason was recorded. See the gate log.";
}

export interface Lane {
  id: string;
  label: string;
  status: RunStep["status"];
  start: number;
  end: number;
  sessions: string[];
}

/** One lane per (step, attempt), in time order; a running step ends now. */
export function lanes(run: WorkflowRun, now: number): { lanes: Lane[]; from: number; to: number } {
  const rows = [...run.steps]
    .sort((a, b) => Date.parse(a.started_at) - Date.parse(b.started_at))
    .map((step) => ({
      id: `${step.key}-${String(step.attempt)}`,
      label: `${STEP_LABEL[step.key] ?? step.key} #${String(step.attempt)}`,
      status: step.status,
      start: Date.parse(step.started_at),
      end: step.ended_at ? Date.parse(step.ended_at) : now,
      sessions: step.session_ids,
    }));
  const from = Math.min(Date.parse(run.started_at), ...rows.map((r) => r.start));
  const to = Math.max(from + 1000, ...rows.map((r) => r.end));
  return { lanes: rows, from, to };
}

export function chipOf(stage: Stage): ChipStage {
  return stage === "FAILED" ? "PICKED" : stage;
}
