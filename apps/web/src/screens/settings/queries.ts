import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { components } from "../../api/schema";
import { apiDelete, apiGet, apiKey, apiPost, apiPut, useApi, ApiProblem } from "../../lib/api";

type HubView = components["schemas"]["HubView"];
type LinearConnectionView = components["schemas"]["LinearConnectionView"];

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

/** `GET /tracker/linear`: whether hub web reads Linear (checked against Linear, cached 60 s). */
export function useLinearConnection() {
  return useApi("/api/v1/tracker/linear");
}

function useLinearWrite<V>(mutationFn: (value: V) => Promise<LinearConnectionView>) {
  const client = useQueryClient();
  return useMutation<LinearConnectionView, ApiProblem, V>({
    mutationFn,
    onSuccess: (view) => {
      client.setQueryData(apiKey("/api/v1/tracker/linear"), view);
      // A feature's tickets read Linear too: read them again with the new key.
      void client.invalidateQueries({
        predicate: (query) => String(query.queryKey[1]).startsWith("/api/v1/features"),
      });
    },
  });
}

/** `PUT /tracker/linear`: check a key and save it when Linear accepts it. */
export function useConnectLinear() {
  return useLinearWrite<string>(async (key) => {
    const view = await apiPut("/api/v1/tracker/linear", { api_key: key });
    // A refused key is not saved: keep the current connection, show why under the input.
    if (!view.connected && view.source !== "environment") {
      throw new ApiProblem({ status: 422, title: "Linear refused the key", detail: view.problem });
    }
    return view;
  });
}

/** `DELETE /tracker/linear`: forget the saved key, then read where the connection stands. */
export function useDisconnectLinear() {
  return useLinearWrite<undefined>(async () => {
    await apiDelete("/api/v1/tracker/linear", {});
    return apiGet("/api/v1/tracker/linear");
  });
}

/** `GET /tracker/linear?fresh=true`: check against Linear now. */
export function useCheckLinear() {
  return useLinearWrite<undefined>(() =>
    apiGet("/api/v1/tracker/linear", { query: { fresh: true } }),
  );
}
