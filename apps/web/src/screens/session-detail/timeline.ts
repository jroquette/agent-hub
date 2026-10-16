/*
 * The Session detail trace, built from the API's timeline events (spec 10, "Timeline tab"):
 * results fold into their calls, consecutive reads and searches group, a subagent's events
 * gather into one lane, prompts start turns. Pure functions, so the screen only renders.
 */
import type { components } from "../../api/schema";
import type { EventCategory, IconName, MinimapMarkKind } from "../../components";
import { fmtInt } from "../../lib/format";
import {
  contentPhrase,
  gatePhrase,
  guardAskPhrase,
  guardDeniedPhrase,
  learningPhrase,
  phraseText,
  sessionEndPhrase,
  sessionStartPhrase,
  stepPhrase,
  stopBlockedPhrase,
  toolPhrase,
  type Phrase,
} from "./verbs";

export type ApiEvent = components["schemas"]["TimelineEvent"];
export type SessionActor = components["schemas"]["Actor"];

/** Who did a row (S2): the main agent, a subagent of a type, you (a prompt) or a workflow run. */
export interface RowActor {
  kind: "main" | "subagent" | "you" | "run";
  label: string;
  /** The subagent type. */
  type?: string | undefined;
}

export const MAIN_AGENT: RowActor = { kind: "main", label: "Main agent" };
export const YOU: RowActor = { kind: "you", label: "You" };
export const WORKFLOW_RUN: RowActor = { kind: "run", label: "Workflow run" };

export function subagentActor(type: string): RowActor {
  return { kind: "subagent", label: `Subagent · ${type}`, type };
}

/** The row actor of a session actor (the API's `actor` object). */
export function rowActorOf(actor: SessionActor): RowActor {
  return actor.kind === "subagent" ? subagentActor(actor.type ?? "subagent") : MAIN_AGENT;
}

/** Sessions with at least this many events open with their middle turns collapsed (spec 10). */
export const LONG_SESSION_EVENTS = 5000;
/** Turns kept open at each end of a long session. */
const OPEN_EDGE_TURNS = 3;
/** Two copies of one prompt (hook and transcript) arrive within this many ms. */
const PROMPT_TWIN_MS = 10_000;
/** A pause longer than this shows a "6 min later" divider. */
const GAP_SECONDS = 120;

/** What a message or reasoning row says about content it never stored (AC-200.47). */
export interface ContentInfo {
  role: string;
  chars: number | null;
}

/** One row of the trace: an event, or a call with its result folded in. */
export interface TraceEvent {
  kind: "event";
  id: string;
  at: string;
  cat: EventCategory;
  label: string;
  icon?: IconName | undefined;
  tool?: string | undefined;
  /** The collapsed text; it may hold `[redacted: kind]` markers. */
  text: string;
  /** Who did it, and the plain-verb sentence of what was done (AC-201.16, AC-201.17). */
  actor: RowActor;
  phrase: Phrase;
  mono: boolean;
  exit?: number | undefined;
  durationS?: number | undefined;
  plus?: number | undefined;
  minus?: number | undefined;
  note?: string | undefined;
  derived?: string | undefined;
  running?: boolean | undefined;
  content?: ContentInfo | undefined;
  /** Key facts shown when the row expands (cwd, branch, rule…). */
  facts: [string, string][];
  turn: number;
  lane: string | null;
  /** The stored events behind the row (call first). */
  events: ApiEvent[];
  search: string;
}

/** Consecutive reads and searches collapsed into one row (spec 10, collapsing rule 1). */
export interface TraceGroup {
  kind: "group";
  id: string;
  at: string;
  tool: string;
  summary: string;
  items: TraceEvent[];
  turn: number;
  lane: string | null;
  actor: RowActor;
}

/** A subagent's events, contiguous, under its header (spec 10, "Subagent lanes"). */
export interface TraceLane {
  kind: "lane";
  id: string;
  /** The subagent type. */
  agent: string;
  actor: RowActor;
  /** The task of the Agent call that started it, when linked. */
  description: string | null;
  /** The row id of the Agent call that started it, when linked (rows nest under it). */
  startedBy: string | null;
  at: string;
  end: string;
  items: (TraceEvent | TraceGroup)[];
  turn: number;
  eventCount: number;
  errors: number;
}

export type TraceItem = TraceEvent | TraceGroup | TraceLane;

export interface Turn {
  n: number;
  at: string;
  end: string;
  items: TraceItem[];
  eventCount: number;
  /** "Read 9 files, Bash 2, Edit 1". */
  tools: string;
}

/** Filter facets of the rail: the type families of the rows. */
export type Facet =
  | "prompt"
  | "message"
  | "reasoning"
  | "tool"
  | "gate"
  | "decision"
  | "learning"
  | "guard"
  | "lifecycle"
  | "error";

export interface Trace {
  turns: Turn[];
  /** Rows (calls with their results count once). */
  total: number;
  counts: Record<Facet, number>;
  tools: Record<string, number>;
  lanes: { id: string; agent: string }[];
  start: string | null;
  end: string | null;
}

/* ---------- payload readers ---------- */

