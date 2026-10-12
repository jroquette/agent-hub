import { useState } from "react";
import type { ReactNode } from "react";
import { useNavigate, useParams } from "react-router";

import {
  AppLink,
  Banner,
  BudgetBar,
  Button,
  CodeBlock,
  DataTable,
  EmptyState,
  Icon,
  Money,
  PhaseTag,
  ProblemError,
  ProvenanceBadge,
  SessionLabel,
  Skeleton,
  Sparkline,
  StageChip,
  StatusBadge,
  Tooltip,
} from "../../components";
import type { DataTableColumn, Provenance } from "../../components";
import { STAGES } from "../../components";
import { useNow } from "../../lib/clock";
import { fmtDuration, fmtMoney, toNumber } from "../../lib/format";
import { useShell } from "../../shell/AppShell";
import { Breadcrumbs } from "../../shell/Breadcrumbs";
import { costDelta } from "../portfolio/model";
import { useRefreshOnCounts } from "../portfolio/queries";
import { StaleStamp } from "../portfolio/StaleStamp";
import { waitedSeconds, waitText } from "../approvals/model";
import {
  attemptText,
  budgetOf,
  durationSeconds,
  finishedCosts,
  lastStep,
  median,
  stageLabel,
} from "../runs-list/model";
import type { WorkflowRun } from "../runs-list/queries";
import {
  COLUMN_CAP,
  daysSince,
  healthBadge,
  healthLine,
  healthSummary,
  kanban,
  recentSessions,
  sessionBadge,
  STALE_DAYS,
  topFindings,
} from "./model";
import {
  useFindings,
  useProject,
  useProjectGates,
  useProjectNow,
  useProjectRepos,
  useProjectRuns,
  useProjectSummary,
  useRecentSessions,
  type NowItem,
  type ProjectDetail,
  type RepoView,
  type Session,
} from "./queries";

const NOT_CONNECTED = (source: string) => `${source} is not connected in this version.`;
const SECTIONS = [
  ["now", "Now"],
  ["repos", "Repos"],
  ["work", "Work in flight"],
  ["sessions", "Recent sessions"],
  ["health", "Health"],
  ["cost", "Cost"],
] as const;

interface QueryLike {
  isPending: boolean;
  isError: boolean;
  error: { detail: string | null; status: number } | null;
  refetch: () => unknown;
}

/** A section's own loading and problem states; its body renders once its data is in. */
function Region({
  query,
  title,
  lines = 3,
  children,
}: {
  query: QueryLike;
  title: string;
  lines?: number;
  children: () => ReactNode;
}) {
  if (query.isPending) {
    return (
      <div className="ah-card" style={{ padding: 16 }} aria-busy="true">
        <Skeleton lines={lines} />
      </div>
    );
  }
  if (query.isError) {
    return (
      <ProblemError
        title={`Could not load ${title}`}
        detail={query.error?.detail}
        status={query.error?.status}
        onRetry={() => void query.refetch()}
      />
    );
  }
  return <>{children()}</>;
}

function Section({
  id,
  title,
  sub,
  action,
  children,
}: {
  id: string;
  title: string;
  sub?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section id={`po-${id}`} aria-labelledby={`po-${id}-t`}>
      <div className="ah-section-title">
        <h2 id={`po-${id}-t`} className="ah-h3" style={{ fontSize: 14 }}>
          {title}
        </h2>
        {sub && <span className="ah-small ah-subtle">{sub}</span>}
        <span className="ah-grow" />
        {action}
      </div>
      {children}
    </section>
  );
}

function OpenLink({ href, children }: { href: string; children: string }) {
  return (
    <AppLink href={href} className="ah-small">
      {children} ›
    </AppLink>
  );
}

