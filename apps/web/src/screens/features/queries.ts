import { useQueries } from "@tanstack/react-query";
import { useMemo } from "react";

import type { TicketInfo, TicketLookup } from "../../components";
import { apiGet, apiKey, useApi } from "../../lib/api";
import { issueId, reasonOf, sessionWaitOf } from "./groups";

/** How often the open Features list rereads the records (local files, Linear cached server-side). */
export const FEATURES_REFRESH_MS = 30_000;

/** Feature records of every registered hub, or of the scoped project (D23), kept fresh while open. */
export function useFeatures(project: string | null) {
  return useApi(
    "/api/v1/features",
    { query: { project } },
    { refetchInterval: FEATURES_REFRESH_MS },
  );
}

/**
 * The tickets the hub's features work on (`ACME-12` → its feature and, once read, its title), so a
 * session on that ticket is named `ACME-12: Export orders as CSV` and links to its feature. Titles
 * come only from tickets already in the cache (the Tickets tab, or `useTicketTitles` of an open
 * session): a list of sessions never makes the server read Linear. The first feature naming a ticket
 * wins.
 */
export function useTicketLookup(project: string | null = null): TicketLookup {
  const items = useApi("/api/v1/features", { query: { project } }, { staleTime: 60_000 }).data
    ?.items;
  const cached = useQueries({
    queries: (items ?? []).map((feature) => ({
      queryKey: ticketsKey(feature.project, feature.slug),
      queryFn: () => apiGet(TICKETS, ticketsParams(feature.project, feature.slug)),
      enabled: false,
    })),
  });
  const rows = cached.map((query) => query.data?.tickets);
  const signature = cached.map((query) => query.dataUpdatedAt).join(",");
  return useMemo(() => {
    const lookup = new Map<string, TicketInfo>();
    (items ?? []).forEach((feature, index) => {
      const titles = new Map(
        (rows[index] ?? []).flatMap((row) =>
          row.id && row.title ? [[row.id.toUpperCase(), row.title] as const] : [],
        ),
      );
      for (const issue of feature.issues) {
        const id = issueId(issue).toUpperCase();
        if (lookup.has(id)) continue;
        lookup.set(id, {
          project: feature.project,
          slug: feature.slug,
          title: titles.get(id) ?? null,
        });
      }
    });
    return lookup;
    // `rows` is new each render; its content changes with `signature`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, signature]);
}

/** Reads one feature's tickets once (titles from Linear's cached snapshot, else the plan), for the
 * session open on it: what `useTicketLookup` names it by. No polling, unlike the Tickets tab. */
export function useTicketTitles(ticket: TicketInfo | undefined) {
  useApi(TICKETS, ticketsParams(ticket?.project ?? "", ticket?.slug ?? ""), {
    enabled: ticket !== undefined,
    staleTime: 5 * 60_000,
    retry: false,
  });
}

const TICKETS = "/api/v1/features/{project}/{slug}/tickets" as const;
const ticketsParams = (project: string, slug: string) => ({ path: { project, slug } });
const ticketsKey = (project: string, slug: string) => apiKey(TICKETS, ticketsParams(project, slug));

/** While a session is live, the list rereads the sessions this often, so a wait shows within seconds. */
export const LIVE_SESSIONS_REFRESH_MS = 5_000;

/** The live session tiles (observed and web-driven), each with its issue and whether it waits on you. */
export function useLiveSessions(project: string | null) {
  return useApi(
    "/api/v1/live-sessions",
    { query: { project } },
    { refetchInterval: LIVE_SESSIONS_REFRESH_MS, retry: false },
  );
}

/**
 * How many features need you, as the Features list counts them (a session waiting on you, a broken
 * record, NO-SHIP, owner steps), for the sidebar badge. It shares the list's queries, so the open
 * list and the badge read the same data.
 */
export function useFeaturesNeedingYou(project: string | null): number | undefined {
  const features = useFeatures(project).data?.items;
  const tiles = useLiveSessions(project).data?.items ?? [];
  if (!features) return undefined;
  return features.filter((f) => reasonOf(f, sessionWaitOf(f, tiles)).needs !== null).length;
}
