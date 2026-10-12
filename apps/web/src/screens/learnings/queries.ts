import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import type { components } from "../../api/schema";
import { apiKey, useApi } from "../../lib/api";
import { useGlobalStream } from "../../shell/GlobalStream";

export type LearningStatus = components["schemas"]["LearningStatus"];

/** The learnings of one status, for every hub or the scoped project. */
export function useLearnings(project: string | null, status: LearningStatus) {
  return useApi("/api/v1/learnings", { query: { project, status, limit: 200 } });
}

/** Refetches when the global stream's count of proposed learnings changes (Live). */
export function useLiveLearnings(): void {
  const client = useQueryClient();
  const { counts } = useGlobalStream();
  const proposed = counts?.learnings_proposed;
  const seen = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (proposed === undefined) return;
    if (seen.current !== undefined && seen.current !== proposed) {
      void client.invalidateQueries({ queryKey: apiKey("/api/v1/learnings") });
    }
    seen.current = proposed;
  }, [client, proposed]);
}
