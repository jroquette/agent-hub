/* The list view: one table per status group, labelled columns, a status badge and a visible action on every row. */
import { useState, type ReactNode } from "react";

import {
  AppLink,
  Button,
  Icon,
  IssueLink,
  Money,
  PathText,
  ProblemError,
  Skeleton,
  StatusBadge,
} from "../../components";
import { useNow } from "../../lib/clock";
import { fmtAgo, fmtClock, fmtInt } from "../../lib/format";
import { rowHref } from "./drivenRows";
import { readStored } from "../../lib/storage";
import { reviewedKey } from "../agent-session/FilesPanel";
import { filesToReview, rowTitle, rowView, summaryOf, type Tone, type ViewContext } from "./inbox";
import type { AgentSession } from "./queries";
import { openHref } from "./rows";
import { isDriven, type SectionId, type SectionRow } from "./sections";
import { waitingLink } from "./tiles";

type Tz = "local" | "utc";

/** Finished shows this many rows until the owner asks for more. */
export const FINISHED_PREVIEW = 5;

/** What each group asks of the owner, and the order of its rows. */
const HINT: Record<SectionId, string> = {
  waiting: "Answer so the agent can continue · oldest first",
  live: "Claude is on it, nothing to do yet · latest first",
  idle: "Claude finished its turn: check the work or send your next message · latest first",
  ended: "Newest first",
};

/** The columns of every group's table; the widths live in sessions-list.css. */
const COLUMNS = [
  { id: "status", label: "Status" },
  { id: "session", label: "Session" },
  { id: "where", label: "Where" },
  { id: "cost", label: "Cost", title: "Estimated from transcript usage" },
  {
    id: "time",
    label: "Last activity",
    title:
      "When the session last did something. Needs you: when it asked. Finished: when it ended.",
  },
  { id: "action", label: "Action" },
] as const;

function Cols() {
  return (
    <colgroup>
      {COLUMNS.map((column) => (
        <col key={column.id} className={`sl-col-${column.id}`} />
      ))}
    </colgroup>
  );
}

/** The one visible header row over all groups; each group's table names its columns for readers. */
export function ColumnHeader() {
  return (
    <table className="sl-table sl-table-head" aria-hidden="true">
      <Cols />
      <thead>
        <tr>
          {COLUMNS.map((column) => (
            <th
              key={column.id}
              className={`sl-th-${column.id}`}
              title={"title" in column ? column.title : undefined}
            >
              {column.id === "action" ? "" : column.label}
            </th>
          ))}
        </tr>
      </thead>
    </table>
  );
}

const plural = (n: number, word: string) => `${String(n)} ${word}${n === 1 ? "" : "s"}`;

