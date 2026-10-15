/**
 * The chat view model of one agent session (AC-165.43): a pure reducer from stream items (persisted
 * records, text deltas, status and reset frames) to what the transcript shows.
 *
 * Deltas append to one assistant bubble per block; the block's `text` record replaces them. Records
 * already applied (`seq` at or below the last one) and deltas already seen are ignored, so a replay
 * after a reconnect never duplicates content. Tool calls pair with their results by `tool_use_id`
 * and nest under the subagent call named by `parent_tool_use_id`. Text holding a
 * `[redacted: <kind>]` marker is the stored copy (E9): live frames carry the original text.
 */
import type { components } from "../../api/schema";

type Schemas = components["schemas"];
export type LogRecord = Schemas["LogRecord"];
export type AgentSession = Schemas["AgentSession"];
export type AgentSessionStatus = Schemas["AgentSessionStatus"];
export type EndReason = Schemas["EndReason"];
export type TokenUsage = Schemas["TokenUsage"];
export type OpenPermission = Schemas["OpenPermission"];
export type PermissionSuggestion = Schemas["PermissionSuggestion"];
export type PermissionMode = Schemas["PermissionMode"];
export type RequestKind = Schemas["RequestKind"];
export type RecordBy = Schemas["RecordBy"];
/** A JSON value from an untyped record body (the schema's `JsonValue` is `unknown`). */
export type JsonValue = unknown;
export type JsonObject = Record<string, unknown>;

/** A text delta on the stream (`event: delta`, id `<after_seq>.<index>`, E8). */
export interface DeltaFrame {
  after_seq: number;
  block: number;
  index: number;
  text: string;
}
/** `event: status`: the session's status changed. */
export interface StatusFrame {
  status: AgentSessionStatus;
  end_reason?: EndReason | null | undefined;
}
/** `event: reset`: the position cannot be resumed; the caller reloads the snapshot and the log. */
export interface ResetFrame {
  reason: string;
}

/** A message this page posts: shown at once, accepted with its record's seq, or failed. */
export type SendItem =
  | { type: "sending"; key: string; text: string }
  | { type: "accepted"; key: string; seq: number }
  | { type: "failed"; key: string };

/** What the reducer takes: one SSE frame, one record of a `GET /{id}/events` page, or a send. */
export type StreamItem =
  | { type: "record"; record: LogRecord }
  | { type: "delta"; delta: DeltaFrame }
  | { type: "status"; status: StatusFrame }
  | { type: "reset"; reset: ResetFrame }
  | SendItem;

/** A sent message until its `user.message` record (the POST's `seq`) arrives (AC-234.27). */
export interface SendingView {
  key: string;
  text: string;
  seq: number | null;
}

export interface ToolResultView {
  content: JsonValue;
  isError: boolean;
  /** The server stored a clipped copy (over 64 KiB); `originalBytes` is the full size. */
  truncated: boolean;
  originalBytes: number | null;
}

export interface ToolView {
  id: string;
  name: string;
  input: JsonObject;
  parentId: string | null;
  /** A unified diff the server attached to the call, when it did. */
  diff: string | null;
  result: ToolResultView | null;
}

export interface PermissionDecisionView {
  decision: "allow" | "deny" | "always";
  by: RecordBy | null;
  message: string | null;
  at: string;
}

export interface PermissionView {
  requestId: string;
  tool: string;
  requestKind: RequestKind;
  summary: string;
  input: JsonObject | null;
  suggestions: PermissionSuggestion[];
  askedAt: string;
  /** When the server denies it unanswered; only the snapshot (memory) knows it. */
  deadlineAt: string | null;
  decision: PermissionDecisionView | null;
  redacted: boolean;
}

export interface TodoView {
  content: string;
  status: string;
  activeForm: string | null;
}

export interface MeterView {
  /** The sum of the turns' estimated costs (USD), null before the first result. */
  costUsd: number | null;
  usage: TokenUsage | null;
  turns: number;
}

