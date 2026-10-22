import "./ticket-flow.css";

import { Fragment, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent, ReactNode } from "react";
import { Link, useSearchParams } from "react-router";

import type { components } from "../../api/schema";
import {
  ArrowMarkers,
  Banner,
  CANVAS_ZOOM_STEP,
  CanvasControls,
  CanvasGrid,
  CanvasMinimap,
  GOLDEN_STATE_TEXT,
  Icon,
  StatusBadge,
  StepBar,
  type IconName,
  type Status,
  useViewportSize,
} from "../../components";
import { fitView, roundedPath } from "../../lib/canvasView";
import { curvePath, useNodeBoxes } from "../../lib/nodeBoxes";
import { usePanZoom } from "../../lib/usePanZoom";
import { goSequencePending, typingIn } from "../../shell/goSequence";
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
  tabIndex,
  describedBy,
}: {
  row: TicketRow;
  onOpen: TicketOpener;
  children: ReactNode;
  className?: string | undefined;
  title?: string | undefined;
  /** A roving Tab stop (the flow's cards): -1 off the current card. */
  tabIndex?: number | undefined;
  /** The id of a hidden description (what the ticket holds back). */
  describedBy?: string | undefined;
}) {
  const [params] = useSearchParams();
  return (
    <Link
      className={className}
      tabIndex={tabIndex}
      aria-describedby={describedBy}
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

/** The icon before a card's readiness words, in the colour the words use (no coloured borders). */
const READINESS_ICON: Partial<Record<Readiness, { icon: IconName; color: string }>> = {
  can_start: { icon: "circle-play", color: "var(--done)" },
  in_progress: { icon: "circle-dot", color: "var(--live)" },
  waiting: { icon: "hourglass", color: "var(--waiting)" },
  in_cycle: { icon: "octagon-x", color: "var(--failed)" },
};

/** "3/7 ACs" (all passing in `done`), or "4 ACs" when passing is not known. */
function AcFact({
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
    <span
      className="ah-flow-card-fact"
      style={all ? { color: "var(--done)" } : undefined}
      title={`${String(passing)} of ${String(row.acs.length)} ACs passing`}
    >
      {all && <Icon name="circle-check" size="sm" />}
      {passing}/{row.acs.length} ACs
    </span>
  );
}

/**
 * A ticket as a compact card on the flow: its id and Linear status, its title (it opens the
 * ticket's panel), what to do with it now (readiness or signal, and Start), then its facts. The
 * step bar, the AC bar, the assignee and its blockers outside the flow are in the panel.
 */
function FlowCard({
  row,
  rows,
  external,
  critical,
  chosen,
  onChain,
  current,
  inFlow,
  holds,
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
  /** The tickets it holds back, said to assistive tech (the edges only draw it). */
  holds: readonly string[];
  chosen: boolean;
  onChain: boolean;
  /** The card that holds the flow's one Tab stop (its title). */
  current: boolean;
  acPasses?: Readonly<Record<string, boolean>> | undefined;
  ticketAction?: TicketAction | undefined;
  onOpenTicket?: TicketOpener | undefined;
}) {
  const action = ticketAction?.(row);
  // A plan change's wait, a hold or a re-run replaces the readiness line; local drift joins it.
  const signal = row.flow ? signalKind(row.flow) : null;
  const replaced = signal !== null && signal !== "local";
  const note = !readinessRepeatsState(row) && !replaced;
  const look =
    row.readiness === "waiting" && stackedOn(row, rows)
      ? { icon: "git-branch" as const, color: "var(--text-muted)" }
      : READINESS_ICON[row.readiness];
  const reviewedNote = row.readiness === "in_progress" && row.reviewed === true;
  const showReviewed =
    row.reviewed === true && row.readiness !== "done" && row.readiness !== "in_progress";
  const title = row.title ? splitTitle(row.title).text : row.ref;
  // A blocker the status line already names ("Waiting on X") is not repeated in the facts.
  const named = note ? row.waiting_on : [];
  const after = row.blocked_by
    .map((edge) => edge.ref)
    .filter((ref) => !inFlow.has(ref) && !named.includes(ref));
  return (
    <li
      id={ticketAnchor(row.ref)}
      className="ah-flow-card"
      data-node-id={row.ref}
      data-readiness={row.readiness}
      data-critical={critical || undefined}
      data-chain={onChain || undefined}
      data-signal={signal ?? undefined}
      aria-current={chosen || undefined}
      aria-label={[row.ref, row.title, row.flow && ticketStepLine(row.flow)]
        .filter(Boolean)
        .join(" · ")}
    >
      {holds.length > 0 && (
        <span id={`${ticketAnchor(row.ref)}-holds`} hidden>
          Holds back {holds.join(", ")}.
        </span>
      )}
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
          <TicketOpenLink
            row={row}
            onOpen={onOpenTicket}
            tabIndex={current ? 0 : -1}
            describedBy={holds.length > 0 ? `${ticketAnchor(row.ref)}-holds` : undefined}
          >
            {title}
          </TicketOpenLink>
        ) : (
          <span>{title}</span>
        )}
      </span>
      {(note || action != null || signal !== null) && (
        <div className="ah-flow-card-status">
          {replaced && row.flow && <TicketSignal flow={row.flow} />}
          {note && (
            <span className="ah-flow-card-ready">
              {look && !reviewedNote && (
                <Icon name={look.icon} size="sm" style={{ color: look.color }} />
              )}
              {reviewedNote && (
                <Icon name="check-check" size="sm" style={{ color: "var(--done)" }} />
              )}
              {row.readiness === "in_cycle" ? (
                <b style={{ fontWeight: 500, color: "var(--failed)" }}>
                  Waiting: cycle
                  {row.waiting_on.length > 0 && (
                    <>
                      {" with "}
                      <RefList refs={row.waiting_on} rows={rows} external={external} />
                    </>
                  )}
                </b>
              ) : (
                <ReadinessText row={row} rows={rows} external={external} brief />
              )}
            </span>
          )}
          {action}
          {signal === "local" && row.flow && <TicketSignal flow={row.flow} />}
        </div>
      )}
      <div className="ah-flow-card-facts">
        {row.flow && row.readiness !== "canceled" && <span>{ticketStepLine(row.flow)}</span>}
        <AcFact row={row} acPasses={acPasses} />
        <TicketPrLink row={row} />
        {showReviewed && (
          <span className="ah-flow-card-fact" style={{ color: "var(--done)" }}>
            <Icon name="circle-check" size="sm" />
            Reviewed
          </span>
        )}
        {after.length > 0 && (
          <span>
            After <RefList refs={after} rows={rows} external={external} />
          </span>
        )}
        {critical && (
          <span className="ah-flow-critical" title="On the longest chain of tickets not done">
            Critical path
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

/** The steps of a ticket that is chosen or hovered: its chain, as nodes and edge keys. */
function chainOf(edges: readonly FlowEdge[], ref: string, whole: boolean) {
  const nodes = new Set([ref]);
  const hot = new Set<string>();
  const walk = (forward: boolean) => {
    const queue = [ref];
    const seen = new Set([ref]);
    for (let at = queue.shift(); at !== undefined; at = queue.shift()) {
      for (const e of edges) {
        const [near, far] = forward ? [e.from, e.to] : [e.to, e.from];
        if (near !== at) continue;
        hot.add(`${e.from}→${e.to}`);
        nodes.add(far);
        if (whole && !seen.has(far)) {
          seen.add(far);
          queue.push(far);
        }
      }
    }
  };
  walk(true);
  walk(false);
  return { nodes, edges: hot };
}

/** Below this zoom the cards show only their id, status and title. */
const FAR = 0.6;
/** The first view fits the flow only when its text still reads (cards at 85% or more). */
const FIRST_FIT = 0.85;
const PAD = 32;

/** A ticket's readiness as the minimap's state colours (Canvas.css). */
const MINI_STATE: Record<Readiness, string> = {
  can_start: "ok",
  done: "ok",
  in_progress: "running",
  waiting: "waiting",
  in_cycle: "failed",
  canceled: "pending",
  epic: "pending",
  unknown: "pending",
};

/** The tallest the canvas grows: 75% of the window, between 320 and 900 px. */
function heightCap(): number {
  return Math.min(900, Math.max(320, window.innerHeight * 0.75));
}

/**
 * The flow on a pan and zoom canvas: the groups as columns in the world, left to right, each with
 * its header; an edge from each blocker to the ticket it holds back. The chosen ticket (its panel
 * is open) lights its whole chain, drawn again above the cards; hover lights the direct edges.
 * Held back and Done draw no edges: their cards name what they wait on. One Tab stop: the arrow
 * keys follow the edges, up and down move in a column.
 */
function FlowGraph({
  columns,
  byRef,
  tickets,
  external,
  critical,
  criticalPath,
  chosen,
  acPasses,
  ticketAction,
  onOpenTicket,
  legend,
}: {
  columns: readonly FlowColumn[];
  byRef: ReadonlyMap<string, TicketRow>;
  tickets: readonly TicketRow[];
  external: readonly ExternalBlocker[];
  critical: ReadonlySet<string>;
  criticalPath: readonly string[];
  chosen: string | null;
  acPasses?: Readonly<Record<string, boolean>> | undefined;
  ticketAction?: TicketAction | undefined;
  onOpenTicket?: TicketOpener | undefined;
  legend: ReactNode;
}) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const worldRef = useRef<HTMLDivElement>(null);
  const hintId = useId();
  const arrowId = `ah-flow-arrow-${useId().replace(/:/g, "")}`;
  // Held back and the settled Done column draw no edges: their cards name what they wait on.
  const drawn = new Set(
    columns.filter(({ key }) => key !== "held" && key !== "done").flatMap((column) => column.refs),
  );
  const inFlow = new Set(columns.flatMap((column) => column.refs));
  const edges = flowEdges(tickets, drawn, criticalPath);
  const order = columns.flatMap((column) => column.refs);
  const pz = usePanZoom(viewportRef, { wheel: "page" });
  const { view } = pz;
  const far = view.k < FAR;
  const shape = `${columns.map((column) => column.refs.join(",")).join("|")}#${edges
    .map((e) => `${e.from}>${e.to}`)
    .join(",")}|${far ? "far" : "near"}`;
  const viewport = useViewportSize(viewportRef);
  const { boxes, size } = useNodeBoxes(worldRef, shape);
  const [height, setHeight] = useState(320);
  const [hover, setHover] = useState<string | null>(null);
  const [focusRef, setFocusRef] = useState<string | null>(null);
  // The card whose title holds keyboard focus now (its edges light), cleared on blur.
  const [lit, setLit] = useState<string | null>(null);
  const shown = chosen !== null && drawn.has(chosen) ? chosen : null;
  const chain = shown ? chainOf(edges, shown, true) : null;
  const pointed = hover ?? lit;
  const near = !chain && pointed ? chainOf(edges, pointed, false) : null;
  const hotEdges = chain?.edges ?? near?.edges ?? new Set<string>();
  const current =
    focusRef && inFlow.has(focusRef) ? focusRef : chosen && inFlow.has(chosen) ? chosen : order[0];

  // One Tab stop: only the current card's links and buttons are in the tab order (its title is
  // the stop itself); the arrow keys reach the others.
  useEffect(() => {
    const world = worldRef.current;
    if (!world) return;
    for (const card of world.querySelectorAll<HTMLElement>(".ah-flow-card")) {
      const here = card.dataset.nodeId === current;
      for (const el of card.querySelectorAll<HTMLElement>("a, button")) {
        if (el.matches("[data-ticket-open]")) continue;
        if (here) el.removeAttribute("tabindex");
        else el.setAttribute("tabindex", "-1");
      }
    }
  });

  // The first view, once: fit when it reads (60% or more), else 100% from the left; the canvas's
  // height follows it. Live refreshes never move it.
  const placed = useRef(false);
  useLayoutEffect(() => {
    if (placed.current || size.width === 0 || viewport.width === 0) return;
    const cap = heightCap();
    let k = Math.min(1, (viewport.width - 2 * PAD) / size.width, (cap - 2 * PAD) / size.height);
    if (k < FIRST_FIT) k = 1;
    const h = Math.round(Math.max(240, Math.min(cap, size.height * k + 2)));
    setHeight(h);
    const box = shown ? boxes[shown] : undefined;
    if (box && size.width * k > viewport.width) {
      pz.setView({ k, x: viewport.width / 2 - ((box.left + box.right) / 2) * k, y: 0 });
    } else {
      pz.setView({
        k,
        x: size.width * k <= viewport.width ? (viewport.width - size.width * k) / 2 : 0,
        y: size.height * k <= h ? (h - size.height * k) / 2 : 0,
      });
    }
    placed.current = true;
  }, [boxes, size, viewport, shown, pz]);

  /** Keep a focused card on screen, with a margin. */
  const reveal = (ref: string) => {
    const box = boxes[ref];
    if (!box || viewport.width === 0) return;
    const m = 48;
    const { x, y, k } = pz.view;
    let nx = x;
    let ny = y;
    const left = box.left * k + x;
    const right = box.right * k + x;
    const top = box.top * k + y;
    const bottom = box.bottom * k + y;
    if (left < m) nx += m - left;
    else if (right > viewport.width - m) nx -= right - (viewport.width - m);
    if (top < m) ny += m - top;
    else if (bottom > viewport.height - m) ny -= bottom - (viewport.height - m);
    if (nx !== x || ny !== y) pz.setView({ k, x: nx, y: ny }, true);
  };

  const fit = () => {
    pz.setView(fitView(size, viewport, { max: 1 }), true);
  };

  const moveTo = (ref: string | undefined) => {
    if (!ref) return;
    const card = window.document.getElementById(ticketAnchor(ref));
    setFocusRef(ref);
    card?.querySelector<HTMLElement>("[data-ticket-open]")?.focus({ preventScroll: true });
    reveal(ref);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
    if (typingIn(event.target) || goSequencePending()) return;
    const ref = (event.target as HTMLElement).closest<HTMLElement>(".ah-flow-card")?.dataset.nodeId;
    switch (event.key) {
      case "+":
      case "=":
        event.preventDefault();
        pz.zoomBy(CANVAS_ZOOM_STEP);
        return;
      case "-":
        event.preventDefault();
        pz.zoomBy(1 / CANVAS_ZOOM_STEP);
        return;
      case "0":
        event.preventDefault();
        fit();
        return;
      case "1":
        event.preventDefault();
        pz.zoomTo(1);
        return;
    }
    if (!ref) return;
    const col = columns.findIndex((column) => column.refs.includes(ref));
    const at = columns[col]?.refs.indexOf(ref) ?? 0;
    const sideways = (step: number) => {
      const next = columns[col + step];
      return next?.refs[Math.min(at, next.refs.length - 1)];
    };
    let to: string | undefined;
    switch (event.key) {
      case "ArrowRight":
        to = edges.find((e) => e.from === ref)?.to ?? sideways(1);
        break;
      case "ArrowLeft":
        to = edges.find((e) => e.to === ref)?.from ?? sideways(-1);
        break;
      case "ArrowDown":
      case "ArrowUp":
        to = columns[col]?.refs[at + (event.key === "ArrowDown" ? 1 : -1)];
        break;
      case "j":
      case "k":
        to = order[order.indexOf(ref) + (event.key === "j" ? 1 : -1)];
        break;
      default:
        return;
    }
    event.preventDefault();
    moveTo(to);
  };

  const columnOf = new Map(columns.flatMap((column, i) => column.refs.map((r) => [r, i])));
  // The lanes of the edges that skip a column, 5 px apart over the columns.
  const lanes = new Map<string, number>();
  for (const e of edges) {
    if ((columnOf.get(e.to) ?? 0) - (columnOf.get(e.from) ?? 0) > 1) {
      lanes.set(`${e.from}→${e.to}`, lanes.size % 4);
    }
  }
  /** A curve to the next column; over the columns (in their gaps) to one further on. */
  const path = (e: FlowEdge) => {
    const a = boxes[e.from];
    const b = boxes[e.to];
    const lane = lanes.get(`${e.from}→${e.to}`);
    if (!a || !b || lane === undefined) return curvePath(a, b);
    const top = 14 - lane * 5;
    const out = a.right + 30 + lane * 5;
    const into = b.left - 30 - lane * 5;
    return roundedPath([
      [a.right, a.mid],
      [out, a.mid],
      [out, top],
      [into, top],
      [into, b.mid],
      [b.left, b.mid],
    ]);
  };
  const cardOf = (target: EventTarget) =>
    target instanceof Element ? target.closest<HTMLElement>(".ah-flow-card") : null;
  const overflow =
    size.width * view.k > viewport.width + 1 || size.height * view.k > viewport.height + 1;
  const worldStyle: CSSProperties & Record<"--k", string> = {
    transform: `translate(${String(view.x)}px, ${String(view.y)}px) scale(${String(view.k)})`,
    "--k": String(view.k),
  };
  const tone = (e: FlowEdge) => (e.early ? "early" : e.critical ? "critical" : "plain");
  return (
    // The flow's keys (arrows, zoom) bubble here from its cards' links and buttons; hover and a
    // press on a card's background are pointer extras (the title link is the keyboard's way in).
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions
    <div
      className="ah-canvas ah-flow-canvas"
      data-canvas="ticket-flow"
      style={{ height }}
      onKeyDown={onKeyDown}
      onFocus={(event) => {
        if (!(event.target instanceof HTMLElement) || !event.target.matches("[data-ticket-open]")) {
          return;
        }
        const ref = cardOf(event.target)?.dataset.nodeId;
        if (ref) {
          setFocusRef(ref);
          setLit(ref);
        }
      }}
      onBlur={() => {
        setLit(null);
      }}
      onMouseOver={(event) => {
        setHover(cardOf(event.target)?.dataset.nodeId ?? null);
      }}
      onMouseLeave={() => {
        setHover(null);
      }}
      onClick={(event) => {
        // A press on a card's background opens its panel as its title does; a drag does not.
        const target = event.target as HTMLElement;
        if (pz.wasDrag() || target.closest("a, button, summary, input")) return;
        cardOf(target)?.querySelector<HTMLElement>("[data-ticket-open]")?.click();
      }}
    >
      <div
        ref={viewportRef}
        className="ah-canvas-viewport"
        data-dragging={pz.dragging ? "" : undefined}
        {...pz.handlers}
      >
        <CanvasGrid view={view} />
        <div
          ref={worldRef}
          className="ah-canvas-world ah-flow"
          role="group"
          aria-label="Ticket flow"
          aria-describedby={hintId}
          data-zoom={far ? "far" : undefined}
          data-animate={pz.animated ? "" : undefined}
          data-chosen={chain ? "" : undefined}
          style={worldStyle}
        >
          <svg className="ah-flow-edges" aria-hidden="true" data-edges="" width={1} height={1}>
            <ArrowMarkers id={arrowId} tones={["plain", "critical", "early", "hot"]} />
            {edges.map((e) => {
              const key = `${e.from}→${e.to}`;
              const hot = hotEdges.has(key);
              return (
                <path
                  key={key}
                  data-edge={key}
                  data-source={e.source}
                  data-critical={e.critical || undefined}
                  data-early={e.early || undefined}
                  data-settled={e.settled || undefined}
                  data-hot={hot ? "" : undefined}
                  data-dim={(chain ?? near) && !hot ? "" : undefined}
                  d={path(e)}
                  markerEnd={`url(#${arrowId}-${tone(e)})`}
                />
              );
            })}
          </svg>
          <div className="ah-flow-cols">
            {columns.map((column) => (
              <section
                key={column.key}
                className="ah-flow-col"
                data-kind={column.kind}
                aria-label={`${column.title} · ${column.hint}`}
              >
                <div className="ah-flow-col-head">
                  {column.kind === "done" &&
                    (column.refs.every((r) => byRef.get(r)?.readiness === "done") ? (
                      <Icon name="circle-check" size="sm" style={{ color: "var(--done)" }} />
                    ) : (
                      <Icon name="check-check" size="sm" style={{ color: "var(--idle)" }} />
                    ))}
                  {column.kind === "held" && (
                    <Icon name="circle-pause" size="sm" style={{ color: "var(--idle)" }} />
                  )}
                  <b>{column.title}</b>
                  <span>{column.hint}</span>
                  <span className="ah-flow-col-n">{column.refs.length}</span>
                </div>
                <ol
                  className="ah-flow-col-list"
                  aria-label={`${column.title} · ${column.hint} · ${String(column.refs.length)} tickets`}
                >
                  {column.refs.map((r) => {
                    const row = byRef.get(r);
                    if (!row) return null;
                    return (
                      <FlowCard
                        key={r}
                        row={row}
                        rows={tickets}
                        external={external}
                        critical={critical.has(r)}
                        chosen={chosen === r}
                        onChain={chain?.nodes.has(r) ?? false}
                        current={current === r}
                        holds={edges.filter((e) => e.from === r).map((e) => e.to)}
                        inFlow={inFlow}
                        acPasses={acPasses}
                        ticketAction={ticketAction}
                        onOpenTicket={onOpenTicket}
                      />
                    );
                  })}
                </ol>
              </section>
            ))}
          </div>
          {/* The lit edges again, above the cards, so a blocker two groups back is never hidden. */}
          <svg className="ah-flow-edges ah-flow-edges-top" aria-hidden="true" width={1} height={1}>
            {edges
              .filter((e) => hotEdges.has(`${e.from}→${e.to}`))
              .map((e) => (
                <path
                  key={`${e.from}→${e.to}`}
                  data-source={e.source}
                  data-early={e.early || undefined}
                  data-hot=""
                  d={path(e)}
                  markerEnd={`url(#${arrowId}-${e.early ? "early" : "hot"})`}
                />
              ))}
          </svg>
        </div>
        <span id={hintId} className="ah-sr">
          Arrow keys follow the arrows, up and down move in a group, Enter opens a ticket, plus and
          minus zoom, 0 fits the flow, v shows the same tickets as a table.
        </span>
        <div className="ah-canvas-overlay">{legend}</div>
        <CanvasControls
          view={view}
          onZoomBy={(f) => {
            pz.zoomBy(f);
          }}
          onZoomTo={(k) => {
            pz.zoomTo(k);
          }}
          onFit={fit}
        />
        {overflow && size.width > 0 && (
          <CanvasMinimap
            boxes={boxes}
            size={size}
            view={view}
            viewport={viewport}
            look={(id) => {
              const row = byRef.get(id);
              return row ? { frame: false, state: MINI_STATE[row.readiness] } : null;
            }}
            onCentre={(x, y) => {
              pz.setView({
                k: view.k,
                x: viewport.width / 2 - x * view.k,
                y: viewport.height / 2 - y * view.k,
              });
            }}
          />
        )}
      </div>
    </div>
  );
}

/** How to read the flow, folded at the canvas's top right so it stays one click away. */
function FlowLegend({ showCritical }: { showCritical: boolean }) {
  const lines: [Readiness, string][] = [
    ["can_start", "Can start: not started, blockers done"],
    ["in_progress", "In progress: started in Linear"],
    ["waiting", "Waiting: a blocker is not done"],
    ["in_cycle", "Waiting: a cycle of blockers"],
  ];
  return (
    <details className="ah-flow-legend">
      <summary>
        <Icon name="info" size="sm" />
        How to read
      </summary>
      <div className="ah-flow-legend-body" aria-label="Legend">
        {lines.map(([r, text]) => {
          const look = READINESS_ICON[r];
          return (
            <span key={r} title={READINESS_HELP[r]}>
              {look && <Icon name={look.icon} size="sm" style={{ color: look.color }} />}
              {text}
            </span>
          );
        })}
        <span title={READINESS_HELP.waiting}>
          <Icon name="git-branch" size="sm" style={{ color: "var(--text-muted)" }} />
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
          <span className="ah-flow-line" data-source="linear" aria-hidden="true" />
          From Linear only
        </span>
        <span>
          <span className="ah-flow-line" data-early="true" aria-hidden="true" />
          Started before its blocker was done
        </span>
        <span>
          <span className="ah-flow-line" data-settled="true" aria-hidden="true" />
          Faded: its blocker is done
        </span>
        <span>
          <span className="ah-flow-line" data-critical="true" aria-hidden="true" />
          {showCritical
            ? "Accent: the critical path (the longest chain not done), or the chosen ticket's chain"
            : "Accent: the chosen ticket's chain"}
        </span>
        <span>
          Drag to move · Shift + scroll moves sideways · ⌘ or Ctrl + scroll zooms · arrow keys
          follow the arrows · v shows the table
        </span>
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
  /** The ticket whose panel is open (its ref): the flow lights its chain. */
  chosen?: string | null | undefined;
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
  chosen = null,
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
            a blocker to the ticket it holds back. Choose a ticket to see its whole chain.
            {epics.length > 0 && " The epic only tracks them, so it is in no group."}
          </span>
        </div>
        <div className="ah-row" style={{ gap: 8, alignItems: "flex-start" }}>
          <ReadinessSummary tickets={work} />
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
          chosen={chosen}
          legend={<FlowLegend showCritical={critical.size > 0} />}
        />
      )}
    </section>
  );
}
