import type { ActivityEntry, NeedsYouEntry, ProjectCardData, Stage } from "../../components";
import { STAGES } from "../../components";
import { fmtAgo, fmtMoney, toNumber } from "../../lib/format";
import type { ActivityItem, NeedsYouItem, ProjectSummary } from "./queries";

/* View models of the Portfolio: API bodies in, the design components' props out. */

/** Needs you shows this many rows before "Show N more" (working memory, spec 12). */
export const NEEDS_VISIBLE = 4;
/** Expanded, it shows at most this many. */
export const NEEDS_MAX = 12;

/** An agent blocked on a person first, then blocked sessions, failed runs, doctor, learnings. */
const KIND_ORDER: Record<NeedsYouItem["kind"], number> = {
  approval: 0,
  waiting: 0,
  blocked: 1,
  failed: 2,
  doctor: 3,
  learning: 4,
};

function sinceMs(item: NeedsYouItem): number {
  return item.since ? Date.parse(item.since) : Number.POSITIVE_INFINITY;
}

/** Kind priority, then the longest wait first (spec 12 ordering rules). */
export function orderNeeds(items: readonly NeedsYouItem[]): NeedsYouItem[] {
  return [...items].sort(
    (a, b) => KIND_ORDER[a.kind] - KIND_ORDER[b.kind] || sinceMs(a) - sinceMs(b),
  );
}

/**
 * Proposed learnings collapse into one "Triage N learnings" line per project (spec 12: learnings
 * are always one aggregated line), so they never push an approval or a failure out of view.
 */
export function groupLearnings(items: readonly NeedsYouItem[]): NeedsYouItem[] {
  const byProject = new Map<string, NeedsYouItem[]>();
  for (const item of items) {
    if (item.kind !== "learning") continue;
    byProject.set(item.project, [...(byProject.get(item.project) ?? []), item]);
  }
  const grouped: NeedsYouItem[] = items.filter(
    (item) => item.kind !== "learning" || (byProject.get(item.project)?.length ?? 0) < 2,
  );
  for (const [project, learnings] of byProject) {
    if (learnings.length < 2) continue;
    const oldest = learnings.reduce((a, b) => (sinceMs(a) <= sinceMs(b) ? a : b));
    grouped.push({
      ...oldest,
      verb: `Triage ${String(learnings.length)} learnings`,
      context: `${project} · proposed, waiting for review`,
      href: "/knowledge/learnings?status=proposed",
    });
  }
  return grouped;
}

/** "41 min", "2 h": how long an item has waited; "now" when it has no time. */
export function age(iso: string | null | undefined, now: number): string {
  if (!iso) return "now";
  return fmtAgo(Math.max(0, (now - Date.parse(iso)) / 1000)).replace(/ ago$/, "");
}

export function needsEntry(item: NeedsYouItem, now: number): NeedsYouEntry {
  return {
    kind: item.kind,
    verb: item.verb,
    context: item.context,
    age: age(item.since, now),
    href: item.href,
  };
}

/** "Show 2 more (Triage 3 learnings, Fix doctor error in agent-hub)". */
export function moreLabel(hidden: readonly NeedsYouItem[]): string {
  const names = hidden.slice(0, 2).map((item) => item.verb);
  const rest = hidden.length > 2 ? ", …" : "";
  return `Show ${String(hidden.length)} more (${names.join(", ")}${rest})`;
}

/** "+22.6 % vs $50.10"; a missing or zero previous period cannot be compared. */
export function costDelta(
  current: string | null,
  previous: string | null,
): { text: string; tone: "neutral" | "bad"; pct: number | null } {
  const now = toNumber(current) ?? 0;
  const before = toNumber(previous);
  if (before === null || before === 0) {
    return { text: "No previous period to compare", tone: "neutral", pct: null };
  }
  const pct = ((now - before) / before) * 100;
  const sign = pct > 0 ? "+" : pct < 0 ? "−" : "";
  return {
    text: `${sign}${Math.abs(pct).toFixed(1)} % vs ${fmtMoney(before)}`,
    // Red only for a deviation, not for every increase (spec 12).
    tone: pct > 50 ? "bad" : "neutral",
    pct,
  };
}

function isStage(key: string): key is Stage {
  return STAGES.some((stage) => stage.id === key);
}

