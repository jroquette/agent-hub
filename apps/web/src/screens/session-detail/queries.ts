import { infiniteQueryOptions, useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { useContext, useEffect, useMemo, useState } from "react";

import type { components } from "../../api/schema";
import {
  apiGet,
  apiKey,
  ScreenReadContext,
  useApi,
  type ApiProblem,
  type ScreenReadHold,
} from "../../lib/api";
import type { ScreenReadSeed } from "../../lib/screenRead";
import { useEventStream, type StreamHealth } from "../../lib/sse";
import type { ApiEvent } from "./timeline";

export type Session = components["schemas"]["Session"];
type EventsPage = components["schemas"]["Page_TimelineEvent_"];
type SessionDetailView = components["schemas"]["SessionDetailView"];

/** The API's largest events page; a 5,000-event session loads in 5 pages. */
export const EVENTS_PAGE = 1000;

/** Session detail's screen read (ADR 0056): its first view in one call. */
export const SESSION_DETAIL_READ = "/api/v1/screens/session-detail/{session_id}";

const sessionPath = (id: string) => ({ path: { session_id: id } });

/** The cached query of every events page: the key the timeline reads and the read writes. */
const eventsKey = (id: string) =>
  [...apiKey("/api/v1/sessions/{session_id}/events", sessionPath(id)), "all"] as const;

/** The first page a screen read wrote under the events key, if it wrote one. */
const firstPage = (data: unknown) => (data as { pages?: EventsPage[] } | undefined)?.pages?.[0];

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

/** Every page of a session's events, as one cached query: the screen starts it as soon as it
 * knows the id, alongside the session itself, and the timeline reads it when the session lands.
 * The first page waits for a screen read above that brings it (ADR 0056). */
function eventsQuery(id: string, screenRead: ScreenReadHold | null) {
  return infiniteQueryOptions<
    EventsPage,
    ApiProblem,
    { pages: EventsPage[] },
    readonly unknown[],
    string | null
  >({
    queryKey: eventsKey(id),
    initialPageParam: null,
    queryFn: ({ pageParam, queryKey, signal }) => {
      const read = () =>
        apiGet(
          "/api/v1/sessions/{session_id}/events",
          { path: { session_id: id }, query: { limit: EVENTS_PAGE, cursor: pageParam } },
          signal,
        );
      const held = pageParam === null ? screenRead?.hold(queryKey) : null;
      if (!held) return read();
      return held.then((data) => firstPage(data) ?? read());
    },
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    staleTime: Infinity,
  });
}

/** Starts reading the session's first events page while the session itself is read, unless a
 * screen read above brings that page. */
export function usePrefetchSessionEvents(id: string): void {
  const queryClient = useQueryClient();
  const screenRead = useContext(ScreenReadContext);
  useEffect(() => {
    const query = eventsQuery(id, screenRead);
    if (screenRead?.hold(query.queryKey)) return;
    // Its failure shows where the timeline reads it; nothing to do here.
    queryClient.infiniteQuery(query).catch(() => undefined);
  }, [queryClient, id, screenRead]);
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
 * Every event of the session, paged in 1,000s (each page loads as the previous one lands), then
 * kept current by the session stream while `live`. Stream events are deduplicated by id.
 */
export function useSessionEvents(
  id: string,
  live: boolean,
): SessionEvents & { health: StreamHealth } {
  const queryClient = useQueryClient();
  const screenRead = useContext(ScreenReadContext);
  const pages = useInfiniteQuery(eventsQuery(id, screenRead));
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

/**
 * The detail read's parts, each under the key its region's query reads: the session, its first
 * events page (the timeline reads the further pages from the events route), its summary and its
 * problems when it carries them, its project's features (the header's ticket names) and, when
 * carried, whether this machine can drive sessions. A `null` part is not written, so its query
 * reads its route once the read has answered.
 */
export function sessionDetailSeeds(id: string, read: SessionDetailView): ScreenReadSeed[] {
  const seeds: ScreenReadSeed[] = [
    [apiKey("/api/v1/sessions/{session_id}", sessionPath(id)), read.session],
    [eventsKey(id), { pages: [read.events], pageParams: [null] }],
  ];
  if (read.summary !== null) {
    seeds.push([apiKey("/api/v1/sessions/{session_id}/summary", sessionPath(id)), read.summary]);
  }
  if (read.problems !== null) {
    seeds.push([apiKey("/api/v1/sessions/{session_id}/problems", sessionPath(id)), read.problems]);
  }
  // The features' key names the session's project, which only the answer knows: the answer with
  // no parts that names the covered keys leaves it out. The header, its one reader here, mounts
  // once the session has arrived, which on a first visit is after this part is written.
  const project = (read.session as Session | undefined)?.project;
  if (project !== undefined) {
    seeds.push([apiKey("/api/v1/features", { query: { project } }), read.features]);
  }
  if (read.capabilities !== null) {
    seeds.push([apiKey("/api/v1/agent-sessions/capabilities"), read.capabilities]);
  }
  return seeds;
}
