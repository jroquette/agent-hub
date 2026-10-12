import type { components } from "../../api/schema";
import { useApi } from "../../lib/api";

export type WorkflowRun = components["schemas"]["WorkflowRun"];
export type RunStep = components["schemas"]["RunStep"];
export type Stage = components["schemas"]["Stage"];

/** The filters the API applies; the rail's facets set them through the URL (spec 13). */
export interface RunFilters {
  project: string | null;
  stage: Stage | null;
  outcome: "done" | "failed" | null;
  failure_stage: Stage | null;
  repo: string | null;
  mode: "live" | "dry_run" | null;
}

export function useRuns(filters: RunFilters, limit: number) {
  return useApi("/api/v1/workflow-runs", { query: { ...filters, limit } });
}
