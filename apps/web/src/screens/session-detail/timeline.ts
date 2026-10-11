/*
 * The Session detail trace, built from the API's timeline events (spec 10, "Timeline tab"):
 * results fold into their calls, consecutive reads and searches group, a subagent's events
 * gather into one lane, prompts start turns. Pure functions, so the screen only renders.
 */
import type { components } from "../../api/schema";
import type { EventCategory, IconName, MinimapMarkKind } from "../../components";
import { fmtInt } from "../../lib/format";

export type ApiEvent = components["schemas"]["TimelineEvent"];

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
}

/** A subagent's events, contiguous, under its header (spec 10, "Subagent lanes"). */
export interface TraceLane {
  kind: "lane";
  id: string;
  agent: string;
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
    "kind" | "id" | "at" | "turn" | "lane" | "events" | "search" | "facts"
  > & { facts?: [string, string][] },
): TraceEvent {
  return {
    kind: "event",
    id: event.event_id,
    at: event.timestamp,
    turn: 0,
    lane: lane(event),
    events: [event],
    search: "",
    facts: [],
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
  const shown = toolText(str(payload, "tool") ?? "tool", payload);
  const row = base(call, {
    cat: "tool",
    label: "Tool call",
    tool: shown.tool,
    text: shown.text,
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
  row.durationS = ms === undefined ? undefined : ms / 1000;
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
      mono: false,
      content: { role: "reasoning", chars },
    });
  }
  const command = str(payload, "slash_command");
  return base(event, {
    cat: isPrompt ? "prompt" : "message",
    label: isPrompt ? `Prompt${command ? ` · ${command}` : ""}` : "Agent message",
    text: size,
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
    text: `${event.agent ?? "main"} in ${event.repo ?? event.project}${model ? ` · ${model}` : ""}`,
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
        mono: false,
      });
    case "step.end":
      return base(event, {
        cat: "lifecycle",
        label: `Step ${event.step ?? ""} ended`.replace("  ", " "),
        icon: "route",
        text: str(payload, "status") ?? "ended",
        mono: false,
        note: str(payload, "reason"),
      });
    case "run.end":
      return base(event, {
        cat: "lifecycle",
        label: "Run ended",
        icon: "route",
        text: str(payload, "status") ?? "ended",
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

function withSearch(row: TraceEvent): TraceEvent {
  row.search = searchable([row.label, row.tool ?? "", row.text, row.note ?? ""].join(" "));
  return row;
}

/** The rows of `events` in time order, one per fact, before turns and lanes. */
function rowsOf(events: ApiEvent[]): TraceEvent[] {
  const kept = events
    .filter(
      (event) => !event.conflict && event.type !== "session.summary" && !isUsageCarrier(event),
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

function turnItems(rows: TraceEvent[]): TraceItem[] {
  const items: TraceItem[] = [];
  const lanes = new Map<string, TraceEvent[]>();
  const order: (TraceEvent | string)[] = [];
  for (const row of rows) {
    if (row.lane === null) {
      order.push(row);
    } else {
      const list = lanes.get(row.lane);
      if (list) list.push(row);
      else {
        lanes.set(row.lane, [row]);
        order.push(row.lane);
      }
    }
  }
  let main: TraceEvent[] = [];
  const flushMain = () => {
    items.push(...grouped(main));
    main = [];
  };
  for (const entry of order) {
    if (typeof entry !== "string") {
      main.push(entry);
      continue;
    }
    flushMain();
    const laneRows = lanes.get(entry) ?? [];
    const first = laneRows[0];
    const last = laneRows[laneRows.length - 1];
    if (!first || !last) continue;
    items.push({
      kind: "lane",
      id: entry,
      agent: first.events[0]?.agent ?? "subagent",
      at: first.at,
      end: last.at,
      items: grouped(laneRows),
      turn: first.turn,
      eventCount: laneRows.length,
      errors: laneRows.filter((row) => row.cat === "error").length,
    });
  }
  flushMain();
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
export function buildTrace(events: ApiEvent[]): Trace {
  const rows = rowsOf(events);
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
    items: turnItems(list),
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
      lanes.set(row.lane, row.events[0]?.agent ?? "subagent");
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
  /** Lanes start open (a live session) unless closed by the reader. */
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
      lastAt = Date.parse(turn.end);
      return;
    }
    out.push({ t: "turn", key: `turn-${String(turn.n)}`, turn });
    for (const item of turn.items) {
      if (item.kind !== "lane") {
        emitRows([item], 0);
        continue;
      }
      const matches = item.items.flatMap((entry) =>
        entry.kind === "group" ? entry.items : [entry],
      );
      const shown = matches.filter((row) => keep(row, view)).length;
      if (filtered && shown === 0) {
        hidden += matches.length;
        continue;
      }
      flushHidden(item.id);
      gapBefore(item.at, item.id);
      const open = view.closedLanes?.has(item.id)
        ? false
        : Boolean(view.lanesOpenByDefault) || Boolean(view.openLanes?.has(item.id)) || filtered;
      out.push({ t: "lane", key: `lane-${item.id}`, lane: item, open });
      if (open) emitRows(item.items, 1);
      else lastAt = Date.parse(item.end);
    }
    flushHidden(`end-${String(turn.n)}`);
  });
  flushHidden("end");
  return out;
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
      marks.push({ at, kind, label: `${clock} · ${row.label} · ${row.text}`, id: row.id });
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