type Payload = ApiEvent["payload"];

function str(payload: Payload, key: string): string | undefined {
  const value = payload[key];
  return typeof value === "string" && value !== "" ? value : undefined;
}

function num(payload: Payload, key: string): number | undefined {
  const value = payload[key];
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

const MARKER = /\[redacted: ([^\]]+)\]/g;

/** Lowercased text without redaction markers: a secret's existence is never searchable. */
export function searchable(text: string): string {
  return text.replace(MARKER, "").toLowerCase();
}

/** Text split into plain parts and redaction kinds, for rendering markers as chips. */
export function renderParts(text: string): ({ text: string } | { redacted: string })[] {
  const parts: ({ text: string } | { redacted: string })[] = [];
  let last = 0;
  for (const match of text.matchAll(MARKER)) {
    if (match.index > last) parts.push({ text: text.slice(last, match.index) });
    parts.push({ redacted: match[1] ?? "secret" });
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last) });
  return parts;
}

function dirOf(path: string): string {
  const cut = path.lastIndexOf("/");
  return cut < 0 ? "" : path.slice(0, cut + 1);
}

function commonDir(paths: string[]): string {
  const dirs = paths.map(dirOf);
  let common = dirs[0] ?? "";
  for (const dir of dirs.slice(1)) {
    while (common && !dir.startsWith(common)) common = dirOf(common.slice(0, -1));
  }
  return common;
}

const plural = (n: number, one: string, many: string) => `${fmtInt(n)} ${n === 1 ? one : many}`;

/* ---------- rows ---------- */

const SEARCH_TOOLS = new Set(["Read", "Grep", "Glob"]);

function lane(event: ApiEvent): string | null {
  return str(event.payload, "agent_id") ?? null;
}

function base(
  event: ApiEvent,
  fields: Omit<
    TraceEvent,
    "kind" | "id" | "at" | "turn" | "lane" | "events" | "search" | "facts" | "actor"
  > & { facts?: [string, string][]; actor?: RowActor },
): TraceEvent {
  const laneId = lane(event);
  return {
    kind: "event",
    id: event.event_id,
    at: event.timestamp,
    turn: 0,
    lane: laneId,
    events: [event],
    search: "",
    facts: [],
    // A subagent's type is settled once its lane is linked (buildTrace).
    actor: laneId === null ? MAIN_AGENT : subagentActor(event.agent ?? "subagent"),
    ...fields,
  };
}

function toolText(tool: string, payload: Payload): { text: string; tool: string; mono: boolean } {
  if (tool.startsWith("mcp__")) {
    const server = str(payload, "mcp_server") ?? "mcp";
    const name = str(payload, "mcp_tool") ?? tool;
    return { tool: "MCP", text: `${server}.${name}`, mono: true };
  }
  if (tool === "Bash") return { tool, text: str(payload, "command") ?? "Bash", mono: true };
  if (tool === "Grep" || tool === "Glob") {
    const pattern = str(payload, "pattern");
    const path = str(payload, "path");
    const text = pattern ? `"${pattern}"${path ? ` in ${path}` : ""}` : (path ?? tool);
    return { tool, text, mono: true };
  }
  if (tool === "WebFetch") return { tool, text: str(payload, "url") ?? "WebFetch", mono: true };
  if (tool === "Agent" || tool === "Task") {
    const type = str(payload, "subagent_type") ?? "subagent";
    const description = str(payload, "description");
    return { tool: "Agent", text: description ? `${type} · ${description}` : type, mono: false };
  }
  const path = str(payload, "path");
  return { tool, text: path ?? tool, mono: path !== undefined };
}

function callRow(call: ApiEvent, result: ApiEvent | undefined): TraceEvent {
  const payload = call.payload;
  const tool = str(payload, "tool") ?? "tool";
  const shown = toolText(tool, payload);
  const row = base(call, {
    cat: "tool",
    label: "Tool call",
    tool: shown.tool,
    text: shown.text,
    phrase: toolPhrase(tool, payload),
    mono: shown.mono,
    plus: num(payload, "lines_added"),
    minus: num(payload, "lines_removed"),
    running: result === undefined,
  });
  if (result) applyResult(row, result);
  return row;
}

function applyResult(row: TraceEvent, result: ApiEvent): void {
  const payload = result.payload;
  row.events.push(result);
  row.running = false;
  row.exit = num(payload, "exit_code");
  const ms = num(payload, "duration_ms");
  // Sub-second tool timings read as "0 s"; only commands worth timing show one.
  row.durationS = ms === undefined || ms < 1000 ? undefined : ms / 1000;
  const status = str(payload, "status");
  if (status === "error") {
    row.cat = "error";
    row.label = "Tool result · error";
    row.note = str(payload, "error_line");
  } else if (status === "denied") {
    row.cat = "guard";
    row.label = "Denied by guard";
    row.icon = "shield-x";
    const rule = str(payload, "rule");
    row.phrase = guardDeniedPhrase(row.tool ?? str(payload, "tool"), rule);
    row.note = rule ? `rule: ${rule}` : undefined;
    row.facts.push([
      "Rule",
      `${rule ?? "guard"} (hub-workflow guard, PreToolUse). The command was not run.`,
    ]);
  }
}

