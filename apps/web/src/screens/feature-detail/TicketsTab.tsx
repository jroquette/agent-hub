import type { ReactNode } from "react";
import { Link } from "react-router";

import type { components } from "../../api/schema";
import { EmptyState, ProblemError, Skeleton, StatusBadge } from "../../components";
import { useApi, type ApiProblem } from "../../lib/api";
import { fmtClock, fmtDateTime, fmtMoney } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { badgeOf } from "../sessions-list/badge";
import { rowHref } from "../sessions-list/drivenRows";
import type { Session } from "../sessions-list/queries";
import {
  AcMeter,
  PlanningView,
  ReadinessText,
  StateBadge,
  TicketIdLine,
  TicketRef,
  splitTitle,
  ticketAnchor,
  type TicketAction,
} from "./PlanningView";
import { StartTicketButton, canStartTicket } from "./StartTicket";
import { TICKETS_REFRESH_MS } from "./queries";
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
  return <TicketIdLine row={row} />;
}

/** The conventional prefix of the title (`feat(brand-api)`) as a chip in its own column. */
function ScopeCell({ row }: { row: TicketRow }) {
  const { type, scope } = splitTitle(row.title ?? "");
  if (!type) return <span className="ah-subtle">—</span>;
  return (
    <span className="ah-ticket-scope" title={`${type}${scope ? `(${scope})` : ""}`}>
      {scope ?? type}
    </span>
  );
}

/** The words of the title, the epic tag before them and a branch mark on an epic's child. */
function TitleCell({ row, child }: { row: TicketRow; child: boolean }) {
  const text = row.title ? splitTitle(row.title).text : null;
  return (
    <span className="ah-ticket-title" data-child={child || undefined}>
      {child && (
        <span className="ah-ticket-branch" aria-hidden="true">
          └
        </span>
      )}
      {row.children.length > 0 && <span className="ah-flow-epic-tag">Epic</span>}
      <span>{text ?? <span className="ah-subtle">—</span>}</span>
    </span>
  );
}

/** How many sessions one ticket row shows before the rest fold away. */
const SESSIONS_SHOWN = 2;

function SessionLink({ session }: { session: Session }) {
  const { tz } = usePreferences();
  const [status, label] = badgeOf(session);
  const day = new Date(session.started_at).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    ...(tz === "utc" ? { timeZone: "UTC" } : {}),
  });
  const facts = [
    session.label?.title,
    `started ${fmtDateTime(session.started_at, tz)}`,
    `${String(session.turns)} turn${session.turns === 1 ? "" : "s"}`,
    session.cost_usd != null ? fmtMoney(session.cost_usd) : null,
  ].filter(Boolean);
  return (
    <Link
      className="ah-ticket-session"
      to={rowHref(session)}
      title={`Open the session: ${facts.join(" · ")}`}
    >
      <StatusBadge status={status} label={label} quiet />
      <span className="ah-small">
        {day}, {fmtClock(session.started_at, tz)}
      </span>
    </Link>
  );
}

/** The sessions whose branch or run names this ticket, newest first, each one click from its dialogue. */
function TicketSessions({ row, project }: { row: TicketRow; project: string }) {
  const sessions = useApi(
    "/api/v1/sessions",
    { query: { project, issue: row.id ?? "", limit: 20 } },
    { enabled: row.id != null, refetchInterval: TICKETS_REFRESH_MS },
  );
  if (!row.id) return <span className="ah-subtle">—</span>;
  if (sessions.isPending) return <Skeleton width={90} height={18} />;
  if (sessions.isError) {
    return (
      <span className="ah-subtle" title={sessions.error.title}>
        —<span className="ah-sr">sessions not read</span>
      </span>
    );
  }
  const items = sessions.data.items;
  if (items.length === 0) {
    return (
      <span className="ah-small ah-subtle" title={`No session's branch or run names ${row.id}`}>
        none
      </span>
    );
  }
  const links = (list: readonly Session[]) => (
    <span className="ah-stack" style={{ gap: 4 }}>
      {list.map((session) => (
        <SessionLink key={session.id} session={session} />
      ))}
    </span>
  );
  if (items.length <= SESSIONS_SHOWN) return links(items);
  const more = sessions.data.next_cursor ? "+" : "";
  return (
    <span className="ah-stack" style={{ gap: 4 }}>
      {links(items.slice(0, SESSIONS_SHOWN))}
      <details>
        <summary className="ah-small" style={{ cursor: "pointer", whiteSpace: "nowrap" }}>
          {items.length - SESSIONS_SHOWN}
          {more} more
        </summary>
        <div style={{ paddingTop: 4 }}>{links(items.slice(SESSIONS_SHOWN))}</div>
      </details>
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
      <summary className="ah-small" style={{ cursor: "pointer", whiteSpace: "nowrap" }}>
        {passing === null ? (
          `${String(row.acs.length)} ACs`
        ) : (
          <AcMeter
            passing={passing}
            total={row.acs.length}
            label={`${String(passing)}/${String(row.acs.length)} passing`}
          />
        )}
      </summary>
      <div style={{ paddingTop: 4 }}>{links}</div>
    </details>
  );
}

