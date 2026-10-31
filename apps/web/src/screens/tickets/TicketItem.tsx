/* One ticket's row: the Tickets list shows it, and so does the Project overview, which must not
 * load the Tickets screen with it (each screen's code loads on demand). */
import "../features/features.css";

import { useId, useState } from "react";
import { Link } from "react-router";

import { Icon, type IconName } from "../../components";
import { fmtAgo, fmtMoney } from "../../lib/format";
import { ticketHref } from "../ticket-detail/routes";
import { SessionLink } from "../feature-detail/TicketsTab";
import { KINDS, type GroupId, type TicketRow } from "./model";

const GROUP_LOOK: Record<GroupId, { icon: IconName | null; color: string | undefined }> = {
  needs: { icon: "hand", color: "var(--waiting)" },
  active: { icon: "circle-play", color: undefined },
  done: { icon: null, color: undefined },
};

function lineOf(row: TicketRow, now: number): string {
  const ago = fmtAgo(Math.max(0, (now - Date.parse(row.lastActivityAt)) / 1000));
  const parts = [
    row.workflows.length ? row.workflows.join(" → ") : "no skill",
    `${String(row.sessions)} session${row.sessions === 1 ? "" : "s"}`,
    row.pr ? `PR #${String(row.pr.number)} ${row.pr.state}` : null,
    row.group === "needs"
      ? (row.latest.waiting_reason ?? "waits on you")
      : row.group === "done"
        ? `ended ${row.latest.outcome ?? ""} ${ago}`.replace(/\s+/g, " ")
        : `active ${ago}`,
  ];
  return parts.filter(Boolean).join(" · ");
}

export function TicketItem({
  row,
  showProject,
  now,
  onOpen,
}: {
  row: TicketRow;
  showProject: boolean;
  now: number;
  onOpen: (href: string) => void;
}) {
  const href = ticketHref(row.project, row.issue);
  const [expanded, setExpanded] = useState(false);
  const sessionsId = useId();
  const featureHref = row.feature
    ? `/features/${encodeURIComponent(row.feature.project)}/${encodeURIComponent(row.feature.slug)}?doc=tickets&ticket=${encodeURIComponent(row.issue)}`
    : null;
  const look = GROUP_LOOK[row.group];
  const line = lineOf(row, now);
  const tags = [...(showProject ? [row.project] : []), ...row.repos];
  const kind = KINDS.find((k) => k.id === row.kind)?.label ?? row.kind;
  return (
    // The row is one keyboard stop (Enter opens), as the Features rows are.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <li
      className="ft-row"
      data-muted={row.group === "done" || undefined}
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={0}
      data-nav-row=""
      aria-label={[row.issue, row.title, kind, line].filter(Boolean).join(". ")}
      onClick={() => {
        onOpen(href);
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter" && event.target === event.currentTarget) onOpen(href);
      }}
    >
      <span className="ft-row-lead" aria-hidden="true" style={{ color: look.color }}>
        {look.icon && <Icon name={look.icon} size="sm" />}
      </span>
      <div className="ft-row-main">
        <div className="ft-row-head">
          {/* A real link, as the Features rows' title, so it opens in a new tab too. */}
          <Link
            to={href}
            className="ft-row-title"
            tabIndex={-1}
            onClick={(event) => {
              event.stopPropagation();
            }}
          >
            {row.issue}
          </Link>
          {row.title && <span className="ft-row-slug">{row.title}</span>}
          <span className="ft-row-tag">{kind}</span>
          {row.feature && featureHref && (
            <Link
              to={featureHref}
              className="ft-row-tag"
              tabIndex={-1}
              title={`Open ${row.issue} in the feature ${row.feature.slug}`}
              onClick={(event) => {
                event.stopPropagation();
              }}
            >
              {row.feature.slug}
            </Link>
          )}
          {tags.map((tag) => (
            <span key={tag} className="ft-row-tag">
              {tag}
            </span>
          ))}
        </div>
        <div
          className="ft-row-line"
          title={line}
          style={row.group === "needs" ? { color: look.color } : undefined}
        >
          {line}
        </div>
        {expanded && (
          // The sessions are reached by pointer here; the keyboard opens the newest from the row.
          // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions
          <div
            id={sessionsId}
            className="tk-sessions"
            onClick={(event) => {
              event.stopPropagation();
            }}
          >
            {row.sessionList.map((session) => (
              <div key={session.id} className="tk-session">
                <SessionLink session={session} />
                <span className="ah-small ah-muted tk-session-what">
                  {[
                    session.label?.title,
                    (session.label?.workflows ?? []).join(" → ") || null,
                    session.cost_usd != null ? fmtMoney(session.cost_usd) : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="ft-row-meta tk-row-meta">
        <button
          type="button"
          className="ah-btn ah-btn-ghost ah-btn-sm tk-sessions-toggle"
          aria-expanded={expanded}
          aria-controls={expanded ? sessionsId : undefined}
          onClick={(event) => {
            event.stopPropagation();
            setExpanded((open) => !open);
          }}
          onKeyDown={(event) => {
            event.stopPropagation();
          }}
        >
          {row.sessions} session{row.sessions === 1 ? "" : "s"}
          <Icon name={expanded ? "chevron-down" : "chevron-right"} size="sm" />
        </button>
        <span className="ah-small ah-muted ah-mono">{fmtMoney(row.costUsd)}</span>
      </div>
    </li>
  );
}