function contentRow(event: ApiEvent, isPrompt: boolean): TraceEvent {
  const payload = event.payload;
  const chars = num(payload, "chars") ?? null;
  const size = chars === null ? "size unknown" : plural(chars, "character", "characters");
  if (event.type === "reasoning") {
    return base(event, {
      cat: "reasoning",
      label: "Recorded reasoning summary",
      text: size,
      phrase: contentPhrase("reasoning", chars, undefined),
      mono: false,
      content: { role: "reasoning", chars },
    });
  }
  const command = str(payload, "slash_command");
  return base(event, {
    cat: isPrompt ? "prompt" : "message",
    label: isPrompt ? `Prompt${command ? ` · ${command}` : ""}` : "Agent message",
    text: size,
    phrase: contentPhrase(isPrompt ? "prompt" : "message", chars, command),
    ...(isPrompt ? { actor: YOU } : {}),
    mono: false,
    content: { role: str(payload, "role") ?? "assistant", chars },
  });
}

function startRow(event: ApiEvent, segment: number): TraceEvent {
  const payload = event.payload;
  const model = str(payload, "model");
  const facts: [string, string][] = [];
  for (const [label, key] of [
    ["Trigger", "trigger"],
    ["Working directory", "cwd"],
    ["Branch", "git_branch"],
    ["Permission mode", "permission_mode"],
    ["Model", "model"],
  ] as const) {
    const value = str(payload, key);
    if (value) facts.push([label, value]);
  }
  return base(event, {
    cat: "lifecycle",
    label: segment > 1 ? `Session resumed · segment ${String(segment)}` : "Session started",
    icon: "play",
    text: `${event.repo ?? event.project}${model ? ` · ${model}` : ""}`,
    phrase: sessionStartPhrase(segment, event.repo ?? event.project, model),
    mono: false,
    facts,
  });
}

function endRow(event: ApiEvent): TraceEvent {
  const outcome = str(event.payload, "outcome") ?? "ended";
  const reason = str(event.payload, "end_reason");
  return base(event, {
    cat: "lifecycle",
    label: "Session ended",
    icon: "circle-stop",
    text: [outcome, reason].filter(Boolean).join(" · "),
    phrase: sessionEndPhrase(outcome, reason),
    mono: false,
  });
}

interface GateIndex {
  results: Map<string, ApiEvent>;
  toolResults: Map<string, ApiEvent>;
  laterStops: ApiEvent[];
}

function askResolution(request: ApiEvent, index: GateIndex): string {
  const gateId = str(request.payload, "gate_id") ?? "";
  const result = index.results.get(gateId);
  if (result) return str(result.payload, "result") ?? "decided";
  const ran = index.toolResults.get(gateId);
  if (ran && str(ran.payload, "status") !== "denied") return "approved in terminal";
  const after = index.laterStops.some((event) => event.timestamp > request.timestamp);
  return after ? "declined in terminal (inferred)" : "waiting";
}

function gateRequestRow(event: ApiEvent, index: GateIndex): TraceEvent {
  const payload = event.payload;
  const kind = str(payload, "kind") ?? "gate";
  const note = askResolution(event, index);
  const result = index.results.get(str(payload, "gate_id") ?? "");
  if (kind === "guard_ask") {
    const path = str(payload, "path");
    const rule = str(payload, "rule");
    return base(event, {
      cat: "guard",
      label: "Guard asks",
      icon: "shield-alert",
      text: `${path ?? "A tool call"} needs approval`,
      phrase: guardAskPhrase(path),
      mono: false,
      note,
      facts: rule ? [["Rule", rule]] : [],
    });
  }
  if (kind === "permission") {
    return base(event, {
      cat: "gate",
      label: "Permission prompt",
      text: "Claude Code asked for permission",
      phrase: { verb: "Asked you for permission" },
      mono: false,
      note,
    });
  }
  const name = str(payload, "name") ?? kind;
  const command = str(payload, "command");
  const row = base(event, {
    cat: "gate",
    label: "Gate",
    text: `${name} requested${command ? ` · ${command}` : ""}`,
    phrase: gatePhrase(name, result ? (str(result.payload, "result") ?? "decided") : undefined),
    mono: false,
    note,
  });
  if (result) {
    row.events.push(result);
    row.exit = num(result.payload, "exit_code");
    if (str(result.payload, "result") === "failed") row.cat = "error";
  }
  return row;
}

function gateResultRow(event: ApiEvent): TraceEvent {
  const payload = event.payload;
  if (str(payload, "kind") === "stop_gate") {
    return base(event, {
      cat: "guard",
      label: "Stop blocked",
      icon: "octagon-x",
      text: str(payload, "command") ?? "Stop gate",
      phrase: stopBlockedPhrase(str(payload, "command")),
      mono: true,
      exit: num(payload, "exit_code"),
      note: "check_fast failing for changed code",
    });
  }
  const result = str(payload, "result") ?? "decided";
  return base(event, {
    cat: result === "failed" ? "error" : "gate",
    label: "Gate result",
    text: `${str(payload, "name") ?? str(payload, "kind") ?? "gate"} ${result}`,
    phrase: gatePhrase(str(payload, "name") ?? str(payload, "kind") ?? "gate", result),
    mono: false,
    exit: num(payload, "exit_code"),
  });
}

