import "./ticket-flow.css";

import { Fragment, useRef } from "react";
import type { ReactNode } from "react";
import { Link, useSearchParams } from "react-router";

import type { components } from "../../api/schema";
import {
  Banner,
  GOLDEN_STATE_TEXT,
  Icon,
  StatusBadge,
  StepBar,
  type IconName,
  type Status,
} from "../../components";
import { curvePath, useNodeBoxes } from "../../lib/nodeBoxes";
import { githubPullHref, linearHref } from "../../lib/safeHref";

type TicketRow = components["schemas"]["TicketRow"];
type TicketFlow = components["schemas"]["TicketFlow"];
type TicketStepName = components["schemas"]["TicketStepName"];
type TicketPlan = components["schemas"]["TicketPlan"];
type ExternalBlocker = components["schemas"]["ExternalBlocker"];
type IssueStateType = components["schemas"]["IssueStateType"];
type Readiness = components["schemas"]["Readiness"];

export type InReview = TicketRow & { id: string; pr_url: string };

/**
 * The blocker a waiting ticket can be stacked on: its only blocker not done, a ticket of this
 * feature already started with a pull request open (in review, not merged). Working on top of its
 * branch saves waiting for the merge. Null when the ticket waits on anything else.
 */
export function stackedOn(row: TicketRow, rows: readonly TicketRow[]): InReview | null {
  if (row.id == null || row.readiness !== "waiting" || row.waiting_on.length !== 1) return null;
  const blocker = rows.find((r) => r.ref === row.waiting_on[0]);
  if (blocker?.id == null || blocker.pr_url == null || blocker.readiness !== "in_progress") {
    return null;
  }
  return blocker as InReview;
}

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
  waiting:
    "Not started yet; a blocker is not done. When its only blocker is in review, it can start on that blocker's branch.",
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
  brief = false,
}: {
  row: TicketRow;
  rows: readonly TicketRow[];
  external: readonly ExternalBlocker[];
  /** Beside the Linear status badge (the card): leave out the words the badge already says. */
  brief?: boolean;
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
      if (brief && !row.reviewed && row.waiting_on.length > 0) {
        return (
          <span title={help} style={{ color: "var(--live)" }}>
            Started before {refs(row.waiting_on)} was done
          </span>
        );
      }
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
    case "waiting": {
      const base = stackedOn(row, rows);
      if (!base) {
        return (
          <span title={help} style={{ color: "var(--waiting)" }}>
            Waiting on {refs(row.waiting_on)}
          </span>
        );
      }
      const branch = <>Can start on {refs([base.ref])}'s branch</>;
      if (brief) {
        return (
          <span title={help} style={{ color: "var(--text-muted)" }}>
            {branch}
          </span>
        );
      }
      return (
        <span className="ah-stack" style={{ gap: 2 }} title={help}>
          <b style={{ fontWeight: 500 }}>{branch}</b>
          <span className="ah-small ah-subtle">{base.id} is in review, not merged</span>
        </span>
      );
    }
    default:
      return (
        <span className="ah-muted" title={help}>
          Unknown
        </span>
      );
  }
}

/** Whether the readiness only repeats the Linear status a card's badge already shows. */
export function readinessRepeatsState(row: TicketRow): boolean {
  switch (row.readiness) {
    case "done":
    case "canceled":
    case "unknown":
      return true;
    case "in_progress":
      return !row.reviewed && row.waiting_on.length === 0;
    default:
      return false;
  }
}

/** The element id of a ticket's row, the target of every in-page ticket link. */
export function ticketAnchor(ref: string): string {
  return `ticket-${ref.replace(/[^A-Za-z0-9_-]/g, "-")}`;
}

/** Records the element that opened a ticket's panel, so closing it returns focus there. */
export type TicketOpener = (opener: HTMLElement) => void;

/** The panel's id of a ticket: its tracker id once created, else its plan key (AC-1.10). */
export function ticketParam(row: TicketRow): string {
  return row.id ?? row.key ?? row.ref;
}