function Header({
  project,
  health,
}: {
  project: ProjectDetail;
  health: ReturnType<typeof healthSummary> | null;
}) {
  const badge = health ? healthBadge(health) : null;
  const pending = project.lock_state === "sync_pending" || project.lock_state === "drift";
  return (
    <header className="ah-stack" style={{ gap: 8 }}>
      <Breadcrumbs items={[{ label: "Portfolio", href: "/" }, { label: project.name }]} />
      <div className="ah-row ah-wrap" style={{ gap: 12 }}>
        <h1 className="ah-h1">{project.name}</h1>
        {badge && <StatusBadge status={badge.status} label={badge.label} />}
        <StaleStamp />
        <span className="ah-grow" />
        <Tooltip label="The last 7 days. Phase 2 reports this period only.">
          <span className="ah-small ah-subtle">Period · 7 d</span>
        </Tooltip>
      </div>
      <div className="ah-row ah-wrap ah-small ah-muted" style={{ gap: 12 }}>
        <span className="ah-mono" title={project.hub_path}>
          {project.hub_repo}
        </span>
        <span>
          {project.tracker.kind === "linear" ? "Linear" : project.tracker.kind} team{" "}
          <span className="ah-mono" style={{ color: "var(--text)" }}>
            {project.tracker.teams.join(", ") || "—"}
          </span>
        </span>
        <span>
          platform{" "}
          <span className="ah-mono" style={{ color: "var(--text)" }}>
            {project.platform_version}
          </span>{" "}
          pinned
        </span>
        {pending && (
          <Tooltip label="hub.lock records what hub sync last wrote. Run ./hub sync, review the diff, open a hub PR.">
            <StatusBadge
              status="waiting"
              label={`${project.lock_state === "drift" ? "Drift" : "Sync pending"} (lock ${project.lock_version ?? "—"}, pin ${project.platform_version})`}
            />
          </Tooltip>
        )}
        {project.modules.length > 0 && (
          <span className="ah-row" style={{ gap: 4 }}>
            Modules
            {project.modules.map((m) => (
              <span key={m} className="ah-fm-chip">
                {m}
              </span>
            ))}
          </span>
        )}
      </div>
      <nav className="ah-row ah-wrap ah-small" style={{ gap: 12 }} aria-label="Sections">
        <span className="ah-subtle">Jump to</span>
        {SECTIONS.map(([id, label]) => (
          <a key={id} href={`#po-${id}`}>
            {label}
          </a>
        ))}
      </nav>
      {project.warnings.map((warning) => (
        <Banner key={warning} tone="warning" boxed>
          {warning}
        </Banner>
      ))}
    </header>
  );
}

const PROVENANCE: readonly string[] = ["human", "agent", "agent-from-code", "agent-from-external"];

function NowCard({ title, items, now }: { title: string; items: NowItem[]; now: number }) {
  const verified = items.find((item) => item.last_verified)?.last_verified ?? null;
  const provenance = items.find((item) => item.provenance)?.provenance ?? null;
  const days = daysSince(verified, now);
  const old = days !== null && days > STALE_DAYS;
  return (
    <article
      className="ah-card"
      aria-label={title}
      style={{
        padding: 16,
        borderColor: old ? "var(--waiting)" : undefined,
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <div className="ah-row">
        <b>{title}</b>
        <span className="ah-grow" />
        {old && (
          <Tooltip label={`Not verified for ${String(days)} days. It may be out of date.`}>
            <span className="ah-row ah-small" style={{ gap: 4, color: "var(--waiting)" }}>
              <Icon name="clock" size="sm" />
              Not verified for {days} days
            </span>
          </Tooltip>
        )}
      </div>
      {items.length === 0 ? (
        <span className="ah-small ah-subtle">Nothing listed.</span>
      ) : (
        <ul className="ah-md" style={{ margin: 0, paddingLeft: 18 }}>
          {items.slice(0, 5).map((item) => (
            <li key={item.text}>{item.text}</li>
          ))}
          {items.length > 5 && <li className="ah-subtle">and {items.length - 5} more</li>}
        </ul>
      )}
      <div className="ah-row ah-wrap" style={{ gap: 6 }}>
        {verified && (
          <span className="ah-fm-chip" data-tone={old ? "stale" : undefined}>
            <i>last verified</i>
            {verified}
          </span>
        )}
        {provenance && PROVENANCE.includes(provenance) && (
          <ProvenanceBadge provenance={provenance as Provenance} />
        )}
      </div>
    </article>
  );
}

function NowSection({ project }: { project: string }) {
  const now = useProjectNow(project);
  const clock = useNow(3_600_000);
  return (
    <Section id="now" title="Now" sub="from brain/now.md · read-only">
      <Region query={now} title="brain/now.md">
        {() => {
          const data = now.data;
          if (!data) return null;
          const empty = data.focus.length + data.next.length + data.watch.length === 0;
          if (data.problem || empty) {
            return (
              <div className="ah-card">
                <EmptyState icon="file-text" title="No current focus recorded">
                  {data.problem ??
                    "This reads brain/now.md in the hub. /handoff updates it at the end of a session."}
                </EmptyState>
              </div>
            );
          }
          return (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
                gap: 16,
              }}
            >
              <NowCard title="Focus" items={data.focus} now={clock} />
              <NowCard title="Next" items={data.next} now={clock} />
              <NowCard title="Watch" items={data.watch} now={clock} />
            </div>
          );
        }}
      </Region>
    </Section>
  );
}

