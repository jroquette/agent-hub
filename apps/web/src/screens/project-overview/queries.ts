import type { components } from "../../api/schema";
import { useApi } from "../../lib/api";
import { SESSIONS_READ } from "../tickets";

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

/** The project's newest sessions, read as the Tickets screen reads them (one shared cache entry). */
export function useProjectSessions(project: string) {
  return useApi("/api/v1/sessions", {
    query: { project, limit: SESSIONS_READ, sort: "-last_activity_at" },
  });
}

export function useFindings(project: string) {
  return useApi("/api/v1/doctor/findings", { query: { project } });
}

/** The project's effective hub configuration, the same query the Hub config screen reads. */
export function useProjectConfig(project: string) {
  return useApi("/api/v1/projects/{project}/config", path(project));
}
