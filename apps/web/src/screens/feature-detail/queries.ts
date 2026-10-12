import { useApi } from "../../lib/api";

/** One feature record with its acceptance criteria rows (D23). */
export function useFeature(project: string, slug: string) {
  return useApi("/api/v1/features/{project}/{slug}", { path: { project, slug } });
}
