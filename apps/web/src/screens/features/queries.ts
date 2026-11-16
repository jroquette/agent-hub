import { useQueries } from "@tanstack/react-query";
import { useMemo } from "react";

import type { TicketInfo, TicketLookup } from "../../components";
import { apiGet, apiKey, useApi } from "../../lib/api";
import { issueId } from "./groups";

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
 * session on that ticket is named `ACME-12: Export orders as CSV` and links to its feature. A ticket
 * is a feature's when the feature lists it (`issues`, often only its epic) or its ticket plan has a
 * row for it. Titles come from tickets already in the cache (the Tickets tab, or `useTicketTitles`
 * of an open session); `read` also reads each feature's tickets once (the server's cached snapshot,
 * no polling), for the views that name sessions on tickets the features do not list. The first
 * feature naming a ticket wins, `issues` before the plans' rows.
 */
export function useTicketLookup(
  project: string | null = null,
  { read = false }: { read?: boolean } = {},
): TicketLookup {
  const items = useApi("/api/v1/features", { query: { project } }, { staleTime: 60_000 }).data
    ?.items;
  const cached = useQueries({
    queries: (items ?? []).map((feature) => ({
      queryKey: ticketsKey(feature.project, feature.slug),
      queryFn: () => apiGet(TICKETS, ticketsParams(feature.project, feature.slug)),
      enabled: read,
      staleTime: TICKETS_STALE_MS,
      retry: false,
    })),
  });
  const rows = cached.map((query) => query.data?.tickets);
  const signature = cached.map((query) => query.dataUpdatedAt).join(",");
  return useMemo(() => {
    const lookup = new Map<string, TicketInfo>();
    const titlesOf = (index: number) =>
      new Map(
        (rows[index] ?? []).flatMap((row) =>
          row.id && row.title ? [[row.id.toUpperCase(), row.title] as const] : [],
        ),
      );
    (items ?? []).forEach((feature, index) => {
      const titles = titlesOf(index);
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
    (items ?? []).forEach((feature, index) => {
      for (const [id, title] of titlesOf(index)) {
        if (!lookup.has(id))
          lookup.set(id, { project: feature.project, slug: feature.slug, title });
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
    staleTime: TICKETS_STALE_MS,
    retry: false,
  });
}

const TICKETS = "/api/v1/features/{project}/{slug}/tickets" as const;
/** How long a feature's tickets read for a session's name stay fresh. */
const TICKETS_STALE_MS = 5 * 60_000;
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
