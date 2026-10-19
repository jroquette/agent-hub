import { useApi } from "../../lib/api";

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
