import "./sessions-list.css";

import { useEffect, useMemo, useRef, useState, type RefObject } from "react";
import { useNavigate, useSearchParams } from "react-router";

import { AsOfStamp, Button, EmptyState, Icon, SegmentedControl, Skeleton } from "../../components";
import { fmtClock, fmtInt } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { useScope } from "../../lib/scope";
import { readStored, writeStored } from "../../lib/storage";
import { useCollectorState } from "../../shell/GlobalStream";
import { typingIn } from "../../shell/goSequence";
import {
  CloudSessions,
  DrivenBanner,
  NewSessionControl,
  useDriving,
  useResumeLink,
} from "./DrivenControls";
import { rowHref } from "./drivenRows";
import { FILTER_KEYS, STATUSES, periodOf, viewOf, withinOf, type View } from "./filters";
import { GridSection } from "./GridSection";
import { LiveDigest } from "./LiveDigest";
import {
  useAgentSessions,
  useProjects,
  useSectionPages,
  useSectionRefresh,
  type Session,
} from "./queries";
import { commonRepoOf, orderRows } from "./inbox";
import { fold, searchText } from "./rows";
import {
  SECTIONS,
  isDriven,
  placeDriven,
  sectionCount,
  sectionQueries,
  type SectionId,
  type SectionRow,
} from "./sections";
import { SessionSection, useCollapsed } from "./SessionSection";
import { SessionsInbox, type InboxGroup } from "./SessionsInbox";
import { Toolbar, periodLabel } from "./Toolbar";
import { useScrollAnchor } from "./useScrollAnchor";

const VIEW_KEY = "ah.sessions.view";
/** The session's issue: the label's (S1), else the run's. */
const issueOf = (s: Session) => s.label?.issue ?? s.issue ?? null;

function csvOf(rows: Session[]): string {
  const head = [
    "id",
    "started_at",
    "ended_at",
    "project",
    "repo",
    "branch",
    "issue",
    "workflow",
    "run_id",
    "status",
    "outcome",
    "turns",
    "cost_usd",
    "files_touched",
    "errors",
    "guard_denials",
  ];
  const cell = (value: string | number | null | undefined) => {
    const text = value === null || value === undefined ? "" : String(value);
    return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  const lines = rows.map((s) =>
    [
      s.id,
      s.started_at,
      s.ended_at,
      s.project,
      s.repo,
      s.label?.branch,
      issueOf(s),
      s.label?.workflow,
      s.run_id,
      s.status,
      s.outcome,
      s.turns,
      s.cost_usd,
      s.files_touched,
      s.errors,
      s.guard_denials,
    ]
      .map(cell)
      .join(","),
  );
  return [head.join(","), ...lines].join("\n");
}

function download(name: string, text: string): void {
  if (typeof URL.createObjectURL !== "function") return;
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

/** The stale stamp while the collector is offline; its second clock re-renders only this stamp. */
function OfflineStamp({ tz }: { tz: "local" | "utc" }) {
  const collector = useCollectorState();
  return collector.state === "offline" ? (
    <AsOfStamp stale time={fmtClock(collector.asOf, tz)} source="collector heartbeat" />
  ) : null;
}

/** The grid or the list: the URL's `view`, else `ah.sessions.view`, else the list; `v` switches. */
function useView(
  params: URLSearchParams,
  update: (changes: Record<string, string | null>) => void,
): [View, (view: View) => void] {
  const [stored, setStored] = useState(() => readStored(VIEW_KEY));
  const view = viewOf(params, stored);
  const setView = (next: View) => {
    writeStored(VIEW_KEY, next);
    setStored(next);
    update({ view: next });
  };
  const latest = useRef({ view, setView });
  useEffect(() => {
    latest.current = { view, setView };
  });
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "v" || event.defaultPrevented) return;
      if (event.ctrlKey || event.metaKey || event.altKey || typingIn(event.target)) return;
      latest.current.setView(latest.current.view === "grid" ? "list" : "grid");
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, []);
  return [view, setView];
}

