/* Learnings queue: search and facets ⇄ URL query, mirroring the Skills catalog's filters. */
import type { components } from "../../api/schema";

type Learning = components["schemas"]["Learning"];
export type Provenance = NonNullable<Learning["provenance"]>;
export type Readiness = "ready" | "blocked";

export const PROVENANCES: readonly Provenance[] = [
  "human",
  "agent",
  "agent-from-code",
  "agent-from-external",
];
export const READINESS: readonly Readiness[] = ["ready", "blocked"];
/** The longest search kept from the URL; longer text is cut. */
export const MAX_QUERY_CHARS = 200;

export interface LearningFilters {
  q: string;
  /** One project, or every project when null. */
  project: string | null;
  provenance: Provenance[];
  readiness: Readiness[];
}

export const NO_FILTERS: LearningFilters = {
  q: "",
  project: null,
  provenance: [],
  readiness: [],
};

/** URL keys the queue owns; any other parameter is left as it is. */
const KEYS = ["q", "project", "provenance", "readiness"] as const;

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
  return next;
}

export function hasFilters(filters: LearningFilters): boolean {
  return (
    filters.q.trim() !== "" ||
    filters.project !== null ||
    filters.provenance.length > 0 ||
    filters.readiness.length > 0
  );
}

/** A proposed learning that cannot be accepted or rejected here (its note is gone, ...). */
export const blockedReason = (l: Learning): string | null =>
  l.status === "proposed" ? (l.actions_unavailable ?? null) : null;

const readinessOf = (l: Learning): Readiness => (blockedReason(l) === null ? "ready" : "blocked");

type FacetId = "project" | "provenance" | "readiness";

function matches(l: Learning, filters: LearningFilters, skip?: FacetId): boolean {
  const q = filters.q.trim().toLowerCase();
  if (q && !`${l.text}\n${l.summary ?? ""}\n${l.project}`.toLowerCase().includes(q)) return false;
  if (skip !== "project" && filters.project !== null && l.project !== filters.project) return false;
  if (
    skip !== "provenance" &&
    filters.provenance.length > 0 &&
    (l.provenance === null || !filters.provenance.includes(l.provenance))
  )
    return false;
  return (
    skip === "readiness" ||
    filters.readiness.length === 0 ||
    filters.readiness.includes(readinessOf(l))
  );
}

/** The learnings search and every facet keep, in their given order. */
export function filterLearnings(rows: readonly Learning[], filters: LearningFilters): Learning[] {
  return rows.filter((l) => matches(l, filters));
}

export interface FacetCounts {
  /** Per project, in name order; the other facets and the search applied. */
  project: [string, number][];
  provenance: Record<Provenance, number>;
  readiness: Record<Readiness, number>;
}

const zeros = <T extends string>(values: readonly T[]) =>
  Object.fromEntries(values.map((value) => [value, 0])) as Record<T, number>;

/** Per facet value, how many learnings it would show: search and the other facets applied. */
export function facetCounts(rows: readonly Learning[], filters: LearningFilters): FacetCounts {
  const project = new Map<string, number>();
  const counts = { provenance: zeros(PROVENANCES), readiness: zeros(READINESS) };
  for (const l of rows) {
    if (!project.has(l.project)) project.set(l.project, 0);
    if (matches(l, filters, "project")) project.set(l.project, (project.get(l.project) ?? 0) + 1);
    if (l.provenance !== null && matches(l, filters, "provenance"))
      counts.provenance[l.provenance] += 1;
    if (matches(l, filters, "readiness")) counts.readiness[readinessOf(l)] += 1;
  }
  return {
    project: [...project.entries()].sort(([a], [b]) => a.localeCompare(b)),
    ...counts,
  };
}

export function toggle<T extends string>(values: readonly T[], value: T): T[] {
  return values.includes(value) ? values.filter((v) => v !== value) : [...values, value];
}
