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
