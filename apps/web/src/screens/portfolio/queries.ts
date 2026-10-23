import { keepPreviousData, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import type { components } from "../../api/schema";
import { useApi, type GetPath } from "../../lib/api";
import { useGlobalStream } from "../../shell/GlobalStream";

export type ProjectSummary = components["schemas"]["ProjectSummary"];
export type NeedsYouItem = components["schemas"]["NeedsYouItem"];
export type ActivityItem = components["schemas"]["ActivityItem"];
export type UsageReport = components["schemas"]["UsageReport"];
export type UsageRow = components["schemas"]["UsageRow"];
export type UsageDays = components["schemas"]["UsageDays"];

/**
 * Live: when the global stream's `counts` change, the given API families refetch (the stream
 * says that something changed, the read models say what). The first counts only arm it.
 */
export function useRefreshOnCounts(paths: readonly GetPath[]): void {
  const { counts } = useGlobalStream();
  const client = useQueryClient();
  const key = counts ? JSON.stringify(counts) : null;
  const seen = useRef<string | null>(null);
  const families = paths.join(" ");
  useEffect(() => {
    if (key === null) return;
    if (seen.current !== null && seen.current !== key) {
      for (const path of families.split(" ")) {
        void client.invalidateQueries({ queryKey: ["api", path] });
      }
    }
    seen.current = key;
  }, [key, families, client]);
}

export function useProjects(project: string | null) {
  return useApi("/api/v1/projects", { query: { project } });
}

export function useNeedsYou(project: string | null) {
  return useApi("/api/v1/needs-you", { query: { project } });
}

export function useActivity(project: string | null, limit: number) {
  return useApi("/api/v1/activity", { query: { project, limit } });
}

/** The hub skills and agents with their runs, never used in `days` first (AGH-482). */
export function useSkillUsage(project: string | null, days: UsageDays) {
  // A window change keeps the shown table until the new report arrives (no flash, no jump);
  // a project change shows the skeleton, so another project's rows never stand in.
  return useApi(
    "/api/v1/skill-usage",
    { query: { project, days } },
    {
      placeholderData: (previous, previousQuery) => {
        // The key is apiKey's ["api", path, { query }]: the project the shown rows are for.
        const params: { query?: { project?: string | null } } | undefined =
          previousQuery?.queryKey[2];
        const before = params?.query?.project;
        return before === project ? keepPreviousData(previous) : undefined;
      },
    },
  );
}
