import type { QueryClient } from "@tanstack/react-query";

import type { components } from "../../api/schema";
import { ApiProblem, apiKey, apiPost } from "../../lib/api";
import { refusalOf } from "./environments";
import type { HubConfigView } from "./environments";

/* The Repositories section's data and words (24-hub-config-repos.md): the repo write, the body
   each form sends, why Save is off, and a refusal shown line by line as the API sends it. */

export type RepoConfigView = HubConfigView["repos"][number];
export type RepoEdit = components["schemas"]["RepoEdit"];
export type AddRepo = components["schemas"]["AddRepo"];
export type SetRepo = components["schemas"]["SetRepo"];

/** Sends one repo edit; the answer is the fresh config, put straight into the screen's query. */
export async function postRepoEdit(
  client: QueryClient,
  project: string,
  body: RepoEdit,
): Promise<HubConfigView> {
  const key = apiKey("/api/v1/projects/{project}/config", { path: { project } });
  let fresh: HubConfigView;
  try {
    fresh = await apiPost("/api/v1/projects/{project}/config/repos", body, { path: { project } });
  } catch (error: unknown) {
    // hub.json changed on disk: show it as it is now, the open form keeps what was typed.
    if (refusalOf(error).changed) void client.invalidateQueries({ queryKey: key });
    throw error;
  }
  client.setQueryData(key, fresh);
  return fresh;
}

/** The form's fields, in the order hub.json writes them; `dir` is the folder. */
export const REPO_FIELDS = [
  "dir",
  "github",
  "check",
  "check_fast",
  "check_fast_timeout",
  "role",
  "default_branch",
] as const;
export type RepoField = (typeof REPO_FIELDS)[number];
export type RepoValues = Record<RepoField, string>;

/** The keys a change may clear, in the order the form shows them. */
const OPTIONAL: readonly RepoField[] = [
  "check_fast",
  "check_fast_timeout",
  "role",
  "default_branch",
];

export const EMPTY_REPO: RepoValues = {
  dir: "",
  github: "",
  check: "",
  check_fast: "",
  check_fast_timeout: "",
  role: "",
  default_branch: "",
};

/** The role hub.json gives a repo that names none. */
const DEFAULT_ROLE = "app";

/** Whether the repo's default branch is its own (hub.json sets it on the repo), not the
 * project's: the view names the repo's key as where it comes from. */
export function ownDefaultBranch(repo: RepoConfigView): boolean {
  return repo.default_branch.where.endsWith(`repos[${String(repo.index)}].default_branch`);
}

/** A change form's starting values: what hub.json says of the repo, empty where it says
 * nothing. */
export function startValues(repo: RepoConfigView): RepoValues {
  return {
    dir: repo.dir,
    github: repo.github,
    check: repo.check,
    check_fast: repo.check_fast ?? "",
    check_fast_timeout: repo.check_fast_timeout === null ? "" : String(repo.check_fast_timeout),
    role: repo.role,
    default_branch: ownDefaultBranch(repo) ? (repo.default_branch.value ?? "") : "",
  };
}

function timeoutOf(text: string): number {
  return Number(text);
}

const WHOLE = /^\d+$/;

/** The folder another repo already has, compared ignoring case, else null. */
export function duplicateOf(dir: string, repos: readonly RepoConfigView[]): string | null {
  const wanted = dir.trim().toLowerCase();
  if (!wanted) return null;
  return repos.find((repo) => repo.dir.toLowerCase() === wanted)?.dir ?? null;
}

/** The add body: the three required fields plus each optional one that is not empty. */
export function addBody(values: RepoValues): AddRepo {
  const body: AddRepo = {
    op: "add_repo",
    dir: values.dir.trim(),
    github: values.github.trim(),
    check: values.check.trim(),
  };
  const fast = values.check_fast.trim();
  const timeout = values.check_fast_timeout.trim();
  const role = values.role.trim();
  const branch = values.default_branch.trim();
  if (fast) body.check_fast = fast;
  if (timeout) body.check_fast_timeout = timeoutOf(timeout);
  if (role) body.role = role;
  if (branch) body.default_branch = branch;
  return body;
}

/** The same value for hub.json: an empty role is the default one. */
function same(field: RepoField, start: string, now: string): boolean {
  if (field === "role") return (start || DEFAULT_ROLE) === (now || DEFAULT_ROLE);
  return start === now;
}

