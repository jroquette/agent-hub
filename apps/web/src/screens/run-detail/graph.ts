import type { Status } from "../../components";
import { FAILURE_KIND_LABEL, SKIP_CAUSE_LABEL } from "../runs-list/model";
import type { RunStep, WorkflowRun } from "../runs-list/queries";
import type { WorkflowNode } from "../workflows/queries";

/* The run graph of an engine run (plan 6.4, AC-213.15): the declared nodes joined by id to the
 * run's steps as the API folded them (never refolded here); a node with no step has not run. */

/** issue-to-pr keeps its stage pipeline and labels; every other workflow shows its graph. */
export function isGraphRun(run: WorkflowRun): boolean {
  return run.workflow !== "issue-to-pr";
}

export interface RunNode {
  id: string;
  type: string;
  depends_on: string[];
  /** The latest attempt; none when the node has not run. */
  step: RunStep | undefined;
  /** A loop_group's body steps (`<group>__<id>`), latest attempt of each. */
  body: RunStep[];
}

export type NodeState = "pending" | "running" | "ok" | "failed" | "skipped" | "cached";

export const STATE_LOOK: Record<NodeState, { status: Status; label: string }> = {
  pending: { status: "queued", label: "Not run" },
  running: { status: "running", label: "Running" },
  ok: { status: "done", label: "Completed" },
  failed: { status: "failed", label: "Failed" },
  skipped: { status: "idle", label: "Skipped" },
  cached: { status: "done", label: "Completed (cached)" },
};

function latestByKey(steps: readonly RunStep[]): Map<string, RunStep> {
  const latest = new Map<string, RunStep>();
  for (const step of steps) {
    const seen = latest.get(step.key);
    if (!seen || step.attempt > seen.attempt) latest.set(step.key, step);
  }
  return latest;
}

/**
 * The graph's layers: the workflow's (null when it could not be read: the steps in start order,
 * one column), each node with its latest step; a step of no declared node is a body step of its
 * `<group>__` prefix, else it joins a last column.
 */
export function runLayers(run: WorkflowRun, layers: WorkflowNode[][] | null): RunNode[][] {
  const latest = latestByKey(run.steps);
  const first = new Map<string, number>();
  for (const step of run.steps) {
    const t = Date.parse(step.started_at);
    first.set(step.key, Math.min(t, first.get(step.key) ?? t));
  }
  const ordered = [...latest.values()].sort(
    (a, b) => (first.get(a.key) ?? 0) - (first.get(b.key) ?? 0),
  );
  const asNode = (step: RunStep): RunNode => ({
    id: step.key,
    type: step.kind ?? "step",
    depends_on: [],
    step,
    body: [],
  });
  if (layers === null) return ordered.length ? [ordered.map(asNode)] : [];
  const nodes = new Map<string, RunNode>();
  const graph = layers.map((layer) =>
    layer.map((node) => {
      const runNode: RunNode = { ...node, step: latest.get(node.id), body: [] };
      nodes.set(node.id, runNode);
      return runNode;
    }),
  );
  const extra: RunNode[] = [];
  for (const step of ordered) {
    if (nodes.has(step.key)) continue;
    const group = nodes.get(step.key.split("__")[0] ?? "");
    if (step.key.includes("__") && group) group.body.push(step);
    else extra.push(asNode(step));
  }
  return extra.length ? [...graph, extra] : graph;
}

export function nodeState(node: RunNode): NodeState {
  const step = node.step;
  if (!step) return "pending";
  if (step.status === "skipped" && step.skip_cause === "prior_success") return "cached";
  return step.status;
}

/** "Failed · attempt 2 · Timeout", "Skipped · condition false", "Completed". */
export function nodeSummary(node: RunNode): string {
  const step = node.step;
  const parts = [STATE_LOOK[nodeState(node)].label];
  if (step && step.attempt > 1) parts.push(`attempt ${String(step.attempt)}`);
  if (step?.failure_kind) parts.push(FAILURE_KIND_LABEL[step.failure_kind]);
  if (step?.skip_cause && step.skip_cause !== "prior_success") {
    parts.push(SKIP_CAUSE_LABEL[step.skip_cause]);
  }
  return parts.join(" · ");
}

/** "Failed at build · attempt 2 · Timeout": the latest failed node, else the run's kind. */
export function graphFailureTitle(run: WorkflowRun): string {
  const failed = [...run.steps]
    .filter((step) => step.status === "failed")
    .sort((a, b) => Date.parse(a.started_at) - Date.parse(b.started_at) || a.attempt - b.attempt)
    .at(-1);
  if (!failed) {
    const kind = run.failure?.failure_kind;
    return kind ? `Failed · ${FAILURE_KIND_LABEL[kind]}` : "Failed";
  }
  const node: RunNode = { id: failed.key, type: "", depends_on: [], step: failed, body: [] };
  return [`Failed at ${failed.key}`, ...nodeSummary(node).split(" · ").slice(1)].join(" · ");
}