function otherRow(event: ApiEvent): TraceEvent | null {
  const payload = event.payload;
  switch (event.type) {
    case "decision":
      return base(event, {
        cat: "decision",
        label: "Decision",
        text: str(payload, "text") ?? str(payload, "choice") ?? "Decision",
        phrase: {
          verb: "Decided:",
          object: str(payload, "text") ?? str(payload, "choice") ?? "a decision",
          kind: "text",
        },
        mono: false,
        derived: "Extracted from transcript",
      });
    case "learning.proposed":
    case "learning.accepted":
    case "learning.rejected": {
      const target = str(payload, "target");
      const verb = event.type.split(".")[1] ?? "proposed";
      return base(event, {
        cat: "learning",
        label: `Learning ${verb}`,
        text: str(payload, "text") ?? "Learning",
        phrase: learningPhrase(event.type, str(payload, "text")),
        mono: false,
        note: target ? `target ${target}` : undefined,
      });
    }
    case "step.start":
      return base(event, {
        cat: "lifecycle",
        label: `Step ${event.step ?? str(payload, "stage") ?? ""} started`.replace("  ", " "),
        icon: "route",
        text: str(payload, "stage") ?? str(payload, "run") ?? "step",
        phrase: stepPhrase("step.start", event.step ?? str(payload, "stage") ?? "step", undefined),
        actor: WORKFLOW_RUN,
        mono: false,
      });
    case "step.end":
      return base(event, {
        cat: "lifecycle",
        label: `Step ${event.step ?? ""} ended`.replace("  ", " "),
        icon: "route",
        text: str(payload, "status") ?? "ended",
        phrase: stepPhrase("step.end", event.step ?? "step", str(payload, "status")),
        actor: WORKFLOW_RUN,
        mono: false,
        note: str(payload, "reason"),
      });
    case "run.end":
      return base(event, {
        cat: "lifecycle",
        label: "Run ended",
        icon: "route",
        text: str(payload, "status") ?? "ended",
        phrase: stepPhrase("run.end", "run", str(payload, "status")),
        actor: WORKFLOW_RUN,
        mono: false,
        note: str(payload, "reason"),
      });
    default:
      return null;
  }
}

function isUsageCarrier(event: ApiEvent): boolean {
  return (
    event.type === "message" &&
    num(event.payload, "chars") === 0 &&
    str(event.payload, "role") !== "user"
  );
}

function isPrompt(event: ApiEvent): boolean {
  return event.type === "message" && str(event.payload, "role") === "user";
}

/** The row as one line: "Main agent · Ran skill /feature" (AC-201.16). */
export function lineOf(row: TraceEvent): string {
  return `${row.actor.label} · ${phraseText(row.phrase)}`;
}

function withSearch(row: TraceEvent): TraceEvent {
  row.search = searchable(
    [row.label, row.tool ?? "", row.text, row.note ?? "", lineOf(row)].join(" "),
  );
  return row;
}

/** The rows of `events` in time order, one per fact, before turns and lanes. */
function rowsOf(events: ApiEvent[]): TraceEvent[] {
  const kept = events
    .filter(
      (event) =>
        !event.conflict &&
        event.type !== "session.summary" &&
        event.type !== "session.title" &&
        !isUsageCarrier(event),
    )
    .sort((a, b) =>
      a.timestamp === b.timestamp ? a.seq - b.seq : a.timestamp < b.timestamp ? -1 : 1,
    );
  const results = new Map<string, ApiEvent>();
  const calls = new Set<string>();
  const gates: GateIndex = { results: new Map(), toolResults: new Map(), laterStops: [] };
  const requested = new Set<string>();
  for (const event of kept) {
    const useId = str(event.payload, "tool_use_id");
    const gateId = str(event.payload, "gate_id");
    if (event.type === "tool.result" && useId) {
      results.set(useId, event);
      gates.toolResults.set(useId, event);
    }
    if (event.type === "tool.call" && useId) calls.add(useId);
    if (event.type === "gate.result" && gateId) gates.results.set(gateId, event);
    if (event.type === "gate.request" && gateId) requested.add(gateId);
    if (isPrompt(event) || event.type === "session.end") gates.laterStops.push(event);
  }

  const rows: TraceEvent[] = [];
  let segment = 0;
  let lastPrompt: { at: number; source: string } | null = null;
  for (const event of kept) {
    const useId = str(event.payload, "tool_use_id");
    let row: TraceEvent | null = null;
    if (event.type === "tool.call") {
      row = callRow(event, useId ? results.get(useId) : undefined);
    } else if (event.type === "tool.result") {
      if (useId && calls.has(useId)) continue;
      if (useId && requested.has(useId) && str(event.payload, "status") !== "denied") continue;
      row = base(event, {
        cat: "tool",
        label: "Tool result",
        tool: str(event.payload, "tool"),
        text: str(event.payload, "tool") ?? "tool",
        phrase: {
          verb: "Got a result from",
          object: str(event.payload, "tool") ?? "a tool",
          kind: "text",
        },
        mono: false,
      });
      applyResult(row, event);
      row.events = [event];
    } else if (isPrompt(event)) {
      const time = Date.parse(event.timestamp);
      if (
        lastPrompt &&
        lastPrompt.source !== event.source &&
        time - lastPrompt.at < PROMPT_TWIN_MS
      ) {
        const twin = rows[rows.length - 1];
        twin?.events.push(event);
        continue;
      }
      lastPrompt = { at: time, source: event.source };
      row = contentRow(event, true);
    } else if (event.type === "message" || event.type === "reasoning") {
      row = contentRow(event, false);
    } else if (event.type === "session.start") {
      segment += 1;
      row = startRow(event, segment);
    } else if (event.type === "session.end") {
      row = endRow(event);
    } else if (event.type === "gate.request") {
      row = gateRequestRow(event, gates);
    } else if (event.type === "gate.result") {
      const gateId = str(event.payload, "gate_id");
      if (gateId && requested.has(gateId)) continue;
      row = gateResultRow(event);
    } else {
      row = otherRow(event);
    }
    if (row) rows.push(withSearch(row));
  }
  return rows;
}

