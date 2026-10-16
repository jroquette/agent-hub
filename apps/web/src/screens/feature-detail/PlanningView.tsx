import "./ticket-flow.css";

import { Fragment } from "react";
import type { ReactNode } from "react";

import type { components } from "../../api/schema";
import { Banner, Icon, StatusBadge, type Status } from "../../components";
import { linearHref } from "../../lib/safeHref";

type TicketRow = components["schemas"]["TicketRow"];
type TicketPlan = components["schemas"]["TicketPlan"];
type ExternalBlocker = components["schemas"]["ExternalBlocker"];
type IssueStateType = components["schemas"]["IssueStateType"];
type Readiness = components["schemas"]["Readiness"];

/** The badge tone of a Linear state type; the badge text is always the state's own name. */
const STATE_STATUS: Record<IssueStateType, Status> = {
  triage: "queued",
  backlog: "queued",
  unstarted: "queued",
  started: "running",
  completed: "done",
  canceled: "stopped",
  duplicate: "stopped",
};

/** A ticket's status in Linear, named as Linear names it ("In Review"); Unknown when not read. */
export function StateBadge({ row }: { row: TicketRow }) {
  if (!row.state) {
    return (
      <StatusBadge
        status="idle"
        quiet
        label="Unknown"
        title="No status: Linear was not read for this ticket"
      />
    );
  }
  return (
    <StatusBadge
      status={STATE_STATUS[row.state.type]}
      label={row.state.name}
      title={`${row.state.name} (${row.state.type})`}
    />
  );
}

/** What each readiness means, for the legend and the tooltips. */
export const READINESS_HELP: Record<Readiness, string> = {
  can_start: "Not started in Linear and every blocker is done: pick it up now.",
  in_progress: "Started in Linear (In Progress, In Review…): someone is on it.",
  waiting: "Not started yet; a blocker is not done.",
  done: "Completed in Linear.",
  canceled: "Canceled or a duplicate in Linear: it blocks nothing.",
  in_cycle: "Waits on a ticket that waits on it back: break the cycle.",
  epic: "The epic: it tracks its child tickets and is never worked on itself; it closes when they are done.",
  unknown: "Linear was not read, so its status is unknown.",
};

/** A ticket's readiness in words: what to do with it now. */
export function ReadinessText({
  row,
  rows,
  external,
}: {
  row: TicketRow;
  rows: readonly TicketRow[];
  external: readonly ExternalBlocker[];
}) {
  const refs = (list: readonly string[]) => <RefList refs={list} rows={rows} external={external} />;
  const help = READINESS_HELP[row.readiness];
  switch (row.readiness) {
    case "can_start":
      return (
        <b style={{ fontWeight: 500, color: "var(--done)" }} title={help}>
          Can start now
        </b>
      );
    case "in_progress":
      return (
        <span className="ah-stack" style={{ gap: 2 }} title={help}>
          <b style={{ fontWeight: 500, color: "var(--live)" }}>
            {row.reviewed ? "Reviewed · waiting for Done" : "In progress"}
          </b>
          {row.waiting_on.length > 0 && (
            <span className="ah-small ah-subtle">
              started before {refs(row.waiting_on)} was done
            </span>
          )}
        </span>
      );
    case "done":
      return (
        <b style={{ fontWeight: 500 }} title={help}>
          Done
        </b>
      );
    case "canceled":
      return (
        <b style={{ fontWeight: 500 }} title={help}>
          Canceled
        </b>
      );
    case "in_cycle":
      return (
        <b style={{ fontWeight: 500, color: "var(--failed)" }} title={help}>
          Waiting: cycle
        </b>
      );
    case "epic": {
      const done = rows.filter((r) => row.children.includes(r.ref) && r.readiness === "done");
      return (
        <span className="ah-muted" title={help}>
          Epic · {done.length}/{row.children.length} done
        </span>
      );
    }
    case "waiting":
      return (
        <span title={help} style={{ color: "var(--waiting)" }}>
          Waiting on {refs(row.waiting_on)}
        </span>
      );
    default:
      return (
        <span className="ah-muted" title={help}>
          Unknown
        </span>
      );
  }
}

