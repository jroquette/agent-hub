import { useQueryClient } from "@tanstack/react-query";

import { apiKey, useApi } from "../../lib/api";
import { useEventStream } from "../../lib/sse";

export function useRun(runId: string) {
  return useApi("/api/v1/workflow-runs/{run_id}", { path: { run_id: runId } });
}

/**
 * Live: while the run has not ended, its stream's `run`, `step` and `gate` messages (and a
 * `reset`) refetch the run, so the folded view stays the API's; `gate` and `reset` refetch the
 * open approvals too, which list the run's open gates.
 */
export function useRunStream(runId: string, live: boolean): void {
  const client = useQueryClient();
  const refresh = () => {
    void client.invalidateQueries({
      queryKey: apiKey("/api/v1/workflow-runs/{run_id}", { path: { run_id: runId } }),
    });
  };
  // A gate message opens or closes a gate: the open gates (Approvals) refetch too.
  const refreshGates = () => {
    refresh();
    void client.invalidateQueries({ queryKey: apiKey("/api/v1/approvals") });
  };
  useEventStream(live ? `/api/v1/workflow-runs/${encodeURIComponent(runId)}/stream` : null, {
    run: refresh,
    step: refresh,
    gate: refreshGates,
    reset: refreshGates,
  });
}