export type NoticeTone = "info" | "warning" | "error";

export type TranscriptEntry =
  | {
      kind: "user";
      key: string;
      seq: number;
      at: string;
      text: string;
      redacted: boolean;
      /** Sent while a turn ran: Claude reads it after that turn. */
      queued: boolean;
    }
  | {
      kind: "assistant";
      key: string;
      seq: number | null;
      block: number;
      text: string;
      streaming: boolean;
      /** The index of the last delta appended (-1 once the text record replaced them). */
      lastDelta: number;
      redacted: boolean;
    }
  | { kind: "thinking"; key: string; seq: number; text: string; redacted: boolean }
  | { kind: "tool"; key: string; toolId: string }
  | { kind: "permission"; key: string; requestId: string }
  | { kind: "notice"; key: string; seq: number; tone: NoticeTone; text: string };

export interface TranscriptState {
  entries: TranscriptEntry[];
  tools: Record<string, ToolView>;
  /** Tool ids called by a subagent, by the calling tool's id. */
  children: Record<string, string[]>;
  permissions: Record<string, PermissionView>;
  todos: TodoView[];
  meter: MeterView;
  status: AgentSessionStatus | null;
  endReason: EndReason | null;
  model: string | null;
  mode: PermissionMode | null;
  slashCommands: string[];
  lastSeq: number;
  /** A text block is streaming (its bubble is open). */
  streaming: boolean;
  /** An interrupt was recorded: the turn's result reads "Turn interrupted" (AC-234.21). */
  interrupted: boolean;
  /** Why the stream reset; the caller reloads, then clears it with a fresh state. */
  reset: string | null;
  /** Messages posted from this page whose record has not arrived yet. */
  sending: SendingView[];
  /** A user message started a turn whose result has not arrived. */
  turnOpen: boolean;
}

export function initialTranscript(): TranscriptState {
  return {
    entries: [],
    tools: {},
    children: {},
    permissions: {},
    todos: [],
    meter: { costUsd: null, usage: null, turns: 0 },
    status: null,
    endReason: null,
    model: null,
    mode: null,
    slashCommands: [],
    lastSeq: 0,
    streaming: false,
    interrupted: false,
    reset: null,
    sending: [],
    turnOpen: false,
  };
}

const REDACTION = /\[redacted: [^\]]+\]/;

/** Whether text holds a `[redacted: <kind>]` marker: the stored copy, not the live text (E9). */
export function isRedacted(text: string): boolean {
  return REDACTION.test(text);
}

/* ---------- Reading untyped bodies ---------- */

/** `value` when it is a JSON object, else null. */
export function asObject(value: unknown): JsonObject | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonObject)
    : null;
}
/** `value` when it is a JSON array, else an empty one. */
export function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? (value as unknown[]) : [];
}
/** The string at `key`, else null. */
export function str(body: JsonObject, key: string): string | null {
  const value = body[key];
  return typeof value === "string" ? value : null;
}
function num(body: JsonObject, key: string): number | null {
  const value = body[key];
  if (typeof value === "number") return value;
  if (typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value)))
    return Number(value);
  return null;
}
const obj = asObject;
const arr = asArray;

function suggestionsOf(value: unknown): PermissionSuggestion[] {
  return arr(value).flatMap((item) => {
    const s = obj(item);
    if (!s) return [];
    const index = num(s, "index");
    const destination = str(s, "destination");
    if (index === null || destination === null) return [];
    return [{ index, destination, rule: s.rule ?? null }];
  });
}

/* ---------- Labels ---------- */

const MODE_LABEL: Record<PermissionMode, string> = {
  default: "Ask before edits",
  acceptEdits: "Accept edits",
  plan: "Plan",
};
/** How a permission mode reads in the UI. */
export function modeLabel(mode: PermissionMode): string {
  return MODE_LABEL[mode];
}

