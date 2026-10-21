import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

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
import { ticketName, type TicketInfo } from "../../components";
import { fileBody, type MessageFile } from "../../lib/messageFile";
import { screenshotBody } from "../../lib/pastedImage";
import { rememberMessageScreenshots } from "../../lib/screenshotCopy";
import { useEventStream, type StreamHandlers, type StreamHealth } from "../../lib/sse";
import { useTicketLookup, useTicketTitles } from "../features/queries";
import {
  applySnapshot,
  initialTranscript,
  keepSending,
  reduceTranscript,
  type AgentSession,
  type AgentSessionStatus,
  type DeltaFrame,
  type LogRecord,
  type StatusFrame,
  type StreamItem,
  type TranscriptState,
} from "./model";

/* The data of the chat view (WS): the snapshot, the log pages, the stream and the commands. */

type Schemas = components["schemas"];
export type RecordKind = Schemas["RecordKind"];
export type DriverCapabilities = Schemas["DriverCapabilities"];
export type PermissionAnswer = Schemas["PermissionDecision"];
export type SettingsBody = Schemas["SessionSettings"];
export type MessageAccepted = Schemas["MessageAccepted"];
type LogRecordPage = Schemas["LogRecordPage"];

const SESSION = "/api/v1/agent-sessions/{agent_session_id}" as const;
/** The API's largest log page (plan "Inputs, bounds and budget": `limit` 1-500). */
export const LOG_PAGE = 500;

/** Every record kind the stream names as `record.<kind>` (`RecordKind`): a key per kind, so a
 * kind the API adds fails the typecheck until the stream listens for it. */
const STREAMED: Record<RecordKind, true> = {
  init: true,
  text: true,
  thinking: true,
  "tool.call": true,
  "tool.result": true,
  todos: true,
  task: true,
  "permission.request": true,
  result: true,
  error: true,
  exited: true,
  "user.message": true,
  "permission.decision": true,
  interrupt: true,
  settings: true,
  close: true,
  "log.truncated": true,
  "cloud.start": true,
  "cloud.followup": true,
};
export const RECORD_KINDS = Object.keys(STREAMED) as readonly RecordKind[];

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

/**
 * `GET /agent-sessions/{id}/repo-changes`: what the session's repositories change against their
 * base branch, as git reads them. Read again whenever `version` changes (a file tool ran, a turn
 * ended), since a commit or a shell command changes it without the chat knowing.
 */
export function useRepoChanges(id: string, version: string) {
  const query = useApi(
    "/api/v1/agent-sessions/{agent_session_id}/repo-changes",
    sessionParams(id),
    { retry: false, staleTime: 5_000, refetchOnWindowFocus: true },
  );
  const { refetch } = query;
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    void refetch();
  }, [version, refetch]);
  return query;
}

/** `GET /agent-sessions/{id}/repo-changes/commit`: what one commit changed in one file. A commit
 * never changes, so it is read once. */
export function useRepoCommitDiff(
  id: string,
  { path, oldPath, sha }: { path: string; oldPath: string | null; sha: string },
) {
  return useApi(
    "/api/v1/agent-sessions/{agent_session_id}/repo-changes/commit",
    {
      path: { agent_session_id: id },
      query: { path, sha, ...(oldPath ? { old_path: oldPath } : {}) },
    },
    { retry: false, staleTime: Infinity },
  );
}

/** What a session is about: its name and, when it is on a ticket a hub feature works on, that
 * feature. */
export interface SessionAbout {
  name: string | null;
  feature: TicketInfo | null;
}

/**
 * The session's name: a session on a ticket reads as its commits do (`ACME-12: Export orders as
 * CSV`, from its observed twin's label and the hub's features), else Claude Code's title. It reads
 * the feature's tickets once, so the name says what the ticket is about.
 */
