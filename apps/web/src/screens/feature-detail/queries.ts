import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { apiKey, useApi } from "../../lib/api";

/** One feature record with its acceptance criteria rows (D23). */
export function useFeature(project: string, slug: string) {
  return useApi("/api/v1/features/{project}/{slug}", { path: { project, slug } });
}

/**
 * The feature's tickets (AC-136.28, .31): the only route that reads Linear, so it is asked only
 * when `enabled` (the Tickets tab is open); its cached answer still names the header chips. Each
 * new answer warms the server's snapshot cache, so the feature detail and the list are
 * invalidated and their golden path refetches with it.
 */
export function useFeatureTickets(project: string, slug: string, enabled: boolean) {
  const client = useQueryClient();
  const tickets = useApi(
    "/api/v1/features/{project}/{slug}/tickets",
    { path: { project, slug } },
    { enabled },
  );
  const seen = useRef(tickets.dataUpdatedAt);
  const updatedAt = tickets.isSuccess ? tickets.dataUpdatedAt : 0;
  useEffect(() => {
    if (updatedAt === 0 || updatedAt === seen.current) return;
    seen.current = updatedAt;
    void client.invalidateQueries({
      queryKey: apiKey("/api/v1/features/{project}/{slug}", { path: { project, slug } }),
      exact: true,
    });
    void client.invalidateQueries({ queryKey: ["api", "/api/v1/features"] });
  }, [client, project, slug, updatedAt]);
  return tickets;
}