function ReposSection({ project }: { project: string }) {
  const repos = useProjectRepos(project);
  const columns: DataTableColumn<RepoView>[] = [
    { id: "repo", label: "Repo", render: (r) => <b style={{ fontWeight: 500 }}>{r.name}</b> },
    { id: "role", label: "Role", render: (r) => r.role ?? "—" },
    {
      id: "branch",
      label: "Default",
      render: (r) => <span className="ah-mono ah-small">{r.default_branch ?? "—"}</span>,
    },
    {
      id: "ci",
      label: "Last CI",
      render: () => (
        <span className="ah-small ah-subtle" title={NOT_CONNECTED("GitHub")}>
          —
        </span>
      ),
    },
    {
      id: "prs",
      label: "Open PRs",
      align: "right",
      render: (r) => (
        <span
          className="ah-num"
          title={
            r.open_prs === null || r.open_prs === undefined ? NOT_CONNECTED("GitHub") : undefined
          }
        >
          {r.open_prs ?? "—"}
        </span>
      ),
    },
    {
      id: "fast",
      label: "Fast check",
      render: (r) => (
        <div style={{ width: 240 }}>
          <CodeBlock code={r.check_fast} prompt="" />
        </div>
      ),
    },
    {
      id: "full",
      label: "Full check",
      render: (r) => (
        <div style={{ width: 200 }}>
          <CodeBlock code={r.check} prompt="" />
        </div>
      ),
    },
    {
      id: "agents",
      label: "AGENTS.md",
      render: (r) =>
        r.agents_md_present ? (
          <span
            className="ah-row ah-small"
            style={{ gap: 4, color: (r.agents_md_lines ?? 0) > 100 ? "var(--waiting)" : undefined }}
          >
            <Icon
              name={(r.agents_md_lines ?? 0) > 100 ? "triangle-alert" : "circle-check"}
              size="sm"
              style={{ color: (r.agents_md_lines ?? 0) > 100 ? "var(--waiting)" : "var(--done)" }}
            />
            {r.agents_md_lines ?? "?"} lines
          </span>
        ) : (
          <Tooltip label="Each repo needs its own AGENTS.md. Run hub doctor for the fix.">
            <span className="ah-row ah-small" style={{ gap: 4, color: "var(--failed)" }}>
              <Icon name="circle-x" size="sm" />
              Missing
            </span>
          </Tooltip>
        ),
    },
  ];
  return (
    <Section id="repos" title="Repos">
      <Region query={repos} title="repos">
        {() => (
          <DataTable
            caption="Repos"
            density="compact"
            columns={columns}
            rows={repos.data?.items ?? []}
            rowKey={(r) => r.name}
          />
        )}
      </Region>
    </Section>
  );
}