/* ---------- turns, lanes, groups ---------- */

function groupable(row: TraceEvent): boolean {
  return row.cat === "tool" && SEARCH_TOOLS.has(row.tool ?? "");
}

function groupSummary(items: TraceEvent[]): string {
  const reads = items.filter((item) => item.tool === "Read");
  const searches = items.length - reads.length;
  const paths = items.map((item) => {
    if (item.tool === "Read") return item.text;
    // A search path names a folder unless its last part looks like a file.
    const path = str(item.events[0]?.payload ?? {}, "path") ?? "";
    const last = path.split("/").pop() ?? "";
    return path && !last.includes(".") && !path.endsWith("/") ? `${path}/` : path;
  });
  const dir = commonDir(paths.filter(Boolean));
  const where = dir ? `in ${dir}` : `in ${String(new Set(paths.map(dirOf)).size)} folders`;
  if (searches === 0) return `Read ${plural(reads.length, "file", "files")} ${where}`;
  if (reads.length === 0) return `Searched ${plural(searches, "time", "times")} ${where}`;
  return `Read ${plural(reads.length, "file", "files")}, searched ${plural(searches, "time", "times")} ${where}`;
}

function grouped(rows: TraceEvent[]): (TraceEvent | TraceGroup)[] {
  const out: (TraceEvent | TraceGroup)[] = [];
  let run: TraceEvent[] = [];
  const flush = () => {
    const first = run[0];
    if (first && run.length >= 2) {
      out.push({
        kind: "group",
        id: `group-${first.id}`,
        at: first.at,
        tool: first.tool ?? "Read",
        summary: groupSummary(run),
        items: run,
        turn: first.turn,
        lane: first.lane,
        actor: first.actor,
      });
    } else {
      out.push(...run);
    }
    run = [];
  };
  for (const row of rows) {
    if (groupable(row)) run.push(row);
    else {
      flush();
      out.push(row);
    }
  }
  flush();
  return out;
}

function toolSummary(rows: TraceEvent[]): string {
  const counts = new Map<string, number>();
  for (const row of rows) {
    if (row.tool) counts.set(row.tool, (counts.get(row.tool) ?? 0) + 1);
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([tool, n]) =>
      tool === "Read" ? `Read ${plural(n, "file", "files")}` : `${tool} ${String(n)}`,
    )
    .join(", ");
}

/** How a subagent's lane is named and where it nests (S2). */
interface LaneLink {
  type: string;
  description: string | null;
  startedBy: string | null;
}

function isAgentCall(row: TraceEvent): boolean {
  return row.lane === null && row.tool === "Agent" && row.events[0]?.type === "tool.call";
}

/**
 * Links each subagent lane to the Agent call that started it: by the session's actors when
 * they name the call, else to the one unclaimed Agent call of the same type that starts before
 * the lane and ends (if it ended) after it. Two candidates give no link, never a guess.
 */
