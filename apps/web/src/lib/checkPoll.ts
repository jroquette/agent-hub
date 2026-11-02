import { useRef } from "react";

/* AGH-608: hub web runs the doctor in the background, so a hub has no check until its first
 * background run ends (`checked_at` null). Nothing tells the browser when it ends (the stream's
 * counts do not carry it), so the screens that show health read again until it has. */

/** How often a screen reads again while a check it shows has not ended. */
export const CHECK_POLL_MS = 2_000;
/** After a minute of unchecked answers: a hub whose runs keep failing backs off to 15 min on the
 * server, so the screen stops asking every 2 s. */
export const CHECK_SLOW_POLL_MS = 15_000;
const CHECK_FAST_FOR_MS = 60_000;

/** The part of a TanStack query the rule reads (`refetchInterval` gets the whole query). */
export interface PolledQuery<T> {
  queryHash: string;
  state: { data: T | undefined };
}

/**
 * A `refetchInterval` that reads again while `isUnchecked` holds for the last answer: every
 * `CHECK_POLL_MS` for the first minute of unchecked answers of the same query, then every
 * `CHECK_SLOW_POLL_MS`. A checked answer starts no polling, and the next unchecked answer (or a
 * query with another key, such as another scope) starts a new first minute.
 */
export function useCheckPoll<T>(
  isUnchecked: (data: T) => boolean,
): (query: PolledQuery<T>) => number | false {
  const firstUnchecked = useRef<{ hash: string; at: number } | null>(null);
  return (query) => {
    const data = query.state.data;
    if (data === undefined) return false;
    if (!isUnchecked(data)) {
      firstUnchecked.current = null;
      return false;
    }
    const now = Date.now();
    if (firstUnchecked.current?.hash !== query.queryHash) {
      firstUnchecked.current = { hash: query.queryHash, at: now };
    }
    return now - firstUnchecked.current.at < CHECK_FAST_FOR_MS ? CHECK_POLL_MS : CHECK_SLOW_POLL_MS;
  };
}