function RunCard({
  run,
  failed,
  now,
}: {
  run: WorkflowRun;
  failed?: boolean | undefined;
  now: number;
}) {
  const budget = budgetOf(run);
  const cost = toNumber(run.cost_usd);
  const step = lastStep(run);
  let meta: string;
  if (failed) {
    const stage = run.failure?.stage ?? run.stage;
    meta = `${stageLabel(stage).toLowerCase()} ${step ? `${String(step.attempt)}/${String(step.max_attempts)}` : ""}${run.failure?.reason ? ` · ${run.failure.reason}` : ""}`;
  } else if (run.stage === "REPORTED") {
    meta = run.pr_url ? "PR opened" : "reported · no PR";
  } else if (step) {
    meta = `${attemptText(run).replace(" of ", "/")} · ${fmtDuration(durationSeconds(step.started_at, step.ended_at, now))}`;
  } else {
    meta = `${fmtDuration(durationSeconds(run.started_at, null, now))} since start`;
  }
  return (
    <AppLink
      href={`/runs/${encodeURIComponent(run.id)}`}
      className="ah-card"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        padding: 10,
        color: "var(--text)",
        borderColor: failed ? "var(--failed)" : undefined,
        textDecoration: "none",
      }}
    >
      <span className="ah-small" style={{ lineHeight: "18px" }}>
        <span className="ah-mono" style={{ fontWeight: 500 }}>
          {run.issue?.key ?? run.id.slice(0, 8)}
        </span>{" "}
        {run.issue?.title ?? ""}
      </span>
      <span
        className="ah-small"
        style={{
          color: failed ? "var(--failed)" : "var(--text-muted)",
          fontSize: 12,
          overflowWrap: "anywhere",
        }}
      >
        {meta}
      </span>
      {budget !== null && cost !== null && run.stage !== "REPORTED" && !failed ? (
        <BudgetBar spent={cost} budget={budget} label="Budget" />
      ) : (
        <span className="ah-small ah-num" style={{ fontWeight: 400 }}>
          {fmtMoney(cost)}
        </span>
      )}
    </AppLink>
  );
}

function KanbanColumn({
  runs,
  failed,
  now,
  head,
}: {
  runs: WorkflowRun[];
  failed?: boolean | undefined;
  now: number;
  head: ReactNode;
}) {
  const [all, setAll] = useState(false);
  const shown = all ? runs : runs.slice(0, COLUMN_CAP);
  return (
    <div className="ah-stack" style={{ gap: 8, minWidth: 0 }}>
      {head}
      {runs.length === 0 ? (
        <span className="ah-small ah-subtle" style={{ padding: "8px 2px" }}>
          None
        </span>
      ) : (
        shown.map((run) => <RunCard key={run.id} run={run} failed={failed} now={now} />)
      )}
      {runs.length > COLUMN_CAP && !all && (
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            setAll(true);
          }}
        >
          Show {runs.length - COLUMN_CAP} more
        </Button>
      )}
    </div>
  );
}

