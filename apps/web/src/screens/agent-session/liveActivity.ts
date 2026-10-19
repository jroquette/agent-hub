/**
 * What a live turn is doing right now, for the activity bar above the composer: the phase (thinking,
 * writing, a tool, waiting for you, planning), the calls still running (subagents with their own
 * running calls nested), the todo in progress and when the turn and its last record started. Pure:
 * derived from the transcript state, so the bar reads the same as the conversation below it.
 */
import { resultText } from "./ToolCallCard";
import {
  diffStats,
  toolDiff,
  toolState,
  toolSummary,
  type ToolState,
  type ToolView,
  type TranscriptState,
} from "./model";

export type LivePhase = "waiting" | "writing" | "subagents" | "tool" | "thinking" | "planning";

export interface LiveCall {
  id: string;
  name: string;
  /** What it does: a command, a path, a subagent's description. */
  label: string;
  startedAt: string | null;
  /** A subagent (Task or Agent) call. */
  subagent: boolean;
  /** Its own calls still running, when it is a subagent. */
  running: LiveCall[];
  /** How many calls it made so far, when it is a subagent. */
  calls: number;
}

export interface LiveActivity {
  phase: LivePhase;
  /** The top-level calls still running, latest first. */
  calls: LiveCall[];
  /** The todo in progress, as Claude phrased it. */
  todo: string | null;
  /** When the open turn started (its user message), null when unknown. */
  turnStartedAt: string | null;
  /** When the last record arrived. */
  lastEventAt: string | null;
  /** The turn's steps so far, oldest first (the last `FEED_MAX`). */
  feed: FeedItem[];
  /** Steps of this turn left out of `feed`. */
  earlier: number;
}

/** One step of the turn, as Claude Code prints it: the call, then a few lines of what it gave. */
export type FeedItem =
  | { kind: "thinking"; key: string; seconds: number | null }
  | {
      kind: "tool";
      key: string;
      tool: ToolView;
      state: ToolState;
      /** `Bash(make test)`: the call's one input. */
      summary: string;
      /** The first lines of its output, else a one-line digest ("Read 120 lines", "+3 -1"). */
      preview: string[];
      /** Lines of the output not in `preview`. */
      more: number;
      /** The whole output, for the expanded view. */
      output: string | null;
      /** A subagent's calls, oldest first. */
      children: FeedItem[];
      childCount: number;
    };

const SUBAGENT = new Set(["Task", "Agent"]);

function subagentLabel(tool: ToolView): string {
  const kind = typeof tool.input.subagent_type === "string" ? tool.input.subagent_type : null;
  const what = typeof tool.input.description === "string" ? tool.input.description : null;
  return [kind, what].filter(Boolean).join(" · ") || "Subagent";
}

function liveCall(state: TranscriptState, tool: ToolView, depth: number): LiveCall {
  const subagent = SUBAGENT.has(tool.name);
  const childIds = state.children[tool.id] ?? [];
  const running =
    depth < 2
      ? childIds
          .map((id) => state.tools[id])
          .filter((child): child is ToolView => child?.result === null)
          .reverse()
          .map((child) => liveCall(state, child, depth + 1))
      : [];
  return {
    id: tool.id,
    name: tool.name,
    label: subagent ? subagentLabel(tool) : toolSummary(tool.input),
    startedAt: tool.startedAt ?? null,
    subagent,
    running,
    calls: childIds.length,
  };
}

/** The index of the open turn's user message (a message queued during it starts none); with
 * `ended`, of the last turn's even once it ended. */
function turnIndex(state: TranscriptState, ended = false): number {
  if (!state.turnOpen && !ended) return -1;
  return state.entries.findLastIndex((entry) => entry.kind === "user" && !entry.queued);
}

/** The open turn's start: its user message, when the transcript holds it. */
function turnStart(state: TranscriptState): string | null {
  const user = state.entries[turnIndex(state)];
  return user?.kind === "user" ? user.at : null;
}

export const FEED_MAX = 40;
export const PREVIEW_LINES = 4;
/** A running subagent shows its latest calls, this many. */
export const SUBAGENT_SHOWN = 3;

function digest(tool: ToolView, text: string | null): string | null {
  const diff = toolDiff(tool);
  if (diff) {
    const { added, removed } = diffStats(diff);
    return `+${String(added)} -${String(removed)}`;
  }
  if (text === null) return null;
  const lines = text.split("\n").length;
  if (tool.name === "Read") return `Read ${String(lines)} ${lines === 1 ? "line" : "lines"}`;
  return null;
}

