import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import type { components } from "../../api/schema";
import { apiGet, apiKey, useApi, type ApiProblem } from "../../lib/api";
import { useEventStream, type StreamHealth } from "../../lib/sse";
import type { ApiEvent } from "./timeline";

export type Session = components["schemas"]["Session"];

/** The API's largest events page; a 5,000-event session loads in 25 pages. */
export const EVENTS_PAGE = 200;

const sessionPath = (id: string) => ({ path: { session_id: id } });

export function useSession(id: string) {
  return useApi("/api/v1/sessions/{session_id}", sessionPath(id));
}

export function useSessionSummary(id: string, enabled: boolean) {
  return useApi("/api/v1/sessions/{session_id}/summary", sessionPath(id), { enabled });
}

export function useSessionFiles(id: string, enabled: boolean) {
  return useApi("/api/v1/sessions/{session_id}/files", sessionPath(id), { enabled });
}

export function useSessionCost(id: string, enabled: boolean) {
  return useApi("/api/v1/sessions/{session_id}/cost", sessionPath(id), { enabled });
}

/** "What went wrong" (AC-201.15): asked only when the session counts a problem. */
export function useSessionProblems(id: string, enabled: boolean) {
  return useApi("/api/v1/sessions/{session_id}/problems", sessionPath(id), { enabled });
}

export interface SessionEvents {
  events: ApiEvent[];
  /** True until every page has arrived. */
  loading: boolean;
  /** The failed page, its first row number, and a retry. */
  error: { problem: ApiProblem; from: number; retry: () => void } | null;
  /** Events that arrived over the stream after the pages. */
  liveCount: number;
}

/**
 * Every event of the session, paged in 200s (each page loads as the previous one lands), then
 * kept current by the session stream while `live`. Stream events are deduplicated by id.
 */
export function useSessionEvents(
  id: string,
  live: boolean,
): SessionEvents & { health: StreamHealth } {
  const queryClient = useQueryClient();
  const pages = useInfiniteQuery<
    components["schemas"]["Page_TimelineEvent_"],
    ApiProblem,
    { pages: components["schemas"]["Page_TimelineEvent_"][] },
    readonly unknown[],
    string | null
  >({
    queryKey: [...apiKey("/api/v1/sessions/{session_id}/events", sessionPath(id)), "all"],
    initialPageParam: null,
    queryFn: ({ pageParam, signal }) =>
      apiGet(
        "/api/v1/sessions/{session_id}/events",
        { path: { session_id: id }, query: { limit: EVENTS_PAGE, cursor: pageParam } },
        signal,
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    staleTime: Infinity,
  });
  const { hasNextPage, isFetchingNextPage, fetchNextPage, isError } = pages;
  useEffect(() => {
    if (hasNextPage && !isFetchingNextPage && !isError) void fetchNextPage();
  }, [hasNextPage, isFetchingNextPage, isError, fetchNextPage]);

  const [streamed, setStreamed] = useState<ApiEvent[]>([]);
  const sessionKey = apiKey("/api/v1/sessions/{session_id}", sessionPath(id));
  const health = useEventStream(
    live ? `/api/v1/sessions/${encodeURIComponent(id)}/events/stream` : null,
    {
      event: (data) => {
        if (isEvent(data)) setStreamed((previous) => [...previous, data]);
      },
      session: (data) => {
        if (typeof data !== "object" || data === null) return;
        queryClient.setQueryData<Session>(sessionKey, (previous) =>
          previous ? { ...previous, ...(data as Partial<Session>) } : previous,
        );
      },
      end: () => {
        void queryClient.invalidateQueries({ queryKey: sessionKey });
        void queryClient.invalidateQueries({
          queryKey: apiKey("/api/v1/sessions/{session_id}/summary", sessionPath(id)),
        });
      },
      reset: () => {
        setStreamed([]);
        void pages.refetch();
      },
    },
  );

  const loaded = pages.data?.pages;
  const events = useMemo(() => {
    const all = (loaded ?? []).flatMap((page) => page.items);
    const seen = new Set(all.map((event) => event.event_id));
    for (const event of streamed) {
      if (!seen.has(event.event_id)) {
        seen.add(event.event_id);
        all.push(event);
      }
    }
    return all;
  }, [loaded, streamed]);

  const loadedCount = (loaded ?? []).reduce((sum, page) => sum + page.items.length, 0);
  const error =
    pages.error === null
      ? null
      : {
          problem: pages.error,
          from: loadedCount,
          retry: () => {
            void (loaded ? pages.fetchNextPage() : pages.refetch());
          },
        };
  return {
    events,
    loading: pages.isPending || hasNextPage,
    error,
    liveCount: streamed.length,
    health,
  };
}

function isEvent(data: unknown): data is ApiEvent {
  return (
    typeof data === "object" &&
    data !== null &&
    typeof (data as { event_id?: unknown }).event_id === "string" &&
    typeof (data as { timestamp?: unknown }).timestamp === "string" &&
    typeof (data as { type?: unknown }).type === "string"
  );
}