const SUMMARY_KEYS = [
  "command",
  "file_path",
  "notebook_path",
  "path",
  "pattern",
  "url",
  "query",
  "description",
  "skill",
  "prompt",
];
const SUMMARY_MAX = 120;

/** The one input that tells what a tool call does (a command, a path, a pattern), at most 120 chars. */
export function toolSummary(input: JsonObject): string {
  for (const key of SUMMARY_KEYS) {
    const value = str(input, key);
    if (value !== null) return value.length > SUMMARY_MAX ? value.slice(0, SUMMARY_MAX) : value;
  }
  return "";
}

/** A suggested rule as people read it: `Bash(git status)`, else its type and value. */
export function ruleLabel(rule: unknown): string {
  const r = obj(rule);
  if (!r) return typeof rule === "string" ? rule : JSON.stringify(rule);
  const rules = arr(r.rules).flatMap((item) => {
    const one = obj(item);
    if (!one) return [];
    const tool = str(one, "toolName") ?? "";
    const content = str(one, "ruleContent");
    return [content ? `${tool}(${content})` : tool];
  });
  if (rules.length > 0) return rules.join(", ");
  const type = str(r, "type") ?? "rule";
  const value = str(r, "mode") ?? str(r, "behavior") ?? "";
  return value ? `${type} ${value}` : type;
}

/** Where a tool call stands (AC-234.24). */
export type ToolState = "running" | "waiting" | "done" | "error" | "denied";

/** A call's state from its result and the permission asked for it (by `tool_use_id`): an open
 * request waits for you, a denied one reads denied whatever result the CLI then sent. */
export function toolState(tool: ToolView, request?: PermissionView): ToolState {
  if (request?.decision?.decision === "deny") return "denied";
  if (tool.result === null) return request?.decision === null ? "waiting" : "running";
  return tool.result.isError ? "error" : "done";
}

/* ---------- Diffs ---------- */

const DIFF_MAX_LINES = 2000;

function splitLines(text: string): string[] {
  return text === "" ? [] : text.replace(/\r\n?/g, "\n").split("\n");
}

/** The edit script between two line lists (LCS); a too-large input is all removed then all added. */
function lineOps(a: string[], b: string[]): string[] {
  if (a.length * b.length > (DIFF_MAX_LINES * DIFF_MAX_LINES) / 4) {
    return [...a.map((line) => `-${line}`), ...b.map((line) => `+${line}`)];
  }
  const table: number[][] = Array.from({ length: a.length + 1 }, () =>
    new Array<number>(b.length + 1).fill(0),
  );
  for (let i = a.length - 1; i >= 0; i--) {
    const row = table[i] ?? [];
    const below = table[i + 1] ?? [];
    for (let j = b.length - 1; j >= 0; j--) {
      row[j] = a[i] === b[j] ? (below[j + 1] ?? 0) + 1 : Math.max(below[j] ?? 0, row[j + 1] ?? 0);
    }
  }
  const ops: string[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      ops.push(` ${a[i] ?? ""}`);
      i++;
      j++;
    } else if ((table[i + 1]?.[j] ?? 0) >= (table[i]?.[j + 1] ?? 0)) {
      ops.push(`-${a[i] ?? ""}`);
      i++;
    } else {
      ops.push(`+${b[j] ?? ""}`);
      j++;
    }
  }
  while (i < a.length) ops.push(`-${a[i++] ?? ""}`);
  while (j < b.length) ops.push(`+${b[j++] ?? ""}`);
  return ops;
}

/** A one-hunk unified diff of an edit (`a/` and `b/` headers, the whole snippet as context). */
export function unifiedDiff(path: string, before: string, after: string): string {
  const a = splitLines(before);
  const b = splitLines(after);
  const range = (lines: string[]) => `${String(lines.length ? 1 : 0)},${String(lines.length)}`;
  return [
    `--- a/${path}`,
    `+++ b/${path}`,
    `@@ -${range(a)} +${range(b)} @@`,
    ...lineOps(a, b),
  ].join("\n");
}

