import { useApi } from "../../lib/api";

/** The `.md` notes of a project's brain (`auto/` excluded), sorted by path (D3). */
export function useBrainTree(project: string) {
  return useApi("/api/v1/projects/{project}/brain", { path: { project } });
}

/** One brain note by its path under `brain/`; nothing is fetched while `enabled` is false. */
export function useBrainNote(project: string, path: string, enabled = true) {
  return useApi(
    "/api/v1/projects/{project}/brain/note",
    { path: { project }, query: { path } },
    { enabled },
  );
}