function linkLanes(rows: TraceEvent[], actors: readonly SessionActor[]): Map<string, LaneLink> {
  const lanes = new Map<string, TraceEvent[]>();
  for (const row of rows) {
    if (row.lane === null) continue;
    const list = lanes.get(row.lane);
    if (list) list.push(row);
    else lanes.set(row.lane, [row]);
  }
  const rowOfEvent = new Map<string, TraceEvent>();
  for (const row of rows) for (const event of row.events) rowOfEvent.set(event.event_id, row);
  const known = new Map(
    actors.flatMap((actor) =>
      actor.kind === "subagent" && actor.agent_id ? [[actor.agent_id, actor] as const] : [],
    ),
  );
  const calls = rows.filter(isAgentCall);
  const claimed = new Set<string>();
  const links = new Map<string, LaneLink>();
  const descriptionOf = (row: TraceEvent | undefined) =>
    row ? (str(row.events[0]?.payload ?? {}, "description") ?? null) : null;

  for (const [id, laneRows] of lanes) {
    const actor = known.get(id);
    const type = actor?.type ?? laneRows[0]?.events[0]?.agent ?? "subagent";
    const starter = actor?.started_by_event_id
      ? rowOfEvent.get(actor.started_by_event_id)
      : undefined;
    if (starter) claimed.add(starter.id);
    links.set(id, {
      type,
      description: actor?.description ?? descriptionOf(starter),
      startedBy: starter?.id ?? null,
    });
  }
  for (const [id, laneRows] of lanes) {
    const link = links.get(id);
    const first = laneRows[0];
    const last = laneRows[laneRows.length - 1];
    if (link?.startedBy !== null || !first || !last) continue;
    const candidates = calls.filter((call) => {
      const ended = call.events[1]?.timestamp;
      return (
        !claimed.has(call.id) &&
        str(call.events[0]?.payload ?? {}, "subagent_type") === link.type &&
        call.at <= first.at &&
        (ended === undefined || ended >= last.at)
      );
    });
    const [only] = candidates;
    if (candidates.length !== 1 || !only) continue;
    claimed.add(only.id);
    link.startedBy = only.id;
    link.description ??= descriptionOf(only);
  }
  return links;
}

function laneItem(
  id: string,
  laneRows: TraceEvent[],
  link: LaneLink | undefined,
): TraceLane | null {
  const first = laneRows[0];
  const last = laneRows[laneRows.length - 1];
  if (!first || !last) return null;
  const type = link?.type ?? "subagent";
  return {
    kind: "lane",
    id,
    agent: type,
    actor: subagentActor(type),
    description: link?.description ?? null,
    startedBy: link?.startedBy ?? null,
    at: first.at,
    end: last.at,
    items: grouped(laneRows),
    turn: first.turn,
    eventCount: laneRows.length,
    errors: laneRows.filter((row) => row.cat === "error").length,
  };
}

/** A turn's items: main rows (grouped), each lane right after the Agent call that started it. */
function turnItems(rows: TraceEvent[], links: Map<string, LaneLink>): TraceItem[] {
  const lanes = new Map<string, TraceEvent[]>();
  for (const row of rows) {
    if (row.lane === null) continue;
    const list = lanes.get(row.lane);
    if (list) list.push(row);
    else lanes.set(row.lane, [row]);
  }
  const mainIds = new Set(rows.flatMap((row) => (row.lane === null ? [row.id] : [])));
  const nested = new Map<string, string[]>();
  for (const id of lanes.keys()) {
    const starter = links.get(id)?.startedBy;
    if (starter && mainIds.has(starter)) nested.set(starter, [...(nested.get(starter) ?? []), id]);
  }
  const placed = new Set([...nested.values()].flat());

  const items: TraceItem[] = [];
  let main: TraceEvent[] = [];
  const pushLanes = (ids: string[]) => {
    items.push(...grouped(main));
    main = [];
    for (const id of ids) {
      const item = laneItem(id, lanes.get(id) ?? [], links.get(id));
      if (item) items.push(item);
    }
  };
  for (const row of rows) {
    if (row.lane === null) {
      main.push(row);
      const started = nested.get(row.id);
      if (started) pushLanes(started);
    } else if (!placed.has(row.lane)) {
      placed.add(row.lane);
      pushLanes([row.lane]);
    }
  }
  items.push(...grouped(main));
  return items;
}

const FACETS: Facet[] = [
  "prompt",
  "message",
  "reasoning",
  "tool",
  "gate",
  "decision",
  "learning",
  "guard",
  "lifecycle",
  "error",
];

/** The trace of a session's events: turns of rows, groups and lanes, with facet counts. */
export function buildTrace(events: ApiEvent[], actors: readonly SessionActor[] = []): Trace {
  const rows = rowsOf(events);
  const links = linkLanes(rows, actors);
  for (const row of rows) {
    if (row.lane === null) continue;
    row.actor = subagentActor(links.get(row.lane)?.type ?? "subagent");
    withSearch(row);
  }
  let turn = 1;
  let prompted = false;
  for (const row of rows) {
    if (row.cat === "prompt" && row.lane === null) {
      if (prompted) turn += 1;
      prompted = true;
    }
    row.turn = turn;
  }
  const byTurn = new Map<number, TraceEvent[]>();
  for (const row of rows) {
    const list = byTurn.get(row.turn);
    if (list) list.push(row);
    else byTurn.set(row.turn, [row]);
  }
  const turns: Turn[] = [...byTurn.entries()].map(([n, list]) => ({
    n,
    at: list[0]?.at ?? "",
    end: list[list.length - 1]?.at ?? "",
    items: turnItems(list, links),
    eventCount: list.length,
    tools: toolSummary(list),
  }));
  const counts = Object.fromEntries(FACETS.map((facet) => [facet, 0])) as Record<Facet, number>;
  const tools: Record<string, number> = {};
  const lanes = new Map<string, string>();
  for (const row of rows) {
    counts[row.cat] += 1;
    if (row.tool) tools[row.tool] = (tools[row.tool] ?? 0) + 1;
    if (row.lane !== null && !lanes.has(row.lane)) {
      lanes.set(row.lane, links.get(row.lane)?.type ?? "subagent");
    }
  }
  return {
    turns,
    total: rows.length,
    counts,
    tools,
    lanes: [...lanes.entries()].map(([id, agent]) => ({ id, agent })),
    start: rows[0]?.at ?? null,
    end: rows[rows.length - 1]?.at ?? null,
  };
}

