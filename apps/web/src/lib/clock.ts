import { useEffect, useState, useSyncExternalStore } from "react";

/** The current time in ms, refreshed every `intervalMs`. */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => {
      setNow(Date.now());
    }, intervalMs);
    return () => {
      clearInterval(timer);
    };
  }, [intervalMs]);
  return now;
}

/** One minute clock shared by every subscriber: a single timer, however many read it. */
const minute = {
  listeners: new Set<() => void>(),
  timer: undefined as ReturnType<typeof setInterval> | undefined,
};

function subscribeMinute(listener: () => void): () => void {
  minute.listeners.add(listener);
  minute.timer ??= setInterval(() => {
    for (const notify of minute.listeners) notify();
  }, 60_000);
  return () => {
    minute.listeners.delete(listener);
    if (minute.listeners.size > 0) return;
    clearInterval(minute.timer);
    minute.timer = undefined;
  };
}

/** The time floored to its minute: stable between ticks, so React can compare snapshots. */
const minuteSnapshot = () => Math.floor(Date.now() / 60_000) * 60_000;

/** The current time in ms, floored to the minute, for relative times shown on many rows at once. */
export function useMinuteNow(): number {
  return useSyncExternalStore(subscribeMinute, minuteSnapshot);
}