function WorkSection({ project }: { project: string }) {
  const runs = useProjectRuns(project);
  const gates = useProjectGates(project);
  const now = useNow(30_000);
  const [showFailed, setShowFailed] = useState(true);
  const humanGates = (gates.data?.items ?? []).filter(
    (g) => g.kind === "plan" || g.kind === "spec" || g.kind === "human_gate",
  );
  return (
    <Section
      id="work"
      title="Work in flight"
      sub="read-only · runs move by the executor"
      action={
        <label className="ah-row ah-small" style={{ gap: 6 }}>
          <input
            type="checkbox"
            className="ah-check"
            checked={showFailed}
            onChange={() => {
              setShowFailed(!showFailed);
            }}
          />
          Show failed (7 d)
        </label>
      }
    >
      <Region query={runs} title="work in flight" lines={4}>
        {() => {
          const columns = kanban(runs.data?.items ?? [], now);
          const inFlight = STAGES.filter((s) => s.id !== "REPORTED").reduce(
            (n, s) => n + columns[s.id].length,
            0,
          );
          return (
            <div className="ah-card" style={{ padding: 12 }}>
              {inFlight === 0 && (
                <p className="ah-small ah-muted" style={{ margin: "0 0 12px" }}>
                  <b style={{ color: "var(--text)", fontWeight: 500 }}>No run in flight.</b> Runs
                  appear when the executor picks an issue labelled agent-ready.
                </p>
              )}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: showFailed
                    ? "repeat(6, minmax(0, 1fr)) 1px minmax(0, 1fr)"
                    : "repeat(6, minmax(0, 1fr))",
                  gap: 10,
                }}
              >
                {STAGES.map(({ id }) => (
                  <KanbanColumn
                    key={id}
                    runs={columns[id]}
                    now={now}
                    head={
                      <div className="ah-row ah-caption ah-muted" style={{ gap: 6 }}>
                        <StageChip
                          stage={id}
                          state={
                            id === "REPORTED" ? "done" : columns[id].length ? "active" : "pending"
                          }
                        />
                        <span className="ah-num" style={{ fontWeight: 400 }}>
                          {columns[id].length}
                        </span>
                      </div>
                    }
                  />
                ))}
                {showFailed && <span style={{ background: "var(--border)" }} aria-hidden="true" />}
                {showFailed && (
                  <KanbanColumn
                    runs={columns.FAILED}
                    failed
                    now={now}
                    head={
                      <div className="ah-row ah-caption" style={{ gap: 6, color: "var(--failed)" }}>
                        <Icon name="circle-x" size="sm" />
                        Failed · 7 d
                        <span className="ah-num" style={{ fontWeight: 400 }}>
                          {columns.FAILED.length}
                        </span>
                      </div>
                    }
                  />
                )}
              </div>
              {humanGates.map((gate) => (
                <AppLink
                  key={gate.id}
                  href={`/approvals/${gate.id}`}
                  className="ah-row ah-small"
                  style={{
                    gap: 8,
                    marginTop: 12,
                    padding: "8px 10px",
                    borderRadius: "var(--radius-md)",
                    background: "var(--waiting-soft)",
                    color: "var(--text)",
                  }}
                >
                  <Icon name="hand" size="sm" style={{ color: "var(--waiting)" }} />
                  <b style={{ fontWeight: 500 }}>Waiting at a gate:</b>
                  {gate.title} · {waitText(waitedSeconds(gate, now))}
                  <span className="ah-grow" />
                  <span>Open approval ›</span>
                </AppLink>
              ))}
            </div>
          );
        }}
      </Region>
    </Section>
  );
}

