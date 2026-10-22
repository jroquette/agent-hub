import { useEffect, useRef } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { components } from "../../api/schema";
import { apiKey, apiPost, useApi, type ApiProblem } from "../../lib/api";

/**
 * How often an open feature screen rereads its record (local files: cheap) and, on the Tickets
 * tab, Linear. The server caches Linear for 60 s, so a tickets poll costs at most one tracker
 * request a minute; a hidden tab does not poll.
 */
export const FEATURE_REFRESH_MS = 15_000;
export const TICKETS_REFRESH_MS = 30_000;

/** One feature record with its acceptance criteria rows (D23), kept fresh while open. */
export function useFeature(project: string, slug: string) {
  return useApi(
    "/api/v1/features/{project}/{slug}",
    { path: { project, slug } },
    { refetchInterval: FEATURE_REFRESH_MS },
  );
}

/**
 * The feature's tickets (AC-136.28, .31): the only route that reads Linear, so it is asked only
 * when `enabled` (the Tickets tab is open), and then every `TICKETS_REFRESH_MS`; its cached answer still names the header chips. Each
 * new answer warms the server's snapshot cache, so the feature detail and the list are
 * invalidated and their golden path refetches with it.
 */
export function useFeatureTickets(project: string, slug: string, enabled: boolean) {
  const client = useQueryClient();
  const tickets = useApi(
    "/api/v1/features/{project}/{slug}/tickets",
    { path: { project, slug } },
    { enabled, refetchInterval: enabled ? TICKETS_REFRESH_MS : false },
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

/**
 * One ticket's records the ticket panel shows (two-level-flows A7): its brief, every preflight
 * run and the change requests it asks or is held by, kept fresh as the feature is.
 */
export function useTicketRecords(project: string, slug: string, ticket: string) {
  return useApi(
    "/api/v1/features/{project}/{slug}/tickets/{ticket}",
    { path: { project, slug, ticket } },
    { refetchInterval: FEATURE_REFRESH_MS, retry: false },
  );
}

type ChangeRequestView = components["schemas"]["ChangeRequestView"];
type ChangeRequestDecisionBody = components["schemas"]["ChangeRequestDecisionBody"];

/**
 * The owner's decision on a change request whose run has no open gate (AC-2.14): recorded in the
 * hub, then the feature, its tickets and the ticket's records are read again.
 */
export function useDecideChangeRequest(project: string, slug: string, n: number) {
  const client = useQueryClient();
  return useMutation<ChangeRequestView, ApiProblem, ChangeRequestDecisionBody>({
    mutationFn: (body) =>
      apiPost("/api/v1/features/{project}/{slug}/change-requests/{n}/decision", body, {
        path: { project, slug, n },
      }),
    onSuccess: () => {
      const path = { path: { project, slug } };
      for (const key of [
        apiKey("/api/v1/features"),
        apiKey("/api/v1/features/{project}/{slug}", path),
        apiKey("/api/v1/features/{project}/{slug}/tickets", path),
        ["api", "/api/v1/features/{project}/{slug}/tickets/{ticket}"],
      ]) {
        void client.invalidateQueries({ queryKey: key });
      }
    },
  });
}
