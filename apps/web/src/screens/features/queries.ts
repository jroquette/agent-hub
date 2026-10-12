import { useApi } from "../../lib/api";

/** Feature records of every registered hub, or of the scoped project (D23). */
export function useFeatures(project: string | null) {
  return useApi("/api/v1/features", { query: { project } });
}
