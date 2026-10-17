/* Sessions as an inbox (v2 design): what each row says, in plain words, one fact per row. */
import { sessionIdentity, type IconName } from "../../components";
import { fmtDuration } from "../../lib/format";
import { modeLabel, resumable } from "../agent-session/model";
import type { AgentSession, Session } from "./queries";
import { isDriven, type SectionId, type SectionRow } from "./sections";

export type Tone = "waiting" | "failed" | "done" | "blocked" | "subtle" | "live";

export interface RowView {
  /** Leading mark: an icon, the live pulse, or nothing. */
  lead: { icon: IconName; tone: Tone } | "pulse" | null;
  /** The one useful fact under the title. */
  line: string;
  lineTone: Tone | null;
  /** Shown after the title only when they say something: Terminal, run, repo, project. */
  tags: string[];
  /** The time on the right and its tooltip. */
  time: string | null;
  timeTip: string;
  /** The always-visible button: only for what needs the owner. */
  action: "answer" | "review" | null;
  /** True when the row may offer Resume (finished, resumable chat). */
  resumable: boolean;
  /** No end signal arrived: the outcome is assumed. */
  inferred: boolean;
}

export interface ViewContext {
  group: SectionId;
  /** The driven session behind a row (itself when twinless driven, a twin's otherwise). */
  drv: AgentSession | null;
  /** The most common repo among loaded rows: a row's repo shows only when it differs. */
  commonRepo: string | null;
  showProject: boolean;
}

const short = (id: string) => id.replace(/-/g, "").slice(0, 8);
const count = (n: number, one: string, many: string) => `${String(n)} ${n === 1 ? one : many}`;
const QUIET_BRANCHES = new Set(["HEAD", "main", "master"]);

const CLOSED: Record<string, string> = {
  closed: "Closed by you",
  idle_timeout: "Closed automatically after a pause",
  server_stopped: "Closed when hub web stopped",
  log_full: "Closed: the conversation is full",
  failed: "Failed",
};

function problemText(s: Session): string {
  return s.needs_you_problem ?? count(s.problems.needs_you, "problem needs you", "problems need you");
}

/** When the session last did something (or was asked), for the right-hand time. */
function lastAt(row: SectionRow, drv: AgentSession | null): string {
  if (isDriven(row)) return row.updated_at;
  return drv && Date.parse(drv.updated_at) > Date.parse(row.last_activity_at)
    ? drv.updated_at
    : row.last_activity_at;
}

function startOf(row: SectionRow): string {
  return isDriven(row) ? row.created_at : row.started_at;
}

/** The outcome word and icon of a finished session. */
function outcomeOf(
  row: SectionRow,
  drv: AgentSession | null,
): { word: string; icon: IconName; tone: Tone; inferred: boolean } {
  const failed = { icon: "circle-x" as const, tone: "failed" as const, inferred: false };
  const closed = { icon: "circle-stop" as const, tone: "subtle" as const, inferred: false };
  if (!isDriven(row) && row.outcome === "error") return { word: "Failed", ...failed };
  const reason = drv?.end_reason ?? (drv?.status === "failed" ? "failed" : null);
  if (reason === "failed") return { word: "Failed", ...failed };
  if (reason) return { word: CLOSED[reason] ?? "Closed", ...closed };
  if (isDriven(row)) return { word: "Closed", ...closed };
  switch (row.outcome) {
    case "done":
      return { word: "Done", icon: "circle-check", tone: "done", inferred: false };
    case "stopped":
      return { word: "Stopped", icon: "octagon-x", tone: "blocked", inferred: false };
    case "blocked":
      return { word: "Blocked", icon: "octagon-x", tone: "blocked", inferred: false };
    default:
      return row.end_inferred
        ? { word: "Closed", icon: "circle-dashed", tone: "subtle", inferred: true }
        : { word: "Closed", ...closed };
  }
}

function tagsOf(row: SectionRow, ctx: ViewContext): string[] {
  const tags: string[] = [];
  if (isDriven(row)) {
    if (ctx.commonRepo !== null && row.workdir_label !== ctx.commonRepo) tags.push(row.workdir_label);
  } else {
    if (!row.agent_session_id) tags.push("Terminal");
    if (row.run_id) tags.push(`Run ${row.issue ?? short(row.run_id)}${row.step ? ` · ${row.step}` : ""}`);
    const repo = row.label?.repo ?? row.repo;
    const branch = row.label?.branch;
    if (repo && ctx.commonRepo !== null && repo !== ctx.commonRepo) {
      tags.push(branch && !QUIET_BRANCHES.has(branch) ? `${repo} · ${branch}` : repo);
    } else if (branch && !QUIET_BRANCHES.has(branch)) {
      tags.push(branch);
    }
  }
  if (ctx.showProject) tags.unshift(row.project);
  return tags;
}

