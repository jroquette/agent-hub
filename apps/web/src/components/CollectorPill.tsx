import { fmtAgo, fmtClock, type TimeZoneMode } from "../lib/format";
import { useNow } from "../lib/clock";
import type { StreamHealth } from "../lib/sse";
import { usePreferences } from "../lib/preferences";
import { Tooltip } from "./core";
import { Icon } from "./Icon";

export type CollectorState = "connected" | "delayed" | "offline";

export type { StreamHealth };

/** Silence before the pill turns Delayed and Offline (heartbeats come every 15 s). */
export const DELAYED_AFTER_MS = 30_000;
export const OFFLINE_AFTER_MS = 60_000;
/** A closed stream whose reconnect keeps failing this long is Offline. */
export const RECONNECT_GRACE_MS = 10_000;

/** Connected < 30 s of silence, Delayed < 60 s, Offline from 60 s or after 10 s closed. */
export function collectorState(health: StreamHealth, now: number): CollectorState {
  if (
    !health.open &&
    health.closedSince !== null &&
    now - health.closedSince >= RECONNECT_GRACE_MS
  ) {
    return "offline";
  }
  const silence = now - health.lastMessageAt;
  if (silence >= OFFLINE_AFTER_MS) return "offline";
  return silence >= DELAYED_AFTER_MS ? "delayed" : "connected";
}

export interface CollectorPillProps {
  health: StreamHealth;
  /** Defaults to the time zone preference. */
  tz?: TimeZoneMode | undefined;
}

/** Shows whether data is flowing, from the global stream's heartbeats. */
export function CollectorPill({ health, tz }: CollectorPillProps) {
  const now = useNow(1000);
  const preferences = usePreferences();
  const zone = tz ?? preferences.tz;
  const state = collectorState(health, now);
  const asOf = fmtClock(new Date(health.lastMessageAt), zone);
  const age = fmtAgo(Math.max(0, now - health.lastMessageAt) / 1000);
  const label = {
    connected: `Connected · last event ${age}`,
    delayed: `Delayed · last event ${age}`,
    offline: `Offline · as of ${asOf}`,
  }[state];
  const tip = {
    connected:
      "Collector: hub web receives hook, transcript and executor events. Details in Settings › Collector.",
    delayed: `No heartbeat for ${age.replace(" ago", "")}. Live views may lag.`,
    offline: `Collector not reachable since ${asOf}. Start it with hub web in the hub directory.`,
  }[state];
  return (
    <Tooltip label={tip}>
      <span className="ah-collector" data-state={state} role="status" aria-live="polite">
        {state === "offline" ? (
          <Icon name="wifi-off" size="sm" />
        ) : state === "delayed" ? (
          <Icon name="clock" size="sm" />
        ) : (
          <span className="ah-dot" />
        )}
        {/* The age changes every second: only the state is announced (rate-limited live region). */}
        <span aria-hidden="true">{label}</span>
        <span className="ah-sr">{`Collector ${state}`}</span>
      </span>
    </Tooltip>
  );
}