/** A new file as a unified diff: every line added. */
export function addedFileDiff(path: string, content: string): string {
  const lines = splitLines(content);
  return [
    "--- /dev/null",
    `+++ b/${path}`,
    `@@ -0,0 +1,${String(lines.length)} @@`,
    ...lines.map((line) => `+${line}`),
  ].join("\n");
}

/** The diff an Edit, MultiEdit or Write shows (the server's when it sent one), else null. */
export function toolDiff(tool: ToolView): string | null {
  if (tool.diff !== null) return tool.diff;
  const path = str(tool.input, "file_path") ?? "file";
  switch (tool.name) {
    case "Edit":
      return unifiedDiff(
        path,
        str(tool.input, "old_string") ?? "",
        str(tool.input, "new_string") ?? "",
      );
    case "MultiEdit":
      return arr(tool.input.edits)
        .flatMap((edit) => {
          const e = obj(edit);
          return e
            ? [unifiedDiff(path, str(e, "old_string") ?? "", str(e, "new_string") ?? "")]
            : [];
        })
        .join("\n");
    case "Write":
      return addedFileDiff(path, str(tool.input, "content") ?? "");
    default:
      return null;
  }
}

/* ---------- The reducer ---------- */

function push(state: TranscriptState, entry: TranscriptEntry): TranscriptState {
  return { ...state, entries: [...state.entries, entry] };
}

function notice(state: TranscriptState, seq: number, text: string, tone: NoticeTone = "info") {
  return push(state, { kind: "notice", key: `n-${String(seq)}`, seq, tone, text });
}

/** The last open bubble of `block`, as an index into entries, or -1. */
function openBubble(entries: TranscriptEntry[], block: number): number {
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i];
    if (entry?.kind === "assistant" && entry.streaming && entry.block === block) return i;
  }
  return -1;
}

function applyDelta(state: TranscriptState, frame: DeltaFrame): TranscriptState {
  if (frame.after_seq < state.lastSeq) return state;
  const at = openBubble(state.entries, frame.block);
  const open = state.entries[at];
  if (open?.kind === "assistant") {
    if (frame.index <= open.lastDelta) return state;
    const entries = [...state.entries];
    entries[at] = { ...open, text: open.text + frame.text, lastDelta: frame.index };
    return { ...state, entries, streaming: true };
  }
  return {
    ...push(state, {
      kind: "assistant",
      key: `d-${String(frame.after_seq)}-${String(frame.block)}`,
      seq: null,
      block: frame.block,
      text: frame.text,
      streaming: true,
      lastDelta: frame.index,
      redacted: false,
    }),
    streaming: true,
  };
}

function applyText(state: TranscriptState, seq: number, body: JsonObject): TranscriptState {
  const block = num(body, "block") ?? 0;
  const text = str(body, "text") ?? "";
  const done = {
    kind: "assistant" as const,
    seq,
    block,
    text,
    streaming: false,
    lastDelta: -1,
    redacted: isRedacted(text),
  };
  const at = openBubble(state.entries, block);
  const open = state.entries[at];
  if (open?.kind === "assistant") {
    const entries = [...state.entries];
    entries[at] = { ...done, key: open.key };
    return { ...state, entries, streaming: false };
  }
  return { ...push(state, { ...done, key: `t-${String(seq)}` }), streaming: false };
}

function applyToolCall(state: TranscriptState, body: JsonObject): TranscriptState {
  const id = str(body, "tool_use_id") ?? "";
  const parentId = str(body, "parent_tool_use_id");
  const tool: ToolView = {
    id,
    name: str(body, "name") ?? "Tool",
    input: obj(body.input) ?? {},
    parentId,
    diff: str(body, "diff"),
    result: state.tools[id]?.result ?? null,
  };
  const known = id in state.tools;
  const next = { ...state, tools: { ...state.tools, [id]: tool } };
  if (known) return next;
  if (parentId !== null && parentId in state.tools) {
    return {
      ...next,
      children: { ...state.children, [parentId]: [...(state.children[parentId] ?? []), id] },
    };
  }
  return push(next, { kind: "tool", key: `tool-${id}`, toolId: id });
}