/** The element id of a ticket's row, the target of every in-page ticket link. */
export function ticketAnchor(ref: string): string {
  return `ticket-${ref.replace(/[^A-Za-z0-9_-]/g, "-")}`;
}

/** A link that opens a Linear issue in a new tab (AC-136.29); plain text when the url is unsafe. */
export function LinearLink({
  id,
  url,
  label,
  title,
}: {
  id: string;
  url: string | null;
  label?: string | undefined;
  title?: string | undefined;
}) {
  const href = linearHref(url);
  if (href === null) {
    return (
      <span className="ah-issue" title={title ?? `${id} · no Linear link`}>
        {id}
      </span>
    );
  }
  return (
    <a
      className="ah-issue"
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={label}
      title={title ?? `${id} · opens in Linear`}
    >
      {id}
      <Icon name="arrow-up-right" />
      {!label && <span className="ah-sr"> (opens in Linear in a new tab)</span>}
    </a>
  );
}

/**
 * A ticket named by `ref`: an in-page link to its row when it is one of the feature's tickets, a
 * Linear link when it is an external blocker with a safe url, else plain text.
 */
export function TicketRef({
  id,
  rows,
  external,
  label,
  title,
}: {
  id: string;
  rows: readonly TicketRow[];
  external: readonly ExternalBlocker[];
  label?: string | undefined;
  title?: string | undefined;
}) {
  const row = rows.find((r) => r.ref === id);
  if (row) {
    return (
      <a
        className="ah-mono"
        href={`#${ticketAnchor(id)}`}
        aria-label={label}
        title={title ?? row.title ?? undefined}
      >
        {id}
      </a>
    );
  }
  const outside = external.find((b) => b.id === id);
  if (outside) {
    return (
      <LinearLink
        id={id}
        url={outside.url}
        label={label}
        title={title ?? `${id}${outside.title ? ` · ${outside.title}` : ""} · outside this feature`}
      />
    );
  }
  return <span className="ah-mono">{id}</span>;
}

function RefList({
  refs,
  rows,
  external,
  separator = ", ",
}: {
  refs: readonly string[];
  rows: readonly TicketRow[];
  external: readonly ExternalBlocker[];
  separator?: ReactNode;
}) {
  return (
    <>
      {refs.map((ref, i) => (
        <Fragment key={ref}>
          {i > 0 && separator}
          <TicketRef id={ref} rows={rows} external={external} />
        </Fragment>
      ))}
    </>
  );
}

/** The readiness counts shown above the flow, in the order a reader acts on them. */
const COUNTED: readonly { readiness: Readiness; label: string }[] = [
  { readiness: "can_start", label: "can start" },
  { readiness: "in_progress", label: "in progress" },
  { readiness: "waiting", label: "waiting" },
  { readiness: "in_cycle", label: "in a cycle" },
  { readiness: "done", label: "done" },
  { readiness: "canceled", label: "canceled" },
];

/** How many tickets are in each readiness: the feature's work at a glance. */
export function ReadinessSummary({ tickets }: { tickets: readonly TicketRow[] }) {
  const counts = COUNTED.map((c) => ({
    ...c,
    n: tickets.filter((t) => t.readiness === c.readiness).length,
  })).filter((c) => c.n > 0);
  if (counts.length === 0) return null;
  return (
    <div className="ah-flow-summary" role="list" aria-label="Tickets by readiness">
      {counts.map((c) => (
        <span
          key={c.readiness}
          role="listitem"
          className="ah-flow-count"
          data-tone={c.readiness}
          aria-label={`${String(c.n)} ${c.label}`}
          title={READINESS_HELP[c.readiness]}
        >
          <span className="ah-flow-dot" data-tone={c.readiness} aria-hidden="true" />
          <b>{c.n}</b> {c.label}
        </span>
      ))}
    </div>
  );
}

