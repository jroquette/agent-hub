import type { components } from "../../api/schema";
import { useApi } from "../../lib/api";

export type ProjectDetail = components["schemas"]["ProjectDetail"];
export type NowItem = components["schemas"]["NowItem"];
export type RepoView = components["schemas"]["RepoView"];
export type Session = components["schemas"]["Session"];
export type Finding = components["schemas"]["FindingView"];

const path = (project: string) => ({ path: { project } });

export function useProject(project: string) {
  return useApi("/api/v1/projects/{project}", path(project));
}

export function useProjectNow(project: string) {
  return useApi("/api/v1/projects/{project}/now", path(project));
}

export function useProjectRepos(project: string) {
  return useApi("/api/v1/projects/{project}/repos", path(project));
}

/** The project's Portfolio card: its period cost and daily series. */
export function useProjectSummary(project: string) {
  return useApi("/api/v1/projects", { query: { project } });
}

export function useProjectRuns(project: string) {
  return useApi("/api/v1/workflow-runs", { query: { project, limit: 200 } });
}

/** Last 10 sessions, newest first (spec 12, Recent sessions). */
export function useRecentSessions(project: string) {
  return useApi("/api/v1/sessions", { query: { project, limit: 10, sort: "-started_at" } });
}

export function useFindings(project: string) {
  return useApi("/api/v1/doctor/findings", { query: { project } });
}