export function stageCounts(byStage: Record<string, number>): Partial<Record<Stage, number>> {
  const counts: Partial<Record<Stage, number>> = {};
  for (const [key, n] of Object.entries(byStage)) if (isStage(key)) counts[key] = n;
  return counts;
}

export function inFlight(project: ProjectSummary): number {
  return Object.entries(project.runs_in_flight_by_stage)
    .filter(([key]) => isStage(key) && key !== "REPORTED")
    .reduce((sum, [, n]) => sum + n, 0);
}

const HEALTH_LABEL = {
  ok: "Health: no doctor errors or warnings",
  warning: "Health: doctor warnings",
  error: "Health: doctor errors",
} as const;

export function projectCard(project: ProjectSummary): ProjectCardData {
  const delta = costDelta(project.cost_period, project.cost_previous_period);
  return {
    name: project.name,
    hub: project.hub_repo,
    team: project.tracker_teams.join(" · "),
    version: project.platform_version,
    lockVersion: project.lock_version,
    syncPending: project.lock_state === "sync_pending" || project.lock_state === "drift",
    repos: project.repos,
    health: project.hub_health,
    healthLabel: project.hub_health
      ? HEALTH_LABEL[project.hub_health]
      : "Health: doctor has not run for this hub",
    live: project.live_sessions,
    runsInProgress: inFlight(project),
    stages: stageCounts(project.runs_in_flight_by_stage),
    prs: project.open_prs ?? null,
    // GitHub owns CI; without it the cell reads "—" under the same tooltip as Open PRs.
    ciLabel: project.open_prs === null || project.open_prs === undefined ? "CI —" : undefined,
    failed7d: project.failed_runs_7d,
    ready: project.ready_issues ?? null,
    cost: toNumber(project.cost_period),
    costDelta: delta.pct === null ? "First period tracked" : delta.text,
    costDeltaTone: delta.tone,
    costSpark: project.cost_daily.map((value) => toNumber(value) ?? 0),
  };
}

/** Projects with items that need you first, then by live sessions, then by name. */
export function orderProjects(
  projects: readonly ProjectSummary[],
  needs: readonly NeedsYouItem[],
): ProjectSummary[] {
  const needing = new Set(needs.map((item) => item.project));
  return [...projects].sort(
    (a, b) =>
      Number(needing.has(b.name)) - Number(needing.has(a.name)) ||
      b.live_sessions - a.live_sessions ||
      a.name.localeCompare(b.name),
  );
}

export interface Totals {
  cost: number;
  previous: number | null;
  failed: number;
  inFlight: number;
  live: number;
}

export function totals(projects: readonly ProjectSummary[]): Totals {
  let previous: number | null = null;
  for (const project of projects) {
    const before = toNumber(project.cost_previous_period);
    if (before !== null) previous = (previous ?? 0) + before;
  }
  return {
    cost: projects.reduce((sum, p) => sum + (toNumber(p.cost_period) ?? 0), 0),
    previous,
    failed: projects.reduce((sum, p) => sum + p.failed_runs_7d, 0),
    inFlight: projects.reduce((sum, p) => sum + inFlight(p), 0),
    live: projects.reduce((sum, p) => sum + p.live_sessions, 0),
  };
}

/** The activity chips and the API kinds each one shows. */
export const ACTIVITY_FILTERS: readonly { id: string; kinds: readonly ActivityItem["kind"][] }[] = [
  // Answered approvals are routine (spec 12: routine items never appear); they live in Approvals.
  { id: "All", kinds: ["reported", "failed", "learning", "doctor"] },
  { id: "Runs", kinds: ["reported", "failed"] },
  { id: "Learnings", kinds: ["learning"] },
  { id: "Health", kinds: ["doctor"] },
];

export function activityEntry(item: ActivityItem, now: number): Omit<ActivityEntry, "node"> {
  return { kind: item.kind, text: item.text, project: item.project, age: age(item.at, now) };
}

/** Consecutive rows with the same text and project become one row with a count. */
export function collapseRepeats(
  items: readonly ActivityItem[],
): { item: ActivityItem; count: number }[] {
  const rows: { item: ActivityItem; count: number }[] = [];
  for (const item of items) {
    const last = rows[rows.length - 1];
    if (last?.item.text === item.text && last.item.project === item.project) last.count++;
    else rows.push({ item, count: 1 });
  }
  return rows;
}
