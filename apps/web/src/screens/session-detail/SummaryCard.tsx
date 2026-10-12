import { useState } from "react";

import { Button, DerivedLabel, Icon, ProblemError, Skeleton } from "../../components";
import { readStored, writeStored } from "../../lib/storage";
import { useSessionSummary, type Session } from "./queries";

const COLLAPSED_KEY = "ah.session.summaryCollapsed";
const HOW =
  "Generated after the session from its events by the collector. It may miss nuance; each line links to the moment it describes.";

export interface SummaryCardProps {
  session: Session;
  onJump: (eventId: string) => void;
  /** The clock time of a loaded event, for the line's link text. */
  timeOf: (eventId: string) => string | null;
}

/** "Summary · derived": 3–5 lines after the session ends, each linking to its moment (D17). */
export function SummaryCard({ session, onJump, timeOf }: SummaryCardProps) {
  const ended = session.status === "ended";
  const summary = useSessionSummary(session.id, ended);
  const [collapsed, setCollapsed] = useState(() => readStored(COLLAPSED_KEY) === "1");
  if (!ended) {
    return (
      <div className="ah-derived-box ah-row" style={{ padding: "10px 14px", gap: 10 }}>
        <Icon name="circle-dashed" size="sm" style={{ color: "var(--text-subtle)" }} />
        <span className="ah-small ah-subtle">Summary appears when the session ends</span>
      </div>
    );
  }
  const toggle = () => {
    writeStored(COLLAPSED_KEY, collapsed ? "0" : "1");
    setCollapsed(!collapsed);
  };
  const lines = summary.data?.lines ?? [];
  return (
    <section
      className="ah-derived-box"
      style={{ padding: "12px 16px", background: "var(--surface)" }}
      aria-label="Session summary"
    >
      <div className="ah-row" style={{ marginBottom: 6 }}>
        <b>Summary</b>
        <DerivedLabel how={HOW}>Summary · derived</DerivedLabel>
        <span className="ah-grow" />
        <Button
          size="sm"
          variant="ghost"
          icon={collapsed ? "chevron-down" : "chevron-up"}
          onClick={toggle}
          aria-expanded={!collapsed}
        >
          {collapsed ? `Show ${String(Math.max(0, lines.length - 1))} more` : "Collapse"}
        </Button>
      </div>
      {summary.isPending && <Skeleton lines={3} />}
      {summary.error && (
        <ProblemError
          compact
          title="Could not load the summary"
          detail={summary.error.detail}
          onRetry={() => {
            void summary.refetch();
          }}
        />
      )}
      {summary.data && (
        <ol
          style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 3 }}
        >
          {(collapsed ? lines.slice(0, 1) : lines).map((line) => (
            <li key={line.event_id} className="ah-small" style={{ lineHeight: "20px" }}>
              {line.text}{" "}
              <a
                href={`?event=${encodeURIComponent(line.event_id)}`}
                className="ah-mono"
                style={{ fontSize: 12 }}
                onClick={(event) => {
                  event.preventDefault();
                  onJump(line.event_id);
                }}
              >
                → {timeOf(line.event_id) ?? "moment"}
              </a>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
