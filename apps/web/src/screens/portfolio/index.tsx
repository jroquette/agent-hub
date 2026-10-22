import { useNavigate, useSearchParams } from "react-router";
import { useState } from "react";

import {
  ActivityFeed,
  AppLink,
  Button,
  DataTable,
  FilterChip,
  Icon,
  KpiStat,
  MiniStageBar,
  Money,
  NeedsYouList,
  ProblemError,
  ProjectCard,
  SegmentedControl,
  Skeleton,
  Sparkline,
  StatusBadge,
  Tooltip,
} from "../../components";
import type { DataTableColumn } from "../../components";
import { useNow } from "../../lib/clock";
import { fmtMoney } from "../../lib/format";
import { useScope } from "../../lib/scope";
import { readStored, writeStored } from "../../lib/storage";
import {
  ACTIVITY_FILTERS,
  activityEntry,
  collapseRepeats,
  costDelta,
  inFlight,
  moreLabel,
  NEEDS_MAX,
  NEEDS_VISIBLE,
  groupLearnings,
  needsEntry,
  orderNeeds,
  orderProjects,
  projectCard,
  stageCounts,
  totals,
} from "./model";
import {
  useActivity,
  useNeedsYou,
  useProjects,
  useRefreshOnCounts,
  type ProjectSummary,
} from "./queries";
import { StaleStamp } from "./StaleStamp";
import { UsageRegion } from "./UsageRegion";

const VIEW_KEY = "ah.portfolio.view";
const ACTIVITY_PAGE = 20;
const NOT_CONNECTED = (source: string) => `${source} is not connected in this version.`;
const NOW_HINT = "Now, not affected by the period";
const PERIOD_HINT = "The last 7 days. Phase 2 reports this period only.";

function NeedsRegion({ project, live }: { project: string | null; live: number }) {
  const needs = useNeedsYou(project);
  const [params] = useSearchParams();
  const now = useNow(60_000);
  if (needs.isPending) {
    return (
      <section className="ah-needs" aria-busy="true" aria-label="Needs you">
        <div className="ah-needs-head">
          <h2 className="ah-h3">Needs you</h2>
        </div>
        {[0, 1, 2].map((i) => (
          <div key={i} className="ah-needs-item" style={{ cursor: "default" }}>
            <Skeleton width={16} height={16} />
            <Skeleton width={`${String(50 + i * 10)}%`} />
            <Skeleton width={40} />
            <span />
          </div>
        ))}
      </section>
    );
  }
  if (needs.isError) {
    return (
      <ProblemError
        title="Could not load what needs you"
        detail={needs.error.detail}
        status={needs.error.status}
        onRetry={() => void needs.refetch()}
      />
    );
  }
  const ordered = orderNeeds(groupLearnings(needs.data.items));
  if (ordered.length === 0 && live === 0) {
    return (
      <section className="ah-needs" aria-labelledby="needs-title">
        <div className="ah-needs-head">
          <h2 id="needs-title" className="ah-h3">
            Needs you
          </h2>
        </div>
        <div className="ah-needs-empty">
          <Icon name="circle-check" />
          <span>
            <b style={{ color: "var(--text)", fontWeight: 500 }}>Nothing needs you.</b> No session
            is running.
          </span>
        </div>
      </section>
    );
  }
  const expanded = params.get("needs") === "all";
  const visible = ordered.slice(0, expanded ? NEEDS_MAX : NEEDS_VISIBLE);
  const hidden = expanded ? [] : ordered.slice(NEEDS_VISIBLE);
  const next = new URLSearchParams(params);
  next.set("needs", "all");
  return (
    <NeedsYouList
      items={visible.map((item) => needsEntry(item, now))}
      more={hidden.length}
      moreLabel={hidden.length ? moreLabel(hidden) : undefined}
      moreHref={`/?${next.toString()}`}
      liveCount={live}
    />
  );
}

