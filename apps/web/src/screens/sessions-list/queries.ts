import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import type { components } from "../../api/schema";
import { apiGet, apiKey, apiPost, useApi, type ApiParams, type ApiProblem } from "../../lib/api";
import { useEventStream, type StreamHealth } from "../../lib/sse";
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

/** A section asked for: collapsed ones are not refetched, only marked to catch up when opened. */
export interface SectionTarget {
  id: SectionId;
  collapsed: boolean;
  refetch: () => unknown;
}

/**
 * Refetches the open sections on tile-stream changes, at most once per STREAM_REFETCH_MS on the
 * trailing edge (a burst is one refetch). A tile does not say which section it left, so every open
 * section refetches; a collapsed one refetches once when it opens again. Closes on unmount.
 */
export function useTileStreamInvalidation(
  project: string | null,
  targets: readonly SectionTarget[],
): StreamHealth {
  const latest = useRef(targets);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const missed = useRef(new Set<SectionId>());
  useEffect(() => {
    latest.current = targets;
    for (const target of targets) {
      if (!target.collapsed && missed.current.delete(target.id)) void target.refetch();
    }
  });
  useEffect(
    () => () => {
      clearTimeout(timer.current);
    },
    [],
  );
  const changed = () => {
    if (timer.current !== undefined) return;
    timer.current = setTimeout(() => {
      timer.current = undefined;
      for (const target of latest.current) {
        if (target.collapsed) missed.current.add(target.id);
        else void target.refetch();
      }
    }, STREAM_REFETCH_MS);
  };
  return useEventStream(tileStreamUrl(project), {
    "tile.upsert": changed,
    "tile.remove": changed,
    reset: changed,
  });
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

/** Past Claude sessions of a folder, to resume or fork. */
export function useResumable(project: string | null, workdirId: string | null) {
  return useApi(
    "/api/v1/agent-sessions/resumable",
    { query: { project: project ?? "", workdir_id: workdirId ?? "" } },
    { enabled: project !== null && workdirId !== null, retry: false },
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

/** `POST /agent-sessions`; the caller navigates to the new session's chat. */
export function useCreateAgentSession() {
  const queryClient = useQueryClient();
  return useMutation<AgentSession, ApiProblem, CreateAgentSession>({
    mutationFn: (body) => apiPost("/api/v1/agent-sessions", body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: apiKey("/api/v1/agent-sessions") });
    },
  });
}