/** "17/18 ACs passing" for a ticket, or its AC count when passing is not known. */
function AcCount({
  row,
  acPasses,
}: {
  row: TicketRow;
  acPasses?: Readonly<Record<string, boolean>> | undefined;
}) {
  if (row.acs.length === 0) return null;
  if (!acPasses) return <span>{row.acs.length} ACs</span>;
  const passing = row.acs.filter((ac) => acPasses[ac]).length;
  const all = passing === row.acs.length;
  return (
    <span style={all ? { color: "var(--done)" } : undefined}>
      {passing}/{row.acs.length} ACs passing
    </span>
  );
}

function FlowCard({
  row,
  rows,
  external,
  critical,
  acPasses,
}: {
  row: TicketRow;
  rows: readonly TicketRow[];
  external: readonly ExternalBlocker[];
  critical: boolean;
  acPasses?: Readonly<Record<string, boolean>> | undefined;
}) {
  const after = row.blocked_by.map((edge) => edge.ref);
  return (
    <li
      className="ah-flow-card"
      data-readiness={row.readiness}
      data-critical={critical || undefined}
      aria-label={`${row.ref}${row.title ? ` · ${row.title}` : ""}`}
    >
      <div className="ah-row" style={{ gap: 8, justifyContent: "space-between" }}>
        {row.id ? (
          <LinearLink id={row.id} url={row.url} />
        ) : (
          <span className="ah-mono ah-small" title="Not created in Linear yet">
            {row.key ?? row.ref}
          </span>
        )}
        <StateBadge row={row} />
      </div>
      <a
        className="ah-flow-card-title"
        href={`#${ticketAnchor(row.ref)}`}
        title={row.title ?? undefined}
      >
        {row.title ?? row.ref}
      </a>
      <div className="ah-small">
        <ReadinessText row={row} rows={rows} external={external} />
      </div>
      <div className="ah-flow-card-meta">
        <AcCount row={row} acPasses={acPasses} />
        {row.reviewed === true && row.readiness !== "done" && (
          <span className="ah-row" style={{ gap: 3, color: "var(--done)" }}>
            <Icon name="circle-check" size="sm" />
            reviewed
          </span>
        )}
        {row.assignee && <span>{row.assignee}</span>}
        {after.length > 0 && row.readiness !== "waiting" && (
          <span>
            after <RefList refs={after} rows={rows} external={external} />
          </span>
        )}
        {critical && (
          <span style={{ color: "var(--accent)" }} title="On the longest chain of tickets not done">
            critical path
          </span>
        )}
      </div>
    </li>
  );
}

/** How an epic's children stand: done, under way, and the rest (not started or waiting). */
function childProgress(epic: TicketRow, rows: readonly TicketRow[]) {
  const children = rows.filter((r) => epic.children.includes(r.ref) && r.readiness !== "canceled");
  const done = children.filter((r) => r.readiness === "done").length;
  const working = children.filter((r) => r.readiness === "in_progress").length;
  return { total: children.length, done, working, rest: children.length - done - working };
}

/**
 * The feature's epic, above the flow: the parent ticket that groups the work. It is never picked
 * up itself, so it is no step of the flow; it shows how far its children are instead.
 */