function SessionsSection({ project, hubPath }: { project: string; hubPath: string }) {
  const sessions = useRecentSessions(project);
  const navigate = useNavigate();
  const now = useNow(30_000);
  const columns: DataTableColumn<Session>[] = [
    {
      id: "started",
      label: "Started",
      render: (s) => (
        <span className="ah-mono ah-small">
          {new Date(s.started_at).toLocaleString("en-GB", {
            day: "2-digit",
            month: "short",
            hour: "2-digit",
            minute: "2-digit",
          })}
        </span>
      ),
    },
    {
      id: "session",
      label: "Session",
      render: (s) => <SessionLabel session={s} />,
    },
    {
      id: "outcome",
      label: "Outcome",
      render: (s) => {
        const badge = sessionBadge(s);
        return <StatusBadge status={badge.status} inferred={s.end_inferred} />;
      },
    },
    {
      id: "duration",
      label: "Duration",
      align: "right",
      render: (s) => (
        <span className="ah-num" style={{ fontWeight: 400 }}>
          {fmtDuration(durationSeconds(s.started_at, s.ended_at, now))}
        </span>
      ),
    },
    {
      id: "turns",
      label: "Turns",
      align: "right",
      render: (s) => (
        <span className="ah-num" style={{ fontWeight: 400 }}>
          {s.turns}
        </span>
      ),
    },
    {
      id: "cost",
      label: "Cost",
      align: "right",
      render: (s) => <Money value={s.cost_usd} precise />,
    },
    {
      id: "errors",
      label: "Errors",
      align: "right",
      render: (s) => (
        <span
          className="ah-num"
          style={{ fontWeight: 400, color: s.errors ? "var(--failed)" : undefined }}
        >
          {s.errors}
        </span>
      ),
    },
  ];
  return (
    <Section
      id="sessions"
      title="Recent sessions"
      action={
        <OpenLink href={`/sessions?scope=${encodeURIComponent(project)}`}>All sessions</OpenLink>
      }
    >
      <Region query={sessions} title="recent sessions">
        {() => {
          const rows = recentSessions(sessions.data?.items ?? []);
          if (rows.length === 0) {
            return (
              <div className="ah-card">
                <EmptyState
                  icon="square-terminal"
                  title="No sessions yet."
                  command={`cd ${hubPath} && claude`}
                >
                  Start Claude Code in the hub directory with hub web running:
                </EmptyState>
              </div>
            );
          }
          return (
            <DataTable
              caption="Recent sessions"
              columns={columns}
              rows={rows}
              rowKey={(s) => s.id}
              onRowClick={(s) => void navigate(`/sessions/${encodeURIComponent(s.id)}`)}
            />
          );
        }}
      </Region>
    </Section>
  );
}

const SEVERITY_ICON = {
  error: ["circle-x", "var(--failed)"],
  warning: ["triangle-alert", "var(--waiting)"],
  info: ["info", "var(--live)"],
} as const;

function HealthSection({
  project,
  findings,
}: {
  project: string;
  findings: ReturnType<typeof useFindings>;
}) {
  return (
    <Section
      id="health"
      title="Health"
      action={
        <OpenLink href={`/health?scope=${encodeURIComponent(project)}`}>Open Health</OpenLink>
      }
    >
      <Region query={findings} title="health">
        {() => {
          const items = findings.data?.items ?? [];
          const summary = healthSummary(items);
          return (
            <div className="ah-card" style={{ padding: 16 }}>
              {items.length === 0 ? (
                <div className="ah-small">No findings.</div>
              ) : (
                <>
                  <div className="ah-small" style={{ marginBottom: 8 }}>
                    {healthLine(summary)}
                  </div>
                  {topFindings(items).map((f) => {
                    const [icon, color] = SEVERITY_ICON[f.severity];
                    return (
                      <div
                        key={`${f.rule}:${f.path ?? ""}:${String(f.line)}`}
                        className="ah-row ah-small"
                        style={{ gap: 8, padding: "7px 0", borderTop: "1px solid var(--border)" }}
                      >
                        <Icon name={icon} size="sm" style={{ color }} title={f.severity} />
                        <span className="ah-rule">{f.rule}</span>
                        {f.path && (
                          <span className="ah-mono">
                            {f.path}
                            {f.line ? `:${String(f.line)}` : ""}
                          </span>
                        )}
                        <span
                          className="ah-muted"
                          style={{
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                            minWidth: 0,
                          }}
                        >
                          {f.message}
                        </span>
                      </div>
                    );
                  })}
                </>
              )}
              <div className="ah-small ah-subtle" style={{ marginTop: 6 }}>
                Run doctor now <PhaseTag phase="P4" />
              </div>
            </div>
          );
        }}
      </Region>
    </Section>
  );
}

