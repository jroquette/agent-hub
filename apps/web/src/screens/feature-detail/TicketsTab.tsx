import type { ReactNode } from "react";
import { Link } from "react-router";

import type { components } from "../../api/schema";
import { EmptyState, ProblemError, Skeleton } from "../../components";
import type { ApiProblem } from "../../lib/api";
import {
  LinearLink,
  PlanningView,
  ReadinessText,
  StateBadge,
  TicketRef,
  ticketAnchor,
} from "./PlanningView";
import { TicketNotice } from "./TicketNotice";

type FeatureTickets = components["schemas"]["FeatureTickets"];
type TicketRow = components["schemas"]["TicketRow"];
type EdgeSource = components["schemas"]["EdgeSource"];
/** Whether each AC passes, by id. */
type AcPasses = Readonly<Record<string, boolean>>;

const EDGE_TITLE: Record<EdgeSource, string> = {
  plan: "From the plan only",
  linear: "From Linear only",
  both: "In the plan and in Linear",
};

function TicketId({ row }: { row: TicketRow }) {
  if (!row.id) {
    return (
      <span className="ah-stack" style={{ gap: 2 }}>
        <span className="ah-mono">{row.key ?? row.ref}</span>
        <span className="ah-small ah-subtle">not created</span>
      </span>
    );
  }
  return (
    <span className="ah-stack" style={{ gap: 2 }}>
      <LinearLink id={row.id} url={row.url} />
      {row.key && row.key !== row.id && (
        <span className="ah-small ah-subtle ah-mono">{row.key}</span>
      )}
    </span>
  );
}

function Assignee({ row }: { row: TicketRow }) {
  if (row.assignee) return <>{row.assignee}</>;
  if (!row.state) {
    return (
      <span className="ah-subtle" title="Unknown: Linear was not read">
        —<span className="ah-sr">unknown</span>
      </span>
    );
  }
  return <span className="ah-muted">Unassigned</span>;
}

function Blockers({ row, data }: { row: TicketRow; data: FeatureTickets }) {
  if (row.blocked_by.length === 0) return <span className="ah-subtle">—</span>;
  return (
    <span className="ah-row ah-wrap" style={{ gap: 6 }}>
      {row.blocked_by.map((edge) => (
        <TicketRef
          key={edge.ref}
          id={edge.ref}
          rows={data.tickets}
          external={data.planning.external_blockers}
          label={`Blocked by ${edge.ref}`}
          title={EDGE_TITLE[edge.source]}
        />
      ))}
    </span>
  );
}

/** How many of the ticket's ACs pass, with the ids one click away (a long list stays folded). */
function Acs({ row, acPasses }: { row: TicketRow; acPasses?: AcPasses | undefined }) {
  if (row.acs.length === 0) return <span className="ah-subtle">—</span>;
  const passing = acPasses ? row.acs.filter((ac) => acPasses[ac]).length : null;
  const links = (
    <span className="ah-row ah-wrap" style={{ gap: 6 }}>
      {row.acs.map((ac) => (
        <Link
          key={ac}
          className="ah-mono ah-small"
          to={{ search: `?ac=${encodeURIComponent(ac)}` }}
          title={`Open ${ac} in Criteria${acPasses ? (acPasses[ac] ? " · passing" : " · not passing yet") : ""}`}
          style={acPasses && !acPasses[ac] ? { color: "var(--waiting)" } : undefined}
        >
          {ac}
        </Link>
      ))}
    </span>
  );
  if (row.acs.length <= 3) return links;
  return (
    <details>
      <summary className="ah-small" style={{ cursor: "pointer" }}>
        {passing === null
          ? `${String(row.acs.length)} ACs`
          : `${String(passing)}/${String(row.acs.length)} passing`}
      </summary>
      <div style={{ paddingTop: 4 }}>{links}</div>
    </details>
  );
}

function TicketsTable({
  data,
  acPasses,
}: {
  data: FeatureTickets;
  acPasses?: AcPasses | undefined;
}) {
  const columns: { label: string; width?: number; cell: (row: TicketRow) => ReactNode }[] = [
    { label: "Ticket", width: 110, cell: (row) => <TicketId row={row} /> },
    { label: "Title", cell: (row) => row.title ?? <span className="ah-subtle">—</span> },
    { label: "Status", width: 130, cell: (row) => <StateBadge row={row} /> },
    { label: "Assignee", width: 130, cell: (row) => <Assignee row={row} /> },
    { label: "Blocked by", width: 150, cell: (row) => <Blockers row={row} data={data} /> },
    { label: "ACs", width: 150, cell: (row) => <Acs row={row} acPasses={acPasses} /> },
    {
      label: "Readiness",
      width: 190,
      cell: (row) => (
        <ReadinessText row={row} rows={data.tickets} external={data.planning.external_blockers} />
      ),
    },
  ];
  return (
    <div className="ah-table-wrap">
      <table className="ah-table" aria-label="Tickets">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.label} scope="col" style={c.width ? { width: c.width } : undefined}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.tickets.map((row) => (
            <tr key={row.ref} id={ticketAnchor(row.ref)} style={{ cursor: "default" }}>
              {columns.map((c) => (
                <td key={c.label} style={{ whiteSpace: "normal" }}>
                  {c.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="ah-table-foot">
        <span>
          {data.tickets.length} ticket{data.tickets.length === 1 ? "" : "s"} ·{" "}
          {data.source === "linear"
            ? "status, assignee and links from Linear; blockers from the plan and Linear"
            : "from the plan (features.json)"}
        </span>
      </div>
    </div>
  );
}

function Loading() {
  return (
    <div className="ah-stack" aria-busy="true">
      <Skeleton width={360} height={20} />
      {Array.from({ length: 6 }, (_, i) => (
        <Skeleton key={i} height={28} />
      ))}
    </div>
  );
}

export interface TicketsTabProps {
  /** The `GET .../tickets` answer; undefined while it loads. */
  data: FeatureTickets | undefined;
  /** The route's failure, shown with a retry. */
  error?: ApiProblem | null | undefined;
  /** Refetches the tickets route (Refresh and retry). */
  onRefresh: () => void;
  refreshing?: boolean | undefined;
  /** Whether each AC passes (by id), from the feature record; shows each ticket's progress. */
  acPasses?: AcPasses | undefined;
}

/**
 * The Tickets tab (AC-136.28): where the data comes from, the flow of the tickets (what runs in
 * parallel, in which order, and where each one is now), then one row per ticket (Linear link,
 * title, status, assignee, blockers, ACs, readiness).
 */
export function TicketsTab({ data, error, onRefresh, refreshing, acPasses }: TicketsTabProps) {
  if (error) {
    return (
      <ProblemError
        title={error.title}
        detail={error.detail ?? undefined}
        status={error.status}
        onRetry={onRefresh}
      />
    );
  }
  if (!data) return <Loading />;
  return (
    <div className="ah-stack" style={{ gap: 12 }}>
      <TicketNotice tickets={data} onRefresh={onRefresh} refreshing={refreshing} />
      {data.tickets.length === 0 ? (
        <div className="ah-card">
          <EmptyState icon="list-todo" title="No tickets for this feature yet.">
            Tickets are planned by <span className="ah-mono">/create-plan</span> in features.json
            and created in Linear by <span className="ah-mono">/feature</span>.
          </EmptyState>
        </div>
      ) : (
        <>
          <PlanningView tickets={data.tickets} planning={data.planning} acPasses={acPasses} />
          <TicketsTable data={data} acPasses={acPasses} />
        </>
      )}
    </div>
  );
}