/* ---------- the rendered rows ---------- */

export type FlatRow =
  | { t: "turn"; key: string; turn: Turn }
  | { t: "turnSummary"; key: string; turn: Turn }
  | { t: "event"; key: string; row: TraceEvent; depth: number }
  | { t: "group"; key: string; group: TraceGroup; depth: number; open: boolean }
  | { t: "lane"; key: string; lane: TraceLane; open: boolean }
  | { t: "hidden"; key: string; count: number }
  | { t: "gap"; key: string; seconds: number };

export interface TraceView {
  /** Long session: turns beyond the first and last three collapse to a summary row. */
  long?: boolean | undefined;
  /** Turns opened (long session) by the reader. */
  openTurns?: ReadonlySet<number> | undefined;
  openLanes?: ReadonlySet<string> | undefined;
  /** Lanes start open (the default) unless closed by the reader. */
  lanesOpenByDefault?: boolean | undefined;
  closedLanes?: ReadonlySet<string> | undefined;
  openGroups?: ReadonlySet<string> | undefined;
  errorsOnly?: boolean | undefined;
  types?: ReadonlySet<Facet> | undefined;
  tools?: ReadonlySet<string> | undefined;
  /** Lane ids to show; "main" is the session's own events. */
  lanes?: ReadonlySet<string> | undefined;
  query?: string | undefined;
}

const ERRORS_ONLY: ReadonlySet<EventCategory> = new Set(["error", "guard", "decision", "gate"]);
const PINNED: ReadonlySet<EventCategory> = new Set(["error", "guard", "gate", "learning"]);
const PINNED_TOOLS: ReadonlySet<string> = new Set(["Skill", "Agent"]);

/**
 * Rows no collapsing ever hides (AC-201.18): errors, gates, guard events, skills, subagent
 * starts and learnings stay on show under a collapsed turn or a closed lane.
 */
export function isPinned(row: TraceEvent): boolean {
  return PINNED.has(row.cat) || (row.cat === "tool" && PINNED_TOOLS.has(row.tool ?? ""));
}

function laneRows(lane: TraceLane): TraceEvent[] {
  return lane.items.flatMap((entry) => (entry.kind === "group" ? entry.items : [entry]));
}

function keep(row: TraceEvent, view: TraceView): boolean {
  if (view.errorsOnly) {
    const lifecycle = row.cat === "lifecycle" && row.label.startsWith("Session");
    if (!ERRORS_ONLY.has(row.cat) && !lifecycle) return false;
  }
  if (view.types && view.types.size > 0 && !view.types.has(row.cat)) return false;
  if (view.tools && view.tools.size > 0 && !view.tools.has(row.tool ?? "")) return false;
  if (view.lanes && view.lanes.size > 0 && !view.lanes.has(row.lane ?? "main")) return false;
  const query = view.query?.trim().toLowerCase();
  if (query && !row.search.includes(query)) return false;
  return true;
}

function filtering(view: TraceView): boolean {
  return (
    view.errorsOnly === true ||
    (view.types?.size ?? 0) > 0 ||
    (view.tools?.size ?? 0) > 0 ||
    (view.lanes?.size ?? 0) > 0 ||
    (view.query?.trim() ?? "") !== ""
  );
}

