import { createContext, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { collectorState, type CollectorState } from "../components/CollectorPill";
import { useNow } from "../lib/clock";
import { useEventStream, type StreamHealth } from "../lib/sse";

/** The global stream's `counts` message (StreamCounts in core). */
export interface StreamCounts {
  approvals_open: number;
  live_sessions: number;
  failed_runs_7d: number;
  learnings_proposed: number;
  doctor_errors?: number | null;
  ready_issues?: number | null;
}

export const GLOBAL_STREAM = "/api/v1/events/stream";

interface GlobalStreamValue {
  health: StreamHealth;
  counts: StreamCounts | null;
}

const GlobalStreamContext = createContext<GlobalStreamValue>({
  health: { open: false, lastMessageAt: 0, closedSince: null },
  counts: null,
});

function isCounts(data: unknown): data is StreamCounts {
  return (
    typeof data === "object" &&
    data !== null &&
    typeof (data as { approvals_open?: unknown }).approvals_open === "number" &&
    typeof (data as { live_sessions?: unknown }).live_sessions === "number"
  );
}

/** Keeps the global stream open for the shell: badge counts and the collector's health. */
export function GlobalStreamProvider({
  project,
  children,
}: {
  project: string | null;
  children: ReactNode;
}) {
  const [counts, setCounts] = useState<StreamCounts | null>(null);
  const url = project ? `${GLOBAL_STREAM}?project=${encodeURIComponent(project)}` : GLOBAL_STREAM;
  const health = useEventStream(url, {
    counts: (data) => {
      if (isCounts(data)) setCounts(data);
    },
  });
  const value = useMemo(() => ({ health, counts }), [health, counts]);
  return <GlobalStreamContext.Provider value={value}>{children}</GlobalStreamContext.Provider>;
}

export function useGlobalStream(): GlobalStreamValue {
  return useContext(GlobalStreamContext);
}

/**
 * The collector's state now (Connected, Delayed, Offline) and the time of the last data, for
 * screens that show `AsOfStamp` or go stale while offline (AC-200.43).
 */
export function useCollectorState(): { state: CollectorState; asOf: Date } {
  const { health } = useGlobalStream();
  const now = useNow(1000);
  return { state: collectorState(health, now), asOf: new Date(health.lastMessageAt) };
}
