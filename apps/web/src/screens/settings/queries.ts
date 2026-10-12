import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { components } from "../../api/schema";
import { apiDelete, apiPost, useApi, type ApiProblem } from "../../lib/api";

type HubView = components["schemas"]["HubView"];

export function useHubs() {
  return useApi("/api/v1/hubs");
}

export function useCollectorStatus() {
  return useApi("/api/v1/collector/status");
}

export function useSettings() {
  return useApi("/api/v1/settings");
}

function useHubWrite<T, V>(mutationFn: (value: V) => Promise<T>) {
  const client = useQueryClient();
  return useMutation<T, ApiProblem, V>({
    mutationFn,
    // Every view of a project reads the registry: refresh them all.
    onSuccess: () => client.invalidateQueries({ queryKey: ["api"] }),
  });
}

/** `POST /hubs`: one of the two writes of Phase 2. */
export function useRegisterHub() {
  return useHubWrite<HubView, string>((path) => apiPost("/api/v1/hubs", { path }));
}

/** `DELETE /hubs/{id}`: the other write; the hub's events stay in the store. */
export function useRemoveHub() {
  return useHubWrite<undefined, string>(async (hubId) => {
    await apiDelete("/api/v1/hubs/{hub_id}", { path: { hub_id: hubId } });
    return undefined;
  });
}
