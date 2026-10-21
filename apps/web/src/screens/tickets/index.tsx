import "../features/features.css";

import { useMemo, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router";

import {
  DerivedLabel,
  EmptyState,
  FacetMenu,
  Icon,
  ProblemError,
  Skeleton,
  type IconName,
} from "../../components";
import { useApi } from "../../lib/api";
import { fmtAgo, fmtMoney } from "../../lib/format";
import { useScope } from "../../lib/scope";
import { useRowKeys } from "../../lib/useRowKeys";
import { useTicketLookup } from "../features/queries";
import { StartTicketControl } from "./StartTicket";
import { GROUPS, KINDS, matchesQuery, ticketsOf, type GroupId, type TicketRow } from "./model";

/** How many of the newest sessions the list groups (the API's page limit). */
export const SESSIONS_READ = 200;
const REFRESH_MS = 10_000;

const GROUP_LOOK: Record<GroupId, { icon: IconName | null; color: string | undefined }> = {
  needs: { icon: "hand", color: "var(--waiting)" },
  active: { icon: "circle-play", color: undefined },
  done: { icon: null, color: undefined },
};

const listOf = (raw: string | null): string[] => (raw ? raw.split(",").filter(Boolean) : []);

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
  const href = `/sessions/${encodeURIComponent(row.latest.id)}`;
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
          <span className="ft-row-title">{row.issue}</span>
          {row.title && <span className="ft-row-slug">{row.title}</span>}
          <span className="ft-row-tag">{kind}</span>
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
      </div>
      <div className="ft-row-meta">
        <span className="ah-small ah-muted ah-mono">{fmtMoney(row.costUsd)}</span>
      </div>
    </li>
  );
}

/** Tickets list: the single-ticket work (/fix, /refactor, /upgrade, …) the sessions did, by ticket. */
export function TicketsScreen() {
  const [scope] = useScope();
  const sessions = useApi(
    "/api/v1/sessions",
    {
      query: {
        ...(scope ? { project: scope } : {}),
        limit: SESSIONS_READ,
        sort: "-last_activity_at",
      },
    },
    { refetchInterval: REFRESH_MS },
  );
  const lookup = useTicketLookup(scope);
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const screenRef = useRef<HTMLDivElement>(null);
  useRowKeys(screenRef);

  const all = useMemo(
    () => ticketsOf(sessions.data?.items ?? [], new Set(lookup.keys())),
    [sessions.data, lookup],
  );
  const q = params.get("q") ?? "";
  const kinds = listOf(params.get("kind"));
  const rows = all.filter(
    (row) => matchesQuery(row, q) && (kinds.length === 0 || kinds.includes(row.kind)),
  );
  const filtered = q.trim() !== "" || kinds.length > 0;
  const projects = new Set(all.map((row) => row.project));
  // Ages are read against the last fetch, so a render stays pure.
  const now = sessions.dataUpdatedAt;
  const set = (key: "q" | "kind", value: string) => {
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (value) next.set(key, value);
        else next.delete(key);
        return next;
      },
      { replace: true },
    );
  };

  return (
    <div ref={screenRef} style={{ padding: "16px 32px 40px" }} className="ah-stack">
      <div className="ft-head">
        <div className="ft-title">
          <h1 className="ah-h1">Tickets</h1>
          <StartTicketControl scope={scope} />
        </div>
        {sessions.isSuccess && all.length > 0 && (
          <p className="ft-summary">
            {GROUPS.map((g) => (
              <span key={g.id} data-group={g.id === "needs" ? "needs" : undefined}>
                <b>{all.filter((row) => row.group === g.id).length}</b> {g.summary}
              </span>
            ))}
            <DerivedLabel
              how={`Grouped by tracker issue from the newest ${String(SESSIONS_READ)} sessions: the issue their first prompt (/fix ACME-12), branch or worktree names. Tickets of a feature show under Features.`}
            >
              derived
            </DerivedLabel>
          </p>
        )}
      </div>
      {sessions.isError && !sessions.data ? (
        <ProblemError
          title={sessions.error.title}
          detail={sessions.error.detail}
          status={sessions.error.status}
          onRetry={() => void sessions.refetch()}
        />
      ) : sessions.isSuccess && all.length === 0 ? (
        <div className="ah-card">
          <EmptyState icon="list-todo" title="No ticket work yet." command="/fix AGH-112">
            A ticket shows here once a session works on it outside a feature: start one with{" "}
            <span className="ah-mono">/fix</span>, <span className="ah-mono">/refactor</span>,{" "}
            <span className="ah-mono">/upgrade</span> or <span className="ah-mono">/incident</span>{" "}
            and the issue id, or on a branch named after the issue.
          </EmptyState>
        </div>
      ) : (
        <>
          <div className="ft-toolbar" role="group" aria-label="Filters">
            <div className="ah-search ft-search">
              <Icon name="search" size="sm" />
              <input
                type="search"
                className="ah-input"
                aria-label="Find tickets"
                placeholder="Find by issue, title, repo or skill"
                value={q}
                onChange={(event) => {
                  set("q", event.target.value);
                }}
              />
            </div>
            <FacetMenu
              label="Kind"
              options={KINDS.map((k) => ({
                id: k.id,
                label: k.label,
                count: all.filter((row) => row.kind === k.id && matchesQuery(row, q)).length,
                checked: kinds.includes(k.id),
              }))}
              onToggle={(id) => {
                const next = kinds.includes(id) ? kinds.filter((k) => k !== id) : [...kinds, id];
                set("kind", next.join(","));
              }}
              onClear={() => {
                set("kind", "");
              }}
            />
            {filtered && sessions.isSuccess && (
              <span className="ah-small ah-muted" role="status">
                {rows.length} of {all.length} ticket{all.length === 1 ? "" : "s"}
              </span>
            )}
          </div>
          <div className="ft-groups">
            {GROUPS.map((g) => {
              const list = sessions.isSuccess ? rows.filter((row) => row.group === g.id) : null;
              if (filtered && list?.length === 0) return null;
              const headId = `tk-group-${g.id}`;
              return (
                <section key={g.id} className="ft-group" aria-labelledby={headId}>
                  <div className="ft-group-head">
                    <h2 className="ft-group-title" id={headId}>
                      {g.title} · <span className="ft-group-count">{list?.length ?? "…"}</span>
                    </h2>
                  </div>
                  {list === null ? (
                    <ul className="ft-rows ft-card" aria-hidden="true">
                      {Array.from({ length: 3 }, (_, i) => (
                        <li key={i} className="ft-row" style={{ cursor: "default" }}>
                          <span className="ft-row-lead" />
                          <div className="ft-row-main">
                            <Skeleton width="40%" />
                            <Skeleton width="60%" />
                          </div>
                        </li>
                      ))}
                    </ul>
                  ) : list.length === 0 ? (
                    <div className="ft-empty">{g.empty}</div>
                  ) : (
                    <div className="ft-card">
                      <ul className="ft-rows" aria-labelledby={headId}>
                        {list.map((row) => (
                          <TicketItem
                            key={`${row.project}/${row.issue}`}
                            row={row}
                            showProject={projects.size > 1}
                            now={now}
                            onOpen={(href) => void navigate(href)}
                          />
                        ))}
                      </ul>
                    </div>
                  )}
                </section>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
