/* Sessions in four status sections, needs-me first (ADR 0033 D3, D4; spec 14). */
import { queryOf } from "./filters";
import type { AgentSession, Session, SessionQuery } from "./queries";

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

/** A row of a section: an observed session, or a driven one without an observed twin (D2, Q4). */
export type SectionRow = Session | AgentSession;

export const isDriven = (row: SectionRow): row is AgentSession => "workdir_id" in row;

/** A section's rows and how many of them are not in its own query's total (P-e). */
export interface Placed {
  rows: SectionRow[];
  added: number;
  removed: number;
}

/**
 * Places the driven sessions into the asked sections. One without a twin joins its status's section,
 * newest `created_at` first, ahead of the observed rows (Q4). A twin is shown once, as its observed
 * row; when its driven session waits on a permission, that row moves to Waiting (needs-me first,
 * D3) and shows as waiting.
 */
export function placeDriven(
  observed: Record<SectionId, readonly Session[]>,
  driven: readonly AgentSession[],
  asked: ReadonlySet<SectionId>,
): Record<SectionId, Placed> {
  const waitingTwins = new Set(
    driven.filter((a) => a.status === "waiting_permission" && a.observed_session_id).map((a) => a.id),
  );
  const twinless = driven
    .filter((a) => !a.observed_session_id && asked.has(sectionOf(a.status)))
    .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
  const moved: Session[] = [];
  const kept = (id: SectionId) =>
    observed[id].filter((s) => {
      const move =
        id !== "waiting" &&
        asked.has("waiting") &&
        s.agent_session_id != null &&
        waitingTwins.has(s.agent_session_id);
      if (move) moved.push({ ...s, status: "waiting" });
      return !move;
    });
  const placed = {} as Record<SectionId, Placed>;
  for (const { id } of SECTIONS) {
    const own = twinless.filter((a) => sectionOf(a.status) === id);
    const rows = kept(id);
    placed[id] = { rows: [...own, ...rows], added: own.length, removed: observed[id].length - rows.length };
  }
  placed.waiting.rows.splice(placed.waiting.added, 0, ...moved);
  placed.waiting.added += moved.length;
  return placed;
}

/** A section's header count: its query's `total_estimate` plus the rows placed into it, less those moved out (P-e). */
export function sectionCount(
  observedTotal: number,
  placed: Pick<Placed, "added" | "removed"> = { added: 0, removed: 0 },
): number {
  return observedTotal + placed.added - placed.removed;
}