export function rowView(row: SectionRow, ctx: ViewContext): RowView {
  const { group, drv } = ctx;
  const tags = tagsOf(row, ctx);
  const base = { tags, resumable: false, inferred: false, action: null, lineTone: null } as const;
  const ask = drv?.open_permission ?? null;

  if (group === "waiting") {
    if (!isDriven(row) && row.problems.needs_you > 0 && row.status !== "waiting") {
      return {
        ...base,
        lead: { icon: "circle-x", tone: "failed" },
        line: problemText(row),
        lineTone: "failed",
        time: lastAt(row, drv),
        timeTip: "Last activity",
        action: "review",
      };
    }
    let line: string;
    let icon: IconName = "hand";
    if (ask) line = `Asks to use ${ask.tool}: ${ask.summary}`;
    else if (isDriven(row) || drv) line = "Asks for a permission";
    else if (row.waiting_reason === "Guard ask") {
      line = "A guard asks you to confirm · no timeout";
      icon = "shield-alert";
    } else if (row.waiting_reason === "Permission prompt") line = "Asks for a permission in the terminal";
    else line = row.waiting_reason ?? "Waiting for you in the terminal";
    return {
      ...base,
      lead: { icon, tone: "waiting" },
      line,
      time: ask?.asked_at ?? lastAt(row, drv),
      timeTip: "Asked",
      action: "answer",
    };
  }

  if (group === "live") {
    if (isDriven(row))
      return { ...base, lead: "pulse", line: "Working on your message", time: lastAt(row, drv), timeTip: "Last activity" };
    if (row.failing_notice)
      return {
        ...base,
        lead: { icon: "circle-x", tone: "failed" },
        line: row.failing_notice,
        lineTone: "failed",
        time: lastAt(row, drv),
        timeTip: "Last activity",
      };
    return {
      ...base,
      lead: "pulse",
      line: row.last_action ?? (drv ? "Working on your message" : "Starting"),
      time: lastAt(row, drv),
      timeTip: "Last activity",
    };
  }

  if (group === "idle") {
    let line: string;
    if (isDriven(row)) line = [`${modeLabel(row.mode)} mode`, row.model].filter(Boolean).join(" · ");
    else line = row.last_action ?? "No tool used yet";
    return { ...base, lead: null, line, time: lastAt(row, drv), timeTip: "Last activity" };
  }

  // Finished
  const outcome = outcomeOf(row, drv);
  let fact: string | null = null;
  let lineTone: Tone | null = null;
  let lead: RowView["lead"] = { icon: outcome.icon, tone: outcome.tone };
  if (!isDriven(row) && row.problems.needs_you > 0) {
    fact = problemText(row);
    lineTone = "failed";
    lead = { icon: "circle-x", tone: "failed" };
  } else if (outcome.word === "Failed") {
    fact = (!isDriven(row) && (row.failing_notice ?? row.last_action)) || null;
  } else if (outcome.word === "Blocked" && !isDriven(row)) {
    fact = row.last_action ?? null;
  } else if (!isDriven(row) && row.pr) {
    fact = `PR #${String(row.pr.number)} ${row.pr.state.toLowerCase()}`;
  }
  const ended = row.ended_at ?? null;
  if (fact === null && ended)
    fact = `ran ${fmtDuration((Date.parse(ended) - Date.parse(startOf(row))) / 1000)}`;
  const canResume =
    drv !== null &&
    (drv.status === "ended" || drv.status === "failed") &&
    resumable(drv, drv.end_reason);
  return {
    ...base,
    lead,
    line: fact ? `${outcome.word} · ${fact}` : outcome.word,
    lineTone,
    time: ended ?? lastAt(row, drv),
    timeTip: "Ended",
    resumable: canResume,
    inferred: outcome.inferred,
  };
}

/** Order inside a group: the oldest wait first in Needs you, the latest activity first while open. */
export function orderRows(
  group: SectionId,
  rows: SectionRow[],
  drvOf: (row: SectionRow) => AgentSession | null,
): SectionRow[] {
  if (group === "ended") return rows;
  const at = (row: SectionRow) => Date.parse(lastAt(row, drvOf(row)));
  const sorted = [...rows];
  sorted.sort((a, b) => (group === "waiting" ? at(a) - at(b) : at(b) - at(a)));
  return sorted;
}

/** The repo most loaded rows share; a row names its repo only when it differs. */
export function commonRepoOf(rows: readonly SectionRow[]): string | null {
  const counts = new Map<string, number>();
  for (const row of rows) {
    const repo = isDriven(row) ? row.workdir_label : (row.label?.repo ?? row.repo);
    if (repo) counts.set(repo, (counts.get(repo) ?? 0) + 1);
  }
  let best: string | null = null;
  let most = 0;
  for (const [repo, n] of counts)
    if (n > most) {
      best = repo;
      most = n;
    }
  return best;
}

/** The searchable title of a row (for aria names). */
export function rowTitle(row: SectionRow): string {
  return isDriven(row) ? (row.title ?? "Untitled session") : sessionIdentity(row).title;
}
