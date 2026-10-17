/* The list view as an inbox (v2 design): four plain groups, each row a title and one useful line. */
import { useState, type ReactNode } from "react";

import { AppLink, Button, Icon, IssueLink, Money, ProblemError, Skeleton } from "../../components";
import { useNow } from "../../lib/clock";
import { fmtAgo, fmtClock, fmtInt } from "../../lib/format";
import { rowHref } from "./drivenRows";
import { rowTitle, rowView, type RowView, type Tone, type ViewContext } from "./inbox";
import type { AgentSession } from "./queries";
import { openHref } from "./rows";
import { isDriven, type SectionId, type SectionRow } from "./sections";
import { waitingLink } from "./tiles";

type Tz = "local" | "utc";

/** Finished shows this many rows until the owner asks for more. */
export const FINISHED_PREVIEW = 5;

const HINT: Partial<Record<SectionId, string>> = {
  idle: "The agent finished its turn and waits for your next message.",
};

export interface InboxGroup {
  id: SectionId;
  title: string;
  /** Null while it loads. */
  count: number | null;
  approximate: boolean;
  collapsed: boolean;
  /** Only this group shows (an old `status=` link): it cannot collapse. */
  fixed: boolean;
  updating: boolean;
  pending: boolean;
  error: {
    detail?: string | null | undefined;
    status?: number | undefined;
    type?: string | undefined;
    instance?: string | null | undefined;
  } | null;
  rows: SectionRow[];
  hasNextPage: boolean;
  loadingMore: boolean;
  onToggle: () => void;
  onRetry: () => void;
  onLoadMore: (() => void) | null;
}

export interface SessionsInboxProps {
  groups: InboxGroup[];
  tz: Tz;
  showProject: boolean;
  commonRepo: string | null;
  drvOf: (row: SectionRow) => AgentSession | null;
  /** Sessions can start here: a finished chat may offer Resume. */
  canDrive: boolean;
  onOpen: (href: string) => void;
  /** The Finished header names the period, so its scope is never hidden. */
  endedScope: string | null;
}

const TONE: Record<Tone, string> = {
  waiting: "var(--waiting)",
  failed: "var(--failed)",
  done: "var(--done)",
  blocked: "var(--blocked)",
  subtle: "var(--text-subtle)",
  live: "var(--live)",
};

function When({ iso, tip, tz }: { iso: string; tip: string; tz: Tz }) {
  const now = useNow(30_000);
  const age = Math.max(0, (now - Date.parse(iso)) / 1000);
  const absolute = `${new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short" })} ${fmtClock(iso, tz)}`;
  const shown = age < 60 ? "now" : age < 86_400 ? fmtAgo(age) : absolute;
  return (
    <time className="sl-row-time" dateTime={iso} title={`${tip} ${absolute}`}>
      {shown}
    </time>
  );
}

function Lead({ lead }: { lead: RowView["lead"] }) {
  if (lead === null) return <span className="sl-row-lead" aria-hidden="true" />;
  if (lead === "pulse")
    return (
      <span className="sl-row-lead" aria-hidden="true">
        <span className="ah-dot ah-pulse" style={{ background: "var(--live)" }} />
      </span>
    );
  return (
    <span className="sl-row-lead" aria-hidden="true" style={{ color: TONE[lead.tone] }}>
      <Icon name={lead.icon} size="sm" />
    </span>
  );
}

function Row({
  row,
  group,
  tz,
  ctx,
  onOpen,
}: {
  row: SectionRow;
  group: SectionId;
  tz: Tz;
  ctx: Omit<ViewContext, "group" | "drv"> & { drv: AgentSession | null; canDrive: boolean };
  onOpen: (href: string) => void;
}) {
  const view = rowView(row, { ...ctx, group });
  const title = rowTitle(row);
  const named = isDriven(row) || Boolean(row.label?.title?.trim());
  const href = openHref(row);
  const lineId = `sl-line-${row.id}`;
  const issue = isDriven(row) ? null : (row.label?.issue ?? row.issue ?? null);
  const cost = row.cost_usd;
  let action: ReactNode = null;
  if (view.action === "answer") {
    action = (
      <AppLink
        href={isDriven(row) ? rowHref(row) : waitingLink(row).href}
        className="ah-btn ah-btn-sm ah-btn-primary"
        aria-label={`Answer ${title}`}
        onClick={(event) => {
          event.stopPropagation();
        }}
      >
        Answer
      </AppLink>
    );
  } else if (view.action === "review") {
    action = (
      <AppLink
        href={`/sessions/${encodeURIComponent(row.id)}`}
        className="ah-btn ah-btn-sm"
        aria-label={`Review problem in ${title}`}
        onClick={(event) => {
          event.stopPropagation();
        }}
      >
        Review problem
      </AppLink>
    );
  } else if (view.resumable && ctx.drv && ctx.canDrive) {
    action = (
      <AppLink
        href={rowHref(row)}
        className="ah-btn ah-btn-sm ah-btn-ghost sl-row-hover"
        aria-label={`Resume ${title}`}
        onClick={(event) => {
          event.stopPropagation();
        }}
      >
        <Icon name="play" size="sm" />
        Resume
      </AppLink>
    );
  } else {
    action = (
      <span className="sl-row-hover sl-row-chevron" aria-hidden="true">
        <Icon name="chevron-right" size="sm" />
      </span>
    );
  }
  return (
    // The row is one keyboard stop (j/k move between rows, Enter opens), as the session tiles are.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <li
      className="sl-row"
      data-nav-row=""
      data-key={row.id}
      data-group-row={group}
      data-trouble={view.lineTone === "failed" || undefined}
      data-muted={group === "ended" || undefined}
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={0}
      aria-label={`${title}. ${view.line}`}
      onClick={() => {
        onOpen(href);
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter" && event.target === event.currentTarget) onOpen(href);
      }}
    >
      <Lead lead={view.lead} />
      <div className="sl-row-main">
        <div className="sl-row-head">
          <AppLink
            href={href}
            className={named ? "sl-row-title" : "sl-row-title ah-mono"}
            title={title}
            aria-describedby={lineId}
            tabIndex={-1}
            onClick={(event) => {
              event.stopPropagation();
            }}
          >
            {title}
          </AppLink>
          {view.tags.map((tag) => (
            <span key={tag} className="sl-row-tag">
              {tag}
            </span>
          ))}
        </div>
        <div
          id={lineId}
          className="sl-row-line"
          style={view.lineTone ? { color: TONE[view.lineTone] } : undefined}
          title={
            view.inferred
              ? `${view.line} · No end signal arrived. agent-hub assumes the session closed.`
              : view.line
          }
        >
          {view.line}
        </div>
      </div>
      <div className="sl-row-meta">
        <span className="sl-row-issue">{issue && <IssueLink id={issue} />}</span>
        <span className="sl-row-cost">
          {cost ? (
            <Money value={cost} />
          ) : group === "waiting" || group === "live" ? null : (
            <span
              className="ah-subtle"
              title={
                isDriven(row)
                  ? "Cost appears after the first turn ends."
                  : (row.cost_unknown_reason ?? "Cost unknown.")
              }
            >
              —
            </span>
          )}
        </span>
        {view.time ? <When iso={view.time} tip={view.timeTip} tz={tz} /> : <span />}
        <span className="sl-row-action">{action}</span>
      </div>
    </li>
  );
}