function applyToolResult(state: TranscriptState, body: JsonObject): TranscriptState {
  const id = str(body, "tool_use_id") ?? "";
  const result: ToolResultView = {
    content: body.content ?? null,
    isError: body.is_error === true,
    truncated: body.truncated === true,
    originalBytes: num(body, "original_bytes"),
  };
  const known = state.tools[id];
  if (known) return { ...state, tools: { ...state.tools, [id]: { ...known, result } } };
  const orphan: ToolView = { id, name: "Tool", input: {}, parentId: null, diff: null, result };
  return push(
    { ...state, tools: { ...state.tools, [id]: orphan } },
    { kind: "tool", key: `tool-${id}`, toolId: id },
  );
}

function upsertPermission(state: TranscriptState, view: PermissionView): TranscriptState {
  const known = state.permissions[view.requestId];
  const merged: PermissionView = known
    ? { ...view, decision: known.decision ?? view.decision }
    : view;
  const next = { ...state, permissions: { ...state.permissions, [view.requestId]: merged } };
  if (known) return next;
  return push(next, {
    kind: "permission",
    key: `perm-${view.requestId}`,
    requestId: view.requestId,
  });
}

function applyPermissionRequest(state: TranscriptState, record: LogRecord): TranscriptState {
  const body = record.body;
  const requestId = str(body, "request_id") ?? "";
  const known = state.permissions[requestId];
  const summary = str(body, "summary") ?? "";
  // The snapshot's raw summary (memory, E10) wins over the stored, redacted one.
  if (known && !known.redacted) return state;
  const kind = str(body, "request_kind");
  return upsertPermission(state, {
    requestId,
    tool: str(body, "tool") ?? "Tool",
    requestKind: kind === "ask_user_question" || kind === "plan_approval" ? kind : "tool",
    summary,
    input: obj(body.input),
    suggestions: suggestionsOf(body.suggestions),
    askedAt: record.at,
    deadlineAt: known?.deadlineAt ?? null,
    decision: known?.decision ?? null,
    redacted: isRedacted(summary),
  });
}

function applyDecision(state: TranscriptState, record: LogRecord): TranscriptState {
  const requestId = str(record.body, "request_id") ?? "";
  const known = state.permissions[requestId];
  if (!known) return state;
  const decision = str(record.body, "decision");
  const view: PermissionDecisionView = {
    decision: decision === "allow" || decision === "always" ? decision : "deny",
    by: record.by ?? null,
    message: str(record.body, "message"),
    at: record.at,
  };
  return {
    ...state,
    permissions: { ...state.permissions, [requestId]: { ...known, decision: view } },
  };
}

function applyResult(state: TranscriptState, record: LogRecord): TranscriptState {
  const body = record.body;
  const cost = num(body, "cost_usd");
  const usage = obj(body.usage);
  const before = state.meter.usage;
  const add = (key: keyof TokenUsage) =>
    (before?.[key] ?? 0) + (usage ? (num(usage, key) ?? 0) : 0);
  const meter: MeterView = {
    costUsd:
      cost === null
        ? state.meter.costUsd
        : Math.round(((state.meter.costUsd ?? 0) + cost) * 1e6) / 1e6,
    usage:
      usage || before
        ? {
            input: add("input"),
            output: add("output"),
            cache_read: add("cache_read"),
            cache_write: add("cache_write"),
          }
        : null,
    turns: state.meter.turns + 1,
  };
  // A turn's end closes a bubble no text record replaced (an interrupt cut it short).
  const ended = endTurn(state);
  const entries = ended.entries.map((entry) =>
    entry.kind === "assistant" && entry.streaming ? { ...entry, streaming: false } : entry,
  );
  const next = { ...ended, entries, meter, streaming: false, interrupted: false };
  const reason = str(body, "terminal_reason");
  if (state.interrupted || reason?.startsWith("aborted"))
    return notice(next, record.seq, "Turn interrupted", "warning");
  const subtype = str(body, "subtype");
  if (subtype !== null && subtype !== "success")
    return notice(next, record.seq, `Turn ended: ${subtype.replace(/_/g, " ")}`, "warning");
  return next;
}

