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
  | components["schemas"]["RemoveEndpoint"]
  | components["schemas"]["AddService"]
  | components["schemas"]["RenameEnvironment"]
  | components["schemas"]["SetService"]
  | components["schemas"]["EditBatch"];
/** One edit, as a batch holds them (a batch never holds another batch). */
export type SingleEdit = Exclude<EnvironmentEdit, components["schemas"]["EditBatch"]>;

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

/** One environment's own page. Singular, so an environment named "new" never meets the flows. */
export function environmentPath(project: string, name: string): string {
  return `/projects/${encodeURIComponent(project)}/environment/${encodeURIComponent(name)}`;
}
export function addEnvironmentPath(project: string): string {
  return `/projects/${encodeURIComponent(project)}/environments/new`;
}
export function addServicePath(project: string, repo?: string): string {
  const path = `/projects/${encodeURIComponent(project)}/environments/services/new`;
  return repo ? `${path}?repo=${encodeURIComponent(repo)}` : path;
}

export function environmentsPage(project: string): string {
  return `/projects/${encodeURIComponent(project)}/environments`;
}

/** Where a setup flow was opened from, so it returns there: the Environments page or the Hub
 * configuration's section. */
export interface FlowOrigin {
  returnTo: string;
  returnLabel: string;
}

/** The origin a flow was handed, when it is one of this project's pages; else the Environments
 * page. */
export function flowOrigin(state: unknown, project: string): FlowOrigin {
  const handed = state as Partial<FlowOrigin> | null;
  const prefix = `/projects/${encodeURIComponent(project)}/`;
  if (
    typeof handed?.returnTo === "string" &&
    typeof handed.returnLabel === "string" &&
    handed.returnTo.startsWith(prefix)
  )
    return { returnTo: handed.returnTo, returnLabel: handed.returnLabel };
  return { returnTo: environmentsPage(project), returnLabel: "Environments" };
}

/** What a flow hands back to the config screen after a save: its toast and whether hub.json
 * changed. */
