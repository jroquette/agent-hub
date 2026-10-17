/* Sessions grid: the SessionTile view model of a session, and the tile order (ADR 0033 D3, D8; spec 14). */
import type { components } from "../../api/schema";
import {
  sessionIdentity,
  type IconName,
  type LiveSession,
  type Status,
  type TileTimes,
} from "../../components";
import { fmtAgo, toNumber } from "../../lib/format";
import type { Within } from "./filters";
import { isDriven, type SectionRow } from "./sections";

type Schemas = components["schemas"];
type Session = Schemas["Session"];
type AgentSession = Schemas["AgentSession"];
type Outcome = Schemas["Outcome"];

/** The fields a tile reads from an observed session. */
export type TileSource = Pick<
  Session,
  | "id"
  | "status"
  | "project"
  | "repo"
  | "started_at"
  | "last_activity_at"
  | "turns"
  | "files_touched"
  | "cost_usd"
  | "problems"
  | "guard_denials"
> &
  Partial<
    Pick<
      Session,
      | "label"
      | "outcome"
      | "ended_at"
      | "waiting_reason"
      | "run_id"
      | "issue"
      | "step"
      | "attempt"
      | "last_action"
      | "last_tool"
      | "needs_you_problem"
      | "failing_notice"
      | "sparkline_60s"
      | "agent_session_id"
    >
  >;

const TOOL_ICON: Record<string, IconName> = {
  Read: "file-text",
  Edit: "file-pen",
  Write: "file-plus",
  Bash: "terminal",
  Grep: "text-search",
  Glob: "folder-search",
  Agent: "network",
  WebFetch: "globe",
};
const OUTCOME: Record<Outcome, Status> = {
  done: "done",
  stopped: "stopped",
  blocked: "blocked",
  error: "error",
};
const short = (id: string) => id.replace(/-/g, "").slice(0, 8);
const seconds = (from: string, to: number) => Math.max(0, (to - Date.parse(from)) / 1000);
const chatHref = (id: string) => `/agent-sessions/${encodeURIComponent(id)}`;
const count = (n: number, one: string, many: string) => `${String(n)} ${n === 1 ? one : many}`;

/** A red edge only when a problem needs the owner (E11); a failing notice alone stays text. */
export function troubled(tile: Pick<TileSource, "problems">): boolean {
  return tile.problems.needs_you > 0;
}

/**
 * The tile's problems line (AC-201.14): the first problem that needs the owner, else what the agent
 * handled, is still on, or the owner interrupted; null without problems.
 */