export function useSessionAbout(session: AgentSession | undefined): SessionAbout {
  const observed = session?.observed_session_id ?? null;
  const twin = useApi(
    "/api/v1/sessions/{session_id}",
    { path: { session_id: observed ?? "" } },
    { enabled: observed !== null, staleTime: 30_000, retry: false },
  );
  const tickets = useTicketLookup(session?.project ?? null);
  const label = twin.data?.label;
  const feature = label?.issue ? tickets.get(label.issue.toUpperCase()) : undefined;
  useTicketTitles(feature);
  return {
    name: ticketName(label, tickets) ?? session?.title ?? null,
    feature: feature ?? null,
  };
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

type Action = { type: "items"; items: StreamItem[] } | { type: "replace"; state: TranscriptState };

function reducer(state: TranscriptState, action: Action): TranscriptState {
  return action.type === "replace"
    ? keepSending(state, action.state)
    : action.items.reduce(reduceTranscript, state);
}

export interface FrameBatcher {
  push: (item: StreamItem) => void;
  /** Drops what is queued and the pending frame (a reset, an unmount). */
  drop: () => void;
}

/**
 * Deltas wait for the next animation frame and go out together, so a burst renders once per
 * frame (AC-234.20); a record or status frame flushes the queued deltas first, in order.
 */
export function frameBatcher(dispatch: (items: StreamItem[]) => void): FrameBatcher {
  let queued: StreamItem[] = [];
  let frame: number | null = null;
  const drop = () => {
    if (frame !== null) cancelAnimationFrame(frame);
    frame = null;
    queued = [];
  };
  const flush = (item?: StreamItem) => {
    const items = item ? [...queued, item] : queued;
    drop();
    if (items.length > 0) dispatch(items);
  };
  return {
    push: (item) => {
      if (item.type !== "delta") {
        flush(item);
        return;
      }
      queued.push(item);
      if (frame === null) {
        frame = -1; // A frame that runs at once (tests) must not leave a stale id behind.
        const id = requestAnimationFrame(() => {
          frame = null;
          flush();
        });
        if (frame === -1) frame = id;
      }
    },
    drop,
  };
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
  /** Posts `text` (and the images and files attached to it) with `post`, showing it as
   * "Sending…" until its record arrives (AC-234.27); the images are kept in this browser under
   * the accepted seq, the files are only named. */
  send: (
    text: string,
    post: (text: string) => Promise<MessageAccepted>,
    screenshots?: readonly string[],
    files?: readonly MessageFile[],
  ) => Promise<unknown>;
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

  const batcher = useMemo(
    () =>
      frameBatcher((items) => {
        dispatch({ type: "items", items });
      }),
    [],
  );
  useEffect(() => batcher.drop, [batcher]);

  const handlers = useMemo(
    () =>
      streamHandlers(
        (item) => {
          batcher.push(item);
          if (item.type === "status") {
            void queryClient.invalidateQueries({ queryKey: sessionKey(id) });
          }
        },
        () => {
          batcher.drop();
          reload();
        },
      ),
    [batcher, id, queryClient, reload],
  );

  const sends = useRef(0);
  const ended = useRef(false);
  useEffect(() => {
    ended.current = isTerminal(state.status);
  });
  const send = useCallback(
    async (
      text: string,
      post: (text: string) => Promise<MessageAccepted>,
      screenshots: readonly string[] = [],
      files: readonly MessageFile[] = [],
    ) => {
      const sendKey = `send-${String((sends.current += 1))}`;
      // A message to an ended session reopens it in place: reload, so the stream opens again.
      const reopens = ended.current;
      const attachedFiles = files.map((file) => ({ name: file.name, bytes: file.bytes }));
      batcher.push({ type: "sending", key: sendKey, text, screenshots, files: attachedFiles });
      try {
        const { seq } = await post(text);
        // The server keeps no image: this browser does, for the message's bubble.
        if (screenshots.length > 0) rememberMessageScreenshots(id, seq, screenshots);
        batcher.push({ type: "accepted", key: sendKey, seq });
      } catch (cause) {
        batcher.push({ type: "failed", key: sendKey });
        throw cause;
      }
      if (reopens) {
        void queryClient.invalidateQueries({ queryKey: sessionKey(id) });
        reload();
      }
    },
    [batcher, id, queryClient, reload],
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
    send,
  };
}

/* ---------- Commands ---------- */

/** A bodiless command still sends `{}` with the JSON content type (Wave 0: JSON writes only). */
const NO_BODY = {} as never;

function isSession(data: unknown): data is AgentSession {
  return isObject(data) && typeof data.id === "string" && typeof data.status === "string";
}

export interface AgentSessionCommands {
  /** Posts a message, with the PNG data URLs of the images pasted in it and its files. */
  send: (
    text: string,
    screenshots?: readonly string[],
    files?: readonly MessageFile[],
  ) => Promise<MessageAccepted>;
  interrupt: () => Promise<unknown>;
  /** Stops a running background task (an agent or a command). */
  stopTask: (taskId: string) => Promise<unknown>;
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
      send: (text, screenshots = [], files = []) =>
        apiPost(
          "/api/v1/agent-sessions/{agent_session_id}/messages",
          {
            text,
            ...(screenshots.length > 0 ? { screenshots: screenshots.map(screenshotBody) } : {}),
            ...(files.length > 0 ? { files: files.map(fileBody) } : {}),
          },
          params,
        ),
      interrupt: () =>
        apiPost("/api/v1/agent-sessions/{agent_session_id}/interrupt", NO_BODY, params).then(keep),
      stopTask: (taskId) =>
        apiPost("/api/v1/agent-sessions/{agent_session_id}/tasks/{task_id}/stop", NO_BODY, {
          path: { agent_session_id: id, task_id: taskId },
        }).then(keep),
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
