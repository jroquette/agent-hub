import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useReducer, useState } from "react";

import type { components } from "../../api/schema";
import {
  apiDelete,
  apiGet,
  apiKey,
  apiPost,
  apiQuery,
  toProblem,
  useApi,
  type ApiProblem,
} from "../../lib/api";
import { useEventStream, type StreamHandlers, type StreamHealth } from "../../lib/sse";
import {
  applySnapshot,
  initialTranscript,
  reduceTranscript,
  type AgentSession,
  type AgentSessionStatus,
  type DeltaFrame,
  type LogRecord,
  type StatusFrame,
  type StreamItem,
  type TranscriptState,
} from "./transcript";

/* The data of the chat view (WS): the snapshot, the log pages, the stream and the commands. */

type Schemas = components["schemas"];
export type RecordKind = Schemas["RecordKind"];
export type DriverCapabilities = Schemas["DriverCapabilities"];
export type PermissionAnswer = Schemas["PermissionDecision"];
export type SettingsBody = Schemas["SessionSettings"];
type LogRecordPage = Schemas["LogRecordPage"];

const SESSION = "/api/v1/agent-sessions/{agent_session_id}" as const;
/** The API's largest log page (plan "Inputs, bounds and budget": `limit` 1-500). */
export const LOG_PAGE = 500;

/** Every record kind the stream names as `record.<kind>` (`RecordKind`). */
export const RECORD_KINDS: readonly RecordKind[] = [
  "init",
  "text",
  "thinking",
  "tool.call",
  "tool.result",
  "todos",
  "permission.request",
  "result",
  "error",
  "exited",
  "user.message",
  "permission.decision",
  "interrupt",
  "settings",
  "close",
  "log.truncated",
  "cloud.start",
  "cloud.followup",
];

const TERMINAL: readonly AgentSessionStatus[] = ["ended", "failed"];
/** Whether a session can do nothing more (its stream would only replay). */
export function isTerminal(status: AgentSessionStatus | null | undefined): boolean {
  return status !== null && status !== undefined && TERMINAL.includes(status);
}

export const sessionParams = (id: string) => ({ path: { agent_session_id: id } });
export const sessionKey = (id: string) => apiKey(SESSION, sessionParams(id));

/** `GET /agent-sessions/{id}`: the snapshot (status, mode, model, the open request). */
export function useAgentSession(id: string) {
  return useApi(SESSION, sessionParams(id), { retry: false });
}

/** What this machine can drive (the model aliases the composer offers). */
export function useCapabilities() {
  return useApi("/api/v1/agent-sessions/capabilities", undefined, {
    staleTime: 60_000,
    retry: false,
  });
}

/** Every persisted record of the session after `after`, page by page (`next_after`). */
export async function loadLog(id: string, signal?: AbortSignal, after = 0): Promise<LogRecord[]> {
  const records: LogRecord[] = [];
  let cursor: number | null = after;
  while (cursor !== null) {
    const page: LogRecordPage = await apiGet(
      "/api/v1/agent-sessions/{agent_session_id}/events",
      { path: { agent_session_id: id }, query: { after: cursor, limit: LOG_PAGE } },
      signal,
    );
    records.push(...page.items);
    const next: number | null = page.next_after ?? null;
    cursor = next !== null && next > cursor && page.items.length > 0 ? next : null;
  }
  return records;
}

/** The stream of a session, resumed after `after` (the browser then resends `Last-Event-ID`). */
export function streamUrl(id: string, after: number): string {
  const base = `/api/v1/agent-sessions/${encodeURIComponent(id)}/stream`;
  return after > 0 ? `${base}?after=${String(after)}` : base;
}

/* ---------- Frames to stream items ---------- */

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

function isRecord(data: unknown): data is LogRecord {
  return (
    isObject(data) &&
    typeof data.seq === "number" &&
    typeof data.kind === "string" &&
    typeof data.at === "string" &&
    isObject(data.body)
  );
}
function isDelta(data: unknown): data is DeltaFrame {
  return (
    isObject(data) &&
    typeof data.after_seq === "number" &&
    typeof data.block === "number" &&
    typeof data.index === "number" &&
    typeof data.text === "string"
  );
}
function isStatus(data: unknown): data is StatusFrame {
  return isObject(data) && typeof data.status === "string";
}

/**
 * The handlers of one session stream: `record.<kind>`, `delta` and `status` become the reducer's
 * stream items; `reset` calls `onReset` (the caller reloads the snapshot and the log).
 */
export function streamHandlers(
  onItem: (item: StreamItem) => void,
  onReset: (reason: string) => void,
): StreamHandlers {
  const handlers: StreamHandlers = {};
  for (const kind of RECORD_KINDS) {
    handlers[`record.${kind}`] = (data) => {
      if (isRecord(data)) onItem({ type: "record", record: data });
    };
  }
  handlers.delta = (data) => {
    if (isDelta(data)) onItem({ type: "delta", delta: data });
  };
  handlers.status = (data) => {
    if (isStatus(data)) onItem({ type: "status", status: data });
  };
  handlers.reset = (data) => {
    const reason = isObject(data) && typeof data.reason === "string" ? data.reason : "reset";
    onReset(reason);
  };
  return handlers;
}