/** The search that opens ticket `id`'s panel on the Tickets tab, the rest of the URL kept. */
export function ticketSearch(params: URLSearchParams, id: string): string {
  const next = new URLSearchParams(params);
  next.set("doc", "tickets");
  next.set("ticket", id);
  next.delete("step");
  return `?${next.toString()}`;
}

/**
 * A link that opens `row`'s ticket panel in place (replace; two-level-flows AC-1.10); its href is
 * the stable URL, so a middle-click opens it in a new tab.
 */
export function TicketOpenLink({
  row,
  onOpen,
  children,
  className,
  title,
}: {
  row: TicketRow;
  onOpen: TicketOpener;
  children: ReactNode;
  className?: string | undefined;
  title?: string | undefined;
}) {
  const [params] = useSearchParams();
  return (
    <Link
      className={className}
      to={{ search: ticketSearch(params, ticketParam(row)) }}
      replace
      title={title}
      data-ticket-open={row.ref}
      onClick={(event) => {
        onOpen(event.currentTarget);
      }}
    >
      {children}
    </Link>
  );
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

/** A conventional-commit title split for reading: `feat(brand-api): add x` → type, scope, text. */
export function splitTitle(title: string): {
  type: string | null;
  scope: string | null;
  text: string;
} {
  const match = /^([a-z]+)(?:\(([^)]+)\))?!?:\s+(.+)$/.exec(title);
  if (!match) return { type: null, scope: null, text: title };
  return { type: match[1] ?? null, scope: match[2] ?? null, text: match[3] ?? title };
}

/** A thin bar of how many of the ticket's ACs pass, with the count in words beside it. */
export function AcMeter({
  passing,
  total,
  label,
}: {
  passing: number;
  total: number;
  label: string;
}) {
  const all = passing === total;
  return (
    <span className="ah-ac-meter" data-all={all || undefined}>
      <span
        className="ah-flow-track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={passing}
        aria-label={`${String(passing)} of ${String(total)} ACs passing`}
      >
        <span
          data-tone="done"
          style={{ width: `${String(total ? (passing / total) * 100 : 0)}%` }}
        />
      </span>
      <span>{label}</span>
    </span>
  );
}

/** "17/18 ACs passing" for a ticket, or its AC count when passing is not known. */
export function AcCount({
  row,
  acPasses,
}: {
  row: { acs: readonly string[] };
  acPasses?: Readonly<Record<string, boolean>> | undefined;
}) {
  if (row.acs.length === 0) return null;
  if (!acPasses) return <span>{row.acs.length} ACs</span>;
  const passing = row.acs.filter((ac) => acPasses[ac]).length;
  return (
    <AcMeter
      passing={passing}
      total={row.acs.length}
      label={`${String(passing)}/${String(row.acs.length)} ACs passing`}
    />
  );
}

/** The ticket's pull request number, from its GitHub url (`.../pull/69` → `69`). */
function pullNumber(url: string): string | null {
  return /\/pull\/(\d+)$/.exec(url)?.[1] ?? null;
}

/**
 * The ticket's pull request as `PR #69`, opening GitHub in a new tab; plain text when the url is
 * not a GitHub pull request. Nothing when the ticket has none.
 */
export function TicketPrLink({ row }: { row: TicketRow }) {
  if (!row.pr_url) return null;
  const number = pullNumber(row.pr_url);
  const text = number ? `PR #${number}` : "PR";
  const href = githubPullHref(row.pr_url);
  if (href === null) {
    return (
      <span
        className="ah-mono ah-small ah-ticket-pr"
        title="Link not shown: only GitHub pull request links are opened"
      >
        <Icon name="git-pull-request" size="sm" />
        {text}
      </span>
    );
  }
  const ticket = row.id ?? row.ref;
  return (
    <a
      className="ah-issue ah-ticket-pr"
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={`${text} of ${ticket} (opens GitHub in a new tab)`}
      title={`${text} · opens in GitHub`}
    >
      <Icon name="git-pull-request" size="sm" />
      {text}
      <Icon name="arrow-up-right" />
    </a>
  );
}