function applySettings(state: TranscriptState, record: LogRecord): TranscriptState {
  const mode = str(record.body, "mode");
  const model = str(record.body, "model");
  const parts: string[] = [];
  let next = state;
  if (mode === "default" || mode === "acceptEdits" || mode === "plan") {
    parts.push(`Mode set to ${modeLabel(mode)}`);
    next = { ...next, mode };
  }
  if (model !== null) {
    parts.push(`${parts.length ? "model" : "Model"} set to ${model}`);
    next = { ...next, model };
  }
  return notice(next, record.seq, parts.join(", ") || "Settings changed");
}

/** The turn ended: queued messages start the next one. */
function endTurn(state: TranscriptState): TranscriptState {
  const queued = state.entries.some((entry) => entry.kind === "user" && entry.queued);
  const entries = queued
    ? state.entries.map((entry) =>
        entry.kind === "user" && entry.queued ? { ...entry, queued: false } : entry,
      )
    : state.entries;
  return { ...state, entries, turnOpen: queued };
}
const idle = (state: TranscriptState, status: AgentSessionStatus) =>
  status === "running" || status === "waiting_permission"
    ? state
    : { ...endTurn(state), turnOpen: false };

function applySend(state: TranscriptState, item: SendItem): TranscriptState {
  const others = state.sending.filter((send) => send.key !== item.key);
  switch (item.type) {
    case "sending":
      return { ...state, sending: [...others, { key: item.key, text: item.text, seq: null }] };
    case "accepted":
      // Its record may have come first: then it is already in the transcript.
      return item.seq <= state.lastSeq
        ? { ...state, sending: others }
        : {
            ...state,
            sending: state.sending.map((send) =>
              send.key === item.key ? { ...send, seq: item.seq } : send,
            ),
          };
    case "failed":
      return { ...state, sending: others };
  }
}

