/* Tickets list: every tracker issue a session worked on, one row per issue, grouped from the
 * sessions about it: single-ticket work (fixes, refactors, upgrades, incidents, deliveries) and the
 * tickets of a feature alike. A feature's ticket names the feature it belongs to. */
import type { TicketInfo, TicketLookup } from "../../components";
import type { components } from "../../api/schema";

export type Session = components["schemas"]["Session"];

/** How many of the newest sessions the list groups (the API's page limit). */
export const SESSIONS_READ = 200;

/**
 * The skills of the feature path, `/implement` (a feature ticket's flow, ADR 0043) among them: an
 * issue they worked on is a feature's ticket.
 */
export const FEATURE_PATH: ReadonlySet<string> = new Set([
  "/feature",
  "/implement",
  "/research",
  "/create-plan",
  "/summarize",
]);

/** The single-ticket skills, in the order the Kind filter lists them. */
export const KINDS = [
  { id: "feature", label: "Feature", workflow: null },
  { id: "fix", label: "Fix", workflow: "/fix" },
  { id: "refactor", label: "Refactor", workflow: "/refactor" },
  { id: "upgrade", label: "Upgrade", workflow: "/upgrade" },
  { id: "incident", label: "Incident", workflow: "/incident" },
  { id: "triage", label: "Triage", workflow: "/triage" },
  { id: "deliver", label: "Deliver", workflow: "/deliver" },
  { id: "review", label: "Review", workflow: "/review" },
  { id: "run", label: "Hub run", workflow: null },
  { id: "other", label: "Other", workflow: null },
] as const;
export type KindId = (typeof KINDS)[number]["id"];

export type GroupId = "needs" | "active" | "done";

export const GROUPS: readonly { id: GroupId; title: string; summary: string; empty: string }[] = [
  {
    id: "needs",
    title: "Needs you",
    summary: "need you",
    empty: "No ticket waits on you.",
  },
  {
    id: "active",
    title: "In progress",
    summary: "in progress",
    empty: "No session is working on a ticket now.",
  },
  {
    id: "done",
    title: "Ended",
    summary: "ended",
    empty: "No ended ticket work in the sessions read.",
  },
];

export interface TicketRow {
  project: string;
  issue: string;
  /** The newest session's short name, when it has one. */
  title: string | null;
  kind: KindId;
  /** Every non-routine skill the ticket's sessions ran, oldest first. */
  workflows: string[];
  repos: string[];
  group: GroupId;
  sessions: number;
  /** The newest session, the row's link. */
  latest: Session;
  /** Every session read that worked on the issue, newest first. */
  sessionList: Session[];
  /** The feature that plans the issue, when one does. */
  feature: TicketInfo | null;
  /** The newest pull request any of its sessions opened. */
  pr: Session["pr"];
  costUsd: number;
  lastActivityAt: string;
}

export function issueOf(session: Session): string | null {
  const issue = session.label?.issue ?? session.issue ?? null;
  return issue === null ? null : issue.toUpperCase();
}

function kindOf(workflows: readonly string[], fromRun: boolean, ofFeature: boolean): KindId {
  if (ofFeature || workflows.some((w) => FEATURE_PATH.has(w))) return "feature";
  for (const kind of KINDS) {
    if (kind.workflow !== null && workflows.includes(kind.workflow)) return kind.id;
  }
  return fromRun ? "run" : "other";
}

function groupOf(sessions: readonly Session[]): GroupId {
  if (sessions.some((s) => s.status === "waiting")) return "needs";
  if (sessions.some((s) => s.status !== "ended")) return "active";
  return "done";
}

const newestFirst = (a: Session, b: Session) =>
  Date.parse(b.last_activity_at) - Date.parse(a.last_activity_at);

/**
 * The tickets the sessions worked on: one row per project and issue. `features` maps the issue ids
 * (upper case) the features plan to their feature.
 */
export function ticketsOf(
  sessions: readonly Session[],
  features: TicketLookup = new Map(),
): TicketRow[] {
  const byIssue = new Map<string, Session[]>();
  for (const session of sessions) {
    const issue = issueOf(session);
    if (issue === null) continue;
    const key = `${session.project}\u0000${issue}`;
    const list = byIssue.get(key);
    if (list) list.push(session);
    else byIssue.set(key, [session]);
  }
  const rows: TicketRow[] = [];
  for (const list of byIssue.values()) {
    const ordered = [...list].sort(newestFirst);
    const workflows = [
      ...new Set(
        [...ordered]
          .reverse()
          .flatMap((s) => s.label?.workflows ?? [])
          .filter((w) => !ROUTINE.has(w)),
      ),
    ];
    const latest = ordered[0];
    if (!latest) continue;
    const issue = issueOf(latest) ?? "";
    const owner = features.get(issue);
    const feature = owner?.project === latest.project ? owner : null;
    rows.push({
      project: latest.project,
      issue,
      title: feature?.title ?? ordered.find((s) => s.label?.title)?.label?.title ?? null,
      kind: kindOf(
        workflows,
        ordered.some((s) => s.run_id),
        feature !== null,
      ),
      workflows,
      repos: [...new Set(ordered.flatMap((s) => s.label?.repo ?? s.repo ?? []))].sort(),
      group: groupOf(ordered),
      sessions: ordered.length,
      latest,
      sessionList: ordered,
      feature,
      pr: ordered.find((s) => s.pr)?.pr ?? null,
      costUsd: ordered.reduce((sum, s) => sum + Number(s.cost_usd ?? 0), 0),
      lastActivityAt: latest.last_activity_at,
    });
  }
  return rows.sort((a, b) => Date.parse(b.lastActivityAt) - Date.parse(a.lastActivityAt));
}

/**
 * The commands run around the work: the session label's `ROUTINE_COMMANDS` (server-side), and the
 * hub's `/learn` and `/plain-language`, which never name a ticket's kind.
 */
const ROUTINE: ReadonlySet<string> = new Set([
  "/kickoff",
  "/handoff",
  "/clear",
  "/compact",
  "/resume",
  "/model",
  "/help",
  "/config",
  "/cost",
  "/status",
  "/exit",
  "/learn",
  "/plain-language",
]);

export function matchesQuery(row: TicketRow, q: string): boolean {
  const needle = q.trim().toLowerCase();
  if (!needle) return true;
  return [
    row.issue,
    row.title ?? "",
    row.project,
    row.feature?.slug ?? "",
    ...row.repos,
    ...row.workflows,
  ].some((text) => text.toLowerCase().includes(needle));
}
