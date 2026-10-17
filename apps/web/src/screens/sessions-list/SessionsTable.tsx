/* The list view: one table, one sticky header, the status sections as row groups (sessions redesign). */
import { useEffect, useState, type ReactNode } from "react";

import { Button, Icon, ProblemError, Skeleton, Tooltip } from "../../components";
import { fmtInt } from "../../lib/format";
import {
  ActionCell,
  CostCell,
  DoingNow,
  DurationCell,
  IssueCell,
  SessionCell,
  StartedCell,
  StatusCell,
  TokensCell,
  TurnsCell,
  needsYou,
} from "./rows";
import type { SectionId, SectionRow } from "./sections";

type Tz = "local" | "utc";
type SortKey = "started_at" | "cost";

interface Column {
  id: string;
  label: ReactNode;
  /** Visually hidden header text (the action column). */
  srLabel?: string;
  width?: number;
  align?: "right";
  sort?: SortKey;
  hint?: string;
  /** Shown only from this viewport width up (column priority, 31-responsive). */
  minWidth?: number;
  render: (row: SectionRow) => ReactNode;
}

export interface TableGroup {
  id: SectionId;
  title: string;
  /** Null while it loads. */
  count: number | null;
  approximate: boolean;
  collapsed: boolean;
  /** Only one group shows (a status tab): it cannot collapse. */
  fixed: boolean;
  updating: boolean;
  pending: boolean;
  error: {
    detail?: string | null;
    status?: number;
    type?: string;
    instance?: string | null;
  } | null;
  rows: SectionRow[];
  hasNextPage: boolean;
  loadingMore: boolean;
  onToggle: () => void;
  onRetry: () => void;
  onLoadMore: (() => void) | null;
}

export interface SessionsTableProps {
  groups: TableGroup[];
  tz: Tz;
  showProject: boolean;
  sort: string;
  onSort: (key: SortKey) => void;
  onOpen: (row: SectionRow) => void;
  resume: (row: SectionRow) => ReactNode;
  /** The Ended group's title names the period, so its scope is never hidden. */
  endedScope: string;
}

const KEY = (row: SectionRow) => row.id;

function useViewportWidth(): number {
  const [width, setWidth] = useState(() => window.innerWidth);
  useEffect(() => {
    const onResize = () => {
      setWidth(window.innerWidth);
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
    };
  }, []);
  return width;
}

