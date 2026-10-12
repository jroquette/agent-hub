import { useInfiniteQuery } from "@tanstack/react-query";

import type { components } from "../../api/schema";
import { apiGet, apiKey, useApi, type ApiParams, type ApiProblem } from "../../lib/api";

export type Session = components["schemas"]["Session"];
type SessionPage = components["schemas"]["Page_Session_"];
export type SessionQuery = NonNullable<ApiParams<"/api/v1/sessions">["query"]>;

/** Rows per page ("Showing 50 of ~1,240"). */
export const PAGE_SIZE = 50;

/** Sessions matching `query`, page by page; "Load more" asks for the next cursor (spec 14). */
export function useSessionPages(query: SessionQuery) {
  return useInfiniteQuery<
    SessionPage,
    ApiProblem,
    { pages: SessionPage[] },
    readonly unknown[],
    string | null
  >({
    queryKey: [...apiKey("/api/v1/sessions", { query }), "pages"],
    initialPageParam: null,
    queryFn: ({ pageParam, signal }) =>
      apiGet(
        "/api/v1/sessions",
        { query: { ...query, limit: PAGE_SIZE, cursor: pageParam } },
        signal,
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
}

/** The registered projects, for the Project facet. */
export function useProjects() {
  return useApi("/api/v1/projects");
}
