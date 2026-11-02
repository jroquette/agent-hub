import {
  skipToken,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import { useEffect, useReducer, useRef } from "react";

import type { components } from "../../api/schema";
import { apiKey, apiPost, useApi, type ApiProblem } from "../../lib/api";
import { CHECK_POLL_MS, useCheckPoll } from "../../lib/checkPoll";
import { useGlobalStream } from "../../shell/GlobalStream";

type DoctorFindings = components["schemas"]["DoctorFindings"];

/** The last Fix answered: the hub it fixed, and when the browser got the answer (ms). */
interface FixAnswer {
  hubId: string;
  at: number;
}

/** The last Fix answered (`FixAnswer`), kept in the query cache for `useFindings`. */
const FIX_ANSWERED_AT = ["health", "fix-answered-at"] as const;
/** How long after a Fix the findings are read again while their check is older than the Fix. */
const FIX_POLL_FOR_MS = 60_000;

/** True while the scope is the one hub a Fix answered in the last minute fixed and the findings'
 * check is not yet later than that Fix: the Fix marks its hub due, and the background doctor
 * checks it again at its next tick (AGH-608). Another hub's scope, or several hubs, never wait. */
function isAwaitingFixCheck(
  fix: FixAnswer | undefined,
  scopeHubId: string | undefined,
  checkedAt: string | null,
): boolean {
  if (fix === undefined || fix.hubId !== scopeHubId) return false;
  if (Date.now() - fix.at >= FIX_POLL_FOR_MS) return false;
  return checkedAt === null || Date.parse(checkedAt) <= fix.at;
}

function awaitingFixCheck(
  client: QueryClient,
  scopeHubId: string | undefined,
  checkedAt: string | null,
): boolean {
  return isAwaitingFixCheck(client.getQueryData<FixAnswer>(FIX_ANSWERED_AT), scopeHubId, checkedAt);
}

/**
 * Whether the findings shown still wait for the check after a Fix of `scopeHubId`, the scope's
 * one hub (see `isAwaitingFixCheck`): the screen keeps that Fix pending meanwhile. Renders again
 * when a Fix is answered and when the minute after it ends, so the wait never outlives the reads.
 */
export function useAwaitingFixCheck(
  checkedAt: string | null | undefined,
  scopeHubId: string | undefined,
): boolean {
  const { data: fix } = useQuery<FixAnswer>({ queryKey: FIX_ANSWERED_AT, queryFn: skipToken });
  const [, rerender] = useReducer((n: number) => n + 1, 0);
  const awaiting = checkedAt !== undefined && isAwaitingFixCheck(fix, scopeHubId, checkedAt);
  const fixedAt = fix?.at;
  useEffect(() => {
    if (!awaiting || fixedAt === undefined) return;
    const timer = setTimeout(rerender, fixedAt + FIX_POLL_FOR_MS - Date.now());
    return () => {
      clearTimeout(timer);
    };
  }, [awaiting, fixedAt]);
  return awaiting;
}

/**
 * Doctor findings of every registered hub, or of the scoped project, from the doctor hub web runs
 * in the background (AGH-608): read again while no check has ended, and after a Fix of
 * `scopeHubId`, the scope's one hub, until a check later than it.
 */
export function useFindings(project: string | null, scopeHubId: string | undefined) {
  const client = useQueryClient();
  const uncheckedPoll = useCheckPoll((data: DoctorFindings) => data.checked_at === null);
  return useApi(
    "/api/v1/doctor/findings",
    { query: { project } },
    {
      refetchInterval: (query) => {
        const data = query.state.data;
        if (data && awaitingFixCheck(client, scopeHubId, data.checked_at)) return CHECK_POLL_MS;
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
    onSuccess: (result) => {
      client.setQueryData<FixAnswer>(FIX_ANSWERED_AT, { hubId: result.hub_id, at: Date.now() });
      return client.invalidateQueries({ queryKey: ["api"] });
    },
  });
}