function applyRecord(state: TranscriptState, record: LogRecord): TranscriptState {
  if (record.seq <= state.lastSeq) return state;
  const s = { ...state, lastSeq: record.seq };
  const body = record.body;
  switch (record.kind) {
    case "user.message": {
      const text = str(body, "text") ?? "";
      const sending = s.sending.filter((send) => send.seq !== record.seq);
      // Core refuses a send while an interrupt awaits its result, so a message after an
      // interrupt means that interrupt cut no turn short (it landed on an idle session).
      return push(
        { ...s, sending, turnOpen: true, interrupted: false },
        {
          kind: "user",
          key: `u-${String(record.seq)}`,
          seq: record.seq,
          at: record.at,
          text,
          redacted: isRedacted(text),
          queued: s.turnOpen,
        },
      );
    }
    case "text":
      return applyText(s, record.seq, body);
    case "thinking": {
      const text = str(body, "text") ?? "";
      return push(s, {
        kind: "thinking",
        key: `th-${String(record.seq)}`,
        seq: record.seq,
        text,
        redacted: isRedacted(text),
      });
    }
    case "tool.call":
      return applyToolCall(s, body);
    case "tool.result":
      return applyToolResult(s, body);
    case "todos":
      return {
        ...s,
        todos: arr(body.items).flatMap((item) => {
          const t = obj(item);
          return t
            ? [
                {
                  content: str(t, "content") ?? "",
                  status: str(t, "status") ?? "pending",
                  activeForm: str(t, "active_form"),
                },
              ]
            : [];
        }),
      };
    case "permission.request":
      return applyPermissionRequest(s, record);
    case "permission.decision":
      return applyDecision(s, record);
    case "result":
      return applyResult(s, record);
    case "init": {
      const model = str(body, "model");
      const commands = arr(body.slash_commands).filter((c): c is string => typeof c === "string");
      return notice(
        { ...s, model: model ?? s.model, slashCommands: commands },
        record.seq,
        model ? `Session started (model ${model})` : "Session started",
      );
    }
    case "settings":
      return applySettings(s, record);
    case "interrupt":
      return notice({ ...s, interrupted: true }, record.seq, "You interrupted the turn", "warning");
    case "close":
      return notice(s, record.seq, "Session closed");
    case "error":
      return notice(
        { ...s, streaming: false },
        record.seq,
        str(body, "message") ?? "Error",
        "error",
      );
    case "exited": {
      const code = num(body, "code");
      return code === null || code === 0
        ? notice(s, record.seq, "claude exited")
        : notice(s, record.seq, `claude exited with code ${String(code)}`, "error");
    }
    case "log.truncated": {
      const cap = str(body, "cap");
      const limit = num(body, "limit") ?? 0;
      const what =
        cap === "bytes"
          ? `${limit.toLocaleString("en-US")} bytes`
          : `${limit.toLocaleString("en-US")} records`;
      return notice(
        s,
        record.seq,
        `The log is full (${what}): resume the session to continue`,
        "warning",
      );
    }
    case "cloud.start":
    case "cloud.followup":
      return notice(
        s,
        record.seq,
        record.kind === "cloud.start" ? "Cloud start" : "Cloud follow-up",
      );
  }
}

/** The next state after one stream item. Pure: the caller keeps the state. */
export function reduceTranscript(state: TranscriptState, item: StreamItem): TranscriptState {
  switch (item.type) {
    case "record":
      return applyRecord(state, item.record);
    case "delta":
      return applyDelta(state, item.delta);
    case "status":
      return {
        ...idle(state, item.status.status),
        status: item.status.status,
        endReason: item.status.end_reason ?? null,
        streaming:
          item.status.status === "running" || item.status.status === "waiting_permission"
            ? state.streaming
            : false,
      };
    case "reset":
      return { ...initialTranscript(), reset: item.reset.reason, sending: state.sending };
    default:
      return applySend(state, item);
  }
}

/** Merges what `GET /{id}` holds: status, mode, model and the open request with its raw summary. */
export function applySnapshot(state: TranscriptState, session: AgentSession): TranscriptState {
  const next: TranscriptState = {
    ...idle(state, session.status),
    status: session.status,
    endReason: session.end_reason ?? null,
    mode: session.mode,
    model: session.model ?? state.model,
  };
  const open = session.open_permission;
  if (!open) return next;
  const known = next.permissions[open.request_id];
  return upsertPermission(next, {
    requestId: open.request_id,
    tool: open.tool,
    requestKind: open.request_kind,
    summary: open.summary,
    input: open.input ?? null,
    suggestions: open.suggestions,
    askedAt: open.asked_at,
    deadlineAt: open.deadline_at,
    decision: known?.decision ?? null,
    redacted: false,
  });
}

/** `loaded` (a reload of the log) with the messages of `previous` whose record it lacks. */
export function keepSending(previous: TranscriptState, loaded: TranscriptState): TranscriptState {
  const sending = previous.sending.filter((send) => send.seq === null || send.seq > loaded.lastSeq);
  return { ...loaded, sending };
}

/** The ids of the requests still waiting for an answer, oldest first. */
export function pendingPermissions(state: TranscriptState): string[] {
  return state.entries.flatMap((entry) =>
    entry.kind === "permission" && state.permissions[entry.requestId]?.decision === null
      ? [entry.requestId]
      : [],
  );
}