/** Totals across projects (spec 12: after the cards); only worth a row from two projects up. */
function TotalsRow({ projects }: { projects: ProjectSummary[] }) {
  const sum = totals(projects);
  const delta = costDelta(String(sum.cost), sum.previous === null ? null : String(sum.previous));
  return (
    <section aria-label="Totals · 7 d" className="ah-pf-totals">
      <KpiStat
        small
        label="Estimated cost · 7 d"
        value={fmtMoney(sum.cost)}
        delta={delta.pct === null ? undefined : delta.text.split(" vs")[0]}
        deltaTone={delta.tone}
        period={delta.pct === null ? "First period tracked" : `vs ${fmtMoney(sum.previous)}`}
        hint={`${PERIOD_HINT} Cost is estimated from transcripts. OpenTelemetry is not connected in this version.`}
      />
      <KpiStat
        small
        label="Failed runs · 7 d"
        value={String(sum.failed)}
        period="Runs that failed"
        hint={PERIOD_HINT}
      />
    </section>
  );
}

function ProjectTable({ projects }: { projects: ProjectSummary[] }) {
  const navigate = useNavigate();
  const columns: DataTableColumn<ProjectSummary>[] = [
    {
      id: "name",
      label: "Project",
      render: (p) => {
        const card = projectCard(p);
        return (
          <span className="ah-row" style={{ gap: 8 }}>
            <b style={{ fontWeight: 500 }}>{p.name}</b>
            <span className="ah-small ah-subtle">
              {p.repos.length} {p.repos.length === 1 ? "repo" : "repos"} · {p.platform_version}
            </span>
            {card.syncPending && <StatusBadge status="waiting" label="Sync pending" />}
          </span>
        );
      },
    },
    {
      id: "live",
      label: "Live",
      align: "right",
      hint: NOW_HINT,
      render: (p) => <span className="ah-num">{p.live_sessions}</span>,
    },
    {
      id: "flight",
      label: "In flight",
      render: (p) => (
        <span className="ah-row" style={{ gap: 8 }}>
          <span style={{ width: 72 }}>
            <MiniStageBar counts={stageCounts(p.runs_in_flight_by_stage)} />
          </span>
          <span className="ah-num">{inFlight(p)}</span>
        </span>
      ),
    },
    {
      id: "prs",
      label: "Open PRs · CI",
      render: (p) => (
        <span className="ah-small ah-subtle" title={NOT_CONNECTED("GitHub")}>
          {p.open_prs ?? "—"} · CI —
        </span>
      ),
    },
    {
      id: "failed",
      label: "Failed 7 d",
      align: "right",
      render: (p) => (
        <span className="ah-num" style={{ color: p.failed_runs_7d ? "var(--failed)" : undefined }}>
          {p.failed_runs_7d}
        </span>
      ),
    },
    {
      id: "cost",
      label: "Cost 7 d",
      align: "right",
      render: (p) => (
        <span className="ah-row" style={{ gap: 8, justifyContent: "flex-end" }}>
          <Sparkline data={projectCard(p).costSpark} width={40} height={16} label="Daily cost" />
          <Money value={p.cost_period} />
        </span>
      ),
    },
    {
      id: "delta",
      label: "Δ",
      align: "right",
      render: (p) => (
        <span className="ah-delta" data-tone="neutral">
          {costDelta(p.cost_period, p.cost_previous_period).text.split(" vs")[0]}
        </span>
      ),
    },
    {
      id: "ready",
      label: "Ready",
      align: "right",
      hint: NOT_CONNECTED("Linear"),
      render: (p) => (
        <span className="ah-num" title={NOT_CONNECTED("Linear")}>
          {p.ready_issues ?? "—"}
        </span>
      ),
    },
  ];
  return (
    <DataTable
      caption="Projects"
      columns={columns}
      rows={projects}
      rowKey={(p) => p.name}
      onRowClick={(p) => void navigate(`/projects/${encodeURIComponent(p.name)}`)}
    />
  );
}

