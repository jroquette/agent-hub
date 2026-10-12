import { useQueryClient } from "@tanstack/react-query";

import { apiKey, useApi } from "../../lib/api";
import { useEventStream } from "../../lib/sse";

export function useRun(runId: string) {
  return useApi("/api/v1/workflow-runs/{run_id}", { path: { run_id: runId } });
}

/**
 * Live: while the run has not ended, its stream's `run`, `step` and `gate` messages (and a
 * `reset`) refetch the run, so the folded view stays the API's.
 */
export function useRunStream(runId: string, live: boolean): void {
  const client = useQueryClient();
  const refresh = () => {
    void client.invalidateQueries({
      queryKey: apiKey("/api/v1/workflow-runs/{run_id}", { path: { run_id: runId } }),
    });
  };
  useEventStream(live ? `/api/v1/workflow-runs/${encodeURIComponent(runId)}/stream` : null, {
    run: refresh,
    step: refresh,
    gate: refresh,
    reset: refresh,
  });
}
