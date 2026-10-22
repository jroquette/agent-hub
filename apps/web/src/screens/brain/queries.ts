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

/** A query holds a word when it has a letter or a digit; the search route refuses any other. */
export function hasWord(query: string): boolean {
  return /[\p{L}\p{N}]/u.test(query);
}

/**
 * The AGH-391 index's matches for `q` in the project's hub and its repos' docs, best first
 * (AGH-393). Nothing is fetched while `enabled` is false; `limit` is the route's, 50 by default.
 */
export function useKnowledgeSearch(
  project: string,
  q: string,
  { limit, enabled = true }: { limit?: number | undefined; enabled?: boolean | undefined } = {},
) {
  return useApi(
    "/api/v1/projects/{project}/knowledge/search",
    { path: { project }, query: limit === undefined ? { q } : { q, limit } },
    { enabled },
  );
}
