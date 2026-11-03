import type { components } from "../../api/schema";
import { apiKey, useApi, type ApiProblem } from "../../lib/api";
import { useCheckPoll } from "../../lib/checkPoll";
import { useScreenRead, type ScreenReadSeed } from "../../lib/screenRead";
import { SESSIONS_READ } from "../tickets/model";

export type DoctorFindings = components["schemas"]["DoctorFindings"];
export type ProjectDetail = components["schemas"]["ProjectDetail"];
export type NowItem = components["schemas"]["NowItem"];
export type RepoView = components["schemas"]["RepoView"];
export type Session = components["schemas"]["Session"];
export type Finding = components["schemas"]["FindingView"];
type ProjectOverviewView = components["schemas"]["ProjectOverviewView"];

/** The overview's screen read (ADR 0056): its first view in one call. */
export const OVERVIEW_READ = "/api/v1/screens/project-overview/{project}";
/** The runs the overview reads, its KPIs and the agents' tickets: the read's first 200. */
const RUNS_READ = 200;

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
  return useApi("/api/v1/workflow-runs", { query: { project, limit: RUNS_READ } });
}

/** The sessions Recent work reads, and whether the project has any ("No sessions yet."). */
export interface RecentSessions {
  items: readonly Session[];
  none: boolean;
  isPending: boolean;
  error: ApiProblem | null;
  refetch: () => void;
}

/** Nothing to retry: only the sessions route fails in a way Recent work offers to retry. */
const noRetry = () => undefined;

/**
 * The sessions Recent work reads: the overview read's sessions of the issues worked on this week,
 * once it has answered. When it failed, the project's newest sessions from their route, read as
 * the Tickets screen reads them (one shared cache entry, never written by the overview read).
 */
export function useRecentSessions(project: string): RecentSessions {
  const read = useScreenRead(OVERVIEW_READ, path(project));
  const route = useApi(
    "/api/v1/sessions",
    { query: { project, limit: SESSIONS_READ, sort: "-last_activity_at" } },
    { enabled: read === null },
  );
  if (read === undefined) {
    return { items: [], none: false, isPending: true, error: null, refetch: noRetry };
  }
  if (read !== null) {
    const items = read.recent_sessions.items;
    return { items, none: !read.has_sessions, isPending: false, error: null, refetch: noRetry };
  }
  const items = route.data?.items ?? [];
  return {
    items,
    none: route.isSuccess && items.length === 0,
    isPending: route.isPending,
    error: route.error,
    refetch: () => void route.refetch(),
  };
}

/** The hub's findings, read again until its first background check has ended (AGH-608). */
export function useFindings(project: string) {
  const refetchInterval = useCheckPoll((data: DoctorFindings) => data.checked_at === null);
  return useApi("/api/v1/doctor/findings", { query: { project } }, { refetchInterval });
}

/** The project's effective hub configuration, the same query the Hub config screen reads. */
export function useProjectConfig(project: string) {
  return useApi("/api/v1/projects/{project}/config", path(project));
}

/**
 * The overview read's resource parts, each under the key its region's query reads. Its recent
 * sessions are not among them: the Tickets screen shares the 200-session key and reads it whole.
 */
export function overviewSeeds(project: string, read: ProjectOverviewView): ScreenReadSeed[] {
  return [
    [apiKey("/api/v1/projects/{project}", path(project)), read.project],
    [apiKey("/api/v1/doctor/findings", { query: { project } }), read.findings],
    [apiKey("/api/v1/projects", { query: { project } }), read.projects],
    [apiKey("/api/v1/needs-you", { query: { project } }), read.needs_you],
    [apiKey("/api/v1/workflow-runs", { query: { project, limit: RUNS_READ } }), read.runs],
    [apiKey("/api/v1/projects/{project}/now", path(project)), read.now],
    [apiKey("/api/v1/features", { query: { project } }), read.features],
    [apiKey("/api/v1/projects/{project}/repos", path(project)), read.repos],
    [apiKey("/api/v1/projects/{project}/config", path(project)), read.config],
  ];
}
