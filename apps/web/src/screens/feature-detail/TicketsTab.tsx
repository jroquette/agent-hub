import { useEffect, useId, useRef, useState, type MutableRefObject, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import type { components } from "../../api/schema";
import {
  EmptyState,
  Icon,
  ProblemError,
  SegmentedControl,
  Skeleton,
  StatusBadge,
  Tooltip,
} from "../../components";
import { goSequencePending, typingIn } from "../../shell/goSequence";
import { useApi, type ApiProblem } from "../../lib/api";
import { fmtClock, fmtDateTime, fmtMoney } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { badgeOf } from "../sessions-list/badge";
import { rowHref } from "../sessions-list/drivenRows";
import type { Session } from "../sessions-list/queries";
import {
  AcCount,
  PlanningView,
  ReadinessText,
  TicketSignal,
  signalKind,
  StateBadge,
  TicketIdLine,
  TicketPrLink,
  TicketRef,
  TicketStepBar,
  splitTitle,
  ticketAnchor,
  TicketOpenLink,
  ticketParam,
  ticketSearch,
  ticketStepLine,
  type TicketAction,
  type TicketOpener,
} from "./PlanningView";
import { PASS, gwtParts, passOf } from "./CriteriaTab";
import { StartTicketButton, canStartTicket } from "./StartTicket";
import { TICKETS_REFRESH_MS } from "./queries";
import { TicketNotice } from "./TicketNotice";
import { TicketPanel } from "./TicketPanel";

type FeatureTickets = components["schemas"]["FeatureTickets"];
type TicketRow = components["schemas"]["TicketRow"];
type EdgeSource = components["schemas"]["EdgeSource"];
type AcRow = components["schemas"]["AcRow"];
type EvalRecord = components["schemas"]["EvalRecord"];
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

/** The ticket's pull request (`PR #69`), else a dash with the reason in its tooltip. */
function PrCell({ row }: { row: TicketRow }) {
  if (row.pr_url) return <TicketPrLink row={row} />;
  if (!row.id) return <span className="ah-subtle">—</span>;
  return (
    <span
      className="ah-subtle"
      title={
        row.reviewed === true
          ? "The review record names no pull request on GitHub (still pending, or a repo outside this hub)."
          : "No pull request yet: /feature records it in the ticket's review once both reviewers pass."
      }
    >
      —
    </span>
  );
}

/** The words of the title, the epic tag before them and a branch mark on an epic's child. */
function TitleCell({
  row,
  child,
  onOpen,
}: {
  row: TicketRow;
  child: boolean;
  /** Given, a ticket's title opens its panel, as its card's does (AC-1.10). */
  onOpen?: TicketOpener | undefined;
}) {
  const text = row.title ? splitTitle(row.title).text : null;
  return (
    <span className="ah-ticket-title" data-child={child || undefined}>
      {child && (
        <span className="ah-ticket-branch" aria-hidden="true">
          └
        </span>
      )}
      {row.children.length > 0 && <span className="ah-flow-epic-tag">Epic</span>}
      {text && onOpen && row.children.length === 0 ? (
        <TicketOpenLink row={row} onOpen={onOpen}>
          {text}
        </TicketOpenLink>
      ) : (
        <span>{text ?? <span className="ah-subtle">—</span>}</span>
      )}
    </span>
  );
}

/** How many sessions one ticket row shows before the rest fold away. */
const SESSIONS_SHOWN = 2;

function SessionLink({
  session,
  context,
}: {
  session: Session;
  /** What the link is to the reader ("Newest session"), leading its accessible name. */
  context?: string | undefined;
}) {
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
      aria-label={
        context
          ? `${context}: ${label}, started ${day}, ${fmtClock(session.started_at, tz)}`
          : undefined
      }
    >
      <StatusBadge status={status} label={label} quiet />
      <span className="ah-small">
        {day}, {fmtClock(session.started_at, tz)}
      </span>
    </Link>
  );
}