function ProjectsRegion({
  projects,
  view,
  needs,
}: {
  projects: ReturnType<typeof useProjects>;
  view: string;
  needs: ReturnType<typeof useNeedsYou>;
}) {
  const navigate = useNavigate();
  if (projects.isPending) {
    return (
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 16 }}>
        {[0, 1].map((i) => (
          <div key={i} className="ah-pcard" style={{ cursor: "default" }} aria-busy="true">
            <Skeleton width="50%" height={18} />
            <Skeleton lines={4} />
            <Skeleton height={22} />
          </div>
        ))}
      </div>
    );
  }
  if (projects.isError) {
    return (
      <ProblemError
        title="Could not load projects"
        detail={projects.error.detail}
        status={projects.error.status}
        onRetry={() => void projects.refetch()}
      />
    );
  }
  const ordered = orderProjects(projects.data.items, needs.data?.items ?? []);
  if (view === "table") return <ProjectTable projects={ordered} />;
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(min(480px, 100%), 1fr))",
        gap: 16,
      }}
    >
      {ordered.map((p) => {
        const quiet = p.live_sessions === 0 && toZero(p);
        return (
          <div key={p.name} className="ah-stack" style={{ gap: 8 }}>
            <ProjectCard
              p={projectCard(p)}
              onOpen={() => void navigate(`/projects/${encodeURIComponent(p.name)}`)}
            />
            {quiet && (
              <p className="ah-small ah-muted" style={{ margin: 0 }}>
                No sessions yet. Start Claude Code in <span className="ah-mono">{p.hub_repo}</span>{" "}
                with hub web running.
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** A project with no recorded activity at all (the "hubs registered, no events yet" state). */
function toZero(p: ProjectSummary): boolean {
  return p.cost_period === null && p.failed_runs_7d === 0 && inFlight(p) === 0;
}

function ActivityRegion({ project, single }: { project: string | null; single: boolean }) {
  const [filter, setFilter] = useState("All");
  const [limit, setLimit] = useState(ACTIVITY_PAGE);
  const activity = useActivity(project, limit);
  const now = useNow(60_000);
  const kinds = ACTIVITY_FILTERS.find((f) => f.id === filter)?.kinds ?? [];
  let body;
  if (activity.isPending) {
    body = (
      <div className="ah-stack" style={{ gap: 14, paddingTop: 10 }} aria-busy="true">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} width={`${String(60 + ((i * 13) % 35))}%`} />
        ))}
      </div>
    );
  } else if (activity.isError) {
    body = (
      <ProblemError
        title="Could not load activity"
        detail={activity.error.detail}
        status={activity.error.status}
        compact
        onRetry={() => void activity.refetch()}
      />
    );
  } else {
    const items = activity.data.items.filter((item) => kinds.includes(item.kind));
    body =
      items.length === 0 ? (
        <p className="ah-small ah-muted" style={{ margin: "16px 0" }}>
          Nothing happened in this period.
        </p>
      ) : (
        <>
          <ActivityFeed
            items={collapseRepeats(items).map(({ item, count }) => ({
              ...activityEntry(item, now),
              project: single ? "" : item.project,
              count,
              node: item.href ? (
                <AppLink href={item.href} className="ah-feed-link">
                  {item.text}
                </AppLink>
              ) : undefined,
            }))}
          />
          {activity.data.next_cursor && limit < 200 && (
            <Button
              size="sm"
              variant="ghost"
              style={{ marginTop: 8 }}
              onClick={() => {
                setLimit(Math.min(200, limit + ACTIVITY_PAGE));
              }}
            >
              Load more
            </Button>
          )}
        </>
      );
  }
  return (
    <section className="ah-card" aria-labelledby="act-t">
      <div className="ah-card-head">
        <h2 id="act-t" className="ah-h3" style={{ fontSize: 14 }}>
          Activity
        </h2>
        <span className="ah-grow" />
        <span className="ah-small ah-subtle">Last 7 days</span>
      </div>
      <div className="ah-row" style={{ gap: 6, padding: "10px 16px 0", overflowX: "auto" }}>
        {ACTIVITY_FILTERS.map((f) => (
          <FilterChip
            key={f.id}
            value={f.id}
            active={filter === f.id}
            onClick={() => {
              setFilter(f.id);
            }}
          />
        ))}
      </div>
      <div style={{ padding: "4px 16px 12px" }}>{body}</div>
    </section>
  );
}

/** "1 project · 2 sessions running · no runs in flight": the now-values, said once. */
function summaryLine(projects: number, live: number, inFlight: number): string {
  const parts = [
    `${String(projects)} ${projects === 1 ? "project" : "projects"}`,
    live === 0
      ? "no session running"
      : `${String(live)} ${live === 1 ? "session" : "sessions"} running`,
    inFlight === 0
      ? "no runs in flight"
      : `${String(inFlight)} ${inFlight === 1 ? "run" : "runs"} in flight`,
  ];
  return parts.join(" · ");
}

function readView(params: URLSearchParams): string {
  const fromUrl = params.get("view");
  if (fromUrl === "cards" || fromUrl === "table") return fromUrl;
  return readStored(VIEW_KEY) === "table" ? "table" : "cards";
}

/** Portfolio (spec 12): what needs me, how the projects are doing, what happened. */
export function PortfolioScreen() {
  const [scope] = useScope();
  const [params, setParams] = useSearchParams();
  const view = readView(params);
  const projects = useProjects(scope);
  const needs = useNeedsYou(scope);
  useRefreshOnCounts([
    "/api/v1/projects",
    "/api/v1/needs-you",
    "/api/v1/activity",
    "/api/v1/skill-usage",
  ]);
  const list = projects.data?.items ?? [];
  const sum = totals(list);
  const setView = (next: string) => {
    writeStored(VIEW_KEY, next);
    setParams(
      (current) => {
        const copy = new URLSearchParams(current);
        copy.set("view", next);
        return copy;
      },
      { replace: true },
    );
  };
  return (
    <div style={{ padding: "16px 32px 40px" }}>
      <div style={{ marginBottom: 16 }}>
        <div className="ah-row ah-wrap" style={{ gap: 12 }}>
          <h1 className="ah-h1">Portfolio</h1>
          <StaleStamp />
          <span className="ah-grow" />
          <Tooltip label={PERIOD_HINT}>
            <span className="ah-small ah-subtle">Last 7 days</span>
          </Tooltip>
          <SegmentedControl
            label="View"
            value={view}
            onChange={setView}
            options={[
              { id: "cards", icon: "layout-dashboard", title: "Cards" },
              { id: "table", icon: "list", title: "Dense table" },
            ]}
          />
        </div>
        <div className="ah-muted" style={{ marginTop: 4 }}>
          {projects.data ? (
            summaryLine(list.length, sum.live, sum.inFlight)
          ) : (
            <Skeleton width={320} />
          )}
        </div>
      </div>
      <div className="ah-pf-layout">
        <div className="ah-stack" style={{ gap: 24, minWidth: 0 }}>
          <NeedsRegion project={scope} live={sum.live} />
          <div>
            <div className="ah-section-title">
              <h2 className="ah-h3" style={{ fontSize: 14 }}>
                {list.length === 1 ? "Project" : "Projects"}
              </h2>
              <span className="ah-grow" />
              <span className="ah-small ah-subtle">Cost is estimated from transcripts</span>
            </div>
            <ProjectsRegion projects={projects} view={view} needs={needs} />
            {projects.data?.items.length === 0 && (
              <p className="ah-small ah-muted">
                No registered hub has a project in this scope. Choose All projects in the top bar.
              </p>
            )}
          </div>
          {list.length > 1 && <TotalsRow projects={list} />}
          <UsageRegion project={scope} single={list.length === 1} />
        </div>
        <ActivityRegion project={scope} single={list.length === 1} />
      </div>
    </div>
  );
}