export function SessionsTable({
  groups,
  tz,
  showProject,
  sort,
  onSort,
  onOpen,
  resume,
  endedScope,
}: SessionsTableProps) {
  const all: Column[] = [
    { id: "status", label: "Status", width: 116, render: (row) => <StatusCell row={row} /> },
    {
      id: "session",
      label: "Session",
      render: (row) => <SessionCell row={row} showProject={showProject} />,
    },
    { id: "doing", label: "Doing now", render: (row) => <DoingNow row={row} /> },
    {
      id: "issue",
      label: "Issue",
      width: 88,
      minWidth: 1100,
      render: (row) => <IssueCell row={row} />,
    },
    {
      id: "started",
      label: "Started",
      width: 104,
      minWidth: 900,
      sort: "started_at",
      render: (row) => <StartedCell row={row} tz={tz} />,
    },
    {
      id: "duration",
      label: "Duration",
      width: 100,
      minWidth: 1280,
      align: "right",
      render: (row) => <DurationCell row={row} />,
    },
    {
      id: "turns",
      label: "Turns",
      width: 64,
      minWidth: 1700,
      align: "right",
      render: (row) => <TurnsCell row={row} />,
    },
    {
      id: "tokens",
      label: "Tokens",
      width: 80,
      minWidth: 1700,
      align: "right",
      render: (row) => <TokensCell row={row} />,
    },
    {
      id: "cost",
      label: "Cost",
      width: 76,
      minWidth: 900,
      align: "right",
      sort: "cost",
      hint: "Estimated from transcript",
      render: (row) => <CostCell row={row} />,
    },
    {
      id: "actions",
      label: "",
      srLabel: "Actions",
      width: 128,
      align: "right",
      render: (row) => <ActionCell row={row} resume={resume(row)} />,
    },
  ];
  const viewport = useViewportWidth();
  // Hidden columns are not rendered: a fixed-layout table keeps a slot for every column it has.
  const columns = all.filter((column) => !column.minWidth || viewport >= column.minWidth);
  const span = columns.length;
  const desc = sort.startsWith("-");
  const sortKey = sort.replace("-", "");

  return (
    <div className="sl-list">
      <table className="ah-table sl-table">
        <caption className="ah-sr">Sessions, grouped by status</caption>
        <thead>
          <tr>
            {columns.map((column) => {
              const dir = column.sort && column.sort === sortKey ? (desc ? "desc" : "asc") : null;
              const label = (
                <span
                  className="ah-row"
                  style={{
                    gap: 4,
                    justifyContent: column.align === "right" ? "flex-end" : undefined,
                  }}
                >
                  {column.label}
                  {column.srLabel && <span className="ah-sr">{column.srLabel}</span>}
                  {dir && <Icon name={dir === "asc" ? "arrow-up" : "arrow-down"} size="sm" />}
                  {column.hint && (
                    <Tooltip label={column.hint}>
                      <Icon name="info" size="sm" />
                    </Tooltip>
                  )}
                </span>
              );
              return (
                <th
                  key={column.id}
                  scope="col"
                  className={`sl-col-${column.id}`}
                  style={{ width: column.width, textAlign: column.align }}
                  aria-sort={dir ? (dir === "asc" ? "ascending" : "descending") : undefined}
                >
                  {column.sort ? (
                    <button
                      type="button"
                      className="ah-th-sort"
                      onClick={() => {
                        if (column.sort) onSort(column.sort);
                      }}
                    >
                      {label}
                    </button>
                  ) : (
                    label
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        {groups.map((group) => {
          const shown =
            group.count === null ? "…" : `${group.approximate ? "~" : ""}${fmtInt(group.count)}`;
          const title = group.id === "ended" ? `${group.title} · ${endedScope}` : group.title;
          const headId = `sl-group-${group.id}`;
          const open = group.fixed || !group.collapsed;
          return (
            <tbody
              key={group.id}
              aria-labelledby={headId}
              aria-busy={group.updating || undefined}
              data-updating={group.updating || undefined}
              data-group={group.id}
            >
              <tr className="sl-group-row">
                <th scope="rowgroup" colSpan={span}>
                  {/* The header names the group and takes focus when a focused row leaves it. */}
                  {group.fixed ? (
                    <span className="sl-group-title" id={headId}>{`${title} · ${shown}`}</span>
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
                  {group.updating && <span className="sl-group-updating ah-muted">Updating…</span>}
                </th>
              </tr>
              {open &&
                group.pending &&
                Array.from({ length: 3 }, (_, i) => (
                  <tr key={`skeleton-${String(i)}`} aria-hidden="true" className="sl-skeleton">
                    {columns.map((column) => (
                      <td key={column.id} className={`sl-col-${column.id}`}>
                        <Skeleton width={column.align === "right" ? 48 : "70%"} />
                      </td>
                    ))}
                  </tr>
                ))}
              {open && group.error && (
                <tr className="sl-static">
                  <td colSpan={span} style={{ padding: "var(--space-3)", whiteSpace: "normal" }}>
                    <ProblemError
                      title={`Could not load ${group.title.toLowerCase()} sessions`}
                      detail={group.error.detail ?? undefined}
                      status={group.error.status}
                      type={group.error.type}
                      instance={group.error.instance ?? undefined}
                      onRetry={group.onRetry}
                      compact
                    />
                  </td>
                </tr>
              )}
              {open &&
                !group.pending &&
                group.rows.map((row) => (
                  <tr
                    key={KEY(row)}
                    data-key={KEY(row)}
                    data-nav-row=""
                    data-trouble={needsYou(row) || undefined}
                    tabIndex={0}
                    onClick={() => {
                      onOpen(row);
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && event.target === event.currentTarget)
                        onOpen(row);
                    }}
                  >
                    {columns.map((column) => (
                      <td
                        key={column.id}
                        className={`sl-col-${column.id}${column.align === "right" ? " ah-r" : ""}`}
                      >
                        {column.render(row)}
                      </td>
                    ))}
                  </tr>
                ))}
              {open && group.hasNextPage && group.count !== null && (
                <tr className="sl-static sl-more-row">
                  <td colSpan={span}>
                    <span className="ah-small ah-subtle">
                      {`Showing ${fmtInt(group.rows.length)} of ~${fmtInt(group.count)} ${group.title.toLowerCase()} sessions`}
                    </span>
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
                  </td>
                </tr>
              )}
            </tbody>
          );
        })}
      </table>
    </div>
  );
}