function EpicCard({
  epic,
  rows,
  acPasses,
}: {
  epic: TicketRow;
  rows: readonly TicketRow[];
  acPasses?: Readonly<Record<string, boolean>> | undefined;
}) {
  const { total, done, working, rest } = childProgress(epic, rows);
  const children = rows.filter((r) => epic.children.includes(r.ref));
  const acs = children.flatMap((r) => r.acs);
  const passing = acPasses ? acs.filter((ac) => acPasses[ac]).length : null;
  const pct = (n: number) => `${String(total ? (n / total) * 100 : 0)}%`;
  return (
    <section
      className="ah-flow-epic"
      data-readiness={epic.readiness}
      aria-label={`Epic ${epic.ref}${epic.title ? ` · ${epic.title}` : ""}`}
    >
      <div className="ah-row ah-wrap" style={{ gap: 8 }}>
        <span className="ah-flow-epic-tag" title={READINESS_HELP.epic}>
          <Icon name="layers" size="sm" />
          Epic
        </span>
        {epic.id ? (
          <LinearLink id={epic.id} url={epic.url} />
        ) : (
          <span className="ah-mono ah-small" title="Not created in Linear yet">
            {epic.key ?? epic.ref}
          </span>
        )}
        <StateBadge row={epic} />
        <span className="ah-flow-epic-title" title={epic.title ?? undefined}>
          {epic.title ?? epic.ref}
        </span>
      </div>
      <div
        className="ah-flow-epic-track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={done}
        aria-label={`${String(done)} of ${String(total)} child tickets done`}
      >
        <span data-tone="done" style={{ width: pct(done) }} />
        <span data-tone="in_progress" style={{ width: pct(working) }} />
      </div>
      <div className="ah-flow-card-meta">
        <span>
          <b style={{ color: "var(--text)", fontWeight: 600 }}>
            {done}/{total}
          </b>{" "}
          child tickets done
        </span>
        {working > 0 && <span style={{ color: "var(--live)" }}>{working} in progress</span>}
        {rest > 0 && <span>{rest} not started</span>}
        {passing !== null && acs.length > 0 && (
          <span style={passing === acs.length ? { color: "var(--done)" } : undefined}>
            {passing}/{acs.length} ACs passing
          </span>
        )}
        <span>Tracks the tickets below; it is done when they all are.</span>
      </div>
    </section>
  );
}

interface FlowColumn {
  key: string;
  title: string;
  hint: string;
  kind: "step" | "held" | "done";
  refs: readonly string[];
}

/** The flow's columns: each parallel group in order, then tickets held back, then the settled. */
function flowColumns(tickets: readonly TicketRow[], planning: TicketPlan): FlowColumn[] {
  const layered = new Set(planning.layers.flat());
  const epics = new Set(planning.epics);
  const work = tickets.filter((t) => !epics.has(t.ref));
  const columns: FlowColumn[] = planning.layers.map((layer, i) => ({
    key: `step-${String(i + 1)}`,
    title: `Step ${String(i + 1)}`,
    hint: layer.length > 1 ? "in parallel" : i === 0 ? "first" : `after step ${String(i)}`,
    kind: "step",
    refs: layer,
  }));
  const held = work
    .filter((t) => !layered.has(t.ref) && t.readiness !== "done" && t.readiness !== "canceled")
    .map((t) => t.ref);
  if (held.length > 0) {
    columns.push({
      key: "held",
      title: "Held back",
      hint: "a cycle or a blocker outside",
      kind: "held",
      refs: held,
    });
  }
  const settled = work
    .filter((t) => t.readiness === "done" || t.readiness === "canceled")
    .map((t) => t.ref);
  if (settled.length > 0) {
    columns.push({ key: "done", title: "Done", hint: "settled", kind: "done", refs: settled });
  }
  return columns;
}

export interface PlanningViewProps {
  tickets: readonly TicketRow[];
  planning: TicketPlan;
  /** Whether each AC passes (by id), to show each ticket's progress; omitted when unknown. */
  acPasses?: Readonly<Record<string, boolean>> | undefined;
}

/**
 * The planning of the feature's tickets (AC-136.30) as a flow: the parallel groups as columns
 * left to right (what can run together, and in which order), each ticket with its live status
 * in Linear and what to do with it now; tickets held back and the settled ones close the flow.
 * An epic (a parent of other tickets) heads the flow with its children's progress, not as a step.
 * Banners name dependency cycles, blockers outside the feature and the server's warnings.
 */