export interface SavedState {
  saved: string;
  team: boolean;
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

/** Sends several edits as one write: all of them or none (one edit goes as it is). */
export async function postEnvironmentEdits(
  client: QueryClient,
  project: string,
  ops: readonly SingleEdit[],
): Promise<HubConfigView> {
  const [only] = ops;
  if (ops.length === 1 && only) return postEnvironmentEdit(client, project, only);
  return postEnvironmentEdit(client, project, { op: "batch", ops: [...ops] });
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
/** "1 address", "3 addresses", "2 services". */
export function count(amount: number, noun: string): string {
  if (amount === 1) return `${String(amount)} ${noun}`;
  return `${String(amount)} ${noun}${noun.endsWith("s") ? "es" : "s"}`;
}

export function lineWithValue(text: string): number | null {
  const index = text.split("\n").findIndex((line) => line.includes("="));
  return index === -1 ? null : index + 1;
}

/** How a kind of service is said: one of it, several (a list's group heading), in a sentence. */
export interface ServiceKindWords {
  id: string;
  label: string;
  /** Several of the kind, as a list groups them ("Databases"). */
  plural: string;
  /** One of the kind in a sentence, with its article ("a database"). */
  one: string;
  icon: IconName;
}

/** What kind of thing a service is: the word people use, a default name and example addresses. */
export interface ServiceKind extends ServiceKindWords {
  hint: string;
  /** The service name offered first; empty: the person names it. */
  name: string;
  /** An example address on this machine, and on a shared or cloud environment. */
  local: string;
  remote: string;
}

export const SERVICE_KINDS: readonly ServiceKind[] = [
  {
    id: "api",
    label: "API or backend",
    plural: "APIs and backends",
    one: "an API or backend",
    hint: "A server agents call over HTTP.",
    icon: "plug",
    name: "api",
    local: "http://localhost:8000",
    remote: "https://api.example.com",
  },
  {
    id: "web",
    label: "Frontend or portal",
    plural: "Frontends and portals",
    one: "a frontend or portal",
    hint: "A site or admin portal in the browser.",
    icon: "globe",
    name: "web",
    local: "http://localhost:3000",
    remote: "https://app.example.com",
  },
  {
    id: "database",
    label: "Database",
    plural: "Databases",
    one: "a database",
    hint: "Postgres, MySQL, DynamoDB, Redis…",
    icon: "database",
    name: "db",
    local: "postgres://localhost:5432/app",
    remote: "orders-table",
  },
  {
    id: "queue",
    label: "Queue or topic",
    plural: "Queues and topics",
    one: "a queue or topic",
    hint: "SQS, SNS, Kafka, RabbitMQ…",
    icon: "layers",
    name: "queue",
    local: "orders-queue-local",
    remote: "orders-queue",
  },
  {
    id: "storage",
    label: "Storage bucket",
    plural: "Storage buckets",
    one: "a storage bucket",
    hint: "S3 or another file store.",
    icon: "package",
    name: "bucket",
    local: "uploads-local",
    remote: "uploads-bucket",
  },
  {
    id: "function",
    label: "Function or job",
    plural: "Functions and jobs",
    one: "a function or job",
    hint: "A Lambda, cron job or worker.",
    icon: "cpu",
    name: "worker",
    local: "orders-worker-local",
    remote: "orders-worker",
  },
  {
    id: "other",
    label: "Something else",
    plural: "Other services",
    one: "a service",
    hint: "Name it and give its address.",
    icon: "circle-dashed",
    name: "",
    local: "http://localhost:9000",
    remote: "my-resource-name",
  },
];

export function serviceKind(id: string | null | undefined): ServiceKind | undefined {
  return SERVICE_KINDS.find((kind) => kind.id === id);
}

/** Kinds a hub.json may name by hand that Add service does not offer, each a form of one it does
 * (`like`): its icon, and its place after that kind in a list. */
const MORE_SERVICE_KINDS: readonly (ServiceKindWords & { like: string })[] = [
  {
    id: "frontend",
    label: "Frontend",
    plural: "Frontends",
    one: "a frontend",
    icon: "globe",
    like: "web",
  },
  {
    id: "dynamodb",
    label: "Table (DynamoDB)",
    plural: "Tables (DynamoDB)",
    one: "a table (DynamoDB)",
    icon: "database",
    like: "database",
  },
  {
    id: "sqs",
    label: "Queue (SQS)",
    plural: "Queues (SQS)",
    one: "a queue (SQS)",
    icon: "layers",
    like: "queue",
  },
  {
    id: "bucket",
    label: "Bucket",
    plural: "Buckets",
    one: "a bucket",
    icon: "package",
    like: "storage",
  },
  {
    id: "lambda",
    label: "Function",
    plural: "Functions",
    one: "a function",
    icon: "cpu",
    like: "function",
  },
  {
    id: "cognito",
    label: "User pool",
    plural: "User pools",
    one: "a user pool",
    icon: "users",
    like: "other",
  },
];

/** How any kind is said, the ones Add service offers and the ones written by hand; a kind hub web
 * does not know is said by its id. */
export function serviceKindWords(id: string): ServiceKindWords {
  return (
    serviceKind(id) ??
    MORE_SERVICE_KINDS.find((kind) => kind.id === id) ?? {
      id,
      label: id,
      plural: id,
      one: `a ${id} service`,
      icon: "server",
    }
  );
}

/** Where a kind goes in a list grouped by kind: in the order Add service offers them, each kind
 * written by hand after the one it is a form of, a kind hub web does not know last. */
export function serviceKindRank(id: string | null | undefined): number {
  const own = SERVICE_KINDS.findIndex((kind) => kind.id === id);
  if (own !== -1) return own * 10;
  const more = MORE_SERVICE_KINDS.findIndex((kind) => kind.id === id);
  if (more === -1) return SERVICE_KINDS.length * 10;
  const like = SERVICE_KINDS.findIndex((kind) => kind.id === MORE_SERVICE_KINDS[more]?.like);
  return like * 10 + 1 + more;
}

/** The example address of a kind in an environment: local-looking ones get the local example. */
export function exampleAddress(kind: ServiceKind, environment: SourcedEnvironment): string {
  return /local|dev|mine|laptop/i.test(environment.name) && !environment.production
    ? kind.local
    : kind.remote;
}

/** Whether an address is a URL (it holds ://) or a resource name. */
export function addressKind(address: string): "url" | "resource" {
  return address.includes("://") ? "url" : "resource";
}

/** The usual environments, so a person picks one and gets sensible values. */
export interface EnvironmentPreset {
  id: string;
  label: string;
  hint: string;
  icon: IconName;
  name: string;
  access: Access;
  production: boolean;
  description: string;
  scope: "local" | "team";
}

export const ENVIRONMENT_PRESETS: readonly EnvironmentPreset[] = [
  {
    id: "local",
    label: "This machine",
    hint: "Docker compose, dev servers and local databases on each developer's laptop.",
    icon: "laptop",
    name: "local",
    access: "write",
    production: false,
    description: "Runs on the developer's machine",
    scope: "team",
  },
  {
    id: "staging",
    label: "Test or staging",
    hint: "A shared environment the team tests on.",
    icon: "flask-conical",
    name: "staging",
    access: "ask",
    production: false,
    description: "Shared test environment",
    scope: "team",
  },
  {
    id: "production",
    label: "Production",
    hint: "Real customers and real data. Agents only read.",
    icon: "shield-x",
    name: "production",
    access: "read",
    production: true,
    description: "Live system with real customer data",
    scope: "team",
  },
  {
    id: "mine",
    label: "My own copy",
    hint: "A personal cloud or sandbox only you use.",
    icon: "user",
    name: "personal",
    access: "write",
    production: false,
    description: "My personal sandbox",
    scope: "local",
  },
  {
    id: "other",
    label: "Something else",
    hint: "Start from blank answers.",
    icon: "circle-dashed",
    name: "",
    access: "read",
    production: false,
    description: "",
    scope: "local",
  },
];