function Group({ group, tz, props }: { group: InboxGroup; tz: Tz; props: SessionsInboxProps }) {
  const [expanded, setExpanded] = useState(false);
  const open = group.fixed || !group.collapsed;
  const shown =
    group.count === null ? "…" : `${group.approximate ? "~" : ""}${fmtInt(group.count)}`;
  const title =
    group.id === "ended" && props.endedScope ? `${group.title} · ${props.endedScope}` : group.title;
  const headId = `sl-group-${group.id}`;
  const preview = group.id === "ended" && !expanded && !group.fixed;
  const rows = preview ? group.rows.slice(0, FINISHED_PREVIEW) : group.rows;
  const hidden = group.rows.length - rows.length;
  const hint = HINT[group.id];
  return (
    <section
      className="sl-group"
      aria-labelledby={headId}
      aria-busy={group.updating || undefined}
      data-updating={group.updating || undefined}
      data-group={group.id}
    >
      <h2 className="sl-group-head">
        {group.fixed ? (
          <span id={headId} className="sl-group-title">{`${title} · ${shown}`}</span>
        ) : (
          <button
            type="button"
            id={headId}
            className="sl-group-toggle"
            aria-expanded={open}
            onClick={group.onToggle}
          >
            <Icon name={open ? "chevron-down" : "chevron-right"} size="sm" />
            {`${title} · ${shown}`}
          </button>
        )}
        {group.updating && <span className="sl-group-note">Updating…</span>}
        {hint && open && <span className="sl-group-hint">{hint}</span>}
      </h2>
      {open && (
        <>
          {group.pending && (
            <ul className="sl-rows" aria-hidden="true">
              {Array.from({ length: 3 }, (_, i) => (
                <li key={i} className="sl-row sl-row-skeleton">
                  <span className="sl-row-lead" />
                  <div className="sl-row-main">
                    <Skeleton width="40%" />
                    <Skeleton width="60%" />
                  </div>
                </li>
              ))}
            </ul>
          )}
          {group.error && (
            <ProblemError
              title={`Could not load ${group.title.toLowerCase()} sessions`}
              detail={group.error.detail}
              status={group.error.status}
              type={group.error.type}
              instance={group.error.instance}
              onRetry={group.onRetry}
              compact
            />
          )}
          {!group.pending && rows.length > 0 && (
            <ul className="sl-rows">
              {rows.map((row) => (
                <Row
                  key={row.id}
                  row={row}
                  group={group.id}
                  tz={tz}
                  ctx={{
                    drv: props.drvOf(row),
                    commonRepo: props.commonRepo,
                    showProject: props.showProject,
                    canDrive: props.canDrive,
                  }}
                  onOpen={props.onOpen}
                />
              ))}
            </ul>
          )}
          {hidden > 0 && (
            <button
              type="button"
              className="sl-more-link"
              data-load-more={group.id}
              onClick={() => {
                setExpanded(true);
              }}
            >
              {`Show ${fmtInt(hidden)} more ${group.title.toLowerCase()} ${hidden === 1 ? "session" : "sessions"}`}
            </button>
          )}
          {hidden === 0 && group.hasNextPage && group.count !== null && (
            <div className="sl-more-row ah-small ah-subtle">
              <span>{`Showing ${fmtInt(group.rows.length)} of ~${fmtInt(group.count)}`}</span>
              {group.onLoadMore && (
                <Button
                  size="sm"
                  disabled={group.loadingMore}
                  data-load-more={group.id}
                  onClick={group.onLoadMore}
                >
                  Load more
                </Button>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}

export function SessionsInbox(props: SessionsInboxProps) {
  return (
    <div className="sl-inbox">
      {props.groups.map((group) => (
        <Group key={group.id} group={group} tz={props.tz} props={props} />
      ))}
    </div>
  );
}