/** The rows to render for `trace` under `view`, in order (virtualised by the screen). */
export function flattenTrace(trace: Trace, view: TraceView): FlatRow[] {
  const out: FlatRow[] = [];
  const filtered = filtering(view);
  let hidden = 0;
  let lastAt: number | null = null;
  const flushHidden = (key: string) => {
    if (hidden > 0) out.push({ t: "hidden", key: `hidden-${key}`, count: hidden });
    hidden = 0;
  };
  const gapBefore = (at: string, key: string) => {
    const time = Date.parse(at);
    if (lastAt !== null && (time - lastAt) / 1000 > GAP_SECONDS) {
      out.push({ t: "gap", key: `gap-${key}`, seconds: Math.round((time - lastAt) / 1000) });
    }
    lastAt = time;
  };
  const emitRows = (items: (TraceEvent | TraceGroup)[], depth: number) => {
    for (const item of items) {
      if (item.kind === "event") {
        if (!keep(item, view)) {
          hidden += 1;
          continue;
        }
        flushHidden(item.id);
        gapBefore(item.at, item.id);
        out.push({ t: "event", key: item.id, row: item, depth });
        continue;
      }
      const shown = item.items.filter((row) => keep(row, view));
      if (shown.length === 0) {
        hidden += item.items.length;
        continue;
      }
      hidden += item.items.length - shown.length;
      flushHidden(item.id);
      gapBefore(item.at, item.id);
      const open = Boolean(view.openGroups?.has(item.id)) || Boolean(view.query?.trim());
      out.push({ t: "group", key: item.id, group: item, depth, open });
      if (open) {
        for (const row of shown) out.push({ t: "event", key: row.id, row, depth: depth + 1 });
      }
    }
  };
  trace.turns.forEach((turn, index) => {
    const edge = index < OPEN_EDGE_TURNS || index >= trace.turns.length - OPEN_EDGE_TURNS;
    if (view.long && !filtered && !edge && !view.openTurns?.has(turn.n)) {
      out.push({ t: "turnSummary", key: `turn-${String(turn.n)}`, turn });
      for (const item of turn.items) {
        if (item.kind === "event" && isPinned(item)) {
          out.push({ t: "event", key: item.id, row: item, depth: 0 });
        } else if (item.kind === "lane") {
          out.push({ t: "lane", key: `lane-${item.id}`, lane: item, open: false });
          for (const row of laneRows(item).filter(isPinned)) {
            out.push({ t: "event", key: row.id, row, depth: 1 });
          }
        }
      }
      lastAt = Date.parse(turn.end);
      return;
    }
    out.push({ t: "turn", key: `turn-${String(turn.n)}`, turn });
    for (const item of turn.items) {
      if (item.kind !== "lane") {
        emitRows([item], 0);
        continue;
      }
      const matches = laneRows(item);
      const shown = matches.filter((row) => keep(row, view)).length;
      if (filtered && shown === 0) {
        hidden += matches.length;
        continue;
      }
      flushHidden(item.id);
      gapBefore(item.at, item.id);
      const open = view.closedLanes?.has(item.id)
        ? false
        : (view.lanesOpenByDefault ?? true) || Boolean(view.openLanes?.has(item.id)) || filtered;
      out.push({ t: "lane", key: `lane-${item.id}`, lane: item, open });
      if (open) emitRows(item.items, 1);
      else {
        for (const row of matches.filter((entry) => isPinned(entry) && keep(entry, view))) {
          out.push({ t: "event", key: row.id, row, depth: 1 });
        }
        lastAt = Date.parse(item.end);
      }
    }
    flushHidden(`end-${String(turn.n)}`);
  });
  flushHidden("end");
  return out;
}

/** The id of the row that shows `eventId` (a result folds into its call's row), if any. */
export function rowIdOf(trace: Trace, eventId: string): string | null {
  for (const row of allRows(trace)) {
    if (row.events.some((event) => event.event_id === eventId)) return row.id;
  }
  return null;
}

/* ---------- minimap ---------- */

export interface MinimapModel {
  bins: { cat: EventCategory; n: number }[];
  marks: { at: number; kind: MinimapMarkKind; label: string; id: string }[];
}

const MARK_OF: Partial<Record<EventCategory, MinimapMarkKind>> = {
  error: "error",
  decision: "decision",
  gate: "gate",
  guard: "guard",
  learning: "learning",
};

function allRows(trace: Trace): TraceEvent[] {
  return trace.turns.flatMap((turn) =>
    turn.items.flatMap((item) => {
      if (item.kind === "event") return [item];
      if (item.kind === "group") return item.items;
      return item.items.flatMap((entry) => (entry.kind === "group" ? entry.items : [entry]));
    }),
  );
}

/** Density bins and markers over time or turns; `at` is a 0–1 fraction of the session. */
export function minimapOf(trace: Trace, axis: "time" | "turn", binCount: number): MinimapModel {
  const rows = allRows(trace);
  const start = trace.start ? Date.parse(trace.start) : 0;
  const end = trace.end ? Date.parse(trace.end) : 0;
  const lastTurn = trace.turns[trace.turns.length - 1]?.n ?? 1;
  const fraction = (row: TraceEvent) =>
    axis === "time"
      ? end > start
        ? (Date.parse(row.at) - start) / (end - start)
        : 0
      : lastTurn > 1
        ? (row.turn - 1) / (lastTurn - 1)
        : 0;
  const tallies = Array.from({ length: binCount }, () => new Map<EventCategory, number>());
  const marks: MinimapModel["marks"] = [];
  for (const row of rows) {
    const at = Math.min(1, Math.max(0, fraction(row)));
    const bin = Math.min(binCount - 1, Math.floor(at * binCount));
    const tally = tallies[bin];
    tally?.set(row.cat, (tally.get(row.cat) ?? 0) + 1);
    const kind = MARK_OF[row.cat];
    if (kind) {
      const clock = new Date(row.at).toISOString().slice(11, 19);
      marks.push({ at, kind, label: `${clock} · ${lineOf(row)}`, id: row.id });
    }
  }
  const bins = tallies.map((tally) => {
    let cat: EventCategory = "tool";
    let best = 0;
    let n = 0;
    for (const [key, count] of tally) {
      n += count;
      if (count > best) {
        best = count;
        cat = key;
      }
    }
    return { cat, n };
  });
  return { bins, marks };
}
