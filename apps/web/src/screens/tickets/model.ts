/* Tickets list: single-ticket work (fixes, refactors, upgrades, incidents, deliveries) grouped from
 * the sessions about each tracker issue. Features keep their own list; a ticket a feature plans, or
 * one a feature-path skill worked on, is left out here so nothing shows twice. */
import type { components } from "../../api/schema";

export type Session = components["schemas"]["Session"];

/**
 * The skills of the feature path, `/implement` (a feature ticket's flow, ADR 0043) among them: an
 * issue they worked on belongs to Features.
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
  /** The newest pull request any of its sessions opened. */
  pr: Session["pr"];
  costUsd: number;
  lastActivityAt: string;
}

export function issueOf(session: Session): string | null {
  const issue = session.label?.issue ?? session.issue ?? null;
  return issue === null ? null : issue.toUpperCase();
}

function kindOf(workflows: readonly string[], fromRun: boolean): KindId {
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
 * The tickets the sessions worked on outside the feature path: one row per project and issue.
 * `featureIssues` holds the issue ids (upper case) the features plan.
 */
export function ticketsOf(
  sessions: readonly Session[],
  featureIssues: ReadonlySet<string>,
): TicketRow[] {
  const byIssue = new Map<string, Session[]>();
  for (const session of sessions) {
    const issue = issueOf(session);
    if (issue === null || featureIssues.has(issue)) continue;
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
    if (workflows.some((w) => FEATURE_PATH.has(w))) continue;
    const latest = ordered[0];
    if (!latest) continue;
    const issue = issueOf(latest) ?? "";
    rows.push({
      project: latest.project,
      issue,
      title: ordered.find((s) => s.label?.title)?.label?.title ?? null,
      kind: kindOf(
        workflows,
        ordered.some((s) => s.run_id),
      ),
      workflows,
      repos: [...new Set(ordered.flatMap((s) => s.label?.repo ?? s.repo ?? []))].sort(),
      group: groupOf(ordered),
      sessions: ordered.length,
      latest,
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
  return [row.issue, row.title ?? "", row.project, ...row.repos, ...row.workflows].some((text) =>
    text.toLowerCase().includes(needle),
  );
}