/** The ticket's Linear id, or its plan key while it is not created; the plan key as a chip. */
export function TicketIdLine({ row }: { row: TicketRow }) {
  return (
    <span className="ah-ticket-id">
      {row.id ? (
        <LinearLink id={row.id} url={row.url} />
      ) : (
        <span className="ah-mono" title="Not created in Linear yet">
          {row.key ?? row.ref}
        </span>
      )}
      {row.id && row.key && row.key !== row.id && (
        <span className="ah-ticket-key" title="The ticket's key in the plan">
          {row.key}
        </span>
      )}
    </span>
  );
}

export const TICKET_STEP_LABEL: Record<TicketStepName, string> = {
  context: "Context",
  preflight: "Preflight",
  implement: "Implement",
  review: "Review",
  eval: "Eval",
  pr: "PR",
  merged: "Merged",
};

/**
 * A ticket's current step in words, as its step bar reads it (A13, A14): "Review · 4/7 · Changes
 * requested", the last step's bare label once it is done.
 */
export function ticketStepLine(flow: TicketFlow): string {
  const at = flow.steps.findIndex((step) => step.name === flow.current);
  const step = flow.steps[at];
  const label = TICKET_STEP_LABEL[flow.current];
  const done = at === flow.steps.length - 1 && step?.state === "done";
  const note = step?.meta ?? (step?.state === "blocked" ? GOLDEN_STATE_TEXT.blocked : null);
  const head = done ? label : `${label} · ${String(at + 1)}/${String(flow.steps.length)}`;
  return note ? `${head} · ${note}` : head;
}

/** What a ticket's one signal says (two-level-flows AC-2.5, AC-2.8). */
export type SignalKind = "waiting" | "held" | "stale" | "local";

/**
 * The kind of a ticket flow's signal, read from its Preflight step's typed state, never its
 * words: the ticket's own plan change waits for you (`waiting`), its Preflight must run again
 * (`stale`) or carries local drift (`local`, a meta that is never a status), else another
 * ticket's change request holds it (`held`).
 */
export function signalKind(flow: TicketFlow): SignalKind | null {
  if (!flow.signal) return null;
  const preflight = flow.steps.find((step) => step.name === "preflight");
  if (preflight?.state === "waiting") return "waiting";
  if (preflight?.meta === flow.signal) return preflight.state === "stale" ? "stale" : "local";
  return "held";
}

const SIGNAL_ICON: Record<Exclude<SignalKind, "local">, IconName> = {
  waiting: "hand",
  held: "circle-pause",
  stale: "clock",
};

/**
 * A ticket's signal line: the owner's wait, a hold or a re-run in words with its icon (it takes
 * the readiness line's place, A13); local drift as a muted meta beside it.
 */
export function TicketSignal({ flow }: { flow: TicketFlow }) {
  const kind = signalKind(flow);
  if (kind === null) return null;
  if (kind === "local") return <span className="ah-small ah-muted">{flow.signal}</span>;
  return (
    <span className="ah-row" style={{ gap: 4 }}>
      <Icon
        name={SIGNAL_ICON[kind]}
        size="sm"
        style={{ color: kind === "waiting" ? "var(--waiting)" : "var(--idle)" }}
      />
      <b style={{ fontWeight: 500 }}>{flow.signal}</b>
    </span>
  );
}

/**
 * A ticket's seven steps as one bar (two-level-flows AC-1.11), labelled with its current step,
 * its position and its meta (or "Blocked"), so the state is never told by color alone ("Review ·
 * 4/7 · Changes requested"); each step's state and meta are in the tooltip and accessible name.
 */
export function TicketStepBar({ flow }: { flow: TicketFlow }) {
  const current = flow.steps.find((step) => step.name === flow.current);
  return (
    <StepBar
      name="Ticket steps"
      label={TICKET_STEP_LABEL[flow.current]}
      current={flow.steps.findIndex((step) => step.name === flow.current)}
      steps={flow.steps.map((step) => ({
        state: step.state,
        summary: `${TICKET_STEP_LABEL[step.name]}: ${GOLDEN_STATE_TEXT[step.state].toLowerCase()}${step.meta ? ` · ${step.meta}` : ""}`,
      }))}
      note={current?.meta ?? (current?.state === "blocked" ? GOLDEN_STATE_TEXT.blocked : null)}
    />
  );
}

