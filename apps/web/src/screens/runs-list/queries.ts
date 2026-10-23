import type { components } from "../../api/schema";
import { useApi } from "../../lib/api";

export type WorkflowRun = components["schemas"]["WorkflowRun"];
export type RunStep = components["schemas"]["RunStep"];
export type Stage = components["schemas"]["Stage"];
export type FailureKind = components["schemas"]["FailureKind"];
export type SkipCause = components["schemas"]["SkipCause"];

/** The filters the API applies; the rail's facets set them through the URL (spec 13). */
export interface RunFilters {
  project: string | null;
  stage: Stage | null;
  outcome: "done" | "failed" | null;
  failure_stage: Stage | null;
  repo: string | null;
  mode: "live" | "dry_run" | null;
  workflow: string | null;
  failure_kind: FailureKind | null;
}

/** Workflow runs only: scenario runs are listed in Scenarios (AM-7). */
export function useRuns(filters: RunFilters, limit: number) {
  return useApi("/api/v1/workflow-runs", { query: { ...filters, kind: "workflow", limit } });
}

/** Whether any workflow run (kind `workflow`) exists, of any project: the sidebar shows Workflow
 * runs only then (AC-382.9), so a hub with only scenario runs shows no empty item. */
export function useHasWorkflowRuns(): boolean {
  return (
    (useApi("/api/v1/workflow-runs", { query: { kind: "workflow", limit: 1 } }).data?.items
      .length ?? 0) > 0
  );
}

/** Whether the project in scope (or any) has a scenario run: the empty list points to Scenarios. */
export function useHasScenarioRuns(project: string | null): boolean {
  return (
    (useApi("/api/v1/workflow-runs", { query: { project, kind: "scenario", limit: 1 } }).data?.items
      .length ?? 0) > 0
  );
}
