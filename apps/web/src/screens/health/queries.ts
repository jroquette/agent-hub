import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { apiKey, useApi } from "../../lib/api";
import { useGlobalStream } from "../../shell/GlobalStream";

/** Doctor findings of every registered hub, or of the scoped project (D22: run on request). */
export function useFindings(project: string | null) {
  return useApi("/api/v1/doctor/findings", { query: { project } });
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