/** The change body: only the fields that differ from `start`; a cleared optional field goes in
 * `unset`. Null when nothing changed. */
export function setBody(start: RepoValues, values: RepoValues): SetRepo | null {
  const body: SetRepo = { op: "set_repo", dir: start.dir, unset: [] };
  let changed = false;
  for (const field of REPO_FIELDS) {
    if (field === "dir") continue;
    const now = values[field].trim();
    if (same(field, start[field], now)) continue;
    changed = true;
    if (now === "" && OPTIONAL.includes(field)) body.unset.push(field);
    else if (field === "check_fast_timeout") body.check_fast_timeout = timeoutOf(now);
    else body[field] = now;
  }
  return changed ? body : null;
}

/** Why Save is off, in words, else null. A change passes its starting values. */
export function blockedReason(values: RepoValues, start: RepoValues | null): string | null {
  const timeout = values.check_fast_timeout.trim();
  if (start === null) {
    if (!values.dir.trim() || !values.github.trim() || !values.check.trim())
      return "Fill in the folder, GitHub repo and full check.";
  } else {
    if (!values.github.trim() || !values.check.trim())
      return "GitHub repo and full check cannot be empty.";
  }
  if (timeout && !WHOLE.test(timeout)) return "Fast check timeout: a whole number of seconds.";
  if (start !== null && setBody(start, values) === null) return "Nothing changed yet.";
  return null;
}

/** The next steps after a write, below the uncommitted notice's sync sentence. */
export function nextLines(kind: "add" | "change" | "remove", dir: string): string[] {
  if (kind === "add")
    return [
      `Run ./hub setup to clone ../${dir}.`,
      `Run /onboard to set ${dir}'s gates and project rules.`,
    ];
  if (kind === "remove")
    return [
      `../${dir} and its worktrees are left in place.`,
      `A teammate whose hub.local.json names ${dir} in repos must drop that entry.`,
    ];
  return [];
}

/** A field's own format line, shown in place of a message that quotes the model's regex. */
const FORMAT: Partial<Record<RepoField, string>> = {
  dir: "Letters, digits and _, joined by . or -.",
  github: "owner/name, e.g. acme/demo-web.",
  default_branch: "Letters, digits and _, joined by . or -, in parts split by /.",
  role: "One line of text.",
  check: "One line, no control characters.",
  check_fast: "One line, no control characters.",
};

export interface RepoProblemLine {
  /** The form field the problem names, else null (it is listed only). */
  field: RepoField | null;
  message: string;
}

export interface RepoRefusal {
  /** The problem's title; null when the one line says it all (no server, changed on disk). */
  title: string | null;
  lines: RepoProblemLine[];
  /** hub.json changed on disk since the page read it: the config reloads. */
  changed: boolean;
}

const REPO_POINTER = /^repos\[\d+\]\.([a-z_]+)$/;

function fieldOf(pointer: string, message: string): RepoField | null {
  // A hub.local.json line names the developer's file, not this form's field.
  if (message.includes("hub.local.json")) return null;
  const key = REPO_POINTER.exec(pointer)?.[1];
  return REPO_FIELDS.find((field) => field === key) ?? null;
}

function shownMessage(field: RepoField | null, message: string): string {
  const lead = /^hub(?:\.local)?\.json: /.exec(message)?.[0] ?? "";
  const text = message.slice(lead.length);
  const format = field === null ? undefined : FORMAT[field];
  if (text.startsWith("String should match pattern") && format) return `${lead}${format}`;
  return message;
}

/** A refused write, each problem on its own line as the API sends it (a regex replaced by the
 * field's format line, O1). */
export function repoRefusalOf(error: unknown): RepoRefusal {
  const plain = refusalOf(error);
  if (!(error instanceof ApiProblem) || error.status === 0 || plain.changed)
    return {
      title: null,
      lines: [{ field: null, message: plain.summary }],
      changed: plain.changed ?? false,
    };
  if (error.errors.length === 0)
    return {
      title: error.title,
      lines: error.detail ? [{ field: null, message: error.detail }] : [],
      changed: false,
    };
  return {
    title: error.title,
    lines: error.errors.map((problem) => {
      const field = fieldOf(problem.pointer, problem.message);
      return { field, message: shownMessage(field, problem.message) };
    }),
    changed: false,
  };
}
