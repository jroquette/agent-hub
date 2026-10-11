import { useApi } from "../../lib/api";

/** How often a step that waits for something checks again (spec 22: every 2 s). */
export const CHECK_MS = 2_000;

export function useHubs() {
  return useApi("/api/v1/hubs");
}

/** The server's status, polled while the API does not answer. */
export function useServerStatus() {
  return useApi("/api/v1/collector/status", undefined, {
    refetchInterval: (query) => (query.state.status === "success" ? false : CHECK_MS),
    retry: false,
  });
}

export function useSettings() {
  return useApi("/api/v1/settings");
}

/** The newest session, polled until the first one arrives (step 3). */
export function useFirstSession(enabled: boolean) {
  return useApi(
    "/api/v1/sessions",
    { query: { limit: 1, sort: "-started_at" } },
    {
      enabled,
      refetchInterval: (query) => ((query.state.data?.items.length ?? 0) > 0 ? false : CHECK_MS),
    },
  );
}