/* ---------- The transcript hook ---------- */

type Action = { type: "item"; item: StreamItem } | { type: "replace"; state: TranscriptState };

function reducer(state: TranscriptState, action: Action): TranscriptState {
  return action.type === "replace" ? action.state : reduceTranscript(state, action.item);
}

/** The log and the snapshot folded into one transcript (the snapshot's raw open request wins). */
export function buildTranscript(records: readonly LogRecord[], session: AgentSession) {
  const folded = records.reduce<TranscriptState>(
    (state, record) => reduceTranscript(state, { type: "record", record }),
    initialTranscript(),
  );
  return applySnapshot(folded, session);
}

export interface AgentTranscript {
  state: TranscriptState;
  /** True until the snapshot and every log page arrived. */
  loading: boolean;
  /** The snapshot or a log page failed. */
  error: ApiProblem | null;
  retry: () => void;
  health: StreamHealth;
  /** Whether the stream is (meant to be) open: a live session whose log has loaded. */
  streaming: boolean;
}

/**
 * The chat view's transcript (WS): the snapshot and every log page, then the stream from the
 * last record loaded. A `reset` closes the stream, reloads both and reopens it; a terminal
 * status closes it for good (an ended session's stream would only replay).
 */
export function useAgentTranscript(id: string): AgentTranscript {
  const queryClient = useQueryClient();
  const [state, dispatch] = useReducer(reducer, undefined, initialTranscript);
  const [generation, setGeneration] = useState(0);
  // What the last load gave (the stream's start, or why it failed), for the load named `key`.
  const [loaded, setLoaded] = useState<{
    key: string;
    after: number | null;
    error: ApiProblem | null;
  } | null>(null);
  const key = `${id}#${String(generation)}`;

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const [session, records] = await Promise.all([
          queryClient.query({ ...apiQuery(SESSION, sessionParams(id)), staleTime: 0 }),
          loadLog(id, controller.signal),
        ]);
        if (controller.signal.aborted) return;
        const built = buildTranscript(records, session);
        dispatch({ type: "replace", state: built });
        setLoaded({ key, after: built.lastSeq, error: null });
      } catch (cause) {
        if (controller.signal.aborted) return;
        setLoaded({ key, after: null, error: toProblem(cause) });
      }
    })();
    return () => {
      controller.abort();
    };
  }, [id, key, queryClient]);

  const reload = useCallback(() => {
    setGeneration((g) => g + 1);
  }, []);

  const handlers = useMemo(
    () =>
      streamHandlers((item) => {
        dispatch({ type: "item", item });
        if (item.type === "status") {
          void queryClient.invalidateQueries({ queryKey: sessionKey(id) });
        }
      }, reload),
    [id, queryClient, reload],
  );

  const current = loaded?.key === key ? loaded : null;
  const after = current?.after ?? null;
  const streaming = after !== null && !isTerminal(state.status);
  const health = useEventStream(streaming ? streamUrl(id, after) : null, handlers);
  return {
    state,
    loading: current === null,
    error: current?.error ?? null,
    retry: reload,
    health,
    streaming,
  };
}

/* ---------- Commands ---------- */

/** A bodiless command still sends `{}` with the JSON content type (Wave 0: JSON writes only). */
const NO_BODY = {} as never;

function isSession(data: unknown): data is AgentSession {
  return isObject(data) && typeof data.id === "string" && typeof data.status === "string";
}

export interface AgentSessionCommands {
  send: (text: string) => Promise<unknown>;
  interrupt: () => Promise<unknown>;
  settings: (change: SettingsBody) => Promise<unknown>;
  answer: (requestId: string, answer: PermissionAnswer) => Promise<unknown>;
  close: () => Promise<unknown>;
  remove: () => Promise<void>;
}

/**
 * The session's commands as same-origin JSON POSTs (and the DELETE). A command answering the
 * session refreshes the snapshot cache; the transcript itself follows the stream's records.
 */
export function useAgentSessionCommands(id: string): AgentSessionCommands {
  const queryClient = useQueryClient();
  return useMemo(() => {
    const params = sessionParams(id);
    const keep = (data: unknown) => {
      if (isSession(data)) queryClient.setQueryData(sessionKey(id), data);
      return data;
    };
    return {
      send: (text) =>
        apiPost("/api/v1/agent-sessions/{agent_session_id}/messages", { text }, params),
      interrupt: () =>
        apiPost("/api/v1/agent-sessions/{agent_session_id}/interrupt", NO_BODY, params).then(keep),
      settings: (change) =>
        apiPost("/api/v1/agent-sessions/{agent_session_id}/settings", change, params).then(keep),
      answer: (requestId, answer) =>
        apiPost("/api/v1/agent-sessions/{agent_session_id}/permissions/{request_id}", answer, {
          path: { agent_session_id: id, request_id: requestId },
        }).then(keep),
      close: () =>
        apiPost("/api/v1/agent-sessions/{agent_session_id}/close", NO_BODY, params).then(keep),
      remove: async () => {
        await apiDelete(SESSION, params);
        queryClient.removeQueries({ queryKey: sessionKey(id) });
        await queryClient.invalidateQueries({ queryKey: apiKey("/api/v1/agent-sessions") });
      },
    };
  }, [id, queryClient]);
}
