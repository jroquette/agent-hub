import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import type { components } from "../../api/schema";
import { apiGet, apiKey, apiPost, useApi, type ApiParams, type ApiProblem } from "../../lib/api";
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
