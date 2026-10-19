import { useMemo } from "react";

import type { TicketSlugs } from "../../components";
import { useApi } from "../../lib/api";
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
 * The slug of each ticket a hub feature works on (`ACME-12` → `checkout-redesign`), so a session
 * on that ticket is named `ACME-12: checkout-redesign`. It reads the Features list's cache (no
 * polling of its own); the first feature naming a ticket wins.
 */
export function useTicketSlugs(project: string | null = null): TicketSlugs {
  const items = useApi("/api/v1/features", { query: { project } }, { staleTime: 60_000 }).data
    ?.items;
  return useMemo(() => {
    const slugs = new Map<string, string>();
    for (const feature of items ?? [])
      for (const issue of feature.issues) {
        const id = issueId(issue).toUpperCase();
        if (!slugs.has(id)) slugs.set(id, feature.slug);
      }
    return slugs;
  }, [items]);
}

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
