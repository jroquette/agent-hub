import { useQueryClient } from "@tanstack/react-query";

import type { components } from "../../api/schema";
import { apiKey, useApi } from "../../lib/api";
import { useEventStream, type StreamHealth } from "../../lib/sse";

export type LiveTile = components["schemas"]["LiveTile"];
type TilePage = components["schemas"]["Page_LiveTile_"];

function params(project: string | null) {
  return project ? { query: { project } } : undefined;
}

function isTile(data: unknown): data is LiveTile {
  return (
    typeof data === "object" &&
    data !== null &&
    typeof (data as { id?: unknown }).id === "string" &&
    typeof (data as { group?: unknown }).group === "string"
  );
}

/**
 * The live tiles of `project` (null: all), kept current by `/live-sessions/stream`:
 * `tile.upsert` patches or inserts a tile, `tile.remove` drops it (spec 11, "SSE behaviour").
 */
export function useLiveTiles(project: string | null): {
  query: ReturnType<typeof useApi<"/api/v1/live-sessions">>;
  health: StreamHealth;
} {
  const queryClient = useQueryClient();
  const query = useApi("/api/v1/live-sessions", params(project));
  const key = apiKey("/api/v1/live-sessions", params(project));
  const url = `/api/v1/live-sessions/stream${project ? `?project=${encodeURIComponent(project)}` : ""}`;
  const health = useEventStream(query.data ? url : null, {
    "tile.upsert": (data) => {
      if (!isTile(data)) return;
      queryClient.setQueryData<TilePage>(key, (page) => {
        if (!page) return page;
        const known = page.items.some((tile) => tile.id === data.id);
        const items = known
          ? page.items.map((tile) => (tile.id === data.id ? { ...tile, ...data } : tile))
          : [...page.items, data];
        return { ...page, items, total_estimate: items.length };
      });
    },
    "tile.remove": (data) => {
      const id = (data as { id?: unknown } | null)?.id;
      if (typeof id !== "string") return;
      queryClient.setQueryData<TilePage>(key, (page) => {
        if (!page) return page;
        const items = page.items.filter((tile) => tile.id !== id);
        return { ...page, items, total_estimate: items.length };
      });
    },
    reset: () => {
      void queryClient.invalidateQueries({ queryKey: key });
    },
  });
  return { query, health };
}

/** The tiles of every project, read only when a scoped view is empty ("N running in other projects"). */
export function useAllLiveTiles(enabled: boolean) {
  return useApi("/api/v1/live-sessions", undefined, { enabled });
}