function toolItem(state: TranscriptState, tool: ToolView, live: boolean): FeedItem {
  const request = state.permissions[tool.id];
  let status = toolState(tool, request);
  // A call left without a result once the turn is over did not run on.
  if (status === "running" && !live) status = "done";
  const output = tool.result ? resultText(tool.result.content) : null;
  const short = digest(tool, output);
  const lines = output === null ? [] : output.replace(/\s+$/, "").split("\n");
  const preview = short !== null ? [short] : lines.slice(0, PREVIEW_LINES);
  const more = short !== null ? 0 : Math.max(0, lines.length - PREVIEW_LINES);
  const childIds = state.children[tool.id] ?? [];
  const children = childIds.flatMap((id) => {
    const child = state.tools[id];
    return child ? [toolItem(state, child, live)] : [];
  });
  return {
    kind: "tool",
    key: tool.id,
    tool,
    state: status,
    summary: SUBAGENT.has(tool.name) ? subagentLabel(tool) : toolSummary(tool.input),
    preview,
    more,
    output,
    children,
    childCount: childIds.length,
  };
}

/** The open turn's steps (with `ended`, the last turn's), oldest first: thoughts and the main
 * agent's calls, the last `max`. */
export function turnFeed(
  state: TranscriptState,
  { ended = false, max = FEED_MAX }: { ended?: boolean; max?: number } = {},
): { feed: FeedItem[]; earlier: number } {
  const start = turnIndex(state, ended);
  if (start < 0) return { feed: [], earlier: 0 };
  const live = state.status === "running" || state.status === "waiting_permission";
  const items = state.entries.slice(start + 1).flatMap((entry): FeedItem[] => {
    if (entry.kind === "thinking")
      return [{ kind: "thinking", key: entry.key, seconds: entry.seconds }];
    if (entry.kind !== "tool") return [];
    const tool = state.tools[entry.toolId];
    return tool ? [toolItem(state, tool, live)] : [];
  });
  return { feed: items.slice(-max), earlier: Math.max(0, items.length - max) };
}

export type TurnEnd = "running" | "finished" | "interrupted" | "ended" | "failed";

export interface TurnSteps {
  /** What runs now; null once the turn is over. */
  activity: LiveActivity | null;
  feed: FeedItem[];
  earlier: number;
  /** How the last turn stands; null before the first turn. */
  end: TurnEnd | null;
  /** How long the last turn took, once it is over (ms). */
  tookMs: number | null;
}

/** Steps the drawer keeps, oldest dropped first. */
export const STEPS_MAX = 200;

/** The Steps drawer's content: the open turn, else the last one and how it ended. */
export function turnSteps(state: TranscriptState): TurnSteps {
  const activity = liveActivity(state);
  const start = turnIndex(state, true);
  const user = state.entries[start];
  if (user?.kind !== "user") return { activity, feed: [], earlier: 0, end: null, tookMs: null };
  const { feed, earlier } = turnFeed(state, { ended: true, max: STEPS_MAX });
  if (activity) return { activity, feed, earlier, end: "running", tookMs: null };
  const end: TurnEnd =
    state.status === "failed"
      ? "failed"
      : state.status === "ended"
        ? "ended"
        : state.entries
              .slice(start)
              .some(
                (entry) =>
                  entry.kind === "notice" &&
                  entry.tone === "warning" &&
                  entry.text === "You interrupted the turn",
              )
          ? "interrupted"
          : "finished";
  const from = Date.parse(user.at);
  const to = state.lastAt ? Date.parse(state.lastAt) : Number.NaN;
  const tookMs = Number.isNaN(from) || Number.isNaN(to) ? null : Math.max(0, to - from);
  return { activity, feed, earlier, end, tookMs };
}

/** What the session is doing now; null when no turn runs (idle, ended, failed). */
export function liveActivity(state: TranscriptState): LiveActivity | null {
  const { status } = state;
  if (status !== "running" && status !== "waiting_permission") return null;
  const turnStartedAt = turnStart(state);
  // Calls of an earlier, interrupted turn never got a result: only this turn's count.
  const calls = Object.values(state.tools)
    .filter(
      (tool) =>
        tool.result === null &&
        tool.parentId === null &&
        (turnStartedAt === null || (tool.startedAt ?? "") >= turnStartedAt),
    )
    .reverse()
    .map((tool) => liveCall(state, tool, 0));
  const todo = state.todos.find((item) => item.status === "in_progress");
  const phase: LivePhase =
    status === "waiting_permission"
      ? "waiting"
      : state.streaming
        ? "writing"
        : calls.some((call) => call.subagent)
          ? "subagents"
          : calls.length > 0
            ? "tool"
            : state.mode === "plan"
              ? "planning"
              : "thinking";
  return {
    phase,
    calls,
    todo: todo ? (todo.activeForm ?? todo.content) : null,
    turnStartedAt,
    lastEventAt: state.lastAt,
    ...turnFeed(state),
  };
}

/** "8 s", "2 min 05 s", "1 h 03 min": a duration as the bar shows it. */
export function elapsed(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  if (seconds < 60) return `${String(seconds)} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${String(minutes)} min ${String(seconds % 60).padStart(2, "0")} s`;
  return `${String(Math.floor(minutes / 60))} h ${String(minutes % 60).padStart(2, "0")} min`;
}

/** Past this long without a record, the bar says so: still alive, just quiet. */
export const QUIET_MS = 45_000;
/** Past this long without a record and nothing running, the session is likely stuck. */
export const STALLED_MS = 5 * 60_000;
