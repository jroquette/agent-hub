import type { components } from "../../api/schema";
import { Banner, Button } from "../../components";
import { fmtClock } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";

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
        <span>
          From Linear · read at {tickets.as_of ? <AsOf value={tickets.as_of} /> : "an unknown time"}
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
