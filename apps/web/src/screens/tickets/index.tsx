import "../features/features.css";

import { useMemo, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router";

import {
  DerivedLabel,
  EmptyState,
  FacetMenu,
  ProblemError,
  SearchField,
  Skeleton,
} from "../../components";
import { useApi } from "../../lib/api";
import { useScope } from "../../lib/scope";
import { useRowKeys } from "../../lib/useRowKeys";
import { useTicketLookup } from "../features/queries";
import { StartTicketControl } from "./StartTicket";
import { TicketItem } from "./TicketItem";
import { GROUPS, KINDS, SESSIONS_READ, matchesQuery, ticketsOf } from "./model";

const REFRESH_MS = 10_000;

const listOf = (raw: string | null): string[] => (raw ? raw.split(",").filter(Boolean) : []);

/** Tickets list: every ticket the sessions worked on (/fix, /refactor, a feature's tickets, …), by ticket. */
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

  const all = useMemo(() => ticketsOf(sessions.data?.items ?? [], lookup), [sessions.data, lookup]);
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
              how={`Grouped by tracker issue from the newest ${String(SESSIONS_READ)} sessions: the issue their first prompt (/fix ACME-12), branch or worktree names. A feature's ticket names its feature.`}
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
            A ticket shows here once a session works on it: start one with{" "}
            <span className="ah-mono">/fix</span>, <span className="ah-mono">/refactor</span>,{" "}
            <span className="ah-mono">/upgrade</span> or <span className="ah-mono">/incident</span>{" "}
            and the issue id, or on a branch named after the issue.
          </EmptyState>
        </div>
      ) : (
        <>
          <div className="ft-toolbar" role="group" aria-label="Filters">
            <SearchField
              value={q}
              onChange={(value) => {
                set("q", value);
              }}
              label="Find tickets"
              placeholder="Find by issue, title, repo or skill"
              className="ft-search"
            />
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
