import { useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import type { components } from "../../api/schema";
import { apiKey, apiPost, useApi, type ApiProblem } from "../../lib/api";
import { CHECK_POLL_MS, useCheckPoll } from "../../lib/checkPoll";
import { useGlobalStream } from "../../shell/GlobalStream";

type DoctorFindings = components["schemas"]["DoctorFindings"];

/** When the browser got the last Fix's answer (ms), kept in the query cache for `useFindings`. */
const FIX_ANSWERED_AT = ["health", "fix-answered-at"] as const;
/** How long after a Fix the findings are read again while their check is older than the Fix. */
const FIX_POLL_FOR_MS = 60_000;

/** True while the findings' check is not yet later than a Fix answered in the last minute: the
 * Fix marks its hub due, and the background doctor checks it again at its next tick (AGH-608). */
function awaitingFixCheck(client: QueryClient, checkedAt: string | null): boolean {
  const fixedAt = client.getQueryData<number>(FIX_ANSWERED_AT);
  if (fixedAt === undefined || Date.now() - fixedAt >= FIX_POLL_FOR_MS) return false;
  return checkedAt === null || Date.parse(checkedAt) <= fixedAt;
}

/**
 * Doctor findings of every registered hub, or of the scoped project, from the doctor hub web runs
 * in the background (AGH-608): read again while no check has ended, and after a Fix until a check
 * later than it.
 */
export function useFindings(project: string | null) {
  const client = useQueryClient();
  const uncheckedPoll = useCheckPoll((data: DoctorFindings) => data.checked_at === null);
  return useApi(
    "/api/v1/doctor/findings",
    { query: { project } },
    {
      refetchInterval: (query) => {
        const data = query.state.data;
        if (data && awaitingFixCheck(client, data.checked_at)) return CHECK_POLL_MS;
        return uncheckedPoll(query);
      },
    },
  );
}

export function useHubs() {
  return useApi("/api/v1/hubs");
}

/** Refetches the findings when the global stream's doctor error count changes (Live). */
export function useLiveFindings(): void {
  const client = useQueryClient();
  const { counts } = useGlobalStream();
  const errors = counts?.doctor_errors;
  const seen = useRef<number | null | undefined>(undefined);
  useEffect(() => {
    if (errors === undefined) return;
    if (seen.current !== undefined && seen.current !== errors) {
      void client.invalidateQueries({ queryKey: apiKey("/api/v1/doctor/findings") });
    }
    seen.current = errors;
  }, [client, errors]);
}

type DoctorFixResult = components["schemas"]["DoctorFixResult"];

/** `POST /hubs/{id}/doctor-fix`: `hub doctor --fix` in the hub, then the findings read again
 * (and, through `useFindings`, again until the background check is later than the Fix). */
export function useFixHub() {
  const client = useQueryClient();
  return useMutation<DoctorFixResult, ApiProblem, string>({
    mutationFn: (hubId) =>
      apiPost("/api/v1/hubs/{hub_id}/doctor-fix", {}, { path: { hub_id: hubId } }),
    onSuccess: () => {
      client.setQueryData(FIX_ANSWERED_AT, Date.now());
      return client.invalidateQueries({ queryKey: ["api"] });
    },
  });
}
