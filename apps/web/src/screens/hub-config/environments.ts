import type { QueryClient } from "@tanstack/react-query";

import type { components } from "../../api/schema";
import type { IconName } from "../../components";
import { ApiProblem, apiKey, apiPost } from "../../lib/api";

/* The Environments section's data and words: one place for the access labels, the write and the
   way a refused write is shown under its field (docs/design/environments.md). */

export type HubConfigView = components["schemas"]["HubConfigView"];
export type EnvironmentsView = HubConfigView["environments"];
export type SourcedEnvironment = EnvironmentsView["environments"][number];
export type SourcedService = EnvironmentsView["services"][number];
export type SourcedEndpoint = SourcedService["endpoints"][number];
export type Access = SourcedEnvironment["access"];
export type EnvironmentEdit =
  | components["schemas"]["AddEnvironment"]
  | components["schemas"]["SetEnvironment"]
  | components["schemas"]["RemoveEnvironment"]
  | components["schemas"]["AddEndpoint"]
  | components["schemas"]["RemoveEndpoint"];

/** An endpoint's values: the generated type is ``unknown`` (its schema is an ``anyOf``). */
export interface EndpointValues {
  url?: string | null;
  resource?: string | null;
  note?: string | null;
}

export function endpointValues(endpoint: SourcedEndpoint): EndpointValues {
  return endpoint.endpoint ?? {};
}

/** What a cell shows: the URL, else the resource name. */
export function endpointText(endpoint: SourcedEndpoint): string {
  const values = endpointValues(endpoint);
  return values.url ?? values.resource ?? "";
}

export const LOCAL_FILE = "hub.local.json";
export const ACCESSES: readonly Access[] = ["read", "ask", "write"];
/** Higher is stricter: hub.local.json may only move an environment up. */
export const STRICTNESS: Record<Access, number> = { write: 0, ask: 1, read: 2 };

export const ACCESS_LOOK: Record<
  Access,
  { icon: IconName; row: string; card: string; help: string; short: string }
> = {
  read: {
    icon: "lock",
    row: "Agents only read",
    card: "Read only",
    help: "Agents only read. Actions that change data are refused.",
    short: "only read",
  },
  ask: {
    icon: "shield-alert",
    row: "Agents ask before writing",
    card: "Ask first",
    help: "Agents ask you before changing data.",
    short: "ask before writing",
  },
  write: {
    icon: "pencil",
    row: "Agents may change data",
    card: "Can change data",
    help: "Agents may change data. Never a deploy.",
    short: "may change data",
  },
};

export const NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$/;
export const VARIABLE_PATTERN = /^[A-Z_][A-Z0-9_]{0,63}$/;

/** Whether the environment comes from the developer's own file (its own, or a tightening). */
export function isMine(environment: SourcedEnvironment): boolean {
  return environment.source === LOCAL_FILE;
}

/** Whether the environment is the team's (hub.json declares it), tightened or not. */
export function isTeams(environment: SourcedEnvironment): boolean {
  return environment.team_access !== null && environment.team_access !== undefined;
}

/** Endpoints of an environment, as "repo › service" pairs. */
export function endpointsIn(view: EnvironmentsView, environment: string) {
  return view.services.flatMap((service) =>
    service.endpoints
      .filter((endpoint) => endpoint.environment === environment)
      .map((endpoint) => ({ service, endpoint })),
  );
}

export function serviceLabel(repo: string, service: string): string {
  return `${repo} › ${service}`;
}

/** Sends one edit; the answer is the fresh config, put straight into the screen's query. */
export async function postEnvironmentEdit(
  client: QueryClient,
  project: string,
  body: EnvironmentEdit,
): Promise<HubConfigView> {
  const key = apiKey("/api/v1/projects/{project}/config", { path: { project } });
  let fresh: HubConfigView;
  try {
    fresh = await apiPost("/api/v1/projects/{project}/config/environments", body, {
      path: { project },
    });
  } catch (error: unknown) {
    // A file changed on disk: show it as it is now, the open form keeps its values.
    if (refusalOf(error).changed) void client.invalidateQueries({ queryKey: key });
    throw error;
  }
  client.setQueryData(key, fresh);
  return fresh;
}

/** The fields a server problem lands under, by its JSON path. */
const FIELD_OF: readonly [RegExp, string][] = [
  [/\.credentials\.env\[(\d+)\]/, "credential_env"],
  [/\.credentials\.env$/, "credential_env"],
  [/\.credentials\.aws_profile/, "aws_profile"],
  [/\.credentials\.env_file/, "env_file"],
  [/\.access$/, "access"],
  [/\.description$/, "description"],
  [/\.production$/, "production"],
  [/\.url$/, "url"],
  [/\.resource$/, "resource"],
  [/\.note$/, "note"],
  [/\.kind$/, "kind"],
];

const PATTERN_HELP: Record<string, string> = {
  aws_profile: "Letters, digits, . _ - only, up to 64.",
  credential_env: "A variable name: capital letters, digits and _, e.g. DEMO_DB_URL.",
  kind: "Lowercase words joined by -, e.g. api or dynamodb.",
};

/** The server's words for a person: a regex means nothing to a reader. */
function plainMessage(field: string, message: string): string {
  const text = message.replace(/^hub(\.local)?\.json: /, "");
  if (text.startsWith("String should match pattern"))
    return PATTERN_HELP[field] ?? "Has a character this field does not accept.";
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export interface Refusal {
  /** One line at the top of the dialog. */
  summary: string;
  /** A message per field, by the field's name. */
  fields: Record<string, string>;
  /** The file changed on disk since the page read it: the caller reloads the config. */
  changed?: boolean;
}

/** What a failed write shows: each problem under its field, the rest in the summary. */
export function refusalOf(error: unknown): Refusal {
  if (!(error instanceof ApiProblem) || error.status === 0)
    return { summary: "Could not reach the server. Nothing was saved.", fields: {} };
  const changed = error.errors.find((problem) => problem.message.includes("changed since"));
  if (changed)
    return {
      summary: `${changed.message.split(" ")[0] ?? "The file"} changed on disk since this page loaded. Nothing was saved. The page now shows the file as it is; check and save again.`,
      fields: {},
      changed: true,
    };
  const fields: Record<string, string> = {};
  const loose: string[] = [];
  for (const problem of error.errors) {
    const match = FIELD_OF.find(([pattern]) => pattern.test(problem.pointer));
    if (!match) {
      loose.push(plainMessage("", problem.message));
      continue;
    }
    const [pattern, field] = match;
    const line = pattern.exec(problem.pointer)?.[1];
    const message = plainMessage(field, problem.message);
    fields[field] = line === undefined ? message : `Line ${String(Number(line) + 1)}: ${message}`;
  }
  if (loose.length > 0) return { summary: `Nothing was saved: ${loose.join(" ")}`, fields };
  if (Object.keys(fields).length > 0)
    return { summary: "Nothing was saved: fix the fields marked below.", fields };
  return {
    summary: `Nothing was saved: ${error.title}${error.detail ? `. ${error.detail}` : ""}`,
    fields,
  };
}

/** Lines of a textarea, trimmed, empty ones dropped. */
export function linesOf(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

/** The first line holding "=" (a value pasted after a name), 1-based, else null. */
/** "1 endpoint", "3 endpoints". */
export function count(amount: number, noun: string): string {
  return `${String(amount)} ${noun}${amount === 1 ? "" : "s"}`;
}

export function lineWithValue(text: string): number | null {
  const index = text.split("\n").findIndex((line) => line.includes("="));
  return index === -1 ? null : index + 1;
}
