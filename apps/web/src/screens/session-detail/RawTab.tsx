import { useMemo, useState } from "react";

import { DataTable, EmptyState, JsonViewer, SegmentedControl, StatusBadge } from "../../components";
import { fmtInt } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import type { ApiEvent } from "./timeline";

function stamp(iso: string | null, utc: boolean): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (utc) return date.toISOString().slice(11, 23);
  const pad = (n: number, size = 2) => String(n).padStart(size, "0");
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}.${pad(date.getMilliseconds(), 3)}`;
}

function middle(text: string, max = 48): string {
  if (text.length <= max) return text;
  const keep = Math.floor((max - 1) / 2);
  return `${text.slice(0, keep)}…${text.slice(-keep)}`;
}

export interface RawTabProps {
  events: ApiEvent[];
  timelineRows: number;
}

/** Every stored event, redacted, with its source, ids, arrival and conflicts (spec 10, "Raw events"). */
export function RawTab({ events, timelineRows }: RawTabProps) {
  const { tz } = usePreferences();
  const [order, setOrder] = useState<"timestamp" | "received_at">("timestamp");
  const [open, setOpen] = useState<string | null>(null);
  const rows = useMemo(() => {
    const key = (event: ApiEvent) =>
      order === "timestamp" ? event.timestamp : (event.received_at ?? "");
    return [...events].sort((a, b) =>
      key(a) === key(b) ? a.seq - b.seq : key(a) < key(b) ? -1 : 1,
    );
  }, [events, order]);
  if (events.length === 0) {
    return (
      <EmptyState icon="braces" title="No events">
        Nothing has been recorded for this session.
      </EmptyState>
    );
  }
  const chosen = rows.find((event) => event.event_id === open);
  return (
    <div className="ah-stack" style={{ gap: 12 }}>
      <div className="ah-row ah-wrap" style={{ gap: 12 }}>
        <span className="ah-small ah-muted">
          {fmtInt(events.length)} events · {fmtInt(timelineRows)} timeline rows (results fold into
          their calls; copies of one fact from several sources merge)
        </span>
        <span className="ah-grow" />
        <SegmentedControl
          label="Sort by"
          value={order}
          onChange={(id) => {
            setOrder(id === "received_at" ? "received_at" : "timestamp");
          }}
          options={[
            { id: "timestamp", label: "Event time" },
            { id: "received_at", label: "Received" },
          ]}
        />
      </div>
      <DataTable
        caption="Raw events"
        density="compact"
        maxHeight={560}
        rows={rows}
        rowKey={(event) => event.event_id}
        onRowClick={(event) => {
          setOpen(open === event.event_id ? null : event.event_id);
        }}
        columns={[
          {
            id: "time",
            label: "Timestamp",
            render: (event) => (
              <span className="ah-mono">{stamp(event.timestamp, tz === "utc")}</span>
            ),
          },
          {
            id: "type",
            label: "Type",
            render: (event) => <span className="ah-mono">{event.type}</span>,
          },
          { id: "source", label: "Source", render: (event) => event.source },
          {
            id: "source_id",
            label: "Source id",
            render: (event) => (
              <span className="ah-mono ah-small" title={event.source_id}>
                {middle(event.source_id)}
              </span>
            ),
          },
          {
            id: "lane",
            label: "Lane",
            render: (event) => <span className="ah-mono ah-small">{event.agent ?? "main"}</span>,
          },
          {
            id: "received",
            label: "Received",
            render: (event) => (
              <span className="ah-mono ah-small">{stamp(event.received_at, tz === "utc")}</span>
            ),
          },
          {
            id: "latency",
            label: "Latency",
            align: "right",
            hint: "Time from the event to its arrival in agent-hub",
            render: (event) =>
              event.latency_ms === null ? "—" : `${(event.latency_ms / 1000).toFixed(2)} s`,
          },
          {
            id: "merged",
            label: "Sources",
            render: (event) =>
              event.merged_sources.length > 1 ? event.merged_sources.join(" + ") : "",
          },
          {
            id: "conflict",
            label: "Conflict",
            render: (event) =>
              event.conflict ? (
                <StatusBadge
                  status="stale"
                  label="conflict"
                  title="Another source's copy of this fact won"
                />
              ) : null,
          },
        ]}
      />
      {chosen && (
        <div className="ah-card ah-pad">
          <div className="ah-small ah-subtle" style={{ marginBottom: 6 }}>
            Canonical event, redacted at ingestion ·{" "}
            <span className="ah-mono">{chosen.event_id}</span>
          </div>
          <JsonViewer value={chosen} maxHeight={420} />
        </div>
      )}
    </div>
  );
}