/** The sessions whose branch, worktree, run or first prompt names the ticket, newest first. */
function useTicketSessions(project: string, row: TicketRow) {
  return useApi(
    "/api/v1/sessions",
    { query: { project, issue: row.id ?? "", limit: 20 } },
    { enabled: row.id != null, refetchInterval: TICKETS_REFRESH_MS },
  );
}

/**
 * What a ticket's card offers next to its readiness: its newest session, one click from its
 * dialogue, and Start while the ticket is free to pick up and no session of it is still open.
 */
function CardAction({
  project,
  slug,
  row,
  rows,
}: {
  project: string;
  slug: string;
  row: TicketRow;
  rows: readonly TicketRow[];
}) {
  const sessions = useTicketSessions(project, row);
  const newest = sessions.data?.items[0];
  const open = newest != null && newest.status !== "ended";
  const start = canStartTicket(row, rows) && !open && (
    <StartTicketButton project={project} slug={slug} row={row} rows={rows} />
  );
  if (!newest) return start ? <span className="ah-flow-card-action">{start}</span> : null;
  return (
    <span className="ah-flow-card-action">
      <span className="ah-flow-card-fact">
        <Icon name="square-terminal" size="sm" />
        Session
      </span>
      <SessionLink session={newest} context="Newest session" />
      {start}
    </span>
  );
}

