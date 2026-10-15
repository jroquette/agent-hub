/* Sessions in four status sections, needs-me first (ADR 0033 D3, D4; spec 14). */
import { queryOf } from "./filters";
import type { SessionQuery } from "./queries";

export type SectionId = "waiting" | "live" | "idle" | "ended";

export const SECTIONS: { id: SectionId; title: string }[] = [
  { id: "waiting", title: "Waiting" },
  { id: "live", title: "Live" },
  { id: "idle", title: "Idle" },
  { id: "ended", title: "Ended or failed" },
];

const SECTION_OF: Record<string, SectionId> = {
  waiting: "waiting",
  waiting_permission: "waiting",
  live: "live",
  running: "live",
  idle: "idle",
  ended: "ended",
  failed: "ended",
};

/** The section of an observed (`Session`) or driven (`AgentSession`) status. */
export function sectionOf(status: string): SectionId {
  return SECTION_OF[status] ?? "ended";
}

/**
 * One `GET /sessions` query per section (null: the section is not asked). The URL's filters apply to
 * every section; a status facet keeps its own section, an outcome keeps Ended, and the period
 * filters Ended only, so a running session older than the period still shows (O-4).
 */
export function sectionQueries(
  params: URLSearchParams,
  project: string | null,
  now: number,
): Record<SectionId, SessionQuery | null> {
  const { from, status, ...base } = queryOf(params, project, now);
  const only: SectionId | undefined = status ?? (base.outcome ? "ended" : undefined);
  const ask = (id: SectionId): SessionQuery | null => {
    if (only && only !== id) return null;
    return id === "ended" && from ? { ...base, status: id, from } : { ...base, status: id };
  };
  return { waiting: ask("waiting"), live: ask("live"), idle: ask("idle"), ended: ask("ended") };
}

/** A section's header count: its query's `total_estimate` plus its driven rows without a twin (P-e). */
export function sectionCount(
  observedTotal: number,
  twinlessDriven: readonly unknown[] = [],
): number {
  return observedTotal + twinlessDriven.length;
}