/** The files you marked viewed in a chat's files panel, kept in this browser (FilesPanel). */
function readReviewed(sessionId: string): Record<string, string> {
  try {
    const value: unknown = JSON.parse(readStored(reviewedKey(sessionId)) ?? "{}");
    if (!value || typeof value !== "object") return {};
    return Object.fromEntries(
      Object.entries(value).filter((pair): pair is [string, string] => typeof pair[1] === "string"),
    );
  } catch {
    return {};
  }
}

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
  const talk = view.conversation;
  const files = ctx.drv ? filesToReview(summaryOf(ctx.drv).files, readReviewed(ctx.drv.id)) : null;
  const title = rowTitle(row);
  const named = isDriven(row) || Boolean(row.label?.title?.trim());
  const href = openHref(row);
  const lineId = `sl-line-${row.id}`;
  const cost = row.cost_usd;
  const where = view.where;
  const stop = (event: { stopPropagation: () => void }) => {
    event.stopPropagation();
  };
  let action: ReactNode;
  if (view.action === "answer") {
    action = (
      <AppLink
        href={isDriven(row) ? rowHref(row) : waitingLink(row).href}
        className="ah-btn ah-btn-sm ah-btn-primary"
        aria-label={`Answer ${title}`}
        onClick={stop}
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
        onClick={stop}
      >
        Review problem
      </AppLink>
    );
  } else if (view.resumable && ctx.drv && ctx.canDrive) {
    action = (
      <AppLink
        href={rowHref(row)}
        className="ah-btn ah-btn-sm"
        aria-label={`Resume ${title}`}
        onClick={stop}
      >
        <Icon name="play" size="sm" />
        Resume
      </AppLink>
    );
  } else {
    const chat = view.origin === "chat" && href.startsWith("/agent-sessions/");
    action = (
      <AppLink
        href={href}
        className="ah-btn ah-btn-sm ah-btn-ghost"
        aria-label={`${chat ? "Open chat" : "Open session"} ${title}`}
        onClick={stop}
      >
        {chat ? "Open chat" : "Open"}
        <Icon name="chevron-right" size="sm" />
      </AppLink>
    );
  }
  const place = [where.project, where.repo].filter(Boolean).join(" / ");
  const placeText = where.branch ? (place ? `${place} · ${where.branch}` : where.branch) : place;
  const hasExtra = Boolean(where.issue ?? where.run) || (files !== null && files.total > 0);
  const activity = (
    <div
      className="sl-row-line"
      style={view.lineTone ? { color: TONE[view.lineTone] } : undefined}
      title={
        view.inferred
          ? `${view.line} · No end signal arrived. agent-hub assumes the session closed.`
          : view.line
      }
    >
      {view.icon && <Icon name={view.icon} size="sm" />}
      <span className="sl-row-say">{view.line}</span>
      {view.detail && (
        <span className="sl-row-detail ah-mono">
          <PathText path={view.detail} max={72} />
        </span>
      )}
    </div>
  );
  return (
    // The row is one keyboard stop (j/k move between rows, Enter opens), as the session tiles are.
    <tr
      className="sl-row"
      data-nav-row=""
      data-key={row.id}
      data-group-row={group}
      data-trouble={view.lineTone === "failed" || undefined}
      data-muted={group === "ended" || undefined}
      tabIndex={0}
      aria-label={`${title}. ${view.status.label}. ${view.line}`}
      onClick={(event) => {
        // A link inside the row (the issue) goes where it says, not to the session.
        if (event.target instanceof Element && event.target.closest("a")) return;
        onOpen(href);
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter" && event.target === event.currentTarget) onOpen(href);
      }}
    >
      <td className="sl-cell-status">
        <StatusBadge
          status={view.status.status}
          label={view.status.label}
          inferred={view.inferred}
        />
      </td>
      <td className="sl-cell-session">
        <div className="sl-row-head">
          <AppLink
            href={href}
            className={named ? "sl-row-title" : "sl-row-title ah-mono"}
            title={title}
            aria-describedby={lineId}
            tabIndex={-1}
            onClick={stop}
          >
            {title}
          </AppLink>
          <span
            className="sl-row-tag"
            data-origin={view.origin}
            title={
              view.origin === "chat"
                ? "Started from the app: opens the chat"
                : "Observed from a terminal session"
            }
          >
            <Icon name={view.origin === "chat" ? "message-square" : "square-terminal"} size="sm" />
            {view.origin === "chat" ? "Chat" : "Terminal"}
          </span>
          {view.mode && <span className="sl-row-tag">{view.mode}</span>}
        </div>
        <div id={lineId}>
          {talk ? (
            <div className="sl-talk">
              {talk.prompt && (
                <div className="sl-talk-line" title={talk.prompt}>
                  <span className="sl-talk-who">You</span>
                  <span className="sl-talk-text">{talk.prompt}</span>
                </div>
              )}
              {group === "live" ? (
                <div className="sl-talk-line">
                  <span className="sl-talk-who">Claude</span>
                  {activity}
                </div>
              ) : (
                <div
                  className="sl-talk-line"
                  title={talk.reply ?? view.line}
                  style={view.lineTone ? { color: TONE[view.lineTone] } : undefined}
                >
                  <span className="sl-talk-who">Claude</span>
                  <span className="sl-talk-text sl-talk-reply">{talk.reply ?? view.line}</span>
                </div>
              )}
            </div>
          ) : (
            activity
          )}
        </div>
      </td>
      <td className="sl-cell-where">
        <div className="sl-where-place ah-mono" title={placeText || undefined}>
          {placeText || (
            <span className="ah-subtle" title="No repo recorded for this session.">
              —
            </span>
          )}
        </div>
        {hasExtra && (
          <div className="sl-where-extra">
            {where.issue && <IssueLink id={where.issue} />}
            {where.run && <span className="sl-where-run">{where.run}</span>}
            {files && files.total > 0 && (
              <span
                className="sl-files"
                data-due={files.toReview > 0 || undefined}
                title={
                  files.toReview > 0
                    ? `${plural(files.total, "file")} changed; ${String(files.toReview)} changed since you last viewed them in the chat`
                    : `${plural(files.total, "file")} changed, all viewed`
                }
              >
                <Icon name="file-pen" size="sm" />
                {files.toReview > 0
                  ? `${plural(files.total, "file")} · ${String(files.toReview)} to review`
                  : plural(files.total, "file")}
              </span>
            )}
          </div>
        )}
      </td>
      <td className="sl-cell-cost">
        {cost ? (
          <Money value={cost} />
        ) : (
          <span
            className="ah-subtle"
            title={
              isDriven(row)
                ? "Cost appears after the first turn ends."
                : (row.cost_unknown_reason ?? "Cost appears after the first turn ends.")
            }
          >
            —
          </span>
        )}
      </td>
      <td className="sl-cell-time">
        {view.time ? <When iso={view.time} tip={view.timeTip} tz={tz} /> : null}
      </td>
      <td className="sl-cell-action">{action}</td>
    </tr>
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
        {open && <span className="sl-group-hint">{hint}</span>}
      </h2>
      {open && (
        <>
          {group.pending && (
            <table className="sl-table sl-rows" aria-hidden="true">
              <Cols />
              <tbody>
                {Array.from({ length: 3 }, (_, i) => (
                  <tr key={i} className="sl-row sl-row-skeleton">
                    <td>
                      <Skeleton width={96} />
                    </td>
                    <td>
                      <Skeleton width="50%" />
                      <Skeleton width="75%" />
                    </td>
                    <td>
                      <Skeleton width="70%" />
                    </td>
                    <td>
                      <Skeleton width={40} />
                    </td>
                    <td>
                      <Skeleton width={56} />
                    </td>
                    <td />
                  </tr>
                ))}
              </tbody>
            </table>
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
            <table className="sl-table sl-rows">
              <caption className="ah-sr">{`${title} sessions`}</caption>
              <Cols />
              <thead className="sl-thead-sr">
                <tr>
                  {COLUMNS.map((column) => (
                    <th key={column.id} scope="col">
                      {column.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
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
              </tbody>
            </table>
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
      <ColumnHeader />
      {props.groups.map((group) => (
        <Group key={group.id} group={group} tz={props.tz} props={props} />
      ))}
    </div>
  );
}