const NAV = "[data-nav-row], .ah-tile";

/** `j` / `k` move across rows and tiles of every group; `o` opens; `l` loads more in the focused group. */
function useRowKeys(root: RefObject<HTMLDivElement | null>) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
      if (typingIn(event.target)) return;
      const el = root.current;
      if (!el) return;
      const items = [...el.querySelectorAll<HTMLElement>(NAV)];
      const active = document.activeElement;
      const at = items.findIndex((item) => item === active || item.contains(active));
      if (event.key === "j" || event.key === "k") {
        if (items.length === 0) return;
        event.preventDefault();
        const next =
          at < 0
            ? event.key === "j"
              ? 0
              : items.length - 1
            : Math.min(items.length - 1, Math.max(0, at + (event.key === "j" ? 1 : -1)));
        items[next]?.focus();
        items[next]?.scrollIntoView({ block: "nearest" });
      } else if (event.key === "o" && at >= 0) {
        event.preventDefault();
        items[at]?.click();
      } else if (event.key === "l" && at >= 0) {
        const group = items[at]?.closest("[data-group]");
        const more = group?.querySelector<HTMLButtonElement>("[data-load-more]");
        if (more && !more.disabled) {
          event.preventDefault();
          more.click();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, [root]);
}

function plural(n: number, one: string, many: string): string {
  return `${fmtInt(n)} ${n === 1 ? one : many}`;
}

