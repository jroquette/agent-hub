import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import type { components } from "../../api/schema";
import { apiGet, apiKey, apiPost, useApi, type ApiParams, type ApiProblem } from "../../lib/api";
import { openStream } from "../../lib/sse";
import type { SectionId } from "./sections";

export type Session = components["schemas"]["Session"];
type SessionPage = components["schemas"]["Page_Session_"];
export type SessionQuery = NonNullable<ApiParams<"/api/v1/sessions">["query"]>;

/** Rows per page ("Showing 50 of ~1,240"). */
export const PAGE_SIZE = 50;

/** Sessions matching `query` (null: not asked), page by page; "Load more" asks for the next cursor (spec 14). */
export function useSessionPages(query: SessionQuery | null) {
  return useInfiniteQuery<
    SessionPage,
    ApiProblem,
    { pages: SessionPage[] },
    readonly unknown[],
    string | null
  >({
    queryKey: [...apiKey("/api/v1/sessions", { query: query ?? {} }), "pages"],
    enabled: query !== null,
    initialPageParam: null,
    queryFn: ({ pageParam, signal }) =>
      apiGet(
        "/api/v1/sessions",
        { query: { ...(query ?? {}), limit: PAGE_SIZE, cursor: pageParam } },
        signal,
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    // A filter or sort change keeps the shown pages until the new ones arrive: no flash, no jump.
    placeholderData: keepPreviousData,
  });
}

/** One paged query per status section (ADR 0033 D4); a section not asked stays idle. */
export function useSectionPages(queries: Record<SectionId, SessionQuery | null>) {
  return {
    waiting: useSessionPages(queries.waiting),
    live: useSessionPages(queries.live),
    idle: useSessionPages(queries.idle),
    ended: useSessionPages(queries.ended),
  };
}

/** The live-tile stream of `project` (null: all); Live patches its tiles from it, Sessions refetches. */
export function tileStreamUrl(project: string | null): string {
  return `/api/v1/live-sessions/stream${project ? `?project=${encodeURIComponent(project)}` : ""}`;
}

/** Sections refetch at most this often on stream changes (AC-234.9). */
export const STREAM_REFETCH_MS = 2_000;

/** A section asked for: collapsed or busy ones are not refetched, only marked to catch up later. */
export interface SectionTarget {
  id: SectionId;
  collapsed: boolean;
  /** A fetch (e.g. Load more) is running: refetching now would cancel it. */
  fetching: boolean;
  refetch: (options: { cancelRefetch: boolean }) => unknown;
}

/**
 * Refetches the open sections on tile-stream changes and when the agent-list poll brings data
 * (`agentsUpdatedAt`), at most once per STREAM_REFETCH_MS on the trailing edge (a burst is one
 * refetch). A tile does not say which section it left, so every open section refetches; a
 * collapsed or fetching one refetches once it is open and idle. `onRefetch` gets the sections
 * asked, before they are. The stream keeps no state, so its messages never re-render the screen.
 */
export function useSectionRefresh(
  project: string | null,
  targets: readonly SectionTarget[],
  agentsUpdatedAt: number,
  onRefetch: (ids: SectionId[]) => void,
): void {
  const latest = useRef({ targets, onRefetch });
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  /** Sections a tick skipped, and why: opening one catches up at once, a fetch at the next edge. */
  const missed = useRef(new Map<SectionId, "collapsed" | "fetching">());
  const refetch = (ids: SectionTarget[]) => {
    if (ids.length === 0) return;
    latest.current.onRefetch(ids.map((target) => target.id));
    for (const target of ids) void target.refetch({ cancelRefetch: false });
  };
  const schedule = useRef(() => {
    if (timer.current !== undefined) return;
    timer.current = setTimeout(() => {
      timer.current = undefined;
      const due = latest.current.targets.filter((target) => {
        if (target.collapsed) missed.current.set(target.id, "collapsed");
        else if (target.fetching) missed.current.set(target.id, "fetching");
        else missed.current.delete(target.id);
        return !target.collapsed && !target.fetching;
      });
      refetch(due);
    }, STREAM_REFETCH_MS);
  });
  useEffect(() => {
    latest.current = { targets, onRefetch };
    const idle = targets.filter((target) => !target.collapsed && !target.fetching);
    if (idle.some((target) => missed.current.get(target.id) === "fetching")) schedule.current();
    refetch(
      idle.filter(
        (target) =>
          missed.current.get(target.id) === "collapsed" && missed.current.delete(target.id),
      ),
    );
  });
  // Only a newer answer for the same project's list: a project switch changes the query, not data.
  const seen = useRef({ project, at: agentsUpdatedAt });
  useEffect(() => {
    const last = seen.current;
    if (last.project === project && last.at !== 0 && agentsUpdatedAt > last.at) {
      schedule.current();
    }
    seen.current = { project, at: agentsUpdatedAt };
  }, [project, agentsUpdatedAt]);
  useEffect(() => {
    const changed = () => {
      schedule.current();
    };
    const close = openStream(
      tileStreamUrl(project),
      { "tile.upsert": changed, "tile.remove": changed, reset: changed },
      () => undefined,
    );
    return () => {
      close();
      clearTimeout(timer.current);
      timer.current = undefined;
    };
  }, [project]);
}

/** The registered projects, for the Project facet. */
export function useProjects() {
  return useApi("/api/v1/projects");
}

/* ---------- Sessions hub web drives (AGH-165) ---------- */

export type AgentSession = components["schemas"]["AgentSession"];
export type CreateAgentSession = components["schemas"]["CreateAgentSession"];
export type CloudSession = components["schemas"]["CloudSession"];

/** While a listed session is live, the list refreshes this often (statuses, waiting). */
export const AGENT_LIST_REFRESH_MS = 5_000;

const live = (s: AgentSession) => s.status !== "ended" && s.status !== "failed";

/** The agent sessions of `project` (null: every project), newest first. */
export function useAgentSessions(project: string | null) {
  return useApi(
    "/api/v1/agent-sessions",
    { query: project ? { project } : {} },
    {
      retry: false,
      refetchInterval: (query) =>
        (query.state.data?.items ?? []).some(live) ? AGENT_LIST_REFRESH_MS : false,
    },
  );
}

/** Whether this machine can drive sessions, and why not. */
export function useAgentCapabilities() {
  return useApi("/api/v1/agent-sessions/capabilities", undefined, {
    staleTime: 60_000,
    retry: false,
  });
}

/** The folders a session of `project` may start in (D6). */
export function useWorkdirs(project: string | null, enabled: boolean) {
  return useApi(
    "/api/v1/agent-sessions/workdirs",
    { query: { project: project ?? "" } },
    { enabled: enabled && project !== null, retry: false },
  );
}

/** The cloud starts of `project`, newest first. */
export function useCloudSessions(project: string | null, enabled: boolean) {
  return useApi(
    "/api/v1/agent-sessions/cloud",
    { query: { project: project ?? "" } },
    { enabled: enabled && project !== null, retry: false },
  );
}

/**
 * `POST /agent-sessions`; the caller navigates to the new session's chat. `release` drops the mutation
 * (its body, a base64 screenshot included) from the cache as soon as its dialog unmounts (AGH-260).
 */
export function useCreateAgentSession({ release = false }: { release?: boolean } = {}) {
  const queryClient = useQueryClient();
  return useMutation<AgentSession, ApiProblem, CreateAgentSession>({
    mutationFn: (body) => apiPost("/api/v1/agent-sessions", body),
    ...(release ? { gcTime: 0 } : {}),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: apiKey("/api/v1/agent-sessions") });
    },
  });
}