/** The rows with each epic first and its children right under it, then the other tickets. */
function epicOrder(tickets: readonly TicketRow[]): TicketRow[] {
  const byRef = new Map(tickets.map((t) => [t.ref, t]));
  const placed = new Set<string>();
  const ordered: TicketRow[] = [];
  for (const epic of tickets.filter((t) => t.children.length > 0)) {
    for (const row of [epic, ...epic.children.flatMap((ref) => byRef.get(ref) ?? [])]) {
      if (!placed.has(row.ref)) {
        placed.add(row.ref);
        ordered.push(row);
      }
    }
  }
  return [...ordered, ...tickets.filter((t) => !placed.has(t.ref))];
}

function TicketsTable({
  data,
  project,
  acPasses,
  ticketAction,
}: {
  data: FeatureTickets;
  project: string;
  acPasses?: AcPasses | undefined;
  ticketAction?: TicketAction | undefined;
}) {
  const byRef = new Set(data.tickets.map((t) => t.ref));
  const isChild = (row: TicketRow) => row.parent != null && byRef.has(row.parent);
  const columns: {
    label: string;
    width?: number;
    nowrap?: boolean;
    className?: string;
    cell: (row: TicketRow) => ReactNode;
  }[] = [
    { label: "Ticket", width: 110, nowrap: true, cell: (row) => <TicketId row={row} /> },
    { label: "Scope", width: 90, nowrap: true, cell: (row) => <ScopeCell row={row} /> },
    {
      label: "Title",
      className: "ah-ticket-title-col",
      cell: (row) => <TitleCell row={row} child={isChild(row)} />,
    },
    { label: "Status", width: 110, nowrap: true, cell: (row) => <StateBadge row={row} /> },
    { label: "Assignee", width: 110, cell: (row) => <Assignee row={row} /> },
    { label: "Blocked by", width: 110, cell: (row) => <Blockers row={row} data={data} /> },
    { label: "ACs", width: 120, cell: (row) => <Acs row={row} acPasses={acPasses} /> },
    {
      label: "Sessions",
      width: 150,
      nowrap: true,
      cell: (row) => <TicketSessions row={row} project={project} />,
    },
    {
      label: "Readiness",
      width: 180,
      cell: (row) => (
        <span className="ah-row ah-wrap" style={{ gap: 8 }}>
          <ReadinessText row={row} rows={data.tickets} external={data.planning.external_blockers} />
          {ticketAction?.(row)}
        </span>
      ),
    },
  ];
  return (
    <div className="ah-table-wrap">
      <table className="ah-table ah-ticket-table" aria-label="Tickets">
        <thead>
          <tr>
            {columns.map((c) => (
              <th
                key={c.label}
                scope="col"
                className={c.className}
                style={c.width ? { width: c.width } : undefined}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {epicOrder(data.tickets).map((row) => (
            <tr
              key={row.ref}
              id={ticketAnchor(row.ref)}
              style={{ cursor: "default" }}
              data-epic={row.children.length > 0 || undefined}
              data-child={isChild(row) || undefined}
            >
              {columns.map((c) => (
                <td
                  key={c.label}
                  className={
                    [c.nowrap && "ah-nowrap", c.className].filter(Boolean).join(" ") || undefined
                  }
                >
                  {c.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="ah-table-foot">
        <span>
          {data.tickets.length} ticket{data.tickets.length === 1 ? "" : "s"}
          {data.planning.epics.length > 0 &&
            ` (${String(data.planning.epics.length)} epic${data.planning.epics.length === 1 ? "" : "s"})`}{" "}
          ·{" "}
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
  /** The feature's project: its sessions are looked up there. */
  project: string;
  /** The feature's slug: a ticket's session reads the record under `brain/features/<slug>/`. */
  slug: string;
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
 * scope, title, status, assignee, blockers, ACs, the sessions that worked on it, readiness).
 */
export function TicketsTab({
  project,
  slug,
  data,
  error,
  onRefresh,
  refreshing,
  acPasses,
}: TicketsTabProps) {
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
  const ticketAction: TicketAction = (row) =>
    canStartTicket(row) ? (
      <StartTicketButton project={project} slug={slug} row={row} rows={data.tickets} />
    ) : null;
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
          <PlanningView
            tickets={data.tickets}
            planning={data.planning}
            acPasses={acPasses}
            ticketAction={ticketAction}
          />
          <TicketsTable
            data={data}
            project={project}
            acPasses={acPasses}
            ticketAction={ticketAction}
          />
        </>
      )}
    </div>
  );
}