/** Sessions: "Does any session need me right now, and which one do I open?" */
export function SessionsListScreen() {
  const [params, setParams] = useSearchParams();
  const [scope] = useScope();
  const navigate = useNavigate();
  const { tz } = usePreferences();
  const [anchor] = useState(() => Date.now());
  const queries = useMemo(() => sectionQueries(params, scope, anchor), [params, scope, anchor]);
  const sections = useSectionPages(queries);
  const [collapsed, toggleCollapsed] = useCollapsed();
  // The same query as the driven rows' list: its poll also refreshes the sections (AC-234.9).
  const agentsUpdatedAt = useAgentSessions(scope).dataUpdatedAt;
  const askedIds = SECTIONS.map((section) => section.id).filter((id) => queries[id] !== null);
  const screenRef = useRef<HTMLDivElement>(null);
  useRowKeys(screenRef);
  const arm = useScrollAnchor(
    screenRef,
    Object.fromEntries(
      askedIds.map((id) => [
        id,
        { at: sections[id].dataUpdatedAt, fetching: sections[id].isFetching },
      ]),
    ),
  );
  useSectionRefresh(
    scope,
    askedIds.map((id) => ({
      id,
      collapsed: collapsed.has(id),
      fetching: sections[id].isFetching,
      refetch: sections[id].refetch,
    })),
    agentsUpdatedAt,
    arm,
  );
  const projects = useProjects();
  const driving = useDriving(
    scope,
    (projects.data?.items ?? []).map((project) => project.name),
  );
  const resumeLink = useResumeLink(driving);

  const update = (changes: Record<string, string | null>) => {
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        for (const [key, value] of Object.entries(changes)) {
          if (value === null || value === "") next.delete(key);
          else next.set(key, value);
        }
        return next;
      },
      { replace: true },
    );
  };
  const [view, setView] = useView(params, update);
  const within = withinOf(params);
  const query = params.get("q") ?? "";
  const statusParam = params.get("status");
  const tab: SectionId | null = STATUSES.find((s) => s === statusParam) ?? null;
  const clearFilters = () => {
    update({
      ...Object.fromEntries(FILTER_KEYS.map((key) => [key, null])),
      q: null,
    });
  };

  const observed = Object.fromEntries(
    SECTIONS.map(({ id }) => [id, (sections[id].data?.pages ?? []).flatMap((page) => page.items)]),
  ) as Record<SectionId, Session[]>;
  // A driven session without a twin has none of the observed fields a filter (beyond period) reads.
  const narrowed = [
    "repo",
    "agent",
    "outcome",
    "workflow",
    "cost_min",
    "cost_max",
    "file",
    "tool",
    "guard_denial",
  ].some((key) => params.get(key));
  const driven = (driving.list.data?.items ?? []).filter(
    (a) => Boolean(a.observed_session_id) || !narrowed,
  );
  const placed = placeDriven(
    observed,
    driven,
    new Set(SECTIONS.filter(({ id }) => queries[id] !== null).map(({ id }) => id)),
    queries.ended?.from ?? null,
  );
  const agentsById = new Map((driving.list.data?.items ?? []).map((a) => [a.id, a]));
  const drvOf = (row: SectionRow) =>
    isDriven(row)
      ? row
      : row.agent_session_id
        ? (agentsById.get(row.agent_session_id) ?? null)
        : null;
  const needle = fold(query.trim());
  const matches = (row: SectionRow) => !needle || fold(searchText(row)).includes(needle);
  const asked = SECTIONS.flatMap((section) => {
    if (queries[section.id] === null) return [];
    const pages = sections[section.id];
    const all = placed[section.id].rows;
    const count = sectionCount(pages.data?.pages[0]?.total_estimate ?? 0, placed[section.id]);
    return [{ ...section, pages, all, rows: all.filter(matches), count }];
  });
  const rows = asked.flatMap((section) => observed[section.id]);
  const pending = asked.some((section) => section.pages.isPending);
  // The digest takes rows that only loaded (first page, Load more) or another query's rows as its baseline.
  const digestKey = JSON.stringify([scope, queries]);
  const settled =
    !driving.list.isPending &&
    !asked.some(
      ({ pages }) => pages.isPending || pages.isPlaceholderData || pages.isFetchingNextPage,
    );
  const period = periodOf(params);
  const shownSections = asked.filter((section) => tab === null || section.id === tab);
  const loadedAll = asked.flatMap((section) => section.all);
  const projectCount = new Set(loadedAll.map((row) => row.project)).size;
  const filtered =
    Boolean(needle) ||
    FILTER_KEYS.some((key) => key !== "period" && key !== "status" && params.get(key));
  const allEmpty =
    !pending && asked.every((section) => !section.pages.error && section.all.length === 0);
  // No session in any section and no filter: the first-run state, with Show all time when bounded (spec 22).
  const neverAny = !filtered && allEmpty;

  const counted = (section: (typeof asked)[number]) =>
    section.pages.isPending || (section.pages.error && !section.pages.data) ? null : section.count;
  const countOf = (id: SectionId) => {
    const section = asked.find((s) => s.id === id);
    return section ? counted(section) : 0;
  };
  const repos = [
    ...new Set(
      (projects.data?.items ?? [])
        .filter((project) => !scope || project.name === scope)
        .flatMap((project) => project.repos),
    ),
  ].sort();
  const workflows = [
    ...new Set(loadedAll.flatMap((row) => (isDriven(row) ? [] : (row.label?.workflows ?? [])))),
  ].sort();

  // What needs the owner: the Needs you group (waits and open sessions with a problem only they can fix).
  const needCount = countOf("waiting") ?? 0;
  const workingCount = countOf("live") ?? 0;
  const pausedCount = countOf("idle") ?? 0;
  const focusNeeds = () => {
    if (collapsed.has("waiting")) toggleCollapsed("waiting");
    if (tab !== null && tab !== "waiting") update({ status: null });
    requestAnimationFrame(() => {
      const target = screenRef.current?.querySelector<HTMLElement>(
        '[data-group="waiting"] [data-nav-row]',
      );
      target?.focus();
      target?.scrollIntoView({ block: "nearest" });
    });
  };
  const others = [
    workingCount ? `${fmtInt(workingCount)} working` : "",
    pausedCount ? `${fmtInt(pausedCount)} paused` : "",
  ].filter(Boolean);
  const attention = pending ? (
    <Skeleton width={320} />
  ) : needCount > 0 ? (
    <span className="sl-attention-parts">
      <button type="button" className="sl-attention-link" onClick={focusNeeds}>
        <Icon name="hand" size="sm" />
        {needCount === 1 ? "1 session needs you" : `${fmtInt(needCount)} sessions need you`}
      </button>
      {others.length > 0 && <span className="ah-muted">{`· ${others.join(" · ")}`}</span>}
    </span>
  ) : (
    <span className="sl-attention-calm">
      <Icon name="circle-check" size="sm" />
      {others.length > 0
        ? `Nothing needs you. ${others.join(" · ")}.`
        : "Nothing needs you. No session is working."}
    </span>
  );

  const emptyFor = (id: SectionId | null) => {
    if (neverAny)
      return (
        <EmptyState
          icon="square-terminal"
          title="No sessions yet."
          command="cd ~/agent-hub-hub && claude"
          action={
            period === "All" ? undefined : (
              <Button
                variant="ghost"
                onClick={() => {
                  update({ period: "All" });
                }}
              >
                Show all time
              </Button>
            )
          }
        >
          Each Claude Code session in a registered hub is listed here after its first event. Start
          one in the hub directory:
        </EmptyState>
      );
    if (filtered)
      return (
        <EmptyState
          icon="list-filter"
          title="No sessions match these filters."
          action={
            <div className="ah-row" style={{ gap: 8 }}>
              <Button icon="x" onClick={clearFilters}>
                Clear filters
              </Button>
              {(period === "24 h" || period === "7 d") && (
                <Button
                  variant="ghost"
                  onClick={() => {
                    update({ period: "30 d" });
                  }}
                >
                  Show last 30 days
                </Button>
              )}
            </div>
          }
        />
      );
    const title =
      id === "waiting"
        ? "Nothing needs you."
        : id === "live"
          ? "No session is working."
          : id === "idle"
            ? "No paused session."
            : id === "ended"
              ? period === "All"
                ? "No session finished yet."
                : `No session finished in the ${periodLabel(period).toLowerCase()}.`
              : period === "All"
                ? "No sessions."
                : `No sessions in the ${periodLabel(period).toLowerCase()}.`;
    return (
      <EmptyState
        icon="circle-dashed"
        title={title}
        action={
          period !== "All" && (id === "ended" || id === null) ? (
            <Button
              variant="ghost"
              onClick={() => {
                update({ period: "All" });
              }}
            >
              Show all time
            </Button>
          ) : undefined
        }
      />
    );
  };

  const visibleSections = shownSections.filter(
    (section) =>
      tab !== null ||
      section.pages.isPending ||
      section.pages.error !== null ||
      section.rows.length > 0,
  );
  const nothingShown =
    !pending &&
    visibleSections.every((section) => !section.pages.error && section.rows.length === 0);

  let body;
  if (nothingShown) {
    body = emptyFor(tab);
  } else if (view === "grid") {
    body = (
      <div className="ah-stack sl-sections">
        {visibleSections.map((section) => (
          <SessionSection
            key={section.id}
            id={section.id}
            title={
              section.id === "ended"
                ? `${section.title} · ${periodLabel(period).toLowerCase()}`
                : section.title
            }
            count={counted(section)}
            approximate={section.pages.hasNextPage}
            updating={section.pages.isPlaceholderData}
            collapsed={tab === null && collapsed.has(section.id)}
            onToggle={() => {
              toggleCollapsed(section.id);
            }}
          >
            {section.pages.isPending ? (
              <Skeleton lines={2} />
            ) : (
              <GridSection
                title={section.title}
                rows={section.rows}
                count={section.count}
                within={within}
                pages={section.pages}
                action={resumeLink}
                onOpen={(row) => {
                  void navigate(rowHref(row));
                }}
              />
            )}
          </SessionSection>
        ))}
      </div>
    );
  } else {
    const groups: InboxGroup[] = visibleSections.map((section) => ({
      id: section.id,
      title: section.title,
      count: counted(section),
      approximate: section.pages.hasNextPage,
      collapsed: collapsed.has(section.id),
      fixed: tab !== null,
      updating: section.pages.isPlaceholderData,
      pending: section.pages.isPending,
      error: section.pages.error,
      rows: orderRows(section.id, section.rows, drvOf),
      hasNextPage: section.pages.hasNextPage,
      loadingMore: section.pages.isFetchingNextPage,
      onToggle: () => {
        toggleCollapsed(section.id);
      },
      onRetry: () => {
        void section.pages.refetch();
      },
      // On placeholder pages TanStack would refetch page 1, not the next one.
      onLoadMore: section.pages.isPlaceholderData
        ? null
        : () => {
            void section.pages.fetchNextPage();
          },
    }));
    body = (
      <SessionsInbox
        groups={groups}
        tz={tz}
        showProject={!scope && projectCount > 1}
        commonRepo={commonRepoOf(loadedAll)}
        drvOf={drvOf}
        onOpen={(href) => {
          void navigate(href);
        }}
        endedScope={period === "All" ? null : periodLabel(period).toLowerCase()}
      />
    );
  }

  const searchNote =
    needle && asked.some((section) => section.pages.hasNextPage)
      ? "Search looks through the loaded sessions only. Load more to search older ones."
      : null;
  const matchCount = needle ? shownSections.reduce((sum, s) => sum + s.rows.length, 0) : null;
  const exportable = rows.filter(matches);

  return (
    <div className="ah-stack sl-screen" ref={screenRef}>
      <div className="ah-row ah-wrap" style={{ gap: 8 }}>
        <h1 className="ah-h1">Sessions</h1>
        <OfflineStamp tz={tz} />
        <span className="ah-grow" />
        <SegmentedControl
          label="View"
          value={view}
          onChange={(id) => {
            setView(id === "grid" ? "grid" : "list");
          }}
          options={[
            { id: "list", label: "List", icon: "list", title: "List view (v)" },
            { id: "grid", label: "Grid", icon: "layout-dashboard", title: "Grid view (v)" },
          ]}
        />
        <NewSessionControl driving={driving} />
      </div>
      <div className="sl-attention ah-small" aria-live="off">
        {attention}
      </div>
      <DrivenBanner driving={driving} />
      {!neverAny && (
        <>
          <Toolbar
            params={params}
            update={update}
            query={query}
            onQuery={(q) => {
              update({ q });
            }}
            period={period}
            repos={repos}
            workflows={workflows}
            view={view}
            within={within}
            matches={matchCount}
            onClearAll={clearFilters}
          />
        </>
      )}
      <div className="sl-body ah-stack" style={{ minWidth: 0 }}>
        {body}
        {searchNote && (
          <p className="ah-small ah-subtle" style={{ margin: 0 }}>
            {searchNote}
          </p>
        )}
        <div className="ah-row ah-wrap sl-foot">
          {exportable.length > 0 && (
            <Button
              size="sm"
              variant="ghost"
              icon="arrow-down"
              onClick={() => {
                download(
                  `sessions-${new Date().toISOString().slice(0, 10)}.csv`,
                  csvOf(exportable),
                );
              }}
            >
              {`Export ${plural(exportable.length, "session", "sessions")} as CSV`}
            </Button>
          )}
          <span className="ah-small ah-subtle sl-keys">
            <kbd className="ah-kbd">j</kbd> <kbd className="ah-kbd">k</kbd> move ·{" "}
            <kbd className="ah-kbd">o</kbd> open · <kbd className="ah-kbd">/</kbd> find ·{" "}
            <kbd className="ah-kbd">v</kbd> grid or list
          </span>
        </div>
        <CloudSessions driving={driving} />
      </div>
      <LiveDigest
        sections={asked.map((section) => ({ id: section.id, rows: section.all }))}
        settled={settled}
        resetKey={digestKey}
      />
    </div>
  );
}
