import type { components } from "../../api/schema";
import { useApi } from "../../lib/api";

export type WorkflowSummary = components["schemas"]["WorkflowSummary"];
export type WorkflowDetail = components["schemas"]["WorkflowDetail"];
export type WorkflowNode = components["schemas"]["WorkflowNodeView"];
export type WorkflowStep = components["schemas"]["WorkflowStepView"];

/** The workflows of every project, or of the one in scope, and the files that do not load. */
export function useWorkflows(project: string | null) {
  return useApi("/api/v1/workflows", { query: { project } });
}

/** One workflow's layers and document; `enabled: false` waits (a run not loaded yet). */
export function useWorkflow(project: string, name: string, enabled = true) {
  return useApi("/api/v1/workflows/{project}/{name}", { path: { project, name } }, { enabled });
}
