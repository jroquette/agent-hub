/* Sessions as an inbox (v2 design): what each row says, in plain words, one fact per row. */
import { sessionIdentity, TOOL_ICON, type IconName, type Status } from "../../components";
import { fmtDuration } from "../../lib/format";
import { isReviewable } from "../agent-session/fileKind";
import { modeLabel, resumable } from "../agent-session/model";
import type { AgentSession, Session } from "./queries";
import { isDriven, type SectionId, type SectionRow } from "./sections";

export type Tone = "waiting" | "failed" | "done" | "blocked" | "subtle" | "live";

/** Where a session runs: the context column of the list. */
export interface RowWhere {
  project: string | null;
  repo: string | null;
  branch: string | null;
  issue: string | null;
  run: string | null;
}

export interface RowView {
  /** The status badge of the row: icon + label, the same words for terminal and chat sessions. */
  status: { status: Status; label: string };
  /** What the session does or did, in plain words, with the tool's icon. */
  icon: IconName | null;
  line: string;
  /** The exact command, path or pattern behind the line (mono, secondary). */
  detail: string | null;
  lineTone: Tone | null;
  /** Started from the app's chat, or observed from a terminal. */
  origin: "chat" | "terminal";
  /** The chat's permission mode when it is not the default one ("Auto mode"). */
  mode: string | null;
  where: RowWhere;
  /** The time on the right and its tooltip. */
  time: string | null;
  timeTip: string;
  /** The always-visible button: only for what needs the owner. */
  action: "answer" | "review" | null;
  /** The conversation so far, for a chat in Working or Your turn: your last ask, Claude's last reply. */
  conversation: { prompt: string | null; reply: string | null } | null;
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

const CLOSED: Record<string, string> = {
  closed: "Closed by you",
  idle_timeout: "Closed automatically after a pause",
  server_stopped: "Closed when hub web stopped",
  log_full: "Closed: the conversation is full",
  failed: "Failed",
};

function problemText(s: Session): string {
  return (
    s.needs_you_problem ?? count(s.problems.needs_you, "problem needs you", "problems need you")
  );
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

function whereOf(row: SectionRow, ctx: ViewContext): RowWhere {
  const project = ctx.showProject ? row.project : null;
  if (isDriven(row))
    return { project, repo: row.workdir_label || null, branch: null, issue: null, run: null };
  const issue = row.label?.issue ?? row.issue ?? null;
  const branch = row.label?.branch ?? null;
  return {
    project,
    repo: row.label?.repo ?? row.repo ?? ctx.drv?.workdir_label ?? null,
    // A detached HEAD names no branch.
    branch: branch === "HEAD" ? null : branch,
    issue,
    run: row.run_id ? `Run ${issue ?? short(row.run_id)}${row.step ? ` · ${row.step}` : ""}` : null,
  };
}

const VERBS: { prefix: string; now: string; past: string; icon: IconName }[] = [
  { prefix: "Ran ", now: "Running a command", past: "ran a command", icon: "terminal" },
  { prefix: "Edited ", now: "Editing a file", past: "edited a file", icon: "file-pen" },
  { prefix: "Read ", now: "Reading a file", past: "read a file", icon: "file-text" },
  {
    prefix: "Searched ",
    now: "Searching the code",
    past: "searched the code",
    icon: "text-search",
  },
];

/**
 * The last tool call in plain words: "Running a command" while it works, "Last step: ran a command"
 * once its turn ended, with the command, path or pattern as the detail (`live_tiles._last_action`).
 */
export function activityOf(
  lastAction: string | null | undefined,
  lastTool: string | null | undefined,
  tense: "now" | "past",
): { icon: IconName | null; line: string; detail: string | null } {
  const toolIcon = lastTool ? (TOOL_ICON[lastTool] ?? null) : null;
  if (!lastAction)
    return { icon: null, line: tense === "now" ? "Starting" : "Turn finished", detail: null };
  const say = (now: string, past: string) => (tense === "now" ? now : `Last step: ${past}`);
  for (const verb of VERBS) {
    if (!lastAction.startsWith(verb.prefix)) continue;
    const write = verb.prefix === "Edited " && lastTool === "Write";
    return {
      icon: toolIcon ?? verb.icon,
      line: write ? say("Writing a file", "wrote a file") : say(verb.now, verb.past),
      detail: lastAction.slice(verb.prefix.length),
    };
  }
  if (lastAction.startsWith("Used ")) {
    const tool = lastAction.slice(5);
    if (tool === "Agent" || tool === "Task")
      return {
        icon: "network",
        line: say("Working with a subagent", "used a subagent"),
        detail: null,
      };
    return { icon: toolIcon ?? "plug", line: say(`Using ${tool}`, `used ${tool}`), detail: null };
  }
  return {
    icon: toolIcon,
    line: tense === "now" ? "Working" : "Turn finished",
    detail: lastAction,
  };
}

export function rowView(row: SectionRow, ctx: ViewContext): RowView {
  const { group, drv } = ctx;
  const summary = drv ? summaryOf(drv) : null;
  const talk =
    summary && (summary.prompt || summary.reply)
      ? { prompt: summary.prompt, reply: summary.reply }
      : null;
  const driven = isDriven(row);
  const chatMode = driven ? row.mode : (drv?.mode ?? null);
  const base = {
    where: whereOf(row, ctx),
    origin: driven || drv || row.agent_session_id ? "chat" : "terminal",
    mode: chatMode && chatMode !== "default" ? `${modeLabel(chatMode)} mode` : null,
    resumable: false,
    inferred: false,
    action: null,
    lineTone: null,
    conversation: null,
    detail: null,
  } as const;
  const ask = drv?.open_permission ?? null;

  if (group === "waiting") {
    if (!driven && row.problems.needs_you > 0 && row.status !== "waiting") {
      return {
        ...base,
        status: { status: "failed", label: "Problem" },
        icon: "circle-x",
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
    else if (driven || drv) line = "Asks for a permission";
    else if (row.waiting_reason === "Guard ask") {
      line = "A guard asks you to confirm · no timeout";
      icon = "shield-alert";
    } else if (row.waiting_reason === "Permission prompt")
      line = "Asks for a permission in the terminal";
    else line = row.waiting_reason ?? "Waiting for you in the terminal";
    return {
      ...base,
      status: { status: "waiting", label: "Waiting for you" },
      icon,
      line,
      time: ask?.asked_at ?? lastAt(row, drv),
      timeTip: "Asked",
      action: "answer",
    };
  }

  if (group === "live") {
    const working = { status: "live", label: "Working" } as const;
    if (driven)
      return {
        ...base,
        status: working,
        conversation: talk,
        icon: "message-square",
        line: "Working on your message",
        time: lastAt(row, drv),
        timeTip: "Last activity",
      };
    if (row.failing_notice)
      return {
        ...base,
        status: working,
        icon: "circle-x",
        line: row.failing_notice,
        lineTone: "failed",
        time: lastAt(row, drv),
        timeTip: "Last activity",
      };
    const act =
      row.last_action || !drv
        ? activityOf(row.last_action, row.last_tool, "now")
        : { icon: "message-square" as const, line: "Working on your message", detail: null };
    return {
      ...base,
      status: working,
      conversation: talk,
      ...act,
      time: lastAt(row, drv),
      timeTip: "Last activity",
    };
  }

  if (group === "idle") {
    const yourTurn = { status: "idle", label: "Your turn" } as const;
    const act =
      driven || (drv && !row.last_action)
        ? { icon: "message-square" as const, line: "Waiting for your next message", detail: null }
        : activityOf(row.last_action, row.last_tool, "past");
    return {
      ...base,
      status: yourTurn,
      conversation: talk,
      ...act,
      time: lastAt(row, drv),
      timeTip: "Last activity",
    };
  }

  // Finished: the badge says how it ended, the line adds why or what it produced.
  const outcome = outcomeOf(row, drv);
  const facts: string[] = [];
  let lineTone: Tone | null = null;
  let icon: IconName | null = null;
  let status: RowView["status"] = { status: STATUS_OF[outcome.tone], label: outcome.word };
  if (outcome.word.startsWith("Closed") && outcome.word !== "Closed") {
    // "Closed by you" and friends: the badge says Closed, the line says how.
    status = { status: "ended", label: "Closed" };
    facts.push(outcome.word);
  }
  if (!driven && row.problems.needs_you > 0) {
    facts.push(problemText(row));
    lineTone = "failed";
    icon = "circle-x";
  } else if (outcome.word === "Failed") {
    const why = driven ? null : (row.failing_notice ?? row.last_action ?? null);
    if (why) facts.push(why);
  } else if (outcome.word === "Blocked" && !driven) {
    if (row.last_action) facts.push(row.last_action);
  } else if (!driven && row.pr) {
    facts.push(`PR #${String(row.pr.number)} ${row.pr.state.toLowerCase()}`);
    icon = row.pr.state.toLowerCase() === "merged" ? "git-merge" : "git-pull-request";
  }
  const ended = row.ended_at ?? null;
  if (ended)
    facts.push(`Ran ${fmtDuration((Date.parse(ended) - Date.parse(startOf(row))) / 1000)}`);
  const canResume =
    drv !== null &&
    (drv.status === "ended" || drv.status === "failed") &&
    resumable(drv, drv.end_reason);
  const line = facts.length > 0 ? facts.join(" · ") : "No details recorded";
  return {
    ...base,
    status,
    icon,
    line: line.charAt(0).toUpperCase() + line.slice(1),
    lineTone,
    time: ended ?? lastAt(row, drv),
    timeTip: "Ended",
    resumable: canResume,
    inferred: outcome.inferred,
  };
}

const STATUS_OF: Record<Tone, Status> = {
  done: "done",
  failed: "failed",
  blocked: "blocked",
  subtle: "ended",
  waiting: "waiting",
  live: "live",
};

/** What hub web keeps about a chat: its last ask and reply, and the files it changed. */
export interface ChatSummary {
  prompt: string | null;
  reply: string | null;
  files: { path: string; last_change_id: string }[];
}

/** What hub web keeps about a chat's last turn and edits. */
export function summaryOf(session: AgentSession): ChatSummary {
  return {
    prompt: session.last_prompt ?? null,
    reply: session.last_reply ?? null,
    // A hub web older than the digest (the playground's conductor) sends no changed_files.
    files: (session as Partial<AgentSession>).changed_files ?? [],
  };
}

/** How many files a chat changed, and how many changed since you last marked them viewed. */
export function filesToReview(
  files: ChatSummary["files"],
  reviewed: Record<string, string>,
): { total: number; toReview: number } {
  return {
    total: files.length,
    // Only the code waits for review: Claude's plans, learnings and scratch never do.
    toReview: files.filter(
      (file) => isReviewable(file.path) && reviewed[file.path] !== file.last_change_id,
    ).length,
  };
}

/** Order inside a group: the oldest wait first in Needs you, else the latest (activity or end) first. */
export function orderRows(
  group: SectionId,
  rows: SectionRow[],
  drvOf: (row: SectionRow) => AgentSession | null,
): SectionRow[] {
  const at = (row: SectionRow) =>
    Date.parse(
      group === "ended" ? (row.ended_at ?? lastAt(row, drvOf(row))) : lastAt(row, drvOf(row)),
    );
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