export function PlanningView({ tickets, planning, acPasses }: PlanningViewProps) {
  const external = planning.external_blockers;
  const byRef = new Map(tickets.map((t) => [t.ref, t]));
  const critical = new Set(planning.critical_path.length > 1 ? planning.critical_path : []);
  const columns = flowColumns(tickets, planning);
  const epics = planning.epics.flatMap((ref) => byRef.get(ref) ?? []);
  const work = tickets.filter((t) => !planning.epics.includes(t.ref));
  return (
    <section className="ah-card ah-pad ah-stack" style={{ gap: 14 }} aria-labelledby="planning-h">
      <div className="ah-row ah-wrap" style={{ gap: 12 }}>
        <h2 id="planning-h" className="ah-h3" style={{ margin: 0 }}>
          Ticket flow
        </h2>
        <span className="ah-small ah-subtle">
          Left to right: tickets in one step can run in parallel; a step starts when the one before
          it is done.{epics.length > 0 && " The epic only tracks them, so it is no step."}
        </span>
      </div>
      {planning.cycles.length > 0 && (
        <Banner tone="error" icon="octagon-x">
          <b style={{ fontWeight: 500 }}>
            Dependency cycle{planning.cycles.length === 1 ? "" : "s"}:
          </b>{" "}
          {planning.cycles.map((cycle, i) => (
            <Fragment key={cycle.join(">")}>
              {i > 0 && "; "}
              <RefList refs={cycle} rows={tickets} external={external} separator=" → " />
            </Fragment>
          ))}
          . These tickets wait on each other and are left out of the steps; break the cycle in the
          plan or in Linear.
        </Banner>
      )}
      {external.length > 0 && (
        <Banner tone="warning" icon="triangle-alert">
          <b style={{ fontWeight: 500 }}>Blocked from outside this feature:</b>
          <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
            {external.map((b) => (
              <li key={b.id}>
                <LinearLink id={b.id} url={b.url} />
                {b.title && ` · ${b.title}`} ·{" "}
                {b.done ? "done" : b.state ? `${b.state.name} (not done)` : "status unknown"}
              </li>
            ))}
          </ul>
        </Banner>
      )}
      {planning.warnings.length > 0 && (
        <Banner tone="info">
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {planning.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </Banner>
      )}
      {epics.map((epic) => (
        <EpicCard key={epic.ref} epic={epic} rows={tickets} acPasses={acPasses} />
      ))}
      <ReadinessSummary tickets={work} />
      {columns.length === 0 ? (
        <span className="ah-small ah-muted">No ticket to show.</span>
      ) : (
        <div className="ah-flow" role="list" aria-label="Ticket flow">
          {columns.map((col, i) => (
            <Fragment key={col.key}>
              {i > 0 && (
                <div className="ah-flow-arrow" aria-hidden="true">
                  <Icon name="arrow-right" />
                </div>
              )}
              <section
                className="ah-flow-col"
                data-kind={col.kind}
                role="listitem"
                aria-label={`${col.title} · ${col.hint}`}
              >
                <div className="ah-flow-col-head">
                  <b>{col.title}</b>
                  <span>{col.hint}</span>
                </div>
                <ul
                  className="ah-stack"
                  style={{ gap: 8, margin: 0, padding: 0, listStyle: "none" }}
                >
                  {col.refs.map((ref) => {
                    const row = byRef.get(ref);
                    if (!row) return null;
                    return (
                      <FlowCard
                        key={ref}
                        row={row}
                        rows={tickets}
                        external={external}
                        critical={critical.has(ref)}
                        acPasses={acPasses}
                      />
                    );
                  })}
                </ul>
              </section>
            </Fragment>
          ))}
        </div>
      )}
      <div className="ah-flow-legend" aria-label="Legend">
        {(["can_start", "in_progress", "waiting", "done"] as const).map((r) => (
          <span key={r} title={READINESS_HELP[r]}>
            <span className="ah-flow-dot" data-tone={r} aria-hidden="true" />
            {r === "can_start"
              ? "Can start: not started, blockers done"
              : r === "in_progress"
                ? "In progress: started in Linear"
                : r === "waiting"
                  ? "Waiting: a blocker is not done"
                  : "Done in Linear"}
          </span>
        ))}
        {critical.size > 0 && (
          <span style={{ color: "var(--accent)" }}>Critical path: the longest chain not done</span>
        )}
      </div>
    </section>
  );
}