function CostSection({ project }: { project: string }) {
  const summary = useProjectSummary(project);
  const runs = useProjectRuns(project);
  return (
    <Section id="cost" title="Cost · 7 d">
      <Region query={summary} title="cost">
        {() => {
          const card = summary.data?.items.find((p) => p.name === project);
          if (!card) return <p className="ah-small ah-muted">No cost recorded for this project.</p>;
          const delta = costDelta(card.cost_period, card.cost_previous_period);
          const costs = finishedCosts(runs.data?.items ?? []);
          const mid = median(costs);
          const daily = card.cost_daily.map((v) => toNumber(v) ?? 0);
          return (
            <div className="ah-card ah-stack" style={{ padding: 16, gap: 10 }}>
              <div className="ah-row ah-wrap" style={{ gap: 16, alignItems: "baseline" }}>
                <span className="ah-kpi-value">{fmtMoney(card.cost_period)}</span>
                <span className="ah-delta" data-tone={delta.tone}>
                  {delta.pct !== null && (
                    <Icon name={delta.pct < 0 ? "trending-down" : "trending-up"} size="sm" />
                  )}
                  {delta.text}
                </span>
                <span className="ah-grow" />
                <span className="ah-small ah-muted">
                  {costs.length >= 5 && mid !== null ? (
                    <>
                      median run <b className="ah-num">{fmtMoney(mid)}</b> (n = {costs.length})
                    </>
                  ) : (
                    `n = ${String(costs.length)}, too few to compare`
                  )}
                </span>
              </div>
              {daily.length > 0 && (
                <div style={{ overflow: "hidden" }}>
                  <Sparkline
                    data={daily}
                    width={480}
                    height={96}
                    area
                    label="Daily cost, this period"
                  />
                </div>
              )}
              <span className="ah-small ah-subtle">
                Estimated from transcripts. OpenTelemetry is not connected in this version.
              </span>
            </div>
          );
        }}
      </Region>
    </Section>
  );
}

function ProjectNotFound({ name }: { name: string }) {
  const { openPalette } = useShell();
  return (
    <div style={{ padding: 32, maxWidth: 760 }} className="ah-stack">
      <h1 className="ah-h2">Project not found</h1>
      <p className="ah-muted" style={{ margin: 0 }}>
        No registered hub has a project named {name}.
      </p>
      <div className="ah-row" style={{ gap: 8 }}>
        <Button
          icon="search"
          onClick={() => {
            openPalette(name);
          }}
        >
          Open command palette
        </Button>
        <AppLink className="ah-btn" href="/">
          Go to Portfolio
        </AppLink>
      </div>
    </div>
  );
}

/** Project overview (spec 12): one project zoomed in, each section linking to its full screen. */
export function ProjectOverviewScreen() {
  const { project: name = "" } = useParams();
  const project = useProject(name);
  const findings = useFindings(name);
  useRefreshOnCounts([
    "/api/v1/workflow-runs",
    "/api/v1/sessions",
    "/api/v1/approvals",
    "/api/v1/projects",
  ]);
  if (project.isPending) {
    return (
      <div style={{ padding: "16px 32px" }} className="ah-stack" aria-busy="true">
        <Skeleton width={240} height={28} />
        <Skeleton width={620} />
        <Skeleton width={380} />
        <div
          style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginTop: 16 }}
        >
          {[0, 1, 2].map((i) => (
            <div key={i} className="ah-card" style={{ padding: 16 }}>
              <Skeleton lines={4} />
            </div>
          ))}
        </div>
      </div>
    );
  }
  if (project.isError) {
    if (project.error.status === 404) return <ProjectNotFound name={name} />;
    return (
      <div style={{ padding: 32, maxWidth: 760 }}>
        <ProblemError
          title="Could not load this project"
          detail={project.error.detail}
          status={project.error.status}
          onRetry={() => void project.refetch()}
        />
      </div>
    );
  }
  return (
    <div style={{ padding: "16px 32px 40px" }} className="ah-stack">
      <Header
        project={project.data}
        health={findings.data ? healthSummary(findings.data.items) : null}
      />
      <NowSection project={name} />
      <ReposSection project={name} />
      <WorkSection project={name} />
      <SessionsSection project={name} hubPath={project.data.hub_path} />
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))",
          gap: 16,
          alignItems: "start",
        }}
      >
        <HealthSection project={name} findings={findings} />
        <CostSection project={name} />
      </div>
    </div>
  );
}
