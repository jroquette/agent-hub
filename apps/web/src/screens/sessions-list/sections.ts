/* Sessions in four status sections, needs-me first (ADR 0033 D3, D4; spec 14). */
import { queryOf } from "./filters";
import type { AgentSession, Session, SessionQuery } from "./queries";

export type SectionId = "waiting" | "live" | "idle" | "ended";

export const SECTIONS: { id: SectionId; title: string }[] = [
  { id: "waiting", title: "Waiting for you" },
  { id: "live", title: "Live" },
  { id: "idle", title: "Idle" },
  { id: "ended", title: "Ended" },
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
 * every section but the status (a tab, applied on screen); an outcome keeps Ended, and the period
 * filters Ended only, so a running session older than the period still shows (O-4).
 */
export function sectionQueries(
  params: URLSearchParams,
  project: string | null,
  now: number,
): Record<SectionId, SessionQuery | null> {
  // The status tab only picks which group shows: every section is asked, so each tab has its count.
  const base: SessionQuery = { ...queryOf(params, project, now) };
  const { from } = base;
  delete base.from;
  delete base.status;
  const only: SectionId | undefined = base.outcome ? "ended" : undefined;
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
 * D3) and shows as waiting. A loaded row naming a driven session makes it a twin even while the
 * agent list still says otherwise. Ended's twinless rows start at `endedFrom`, as its query's
 * `from` bounds `started_at` (O-4: the other sections are not bounded).
 */
export function placeDriven(
  observed: Record<SectionId, readonly Session[]>,
  driven: readonly AgentSession[],
  asked: ReadonlySet<SectionId>,
  endedFrom: string | null = null,
): Record<SectionId, Placed> {
  const named = new Set(SECTIONS.flatMap(({ id }) => observed[id].map((s) => s.agent_session_id)));
  const twinned = (a: AgentSession) => Boolean(a.observed_session_id) || named.has(a.id);
  const waitingTwins = new Set(
    driven.filter((a) => a.status === "waiting_permission" && twinned(a)).map((a) => a.id),
  );
  const inPeriod = (a: AgentSession) =>
    endedFrom === null ||
    sectionOf(a.status) !== "ended" ||
    Date.parse(a.created_at) >= Date.parse(endedFrom);
  const twinless = driven
    .filter((a) => !twinned(a) && asked.has(sectionOf(a.status)) && inPeriod(a))
    .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
  // A twin's row reads the driven session's title (its first prompt, redacted, then the title
  // Claude Code gave it once a turn ends) until Claude Code's title reaches the label.
  const prompts = new Map<string, string>();
  for (const a of driven) {
    if (!a.title) continue;
    prompts.set(a.id, a.title);
    if (a.observed_session_id) prompts.set(a.observed_session_id, a.title);
  }
  const withPrompt = (s: Session): Session => {
    const prompt = prompts.get(s.agent_session_id ?? "") ?? prompts.get(s.id);
    if (!prompt || !s.label || s.label.title) return s;
    return { ...s, label: { ...s.label, title: prompt } };
  };
  const moved: Session[] = [];
  const kept = (id: SectionId) =>
    observed[id].map(withPrompt).filter((s) => {
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
    placed[id] = {
      rows: [...own, ...rows],
      added: own.length,
      removed: observed[id].length - rows.length,
    };
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
