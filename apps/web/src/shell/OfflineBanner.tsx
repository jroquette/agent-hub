import { useState } from "react";

import { Button, copyText, useCopied } from "../components/core";
import { collectorState, type CollectorState } from "../components/CollectorPill";
import { Banner } from "../components/feedback";
import { useNow } from "../lib/clock";
import { fmtClock, type TimeZoneMode } from "../lib/format";
import { usePreferences } from "../lib/preferences";
import type { StreamHealth } from "../lib/sse";

export const START_COMMAND = "hub web";

export interface OfflineBannerProps {
  health: StreamHealth;
  tz?: TimeZoneMode | undefined;
}

/** The non-blocking banner under the top bar while the collector is offline (spec 01). */
export function OfflineBanner({ health, tz }: OfflineBannerProps) {
  const now = useNow(1000);
  const preferences = usePreferences();
  const state = collectorState(health, now);
  const [dismissed, setDismissed] = useState(false);
  const [seen, setSeen] = useState<CollectorState>(state);
  const [copied, markCopied] = useCopied();
  if (seen !== state) {
    // A new state brings the banner back after a dismissal.
    setSeen(state);
    setDismissed(false);
  }
  if (state !== "offline" || dismissed) return null;
  const since = fmtClock(new Date(health.lastMessageAt), tz ?? preferences.tz);
  return (
    <Banner
      tone="offline"
      onDismiss={() => {
        setDismissed(true);
      }}
      action={
        <Button
          size="sm"
          variant="ghost"
          icon={copied ? "check" : "copy"}
          aria-label={copied ? "Copied" : "Copy command"}
          onClick={() => {
            copyText(START_COMMAND);
            markCopied();
          }}
        >
          {copied ? "Copied" : "Copy"}
        </Button>
      }
    >
      Collector offline since {since}. Views show data as of {since}. Start it with{" "}
      <code>{START_COMMAND}</code>.
    </Banner>
  );
}
