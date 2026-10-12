import type { Stage as ChipStage, Status } from "../../components";
import { STAGES } from "../../components";
import type { WorkflowRun } from "../runs-list/queries";
import type { Finding, Session } from "./queries";

/* View models of the Project overview (spec 12): Kanban, Now staleness, health and sessions. */

export const WEEK_MS = 7 * 86_400_000;
export const COLUMN_CAP = 5;
/** Knowledge not verified for longer than this turns amber (calibrated trust). */
export const STALE_DAYS = 60;

export type Column = ChipStage | "FAILED";

/** Runs per Kanban column: in-flight stages now, and Reported / Failed that ended in 7 days. */
export function kanban(runs: readonly WorkflowRun[], now: number): Record<Column, WorkflowRun[]> {
  const columns = Object.fromEntries(
    [...STAGES.map((s) => s.id), "FAILED"].map((id) => [id, [] as WorkflowRun[]]),
  ) as Record<Column, WorkflowRun[]>;
  const recent = (run: WorkflowRun) =>
    run.ended_at !== null && now - Date.parse(run.ended_at) <= WEEK_MS;
  for (const run of runs) {
    if ((run.stage === "REPORTED" || run.stage === "FAILED") && !recent(run)) continue;
    columns[run.stage].push(run);
  }
  const latest = (a: WorkflowRun, b: WorkflowRun) =>
    Date.parse(b.ended_at ?? b.last_activity_at) - Date.parse(a.ended_at ?? a.last_activity_at);
  columns.REPORTED.sort(latest);
  columns.FAILED.sort(latest);
  return columns;
}

/** Days since `last_verified` ("2026-07-30"); null without a date. */
export function daysSince(date: string | null | undefined, now: number): number | null {
  if (!date) return null;
  const at = Date.parse(date);
  return Number.isNaN(at) ? null : Math.floor((now - at) / 86_400_000);
}

export interface HealthSummary {
  error: number;
  warning: number;
  info: number;
}

export function healthSummary(findings: readonly Finding[]): HealthSummary {
  return {
    error: findings.filter((f) => f.severity === "error").length,
    warning: findings.filter((f) => f.severity === "warning").length,
    info: findings.filter((f) => f.severity === "info").length,
  };
}

const SEVERITY_RANK = { error: 0, warning: 1, info: 2 } as const;

export function topFindings(findings: readonly Finding[], n = 3): Finding[] {
  return [...findings]
    .sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity])
    .slice(0, n);
}

function plural(n: number, word: string): string {
  return `${String(n)} ${word}${n === 1 ? "" : "s"}`;
}

export function healthLine(summary: HealthSummary): string {
  return `${plural(summary.error, "error")} · ${plural(summary.warning, "warning")} · ${String(summary.info)} info`;
}

/** The header badge: failed with errors, waiting with warnings, done when clear. */
export function healthBadge(summary: HealthSummary): { status: Status; label: string } {
  if (summary.error) {
    return {
      status: "failed",
      label: `Health · ${plural(summary.error, "error")}${summary.warning ? `, ${plural(summary.warning, "warning")}` : ""}`,
    };
  }
  if (summary.warning)
    return { status: "waiting", label: `Health · ${plural(summary.warning, "warning")}` };
  return { status: "done", label: "Health · no findings" };
}

/** Live first, then by start time (spec 12, Recent sessions). */
export function recentSessions(sessions: readonly Session[]): Session[] {
  const active = (s: Session) => (s.status === "live" || s.status === "waiting" ? 0 : 1);
  return [...sessions].sort(
    (a, b) => active(a) - active(b) || Date.parse(b.started_at) - Date.parse(a.started_at),
  );
}

export function sessionBadge(session: Session): { status: Status; label?: string } {
  if (session.status !== "ended") return { status: session.status };
  if (session.outcome) return { status: session.outcome };
  return { status: "ended" };
}
