/* Sessions list: URL state ⇄ API query (spec 14, "Filters and columns are in the URL"). */
import type { SessionQuery } from "./queries";

export type Period = "24 h" | "7 d" | "30 d" | "All";
export const PERIODS: Period[] = ["24 h", "7 d", "30 d", "All"];
const PERIOD_MS: Record<Period, number | null> = {
  "24 h": 86_400_000,
  "7 d": 7 * 86_400_000,
  "30 d": 30 * 86_400_000,
  All: null,
};
export const STATUSES = ["live", "waiting", "idle", "ended"] as const;
export const OUTCOMES = ["done", "stopped", "blocked", "error"] as const;
export const SORTS = [
  "-started_at",
  "started_at",
  "-last_activity_at",
  "last_activity_at",
  "-cost",
  "cost",
] as const;
export const TOOLS = [
  "Read",
  "Edit",
  "Write",
  "Bash",
  "Grep",
  "Glob",
  "Agent",
  "WebFetch",
] as const;

type Sort = (typeof SORTS)[number];
type SessionStatus = (typeof STATUSES)[number];
type Outcome = (typeof OUTCOMES)[number];

/** URL keys of the filters; `scope` (the project) is the shell's. */
export const FILTER_KEYS = [
  "period",
  "repo",
  "agent",
  "status",
  "outcome",
  "workflow",
  "cost_min",
  "cost_max",
  "file",
  "tool",
  "guard_denial",
] as const;
export type FilterKey = (typeof FILTER_KEYS)[number];

export function periodOf(params: URLSearchParams): Period {
  const value = params.get("period");
  return PERIODS.find((period) => period === value) ?? "7 d";
}

export function sortOf(params: URLSearchParams): Sort {
  const value = params.get("sort");
  return SORTS.find((sort) => sort === value) ?? "-started_at";
}

function pick<T extends string>(values: readonly T[], value: string | null): T | undefined {
  return values.find((item) => item === value);
}

/** The `/sessions` query the URL describes; `now` anchors the period. */
export function queryOf(
  params: URLSearchParams,
  project: string | null,
  now: number,
): SessionQuery {
  const query: SessionQuery = { sort: sortOf(params) };
  const span = PERIOD_MS[periodOf(params)];
  if (span !== null) query.from = new Date(now - span).toISOString();
  if (project) query.project = project;
  const status: SessionStatus | undefined = pick(STATUSES, params.get("status"));
  if (status) query.status = status;
  const outcome: Outcome | undefined = pick(OUTCOMES, params.get("outcome"));
  if (outcome) query.outcome = outcome;
  for (const key of [
    "repo",
    "agent",
    "workflow",
    "file",
    "tool",
    "cost_min",
    "cost_max",
  ] as const) {
    const value = params.get(key)?.trim();
    if (value) query[key] = value;
  }
  if (params.get("guard_denial") === "1") query.guard_denial = true;
  return query;
}

const LABEL: Record<FilterKey, string> = {
  period: "Period",
  repo: "Repo",
  agent: "Agent type",
  status: "Status",
  outcome: "Outcome",
  workflow: "Workflow",
  cost_min: "Cost from",
  cost_max: "Cost to",
  file: "Touched file",
  tool: "Used tool",
  guard_denial: "Flag",
};

/** The active filters as removable chips (the period chip only when not the default). */
export interface Chip {
  key: FilterKey;
  label: string;
  value: string;
}

export function chipsOf(params: URLSearchParams): Chip[] {
  return FILTER_KEYS.flatMap((key): Chip[] => {
    const value = params.get(key);
    if (!value) return [];
    if (key === "guard_denial")
      return value === "1" ? [{ key, label: LABEL[key], value: "Had a guard denial" }] : [];
    if (key === "cost_min" || key === "cost_max")
      return [{ key, label: LABEL[key], value: `$${value}` }];
    return [{ key, label: LABEL[key], value }];
  });
}

/** True when a decimal filter is malformed (the API would answer 400). */
export function badDecimal(value: string | null): boolean {
  return value !== null && value.trim() !== "" && !/^\d+(\.\d+)?$/.test(value.trim());
}

export type View = "grid" | "list";
export type Within = "repo" | "run" | "workflow";
export const WITHINS: { id: Within | "flat"; label: string }[] = [
  { id: "flat", label: "Flat" },
  { id: "repo", label: "Project › repo" },
  { id: "run", label: "Run" },
  { id: "workflow", label: "Workflow" },
];
/** "table" was the list's name before the redesign: old links and stored values still work. */
function asView(value: string | null): View | null {
  if (value === "grid") return "grid";
  if (value === "list" || value === "table") return "list";
  return null;
}

/** The URL's `view` wins over the stored one; with neither, or an unknown value, the list. */
export function viewOf(params: URLSearchParams, stored: string | null): View {
  return asView(params.get("view")) ?? asView(stored) ?? "list";
}

/** The grid's sub-groups inside each section; any other value is none. */
export function withinOf(params: URLSearchParams): Within | null {
  const within = params.get("within");
  return within === "repo" || within === "run" || within === "workflow" ? within : null;
}