function FlowCard({
  row,
  rows,
  external,
  critical,
  inFlow,
  acPasses,
  ticketAction,
  onOpenTicket,
}: {
  row: TicketRow;
  rows: readonly TicketRow[];
  external: readonly ExternalBlocker[];
  critical: boolean;
  /** The refs drawn in the flow: a blocker among them is shown by its edge, not in words. */
  inFlow: ReadonlySet<string>;
  acPasses?: Readonly<Record<string, boolean>> | undefined;
  ticketAction?: TicketAction | undefined;
  onOpenTicket?: TicketOpener | undefined;
}) {
  const action = ticketAction?.(row);
  // A plan change's wait, a hold or a re-run replaces the readiness line; local drift joins it.
  const signal = row.flow ? signalKind(row.flow) : null;
  const replaced = signal !== null && signal !== "local";
  const note = !readinessRepeatsState(row) && !replaced;
  // A blocker the status line already names ("Started before X was done") is not repeated below.
  const named = note && row.readiness === "in_progress" ? row.waiting_on : [];
  const after = row.blocked_by
    .map((edge) => edge.ref)
    .filter((ref) => !inFlow.has(ref) && !named.includes(ref));
  const showAfter = after.length > 0 && row.readiness !== "waiting";
  const showReviewed =
    row.reviewed === true && row.readiness !== "done" && row.readiness !== "in_progress";
  const hasEnd = row.pr_url != null || showReviewed;
  return (
    <li
      id={ticketAnchor(row.ref)}
      className="ah-flow-card"
      data-node-id={row.ref}
      data-readiness={row.readiness}
      data-critical={critical || undefined}
      aria-label={[row.ref, row.title, row.flow && ticketStepLine(row.flow)]
        .filter(Boolean)
        .join(" · ")}
    >
      <div className="ah-flow-card-head">
        <TicketIdLine row={row} />
        {row.id != null || row.state != null ? (
          <StateBadge row={row} />
        ) : (
          <StatusBadge
            status="queued"
            quiet
            label="Not created"
            title="Not created in Linear yet: /feature creates it, then it can be started here"
          />
        )}
      </div>
      <span className="ah-flow-card-title" title={row.title ?? undefined}>
        {onOpenTicket ? (
          <TicketOpenLink row={row} onOpen={onOpenTicket}>
            {row.title ? splitTitle(row.title).text : row.ref}
          </TicketOpenLink>
        ) : (
          <span>{row.title ? splitTitle(row.title).text : row.ref}</span>
        )}
      </span>
      {row.flow && <TicketStepBar flow={row.flow} />}
      <div className="ah-flow-card-foot">
        {(note || action != null || signal !== null) && (
          <div className="ah-flow-card-status">
            {replaced && row.flow && <TicketSignal flow={row.flow} />}
            {note && <ReadinessText row={row} rows={rows} external={external} brief />}
            {action}
            {signal === "local" && row.flow && <TicketSignal flow={row.flow} />}
          </div>
        )}
        <div className="ah-flow-card-facts">
          <AcCount row={row} acPasses={acPasses} />
          {hasEnd && (
            <span className="ah-flow-card-end">
              <TicketPrLink row={row} />
              {showReviewed && (
                <span className="ah-flow-card-fact" style={{ color: "var(--done)" }}>
                  <Icon name="circle-check" size="sm" />
                  Reviewed
                </span>
              )}
            </span>
          )}
        </div>
        {(Boolean(row.assignee) || showAfter || critical) && (
          <div className="ah-flow-card-facts">
            {row.assignee && (
              <span className="ah-flow-card-fact">
                <Icon name="user" size="sm" />
                {row.assignee}
              </span>
            )}
            {showAfter && (
              <span>
                After <RefList refs={after} rows={rows} external={external} />
              </span>
            )}
            {critical && (
              <span
                className="ah-flow-critical ah-flow-card-end"
                title="On the longest chain of tickets not done"
              >
                Critical path
              </span>
            )}
          </div>
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
      id={ticketAnchor(epic.ref)}
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
          {epic.title ? splitTitle(epic.title).text : epic.ref}
        </span>
      </div>
      <div
        className="ah-flow-track"
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

/**
 * The flow's steps: Kahn's layers over the server's open layers plus the done tickets, so a
 * ticket keeps its step once done and the steps after it stay where they were. The server's
 * ``layers`` cover only what is left to do (they drive ``can_start`` and the order); here the
 * done tickets are put back in by their blockers, and an open ticket stays at or after its server
 * layer. Inside a step, done tickets come first, then the server's order. A ticket that cannot be
 * placed (a cycle through a done ticket) is returned apart.
 */
function stableSteps(
  work: readonly TicketRow[],
  planning: TicketPlan,
): { steps: string[][]; unplaced: string[] } {
  const open = planning.layers.flat();
  const done = work.filter((t) => t.readiness === "done").map((t) => t.ref);
  const nodes = new Set([...open, ...done]);
  const rank = new Map([...done, ...open].map((ref, i) => [ref, i]));
  const byRef = new Map(work.map((t) => [t.ref, t]));
  const pending = new Map(
    [...nodes].map((ref) => [
      ref,
      new Set((byRef.get(ref)?.blocked_by ?? []).map((e) => e.ref).filter((b) => nodes.has(b))),
    ]),
  );
  // An open ticket never goes before its server layer; one after a blocker goes a step past it.
  const floor = new Map(planning.layers.flatMap((layer, i) => layer.map((ref) => [ref, i])));
  const level = new Map<string, number>();
  for (;;) {
    const ready = [...pending].filter(([, left]) => left.size === 0).map(([ref]) => ref);
    if (ready.length === 0) break;
    for (const ref of ready) {
      const blockers = (byRef.get(ref)?.blocked_by ?? []).map((e) => level.get(e.ref) ?? -1);
      level.set(ref, Math.max(floor.get(ref) ?? 0, 1 + Math.max(-1, ...blockers)));
      pending.delete(ref);
    }
    for (const left of pending.values()) for (const ref of ready) left.delete(ref);
  }
  const byLevel = new Map<number, string[]>();
  for (const [ref, n] of level) byLevel.set(n, [...(byLevel.get(n) ?? []), ref]);
  const steps = [...byLevel]
    .sort(([a], [b]) => a - b)
    .map(([, refs]) => refs.sort((a, b) => (rank.get(a) ?? 0) - (rank.get(b) ?? 0)));
  return { steps, unplaced: [...pending.keys()] };
}

/** The flow's columns: each step in order (done tickets kept in theirs), then tickets held
 * back, then the canceled ones and any done ticket no step could hold. */
function flowColumns(tickets: readonly TicketRow[], planning: TicketPlan): FlowColumn[] {
  const epics = new Set(planning.epics);
  const work = tickets.filter((t) => !epics.has(t.ref));
  const byRef = new Map(work.map((t) => [t.ref, t]));
  const { steps, unplaced } = stableSteps(work, planning);
  const layered = new Set(steps.flat());
  const columns: FlowColumn[] = steps.map((step, i) => {
    const allDone = step.every((ref) => byRef.get(ref)?.readiness === "done");
    return {
      key: `step-${String(i + 1)}`,
      title: `Group ${String(i + 1)}`,
      hint: allDone
        ? "done"
        : step.length > 1
          ? "in parallel"
          : i === 0
            ? "first"
            : `after group ${String(i)}`,
      kind: allDone ? "done" : "step",
      refs: step,
    };
  });
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
  const settled = [
    ...unplaced,
    ...work.filter((t) => t.readiness === "canceled").map((t) => t.ref),
  ];
  if (settled.length > 0) {
    columns.push({ key: "done", title: "Done", hint: "settled", kind: "done", refs: settled });
  }
  return columns;
}

type EdgeSource = components["schemas"]["EdgeSource"];

interface FlowEdge {
  from: string;
  to: string;
  source: EdgeSource;
  /** Both ends are consecutive on the critical path. */
  critical: boolean;
  /** The ticket started before this blocker was done. */
  early: boolean;
  /** The blocker is settled, so the edge no longer holds anything back. */
  settled: boolean;
}

/** One edge per blocker drawn in the flow, from the blocker to the ticket it holds back. */
function flowEdges(
  tickets: readonly TicketRow[],
  inFlow: ReadonlySet<string>,
  criticalPath: readonly string[],
): FlowEdge[] {
  const byRef = new Map(tickets.map((t) => [t.ref, t]));
  const criticalPairs = new Set(
    criticalPath.slice(1).map((ref, i) => `${criticalPath[i] ?? ""}→${ref}`),
  );
  return tickets
    .filter((t) => inFlow.has(t.ref))
    .flatMap((t) =>
      t.blocked_by
        .filter((edge) => inFlow.has(edge.ref))
        .map((edge) => {
          const blocker = byRef.get(edge.ref);
          return {
            from: edge.ref,
            to: t.ref,
            source: edge.source,
            critical: criticalPairs.has(`${edge.ref}→${t.ref}`),
            early: t.readiness !== "waiting" && t.waiting_on.includes(edge.ref),
            settled: blocker?.readiness === "done" || blocker?.readiness === "canceled",
          };
        }),
    );
}

/** The columns with an SVG layer of edges under them: who blocks whom, at a glance. */
function FlowGraph({
  columns,
  byRef,
  tickets,
  external,
  critical,
  criticalPath,
  acPasses,
  ticketAction,
  onOpenTicket,
}: {
  columns: readonly FlowColumn[];
  byRef: ReadonlyMap<string, TicketRow>;
  tickets: readonly TicketRow[];
  external: readonly ExternalBlocker[];
  critical: ReadonlySet<string>;
  criticalPath: readonly string[];
  acPasses?: Readonly<Record<string, boolean>> | undefined;
  ticketAction?: TicketAction | undefined;
  onOpenTicket?: TicketOpener | undefined;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const inFlow = new Set(columns.flatMap((c) => c.refs));
  const edges = flowEdges(tickets, inFlow, criticalPath);
  const shape = `${columns.map((c) => c.refs.join(",")).join("|")}#${edges
    .map((e) => `${e.from}>${e.to}`)
    .join(",")}`;
  const { boxes, size } = useNodeBoxes(ref, shape);
  return (
    <div ref={ref} className="ah-flow" role="list" aria-label="Ticket flow">
      <svg className="ah-flow-edges" aria-hidden="true" width={size.width} height={size.height}>
        <defs>
          {(["plain", "critical", "early"] as const).map((kind) => (
            <marker
              key={kind}
              id={`ah-flow-arrow-${kind}`}
              className="ah-flow-arrowhead"
              data-kind={kind}
              viewBox="0 0 8 8"
              refX="7"
              refY="4"
              markerWidth="7"
              markerHeight="7"
              orient="auto-start-reverse"
            >
              <path d="M0 0 L8 4 L0 8 z" />
            </marker>
          ))}
        </defs>
        {edges.map((e) => (
          <path
            key={`${e.from}→${e.to}`}
            data-edge={`${e.from}→${e.to}`}
            data-source={e.source}
            data-critical={e.critical || undefined}
            data-early={e.early || undefined}
            data-settled={e.settled || undefined}
            d={curvePath(boxes[e.from], boxes[e.to])}
            markerEnd={`url(#ah-flow-arrow-${e.early ? "early" : e.critical ? "critical" : "plain"})`}
          />
        ))}
      </svg>
      {columns.map((col) => (
        <section
          key={col.key}
          className="ah-flow-col"
          data-kind={col.kind}
          role="listitem"
          aria-label={`${col.title} · ${col.hint}`}
        >
          <div className="ah-flow-col-head">
            <b>{col.title}</b>
            <span>{col.hint}</span>
            <span className="ah-flow-col-n">{col.refs.length}</span>
          </div>
          <ul className="ah-flow-col-list">
            {col.refs.map((r) => {
              const row = byRef.get(r);
              if (!row) return null;
              return (
                <FlowCard
                  key={r}
                  row={row}
                  rows={tickets}
                  external={external}
                  critical={critical.has(r)}
                  inFlow={inFlow}
                  acPasses={acPasses}
                  ticketAction={ticketAction}
                  onOpenTicket={onOpenTicket}
                />
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}

/** How to read the flow, folded next to its title so it stays one click away. */
function FlowLegend({ showCritical }: { showCritical: boolean }) {
  return (
    <details className="ah-flow-legend">
      <summary>
        <Icon name="info" size="sm" />
        How to read
      </summary>
      <div className="ah-flow-legend-body" aria-label="Legend">
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
        <span title={READINESS_HELP.waiting}>
          <span className="ah-flow-dot" data-tone="waiting" aria-hidden="true" />
          Can start on a blocker's branch: its only blocker is in review
        </span>
        <span>
          <span className="ah-flow-line" aria-hidden="true" />
          Blocks: in the plan and in Linear
        </span>
        <span>
          <span className="ah-flow-line" data-source="plan" aria-hidden="true" />
          From the plan only
        </span>
        <span>
          <span className="ah-flow-line" data-early="true" aria-hidden="true" />
          Started before its blocker was done
        </span>
        {showCritical && (
          <span>
            <span className="ah-flow-line" data-critical="true" aria-hidden="true" />
            Critical path: the longest chain not done
          </span>
        )}
      </div>
    </details>
  );
}

export interface PlanningViewProps {
  tickets: readonly TicketRow[];
  planning: TicketPlan;
  /** Whether each AC passes (by id), to show each ticket's progress; omitted when unknown. */
  acPasses?: Readonly<Record<string, boolean>> | undefined;
  /** What a ticket's card offers to do now (Start), or nothing; omitted shows no action. */
  ticketAction?: TicketAction | undefined;
  /** Given, each card's title opens the ticket's panel (two-level-flows AC-1.10). */
  onOpenTicket?: TicketOpener | undefined;
}

/** The control a ticket's card or row shows next to its readiness, or null for none. */
export type TicketAction = (row: TicketRow) => ReactNode;

/**
 * The planning of the feature's tickets (AC-136.30) as a flow: the parallel groups as columns
 * left to right (what can run together, and in which order), each ticket with its live status
 * in Linear and what to do with it now; tickets held back and the settled ones close the flow.
 * An epic (a parent of other tickets) heads the flow with its children's progress, not as a step.
 * Banners name dependency cycles, blockers outside the feature and the server's warnings.
 */
export function PlanningView({
  tickets,
  planning,
  acPasses,
  ticketAction,
  onOpenTicket,
}: PlanningViewProps) {
  const external = planning.external_blockers;
  const byRef = new Map(tickets.map((t) => [t.ref, t]));
  const critical = new Set(planning.critical_path.length > 1 ? planning.critical_path : []);
  const columns = flowColumns(tickets, planning);
  const epics = planning.epics.flatMap((ref) => byRef.get(ref) ?? []);
  const work = tickets.filter((t) => !planning.epics.includes(t.ref));
  return (
    <section className="ah-card ah-pad ah-stack" style={{ gap: 16 }} aria-labelledby="planning-h">
      <div className="ah-flow-header">
        <div className="ah-stack" style={{ gap: 4, flex: "1 1 420px", minWidth: 0 }}>
          <h2 id="planning-h" className="ah-h3" style={{ margin: 0 }}>
            Ticket flow
          </h2>
          <span className="ah-small ah-subtle">
            Groups run left to right; tickets in one group can run in parallel. Each line goes from
            a blocker to the ticket it holds back.
            {epics.length > 0 && " The epic only tracks them, so it is in no group."}
          </span>
        </div>
        <div className="ah-row" style={{ gap: 8, alignItems: "flex-start" }}>
          <ReadinessSummary tickets={work} />
          <FlowLegend showCritical={critical.size > 0} />
        </div>
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
          . These tickets wait on each other and are left out of the groups; break the cycle in the
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
      {columns.length === 0 ? (
        <span className="ah-small ah-muted">No ticket to show.</span>
      ) : (
        <FlowGraph
          columns={columns}
          byRef={byRef}
          tickets={tickets}
          external={external}
          critical={critical}
          criticalPath={planning.critical_path}
          acPasses={acPasses}
          ticketAction={ticketAction}
          onOpenTicket={onOpenTicket}
        />
      )}
    </section>
  );
}
