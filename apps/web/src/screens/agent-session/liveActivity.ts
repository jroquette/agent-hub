/**
 * What a live turn is doing right now, for the activity bar above the composer: the phase (thinking,
 * writing, a tool, waiting for you, planning), the calls still running (subagents with their own
 * running calls nested), the todo in progress and when the turn and its last record started. Pure:
 * derived from the transcript state, so the bar reads the same as the conversation below it.
 */
import { toolSummary, type ToolView, type TranscriptState } from "./model";

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
}

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

/** The open turn's start: its user message, when the transcript holds it. */
function turnStart(state: TranscriptState): string | null {
  if (!state.turnOpen) return null;
  const user = state.entries.findLast((entry) => entry.kind === "user");
  return user?.kind === "user" ? user.at : null;
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