export function problemsLine(
  tile: Pick<TileSource, "problems" | "needs_you_problem">,
): string | null {
  const { needs_you, handled, open, by_you } = tile.problems;
  if (needs_you > 0) {
    return tile.needs_you_problem ?? `Needs you: ${count(needs_you, "problem", "problems")}`;
  }
  const parts = [
    handled > 0 ? `${count(handled, "problem", "problems")}, handled by the agent` : "",
    open > 0 ? `${count(open, "problem", "problems")}, agent is on it` : "",
    by_you > 0 ? `${String(by_you)} handled by you` : "",
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(" · ") : null;
}

/**
 * Where a waiting tile sends the owner: a session hub web drives to its chat, where the
 * permission card answers it (AC-165.25); any other wait, a hook-observed permission prompt
 * included, to the session itself (AC-273.21).
 */
export function waitingLink(tile: Pick<TileSource, "id" | "agent_session_id">): {
  href: string;
  label: string;
} {
  if (tile.agent_session_id) return { href: chatHref(tile.agent_session_id), label: "Open chat" };
  return { href: `/sessions/${encodeURIComponent(tile.id)}`, label: "Open session" };
}

/** The tile of an observed session's fields, with its `tokens` total and whether it is a subagent. */
function tileFrom(
  tile: TileSource,
  now: number,
  { tokens, subagent }: { tokens: number; subagent: boolean },
): LiveSession {
  const ago = seconds(tile.last_activity_at, now);
  const runLine = tile.run_id
    ? `Run ${tile.issue ?? short(tile.run_id)}${tile.step ? ` › ${tile.step}` : ""}${tile.attempt ? ` · attempt ${String(tile.attempt)}` : ""}`
    : "no run";
  const action =
    tile.status === "waiting"
      ? `Waiting ${String(Math.max(1, Math.round(ago / 60)))} min${tile.waiting_reason === "Guard ask" ? " · a guard ask has no timeout" : ""}`
      : tile.status === "idle"
        ? `Last: ${tile.last_action ?? "no tool call yet"} · ${fmtAgo(ago)}`
        : (tile.last_action ?? "Starting");
  const identity = sessionIdentity(tile);
  return {
    id: tile.id,
    status: tile.status,
    outcome: tile.outcome ? OUTCOME[tile.outcome] : undefined,
    reason: tile.waiting_reason ? `Waiting · ${tile.waiting_reason}` : undefined,
    title: identity.title,
    detail: identity.detail,
    subagent,
    project: tile.project,
    repo: `${tile.repo ?? "—"} · ${runLine}`,
    lastAction: action,
    lastIcon: tile.last_tool ? (TOOL_ICON[tile.last_tool] ?? "terminal") : "activity",
    lastAgo: tile.status === "live" ? fmtAgo(ago) : "",
    notice: tile.failing_notice ?? null,
    link: tile.status === "waiting" ? waitingLink(tile) : null,
    elapsed: seconds(tile.started_at, tile.ended_at ? Date.parse(tile.ended_at) : now),
    turns: tile.turns,
    tokens,
    files: tile.files_touched,
    cost: toNumber(tile.cost_usd),
    problems: problemsLine(tile),
    needsYou: troubled(tile),
    denials: tile.guard_denials,
    activity:
      tile.status === "ended" || tile.status === "idle"
        ? undefined
        : (tile.sparkline_60s ?? undefined),
    chat: Boolean(tile.agent_session_id),
  };
}

/** The tile of an observed session (spec 11, "Tile anatomy"). */
export function tileOf(session: Session, now: number): LiveSession {
  const t = session.tokens;
  return tileFrom(session, now, {
    tokens: t ? t.input + t.output + t.cache_read + t.cache_write : 0,
    subagent: session.parent_session_id != null,
  });
}

const DRIVEN_STATUS: Record<AgentSession["status"], LiveSession["status"]> = {
  running: "live",
  idle: "idle",
  waiting_permission: "waiting",
  ended: "ended",
  failed: "ended",
};
const DRIVEN_ACTION: Record<AgentSession["status"], string> = {
  running: "Running a turn",
  idle: "Waiting for your next message",
  waiting_permission: "Asks for a permission",
  ended: "Ended",
  failed: "Failed",
};

/** The tile of a driven session without an observed twin: what an AgentSession knows, blanks for the rest (Q4). */
export function tileOfDriven(session: AgentSession, now: number): LiveSession {
  const status = DRIVEN_STATUS[session.status];
  const ask = session.open_permission;
  const usage = session.usage;
  return {
    id: session.id,
    status,
    outcome: session.status === "failed" ? "failed" : status === "ended" ? "done" : undefined,
    outcomeLabel: session.end_reason ? session.end_reason.replace(/_/g, " ") : undefined,
    reason:
      status !== "waiting"
        ? undefined
        : ask
          ? `Waiting · ${ask.tool}: ${ask.summary}`
          : "Waiting · Permission prompt",
    title: session.title ?? "Untitled session",
    detail: session.workdir_label,
    project: session.project,
    repo: session.workdir_label,
    lastAction: ask ? `Asks to run ${ask.tool}` : DRIVEN_ACTION[session.status],
    lastIcon: ask ? (TOOL_ICON[ask.tool] ?? "terminal") : "message-square",
    lastAgo: status === "ended" ? "" : fmtAgo(seconds(session.updated_at, now)),
    link: status === "waiting" ? { href: chatHref(session.id), label: "Open chat" } : null,
    elapsed: seconds(session.created_at, session.ended_at ? Date.parse(session.ended_at) : now),
    turns: null,
    tokens: usage ? usage.input + usage.output + usage.cache_read + usage.cache_write : 0,
    files: null,
    cost: toNumber(session.cost_usd),
    needsYou: false,
    chat: true,
  };
}

/** A section row as a tile: a driven one without a twin, or an observed one. */
export function tileOfRow(row: SectionRow, now: number): LiveSession {
  return isDriven(row) ? tileOfDriven(row, now) : tileOf(row, now);
}

/** A running row's clock-dependent tile fields; none for an ended row, whose tile cannot change. */
export function tileTimesOf(row: SectionRow): ((now: number) => TileTimes) | undefined {
  if (tileOfRow(row, 0).status === "ended") return undefined;
  return (now) => {
    const { elapsed, lastAction, lastAgo } = tileOfRow(row, now);
    return { elapsed, lastAction, lastAgo };
  };
}

export interface RowGroup {
  key: string;
  label: string;
  rows: SectionRow[];
}

function groupKey(row: SectionRow, within: Within): [string, string] {
  const none: [string, string] = ["", within === "run" ? "Not in a run" : "No workflow"];
  if (isDriven(row)) {
    return within === "repo"
      ? [`${row.project}/${row.workdir_label}`, `${row.project} › ${row.workdir_label}`]
      : none;
  }
  switch (within) {
    case "repo":
      return [`${row.project}/${row.repo ?? ""}`, `${row.project} › ${row.repo ?? "no repo"}`];
    case "run":
      return row.run_id
        ? [row.run_id, `Run ${row.issue ?? short(row.run_id)}${row.step ? ` · ${row.step}` : ""}`]
        : none;
    case "workflow":
      return row.label?.workflow ? [row.label.workflow, row.label.workflow] : none;
  }
}

/** A section's rows by `within`, in the section's order; "Not in a run" and "No workflow" go last. */
export function groupWithin(rows: readonly SectionRow[], within: Within): RowGroup[] {
  const groups = new Map<string, RowGroup>();
  for (const row of rows) {
    const [key, label] = groupKey(row, within);
    const group = groups.get(key);
    if (group) group.rows.push(row);
    else groups.set(key, { key, label, rows: [row] });
  }
  return [...groups.values()].sort((a, b) => Number(a.key === "") - Number(b.key === ""));
}
