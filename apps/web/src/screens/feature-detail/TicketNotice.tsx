import type { components } from "../../api/schema";
import { Banner, Button } from "../../components";
import { useNow } from "../../lib/clock";
import { fmtAgo, fmtClock } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { TICKETS_REFRESH_MS } from "./queries";

type FeatureTickets = components["schemas"]["FeatureTickets"];

export interface TicketNoticeProps {
  tickets: FeatureTickets;
  /** Refetches the tickets route (E11: the server cache still applies, `as_of` shows its age). */
  onRefresh: () => void;
  refreshing?: boolean | undefined;
}

function AsOf({ value }: { value: string }) {
  const { tz } = usePreferences();
  return (
    <time dateTime={value} title={value}>
      {fmtClock(value, tz)}
    </time>
  );
}

/** "12 s ago", ticking, with the clock time on hover. */
function Ago({ value }: { value: string }) {
  const { tz } = usePreferences();
  const now = useNow(1000);
  const seconds = Math.max(0, (now - new Date(value).getTime()) / 1000);
  return (
    <time dateTime={value} title={fmtClock(value, tz, true)}>
      {fmtAgo(seconds)}
    </time>
  );
}

function RefreshButton({ onRefresh, refreshing }: Omit<TicketNoticeProps, "tickets">) {
  return (
    <Button size="sm" icon="refresh-cw" disabled={refreshing} onClick={onRefresh}>
      {refreshing ? "Refreshing" : "Refresh"}
    </Button>
  );
}

/**
 * Where the ticket data comes from (AC-136.31): a warning notice with the server's text, the
 * tracker problem and `as_of` when it is the plan or a stale snapshot; a quiet source line when
 * Linear answered. Both carry Refresh.
 */
export function TicketNotice({ tickets, onRefresh, refreshing }: TicketNoticeProps) {
  const refresh = <RefreshButton onRefresh={onRefresh} refreshing={refreshing} />;
  const fromPlan = tickets.source === "plan";
  if (!fromPlan && !tickets.stale) {
    return (
      <div className="ah-row ah-small ah-muted" style={{ gap: 8 }}>
        <span
          className="ah-live-dot"
          data-busy={refreshing ? true : undefined}
          aria-hidden="true"
          title={refreshing ? "Reading Linear" : "Live"}
        />
        <span>
          Live from Linear · read{" "}
          {tickets.as_of ? <Ago value={tickets.as_of} /> : "at an unknown time"} · updates every{" "}
          {String(TICKETS_REFRESH_MS / 1000)} s while this tab is open
        </span>
        <span className="ah-grow" />
        {refresh}
      </div>
    );
  }
  const text =
    tickets.notice ??
    (fromPlan
      ? "From the plan (features.json); status may be stale."
      : "Linear did not answer; showing the last status read.");
  const problem = tickets.tracker_problem;
  return (
    <Banner tone="warning" boxed icon="triangle-alert" action={refresh}>
      <div className="ah-stack" style={{ gap: 4 }}>
        <b style={{ fontWeight: 500 }}>{text}</b>
        {problem && (
          <span className="ah-small">
            {problem.title}: {problem.detail}
          </span>
        )}
        <span className="ah-small">
          {tickets.as_of ? (
            <>
              Status read from Linear at <AsOf value={tickets.as_of} />.
            </>
          ) : (
            "No status read from Linear yet."
          )}
        </span>
      </div>
    </Banner>
  );
}
