import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { components } from "../../api/schema";
import { apiKey, apiPost, useApi, type ApiProblem } from "../../lib/api";

export type Approval = components["schemas"]["Approval"];

export type WorkflowGate = components["schemas"]["WorkflowGate"];
export type GateDecided = components["schemas"]["GateDecided"];
export type GateDecisionRequest = components["schemas"]["GateDecisionRequest"];

/** What answers an open workflow gate (its decisions or options, and whether it takes text). */
export function useWorkflowGate(id: string, enabled = true) {
  return useApi(
    "/api/v1/approvals/{approval_id}/gate",
    { path: { approval_id: id } },
    { enabled, retry: false },
  );
}

/** Records a person's answer to the gate, then the run resumes; its events tell the rest. */
export function useDecideGate(id: string) {
  const client = useQueryClient();
  const path = { path: { approval_id: id } };
  return useMutation<GateDecided, ApiProblem, GateDecisionRequest>({
    mutationFn: (body) => apiPost("/api/v1/approvals/{approval_id}/decision", body, path),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: apiKey("/api/v1/approvals") });
      void client.invalidateQueries({ queryKey: apiKey("/api/v1/approvals/{approval_id}", path) });
      // Not the gate itself: once decided it answers 409; the approvals refetched close its card.
      void client.invalidateQueries({ queryKey: apiKey("/api/v1/workflow-runs") });
    },
  });
}
