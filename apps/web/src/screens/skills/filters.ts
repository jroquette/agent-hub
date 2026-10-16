/* Skills catalog: search and facets ⇄ URL query (L8, AC-164.14, AC-164.40). */
import type { components } from "../../api/schema";

type Schemas = components["schemas"];
type CatalogItem = Schemas["CatalogItem"];
export type ItemKind = Schemas["ItemKind"];
export type Origin = Schemas["Origin"];
export type Mode = Schemas["Mode"];

export const KINDS: readonly ItemKind[] = ["skill", "agent", "hook"];
export const ORIGINS: readonly Origin[] = ["managed", "project-owned", "local"];
export const MODES: readonly Mode[] = ["user-only", "model-only", "both", "neither"];
/** The longest search kept from the URL; longer text is cut. */
export const MAX_QUERY_CHARS = 200;

/** What a facet's values read as in the UI (status by text, never color alone). */
export const KIND_LABEL: Record<ItemKind, string> = {
  skill: "Skills",
  agent: "Agents",
  hook: "Hooks",
};
/** What each kind is, in a few words: the kind tiles and the Create menu. */
export const KIND_SUMMARY: Record<ItemKind, string> = {
  skill: "Packaged instructions, run as /commands",
  agent: "Specialists the session delegates to",
  hook: "Commands run at lifecycle events",
};
/** What each kind is, in one or two sentences, for someone new to Claude Code. */
export const KIND_HELP: Record<ItemKind, string> = {
  skill:
    "Instructions packaged for one kind of task. You run one as a /command, or the model loads it when a task matches its description.",
  agent:
    "Subagents: specialists with their own prompt, tools and context window. The main session delegates a task to one and gets back only its result.",
  hook: "Shell commands Claude Code runs by itself at lifecycle events (a session starts, a tool is about to run, a turn ends) to check, block or record what happens.",
};
export const ORIGIN_LABEL: Record<Origin, string> = {
  managed: "Managed",
  "project-owned": "Project-owned",
  local: "Local (.claude)",
};
export const ORIGIN_HELP: Record<Origin, string> = {
  managed: "Written by hub sync from the platform; change it through hub.json.",
  "project-owned": "Owned by this project; hub sync never rewrites it.",
  local: "A real entry in .claude/, outside any plugin.",
};
export const MODE_LABEL: Record<Mode, string> = {
  "user-only": "User only",
  "model-only": "Model only",
  both: "User and model",
  neither: "Hidden",
};
export const MODE_HELP: Record<Mode, string> = {
  "user-only": "Only you can invoke it, as a slash command; the model never loads it on its own.",
  "model-only": "Only the model can invoke it; it is not in the / menu.",
  both: "You can invoke it as a slash command, and the model can load it when relevant.",
  neither: "Neither you nor the model can invoke it.",
};

export interface CatalogFilters {
  q: string;
  kind: ItemKind[];
  origin: Origin[];
  mode: Mode[];
  diag: boolean;
}

export const NO_FILTERS: CatalogFilters = { q: "", kind: [], origin: [], mode: [], diag: false };

/** URL keys the catalog owns; any other parameter is left as it is. */
const KEYS = ["q", "kind", "origin", "mode", "diag"] as const;

function listOf<T extends string>(values: readonly T[], raw: string | null): T[] {
  const given = new Set((raw ?? "").split(","));
  return values.filter((value) => given.has(value));
}

/** The filters a URL query describes; unknown values are dropped and the search is cut. */
export function filtersFromParams(params: URLSearchParams): CatalogFilters {
  return {
    q: (params.get("q") ?? "").slice(0, MAX_QUERY_CHARS),
    kind: listOf(KINDS, params.get("kind")),
    origin: listOf(ORIGINS, params.get("origin")),
    mode: listOf(MODES, params.get("mode")),
    diag: params.get("diag") === "1",
  };
}

/** `params` with the catalog's keys replaced by `filters` (empty ones removed). */
export function withFilters(params: URLSearchParams, filters: CatalogFilters): URLSearchParams {
  const next = new URLSearchParams(params);
  for (const key of KEYS) next.delete(key);
  if (filters.q) next.set("q", filters.q.slice(0, MAX_QUERY_CHARS));
  const lists = [
    ["kind", listOf(KINDS, filters.kind.join(","))],
    ["origin", listOf(ORIGINS, filters.origin.join(","))],
    ["mode", listOf(MODES, filters.mode.join(","))],
  ] as const;
  for (const [key, values] of lists) if (values.length > 0) next.set(key, values.join(","));
  if (filters.diag) next.set("diag", "1");
  return next;
}

export function hasFilters(filters: CatalogFilters): boolean {
  return (
    filters.q.trim() !== "" ||
    filters.kind.length > 0 ||
    filters.origin.length > 0 ||
    filters.mode.length > 0 ||
    filters.diag
  );
}

type FacetId = "kind" | "origin" | "mode" | "diag";

function matches(item: CatalogItem, filters: CatalogFilters, skip?: FacetId): boolean {
  const q = filters.q.trim().toLowerCase();
  if (q && !`${item.name}\n${item.description ?? ""}`.toLowerCase().includes(q)) return false;
  if (skip !== "kind" && filters.kind.length > 0 && !filters.kind.includes(item.kind)) return false;
  if (skip !== "origin" && filters.origin.length > 0 && !filters.origin.includes(item.origin))
    return false;
  if (
    skip !== "mode" &&
    filters.mode.length > 0 &&
    (item.mode === null || !filters.mode.includes(item.mode))
  )
    return false;
  return skip === "diag" || !filters.diag || item.diagnostics_count > 0;
}

/** The items search and every facet keep, in catalog order. */
export function filterItems<T extends CatalogItem>(items: readonly T[], filters: CatalogFilters) {
  return items.filter((item) => matches(item, filters));
}

export interface FacetCounts {
  kind: Record<ItemKind, number>;
  origin: Record<Origin, number>;
  mode: Record<Mode, number>;
  diag: Record<"1", number>;
}

const zeros = <T extends string>(values: readonly T[]) =>
  Object.fromEntries(values.map((value) => [value, 0])) as Record<T, number>;

/** Per facet value, how many items it would show: search and the other facets applied. */
export function facetCounts(items: readonly CatalogItem[], filters: CatalogFilters): FacetCounts {
  const counts: FacetCounts = {
    kind: zeros(KINDS),
    origin: zeros(ORIGINS),
    mode: zeros(MODES),
    diag: { "1": 0 },
  };
  for (const item of items) {
    if (matches(item, filters, "kind")) counts.kind[item.kind] += 1;
    if (matches(item, filters, "origin")) counts.origin[item.origin] += 1;
    if (item.mode !== null && matches(item, filters, "mode")) counts.mode[item.mode] += 1;
    if (item.diagnostics_count > 0 && matches(item, filters, "diag")) counts.diag["1"] += 1;
  }
  return counts;
}
