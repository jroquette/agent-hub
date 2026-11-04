import { useEffect, useRef, useState } from "react";

import type { components } from "../../api/schema";
import { apiKey, useApi, type ApiProblem } from "../../lib/api";
import { useCheckPoll } from "../../lib/checkPoll";
import { useKeptScreenRead, useScreenRead, type ScreenReadSeed } from "../../lib/screenRead";
import { useGlobalStream } from "../../shell/GlobalStream";
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
 * Whether the global stream's counts have changed since `armed` turned on: the first counts seen
 * from then on only arm it, as in `useRefreshOnCounts`.
 */
function useCountsChanged(armed: boolean): boolean {
  const { counts } = useGlobalStream();
  const key = armed && counts ? JSON.stringify(counts) : null;
  const first = useRef<string | null>(null);
  const [changed, setChanged] = useState(false);
  useEffect(() => {
    if (key === null) return;
    if (first.current === null) first.current = key;
    else if (key !== first.current) setChanged(true);
  }, [key]);
  return changed;
}

/** Sessions drawn from an answer at hand: nothing to wait for and nothing to retry. */
function drawn(items: readonly Session[], none: boolean): RecentSessions {
  return { items, none, isPending: false, error: null, refetch: noRetry };
}

/**
 * The sessions Recent work reads. Once this visit's overview read has answered: its sessions of
 * the issues worked on this week, and once the stream's counts change after it (Recent work stays
 * live), the project's newest sessions from their route as soon as the route has answered since
 * the screen opened. The route is read as the Tickets screen reads it: one shared cache entry,
 * never written by the overview read, which those changes refresh.
 *
 * Until this visit's read answers, the newest answer the cache holds: the project's last overview
 * read (kept under the read's own key) or the route's entry, whichever was written last. While the
 * read is on its way the route stays off, so that answer costs no request. After the read failed
 * or did not answer in time, the route is asked, and the same cached answer stays until the route
 * has answered since the screen opened. So a return draws at once what was drawn before, or the
 * newer rows the route brought. On a visit whose project is not cached (most first visits, and
 * most returns more than 5 min after leaving: the Learnings screen and a session's chat also
 * keep the project cached), the whole page waits for the read, Recent work with it. Otherwise
 * Recent work waits only when the cache holds neither answer: for the read (or, after it
 * failed, the route).
 */
export function useRecentSessions(project: string): RecentSessions {
  const read = useScreenRead(OVERVIEW_READ, path(project));
  const kept = useKeptScreenRead(OVERVIEW_READ, path(project));
  const live = useCountsChanged(read !== undefined);
  const route = useApi(
    "/api/v1/sessions",
    { query: { project, limit: SESSIONS_READ, sort: "-last_activity_at" } },
    { enabled: read === null || live },
  );
  if (read === undefined || (read === null && !route.isFetchedAfterMount)) {
    // The cache's newest answer: while the read is on its way (the route off, no request), and
    // after it failed or timed out (the route asked) until the route has answered on this visit.
    if (route.data && route.dataUpdatedAt > kept.updatedAt) {
      return drawn(route.data.items, route.data.items.length === 0);
    }
    if (kept.read) return drawn(kept.read.recent_sessions.items, !kept.read.has_sessions);
    if (read === undefined) {
      return { items: [], none: false, isPending: true, error: null, refetch: noRetry };
    }
  } else if (read !== null && !(live && route.isFetchedAfterMount)) {
    // The read's sessions stay until the route has answered since this screen opened.
    return drawn(read.recent_sessions.items, !read.has_sessions);
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
