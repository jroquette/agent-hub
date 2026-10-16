/* Learnings queue: search and facets ⇄ URL query, mirroring the Skills catalog's filters. */
import type { components } from "../../api/schema";

type Learning = components["schemas"]["Learning"];
export type Provenance = NonNullable<Learning["provenance"]>;
export type Readiness = "ready" | "blocked";
/** Claude's recommendation on a learning: a review verdict, where a running review stands
 * (reviewing it now, queued behind others, stopped until you answer), a review that ended without
 * a verdict, or none asked for. */
export type ClaudeVerdict =
  | "ready"
  | "needs_changes"
  | "not_for_brain"
  | "reviewing"
  | "queued"
  | "waiting"
  | "no_verdict"
  | "unreviewed";
/** How a learning's verdict is looked up; without reviews, every learning is unreviewed. */
export type VerdictOf = (l: Learning) => ClaudeVerdict;
const NO_VERDICTS: VerdictOf = () => "unreviewed";

export const PROVENANCES: readonly Provenance[] = [
  "human",
  "agent",
  "agent-from-code",
  "agent-from-external",
];
export const READINESS: readonly Readiness[] = ["ready", "blocked"];
export const CLAUDE_VERDICTS: readonly ClaudeVerdict[] = [
  "ready",
  "needs_changes",
  "not_for_brain",
  "reviewing",
  "queued",
  "waiting",
  "no_verdict",
  "unreviewed",
];
/** The longest search kept from the URL; longer text is cut. */
export const MAX_QUERY_CHARS = 200;

export interface LearningFilters {
  q: string;
  /** One project, or every project when null. */
  project: string | null;
  provenance: Provenance[];
  readiness: Readiness[];
  claude: ClaudeVerdict[];
}

export const NO_FILTERS: LearningFilters = {
  q: "",
  project: null,
  provenance: [],
  readiness: [],
  claude: [],
};

/** URL keys the queue owns; any other parameter is left as it is. */
const KEYS = ["q", "project", "provenance", "readiness", "claude"] as const;

function listOf<T extends string>(values: readonly T[], raw: string | null): T[] {
  const given = new Set((raw ?? "").split(","));
  return values.filter((value) => given.has(value));
}

/** The filters a URL query describes; unknown values are dropped and the search is cut. */
export function filtersFromParams(params: URLSearchParams): LearningFilters {
  const project = params.get("project")?.trim() ?? "";
  return {
    q: (params.get("q") ?? "").slice(0, MAX_QUERY_CHARS),
    project: project === "" ? null : project,
    provenance: listOf(PROVENANCES, params.get("provenance")),
    readiness: listOf(READINESS, params.get("readiness")),
    claude: listOf(CLAUDE_VERDICTS, params.get("claude")),
  };
}

/** `params` with the queue's keys replaced by `filters` (empty ones removed). */
export function withFilters(params: URLSearchParams, filters: LearningFilters): URLSearchParams {
  const next = new URLSearchParams(params);
  for (const key of KEYS) next.delete(key);
  if (filters.q) next.set("q", filters.q.slice(0, MAX_QUERY_CHARS));
  if (filters.project) next.set("project", filters.project);
  const provenance = listOf(PROVENANCES, filters.provenance.join(","));
  if (provenance.length > 0) next.set("provenance", provenance.join(","));
  const readiness = listOf(READINESS, filters.readiness.join(","));
  if (readiness.length > 0) next.set("readiness", readiness.join(","));
  const claude = listOf(CLAUDE_VERDICTS, filters.claude.join(","));
  if (claude.length > 0) next.set("claude", claude.join(","));
  return next;
}

export function hasFilters(filters: LearningFilters): boolean {
  return (
    filters.q.trim() !== "" ||
    filters.project !== null ||
    filters.provenance.length > 0 ||
    filters.readiness.length > 0 ||
    filters.claude.length > 0
  );
}

/** A proposed learning that cannot be accepted or rejected here (its note is gone, ...). */
export const blockedReason = (l: Learning): string | null =>
  l.status === "proposed" ? (l.actions_unavailable ?? null) : null;

const readinessOf = (l: Learning): Readiness => (blockedReason(l) === null ? "ready" : "blocked");

type FacetId = "project" | "provenance" | "readiness" | "claude";

function matches(
  l: Learning,
  filters: LearningFilters,
  verdictOf: VerdictOf,
  skip?: FacetId,
): boolean {
  const q = filters.q.trim().toLowerCase();
  if (q && !`${l.text}\n${l.summary ?? ""}\n${l.project}`.toLowerCase().includes(q)) return false;
  if (skip !== "project" && filters.project !== null && l.project !== filters.project) return false;
  if (
    skip !== "provenance" &&
    filters.provenance.length > 0 &&
    (l.provenance === null || !filters.provenance.includes(l.provenance))
  )
    return false;
  if (skip !== "claude" && filters.claude.length > 0 && !filters.claude.includes(verdictOf(l)))
    return false;
  return (
    skip === "readiness" ||
    filters.readiness.length === 0 ||
    filters.readiness.includes(readinessOf(l))
  );
}

/** The learnings search and every facet keep, in their given order. */
export function filterLearnings(
  rows: readonly Learning[],
  filters: LearningFilters,
  verdictOf: VerdictOf = NO_VERDICTS,
): Learning[] {
  return rows.filter((l) => matches(l, filters, verdictOf));
}

export interface FacetCounts {
  /** Per project, in name order; the other facets and the search applied. */
  project: [string, number][];
  provenance: Record<Provenance, number>;
  readiness: Record<Readiness, number>;
  claude: Record<ClaudeVerdict, number>;
}

const zeros = <T extends string>(values: readonly T[]) =>
  Object.fromEntries(values.map((value) => [value, 0])) as Record<T, number>;

/** Per facet value, how many learnings it would show: search and the other facets applied. */
export function facetCounts(
  rows: readonly Learning[],
  filters: LearningFilters,
  verdictOf: VerdictOf = NO_VERDICTS,
): FacetCounts {
  const project = new Map<string, number>();
  const counts = {
    provenance: zeros(PROVENANCES),
    readiness: zeros(READINESS),
    claude: zeros(CLAUDE_VERDICTS),
  };
  const keeps = (l: Learning, skip: FacetId) => matches(l, filters, verdictOf, skip);
  for (const l of rows) {
    if (!project.has(l.project)) project.set(l.project, 0);
    if (keeps(l, "project")) project.set(l.project, (project.get(l.project) ?? 0) + 1);
    if (l.provenance !== null && keeps(l, "provenance")) counts.provenance[l.provenance] += 1;
    if (keeps(l, "readiness")) counts.readiness[readinessOf(l)] += 1;
    if (keeps(l, "claude")) counts.claude[verdictOf(l)] += 1;
  }
  return {
    project: [...project.entries()].sort(([a], [b]) => a.localeCompare(b)),
    ...counts,
  };
}

export function toggle<T extends string>(values: readonly T[], value: T): T[] {
  return values.includes(value) ? values.filter((v) => v !== value) : [...values, value];
}