/** The sessions whose branch or run names this ticket, newest first, each one click from its dialogue. */
export function TicketSessions({ row, project }: { row: TicketRow; project: string }) {
  const sessions = useTicketSessions(project, row);
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

/**
 * One AC id, linking to it in Criteria. Hover or focus shows what must be true (the "Then" of a
 * Given / When / Then, else the whole text) for a quick check; its status is the icon.
 */
function AcLink({
  id,
  row,
  passes,
}: {
  id: string;
  row?: AcRow | undefined;
  passes?: boolean | undefined;
}) {
  const tipId = useId();
  const pass = row
    ? PASS[passOf(row)]
    : passes === undefined
      ? null
      : PASS[passes ? "yes" : "none"];
  const summary = row ? (gwtParts(row.description)?.then ?? row.description) : null;
  return (
    <Tooltip id={tipId} label={summary && <span className="ah-ticket-ac-tip">{summary}</span>}>
      <Link
        className="ah-row ah-mono ah-small"
        style={{ gap: 4 }}
        to={{ search: `?doc=acs&ac=${encodeURIComponent(id)}` }}
        aria-describedby={summary ? tipId : undefined}
      >
        {pass && <Icon name={pass.icon} size="sm" />}
        {id}
        {pass && <span className="ah-sr"> {pass.label}</span>}
      </Link>
    </Tooltip>
  );
}

/**
 * How many of a list of ACs pass, the same meter as a ticket's card; the ids fold under it. The
 * Tickets table shows a ticket's ACs with it, the Eval table an eval's.
 */
export function AcList({
  ids,
  acPasses,
  acRows,
}: {
  ids: readonly string[];
  acPasses?: AcPasses | undefined;
  acRows?: ReadonlyMap<string, AcRow> | undefined;
}) {
  if (ids.length === 0) return <span className="ah-subtle">—</span>;
  return (
    <details className="ah-ticket-acs">
      <summary className="ah-small">
        <AcCount row={{ acs: ids }} acPasses={acPasses} />
      </summary>
      <ul className="ah-stack">
        {ids.map((ac) => (
          <li key={ac}>
            <AcLink id={ac} row={acRows?.get(ac)} passes={acPasses?.[ac]} />
          </li>
        ))}
      </ul>
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

/** The epic's Stage: an epic has no steps of its own, said in a tooltip a keyboard reaches. */
function EpicStage() {
  const tipId = useId();
  return (
    <Tooltip id={tipId} label="An epic has no steps of its own; each of its tickets has seven.">
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- the tooltip's trigger */}
      <span className="ah-subtle" tabIndex={0} aria-describedby={tipId}>
        —
      </span>
    </Tooltip>
  );
}

/** Keys that never open or move a row: they belong to the link or button inside it. */
const INSIDE_CONTROL = "a, button, summary, input, select, textarea";

function TicketsTable({
  data,
  project,
  acPasses,
  acRows,
  ticketAction,
  onOpen,
  onOpenTicket,
}: {
  data: FeatureTickets;
  project: string;
  acPasses?: AcPasses | undefined;
  acRows?: ReadonlyMap<string, AcRow> | undefined;
  ticketAction?: TicketAction | undefined;
  /** Opens a row's ticket panel (Enter, o or a click on the row). */
  onOpen: (row: TicketRow, opener: HTMLElement) => void;
  /** Records the opener when a row's title link opens the panel. */
  onOpenTicket: TicketOpener;
}) {
  const byRef = new Set(data.tickets.map((t) => t.ref));
  const isChild = (row: TicketRow) => row.parent != null && byRef.has(row.parent);
  // The table body is one tab stop (roving tabindex): j / k and the arrows move between tickets.
  const ordered = epicOrder(data.tickets);
  const nav = ordered.filter((row) => row.children.length === 0).map((row) => row.ref);
  const [active, setActive] = useState<string | null>(null);
  const current = active !== null && nav.includes(active) ? active : nav[0];
  // `hide`: hidden first at 1280 (laptop), and all but the first four while the panel docks
  // (31-responsive.md, column priority).
  const columns: {
    label: string;
    width?: number;
    nowrap?: boolean;
    className?: string;
    hide?: "laptop" | "docked";
    cell: (row: TicketRow) => ReactNode;
  }[] = [
    { label: "Ticket", width: 110, nowrap: true, cell: (row) => <TicketId row={row} /> },
    {
      label: "Title",
      className: "ah-ticket-title-col",
      cell: (row) => <TitleCell row={row} child={isChild(row)} onOpen={onOpenTicket} />,
    },
    {
      label: "Stage",
      width: 130,
      cell: (row) =>
        row.flow ? (
          <TicketStepBar flow={row.flow} />
        ) : row.children.length > 0 ? (
          <EpicStage />
        ) : (
          <span className="ah-subtle">—</span>
        ),
    },
    {
      label: "Status",
      width: 110,
      nowrap: true,
      hide: "docked",
      cell: (row) => <StateBadge row={row} />,
    },
    { label: "Assignee", width: 110, hide: "laptop", cell: (row) => <Assignee row={row} /> },
    {
      label: "Blocked by",
      width: 110,
      hide: "docked",
      cell: (row) => <Blockers row={row} data={data} />,
    },
    {
      label: "ACs",
      width: 150,
      hide: "docked",
      cell: (row) => <AcList ids={row.acs} acPasses={acPasses} acRows={acRows} />,
    },
    {
      label: "Sessions",
      width: 150,
      nowrap: true,
      hide: "laptop",
      cell: (row) => <TicketSessions row={row} project={project} />,
    },
    {
      label: "Readiness",
      width: 180,
      cell: (row) => {
        // A plan change's wait, a hold or a re-run replaces readiness; local drift joins it (A13).
        const signal = row.flow ? signalKind(row.flow) : null;
        return (
          <span className="ah-row ah-wrap" style={{ gap: 8 }}>
            {signal !== null && signal !== "local" && row.flow ? (
              <TicketSignal flow={row.flow} />
            ) : (
              <ReadinessText
                row={row}
                rows={data.tickets}
                external={data.planning.external_blockers}
              />
            )}
            {ticketAction?.(row)}
            {signal === "local" && row.flow && <TicketSignal flow={row.flow} />}
          </span>
        );
      },
    },
    {
      label: "PR",
      width: 100,
      nowrap: true,
      hide: "docked",
      cell: (row) => <PrCell row={row} />,
    },
  ];
  const move = (from: string, by: number) => {
    const next = nav[nav.indexOf(from) + by];
    if (next === undefined) return;
    setActive(next);
    document.getElementById(ticketAnchor(next))?.focus();
  };
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
                data-hide={c.hide}
                style={c.width ? { width: c.width } : undefined}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ordered.map((row) => {
            const epic = row.children.length > 0;
            const name = [row.ref, row.title, row.flow && ticketStepLine(row.flow)]
              .filter(Boolean)
              .join(" · ");
            return (
              <tr
                key={row.ref}
                id={ticketAnchor(row.ref)}
                style={{ cursor: epic ? "default" : "pointer" }}
                data-epic={epic || undefined}
                data-child={isChild(row) || undefined}
                data-ticket-open={epic ? undefined : row.ref}
                aria-label={epic ? undefined : name}

                tabIndex={epic ? undefined : row.ref === current ? 0 : -1}
                onFocus={
                  epic
                    ? undefined
                    : (event) => {
                        if (event.target === event.currentTarget) setActive(row.ref);
                      }
                }
                onClick={
                  epic
                    ? undefined
                    : (event) => {
                        if (event.target instanceof Element && event.target.closest(INSIDE_CONTROL))
                          return;
                        onOpen(row, event.currentTarget);
                      }
                }
                onKeyDown={
                  epic
                    ? undefined
                    : (event) => {
                        if (event.target !== event.currentTarget || goSequencePending()) return;
                        if (event.ctrlKey || event.metaKey || event.altKey) return;
                        if (event.key === "j" || event.key === "ArrowDown") move(row.ref, 1);
                        else if (event.key === "k" || event.key === "ArrowUp") move(row.ref, -1);
                        else if (event.key === "Enter" || event.key === "o") {
                          onOpen(row, event.currentTarget);
                        } else return;
                        event.preventDefault();
                      }
                }
              >
                {columns.map((c) => (
                  <td
                    key={c.label}
                    data-hide={c.hide}
                    className={
                      [c.nowrap && "ah-nowrap", c.className].filter(Boolean).join(" ") || undefined
                    }
                  >
                    {c.cell(row)}
                  </td>
                ))}
              </tr>
            );
          })}
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
  /** The feature's ACs, for each AC's text and status (owner step included) in the ids list. */
  acRows?: readonly AcRow[] | undefined;
  /** The feature's evals: the ticket panel's Eval step and owner-steps signal. */
  evals: readonly EvalRecord[];
  /** The element that opened the ticket panel (a card title, a row, a header chip). */
  openerRef: MutableRefObject<HTMLElement | null>;
}

/** The element that opens `ref`'s panel in the view shown: its card title or its row. */
function openerOf(ref: string): HTMLElement | null {
  const holder = document.getElementById(ticketAnchor(ref));
  if (!holder) return null;
  return holder.matches("[data-ticket-open]")
    ? holder
    : holder.querySelector<HTMLElement>("[data-ticket-open]");
}

/**
 * The Tickets tab (AC-136.28, two-level-flows AC-1.11): where the data comes from, then one of two
 * views of the tickets, toggled: the flow (what runs in parallel, in which order, and where each
 * one is now) or the table, one row per ticket (Linear link, title, its steps, status, assignee,
 * blockers, ACs, the sessions that worked on it, readiness).
 */
export function TicketsTab({
  project,
  slug,
  data,
  error,
  onRefresh,
  refreshing,
  acPasses,
  acRows,
  evals,
  openerRef,
}: TicketsTabProps) {
  const acById = acRows && new Map(acRows.map((ac) => [ac.id, ac]));
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const root = useRef<HTMLDivElement>(null);
  // The view is kept in `?tickets=`: `table`, else Flow, the default, with no parameter.
  const view = params.get("tickets") === "table" ? "table" : "flow";
  const ticket = params.get("ticket");
  const setView = (next: string) => {
    setParams(
      (current) => {
        const search = new URLSearchParams(current);
        if (next === "table") search.set("tickets", "table");
        else search.delete("tickets");
        return search;
      },
      { replace: true },
    );
  };
  // `v` toggles the views while focus is in the tab and not in a text field; focus stays on the
  // same ticket (card title <-> row), else goes to the toggle.
  const refocus = useRef<string | null | undefined>(undefined);
  const latest = useRef({ view, setView });
  useEffect(() => {
    latest.current = { view, setView };
  });
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "v" || event.defaultPrevented) return;
      if (event.ctrlKey || event.metaKey || event.altKey || typingIn(event.target)) return;
      if (!(event.target instanceof HTMLElement) || !root.current?.contains(event.target)) return;
      if (!root.current.querySelector(".ah-seg")) return;
      event.preventDefault();
      refocus.current =
        event.target.closest<HTMLElement>("[data-ticket-open]")?.dataset.ticketOpen ?? null;
      latest.current.setView(latest.current.view === "table" ? "flow" : "table");
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, []);
  useEffect(() => {
    if (refocus.current === undefined) return;
    const ref = refocus.current;
    refocus.current = undefined;
    const target =
      (ref === null ? null : openerOf(ref)) ??
      root.current?.querySelector<HTMLElement>(".ah-seg [aria-pressed='true']");
    target?.focus();
  }, [view]);
  const remember: TicketOpener = (element) => {
    openerRef.current = element;
  };
  const openRow = (row: TicketRow, element: HTMLElement) => {
    remember(element);
    void navigate({ search: ticketSearch(params, ticketParam(row)) }, { replace: true });
  };
  const closeTicket = (ref: string | undefined) => {
    // The opener is gone once the view was toggled: the same ticket in this view takes focus.
    if (!openerRef.current?.isConnected) openerRef.current = ref ? openerOf(ref) : null;
    setParams(
      (current) => {
        const search = new URLSearchParams(current);
        search.delete("ticket");
        search.delete("step");
        return search;
      },
      { replace: true },
    );
  };
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
    canStartTicket(row, data.tickets) ? (
      <StartTicketButton project={project} slug={slug} row={row} rows={data.tickets} />
    ) : null;
  const cardAction: TicketAction = (row) => (
    <CardAction project={project} slug={slug} row={row} rows={data.tickets} />
  );
  const shown = ticket
    ? data.tickets.find((r) => r.id === ticket || r.key === ticket || r.ref === ticket)
    : undefined;
  return (
    <div ref={root} className="ah-stack" style={{ gap: 12 }}>
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
          <SegmentedControl
            label="Show the tickets as"
            options={[
              { id: "flow", label: "Flow" },
              { id: "table", label: "Table" },
            ]}
            value={view}
            onChange={setView}
          />
          <div className="ah-ticket-layout">
            <div className="ah-ticket-main">
              {view === "flow" ? (
                <PlanningView
                  tickets={data.tickets}
                  planning={data.planning}
                  acPasses={acPasses}
                  ticketAction={cardAction}
                  onOpenTicket={remember}
                />
              ) : (
                <TicketsTable
                  data={data}
                  project={project}
                  acPasses={acPasses}
                  acRows={acById}
                  ticketAction={ticketAction}
                  onOpen={openRow}
                  onOpenTicket={remember}
                />
              )}
            </div>
            {ticket && (
              <TicketPanel
                project={project}
                slug={slug}
                data={data}
                ticket={ticket}
                row={shown}
                evals={evals}
                acPasses={acPasses}
                acRows={acById}
                openerRef={openerRef}
                onOpen={remember}
                onClose={() => {
                  closeTicket(shown?.ref);
                }}
              />
            )}
          </div>
        </>
      )}
    </div>
  );
}
