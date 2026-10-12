import { useEffect, useRef, useState } from "react";

/*
 * One wrapper over EventSource for every stream of the API (spec 02 "SSE contract"). The browser
 * resends `Last-Event-ID` when it reconnects, so the server replays what was missed; a final close
 * (the browser gave up) is reopened after RECONNECT_MS.
 */

/** What the client knows about a stream; CollectorPill derives its state from it. */
export interface StreamHealth {
  open: boolean;
  /** Ms of the last message (heartbeats included), or of the first connection attempt. */
  lastMessageAt: number;
  /** Ms since the stream has been closed, null while open. */
  closedSince: number | null;
}

/** Handlers by event name; each gets the parsed JSON body and the message id. */
export type StreamHandlers = Record<string, (data: unknown, id: string) => void>;

export const RECONNECT_MS = 3_000;
/** Event names every stream sends that count as life even when no handler wants them. */
const ALWAYS = ["heartbeat"];

/** Opens `url` and calls `onHealth` on every change; returns a function that closes it for good. */
export function openStream(
  url: string,
  handlers: StreamHandlers,
  onHealth: (health: StreamHealth) => void,
): () => void {
  let health: StreamHealth = { open: false, lastMessageAt: Date.now(), closedSince: null };
  let source: EventSource | null = null;
  let retry: ReturnType<typeof setTimeout> | undefined;
  let stopped = false;

  const report = (next: StreamHealth) => {
    health = next;
    onHealth(health);
  };

  if (typeof EventSource === "undefined") {
    const now = Date.now();
    report({ open: false, lastMessageAt: now, closedSince: now });
    return () => undefined;
  }

  const connect = () => {
    const current = new EventSource(url);
    source = current;
    current.onopen = () => {
      report({ ...health, open: true, closedSince: null });
    };
    current.onerror = () => {
      report({ ...health, open: false, closedSince: health.closedSince ?? Date.now() });
      if (current.readyState === EventSource.CLOSED && !stopped) {
        retry = setTimeout(connect, RECONNECT_MS);
      }
    };
    const names = new Set([...Object.keys(handlers), ...ALWAYS]);
    for (const name of names) {
      current.addEventListener(name, (event: MessageEvent<string>) => {
        report({ open: true, lastMessageAt: Date.now(), closedSince: null });
        let data: unknown;
        try {
          data = JSON.parse(event.data);
        } catch {
          return;
        }
        handlers[name]?.(data, event.lastEventId);
      });
    }
  };
  connect();

  return () => {
    stopped = true;
    clearTimeout(retry);
    source?.close();
  };
}

/**
 * Keeps `url` open while mounted (null: none) and returns its health. Handlers may change on
 * every render; the latest ones are called. Health updates at most once a second.
 */
export function useEventStream(url: string | null, handlers: StreamHandlers): StreamHealth {
  const [health, setHealth] = useState<StreamHealth>(() => ({
    open: false,
    lastMessageAt: Date.now(),
    closedSince: null,
  }));
  const latest = useRef(handlers);
  useEffect(() => {
    latest.current = handlers;
  });
  const names = Object.keys(handlers).sort().join(",");

  useEffect(() => {
    if (url === null) return undefined;
    const proxies: StreamHandlers = {};
    for (const name of names ? names.split(",") : []) {
      proxies[name] = (data, id) => {
        latest.current[name]?.(data, id);
      };
    }
    let shownAt = 0;
    return openStream(url, proxies, (next) => {
      setHealth((previous) => {
        const sameState = previous.open === next.open && previous.closedSince === next.closedSince;
        if (sameState && next.lastMessageAt - shownAt < 1_000) return previous;
        shownAt = next.lastMessageAt;
        return next;
      });
    });
  }, [url, names]);

  return health;
}
