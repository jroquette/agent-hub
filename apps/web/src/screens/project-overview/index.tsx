import "./project-overview.css";

import type { ReactNode } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";

import {
  AppLink,
  Banner,
  BudgetBar,
  Button,
  CodeBlock,
  DataTable,
  EmptyState,
  Icon,
  KpiStat,
  Money,
  NeedsYouList,
  ProblemError,
  ProvenanceBadge,
  SessionLabel,
  Skeleton,
  StatusBadge,
  Time,
  Tooltip,
} from "../../components";
import type { DataTableColumn, IconName, Provenance } from "../../components";
import { STAGES } from "../../components";
import { useNow } from "../../lib/clock";
import { fmtDuration, fmtMoney, toNumber } from "../../lib/format";
import { useShell } from "../../shell/AppShell";
import { Breadcrumbs } from "../../shell/Breadcrumbs";
import { NEEDS_MAX, costDelta, needsEntry, orderNeeds } from "../portfolio/model";
import { useNeedsYou, useRefreshOnCounts } from "../portfolio/queries";
import { StaleStamp } from "../portfolio/StaleStamp";
import { budgetOf, durationSeconds, finishedCosts, median } from "../runs-list/model";
import type { WorkflowRun } from "../runs-list/queries";
import {
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
const PERIOD_HINT = "The last 7 days. Phase 2 reports this period only.";
const NEEDS_VISIBLE = 4;
const TASKS_VISIBLE = 8;

/** Each workflow step in words a product person reads without the state machine in mind. */
const STEP_WORDS: Record<string, string> = {
  PICKED: "Picked up",
  WORKTREE: "Getting ready",
  IMPLEMENTING: "Building",
  VERIFYING: "Testing",
  PR_OPEN: "Waiting for review",
  REPORTED: "Done",
};

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
      <div className="po-section-head">
        <h2 id={`po-${id}-t`}>{title}</h2>
        {sub && <p>{sub}</p>}
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

function plural(n: number, one: string, many = `${one}s`): string {
  return `${String(n)} ${n === 1 ? one : many}`;
}

function Header({
  project,
  health,
}: {
  project: ProjectDetail;
  health: ReturnType<typeof healthSummary> | null;
}) {
  const badge = health ? healthBadge(health) : null;
  const team = project.tracker.teams.join(", ");
  return (
    <header className="ah-stack" style={{ gap: 8 }}>
      <Breadcrumbs items={[{ label: "Portfolio", href: "/" }, { label: project.name }]} />
      <div className="ah-row ah-wrap" style={{ gap: 12 }}>
        <h1 className="ah-h1">{project.name}</h1>
        {badge && health && (health.error || health.warning) ? (
          <Tooltip label="Setup problems an engineer should look at. They do not stop the agents.">
            <a href="#po-setup" style={{ textDecoration: "none" }}>
              <StatusBadge
                status={badge.status}
                label={badge.label.replace("Health ·", "Setup ·")}
              />
            </a>
          </Tooltip>
        ) : (
          badge && <StatusBadge status={badge.status} label="Setup · all good" />
        )}
        <StaleStamp />
        <span className="ah-grow" />
        <Tooltip label={PERIOD_HINT}>
          <span className="ah-small ah-subtle">Showing the last 7 days</span>
        </Tooltip>
      </div>
      <ProjectSentence project={project.name} team={team} tracker={project.tracker.kind} />
      {project.warnings.map((warning) => (
        <Banner key={warning} tone="warning" boxed>
          {warning}
        </Banner>
      ))}
    </header>
  );
}

/** One plain sentence under the title: what is happening right now. */
function ProjectSentence({
  project,
  team,
  tracker,
}: {
  project: string;
  team: string;
  tracker: string;
}) {
  const summary = useProjectSummary(project);
  const card = summary.data?.items.find((p) => p.name === project);
  const where = `${tracker === "linear" ? "Linear" : tracker} team ${team || "—"}`;
  if (!card) return <p className="po-summary">{where}</p>;
  const working = Object.entries(card.runs_in_flight_by_stage)
    .filter(([stage]) => stage !== "REPORTED" && stage !== "FAILED")
    .reduce((n, [, count]) => n + count, 0);
  return (
    <p className="po-summary">
      <b>{plural(card.live_sessions, "agent session")}</b> running now,{" "}
      <b>{plural(working, "ticket")}</b> being worked on
      {card.failed_runs_7d > 0 && (
        <>
          , <b style={{ color: "var(--failed)" }}>{plural(card.failed_runs_7d, "ticket")}</b>{" "}
          stopped with a problem this week
        </>
      )}
      . {where} · {plural(card.repos.length, "repository", "repositories")}.
    </p>
  );
}

function NeedsSection({ project, live }: { project: string; live: number }) {
  const needs = useNeedsYou(project);
  const now = useNow(60_000);
  const [params] = useSearchParams();
  const expanded = params.get("needs") === "all";
  const next = new URLSearchParams(params);
  next.set("needs", "all");
  return (
    <Region query={needs} title="what needs you">
      {() => {
        const ordered = orderNeeds(needs.data?.items ?? []);
        const hidden = expanded ? [] : ordered.slice(NEEDS_VISIBLE);
        return (
          <NeedsYouList
            items={ordered
              .slice(0, expanded ? NEEDS_MAX : NEEDS_VISIBLE)
              .map((item) => needsEntry(item, now))}
            more={hidden.length}
            moreLabel={hidden.length ? `See ${String(hidden.length)} more` : undefined}
            moreHref={`/projects/${encodeURIComponent(project)}?${next.toString()}`}
            liveCount={live}
          />
        );
      }}
    </Region>
  );
}

function KpiSection({ project }: { project: string }) {
  const summary = useProjectSummary(project);
  const runs = useProjectRuns(project);
  const now = useNow(60_000);
  return (
    <Region query={summary} title="this week's numbers" lines={2}>
      {() => {
        const card = summary.data?.items.find((p) => p.name === project);
        const columns = kanban(runs.data?.items ?? [], now);
        const working = STAGES.filter((s) => s.id !== "REPORTED").reduce(
          (n, s) => n + columns[s.id].length,
          0,
        );
        const delta = card ? costDelta(card.cost_period, card.cost_previous_period) : null;
        const costs = finishedCosts(runs.data?.items ?? []);
        const mid = median(costs);
        return (
          <div className="po-kpis">
            <KpiStat
              label="Agent sessions running"
              value={card?.live_sessions ?? "—"}
              period="right now"
              hint="People and agents working in Claude Code on this project at this moment."
            />
            <KpiStat
              label="Tickets in progress"
              value={runs.data ? working : "—"}
              period="right now"
              hint="Linear tickets an agent picked up and has not finished yet."
            />
            <KpiStat
              label="Tickets delivered"
              value={runs.data ? columns.REPORTED.length : "—"}
              period={
                columns.FAILED.length
                  ? `last 7 days · ${String(columns.FAILED.length)} stopped`
                  : "last 7 days"
              }
              hint="Tickets an agent finished and reported on, usually with a pull request."
            />
            <KpiStat
              label="Spent"
              value={card ? fmtMoney(card.cost_period) : "—"}
              delta={delta && delta.pct !== null ? delta.text.split(" vs")[0] : undefined}
              deltaTone={delta?.tone ?? "neutral"}
              period={
                delta && delta.pct !== null
                  ? `vs ${fmtMoney(card?.cost_previous_period)} the week before`
                  : "last 7 days"
              }
              spark={card?.cost_daily.map((v) => toNumber(v) ?? 0)}
              hint={`Estimated from transcripts. ${
                costs.length >= 5 && mid !== null
                  ? `A ticket costs ${fmtMoney(mid)} on average (median of ${String(costs.length)}).`
                  : "Too few finished tickets to give an average yet."
              }`}
            />
          </div>
        );
      }}
    </Region>
  );
}

const PROVENANCE: readonly string[] = ["human", "agent", "agent-from-code", "agent-from-external"];

function FocusCard({
  title,
  icon,
  items,
  now,
}: {
  title: string;
  icon: IconName;
  items: NowItem[];
  now: number;
}) {
  const verified = items.find((item) => item.last_verified)?.last_verified ?? null;
  const provenance = items.find((item) => item.provenance)?.provenance ?? null;
  const days = daysSince(verified, now);
  const old = days !== null && days > STALE_DAYS;
  return (
    <article className="ah-card po-focus-card" aria-label={title} data-stale={old || undefined}>
      <div className="po-focus-title">
        <Icon name={icon} size="sm" style={{ color: "var(--text-subtle)" }} />
        {title}
      </div>
      {items.length === 0 ? (
        <span className="ah-small ah-subtle">Nothing listed.</span>
      ) : (
        <ul>
          {items.slice(0, 5).map((item) => (
            <li key={item.text}>{item.text}</li>
          ))}
          {items.length > 5 && <li className="ah-subtle">and {items.length - 5} more</li>}
        </ul>
      )}
      <span className="ah-grow" />
      <div className="ah-row ah-wrap ah-small ah-subtle" style={{ gap: 6 }}>
        {old ? (
          <Tooltip label={`Not verified for ${String(days)} days. It may be out of date.`}>
            <span className="ah-row" style={{ gap: 4, color: "var(--waiting)" }}>
              <Icon name="clock" size="sm" />
              Not checked for {days} days
            </span>
          </Tooltip>
        ) : (
          verified && <span>Checked {verified}</span>
        )}
        {provenance && PROVENANCE.includes(provenance) && (
          <ProvenanceBadge provenance={provenance as Provenance} />
        )}
      </div>
    </article>
  );
}

function FocusSection({ project }: { project: string }) {
  const now = useProjectNow(project);
  const clock = useNow(3_600_000);
  return (
    <Section id="now" title="What the team is focused on" sub="Updated at the end of each session">
      <Region query={now} title="the team's focus">
        {() => {
          const data = now.data;
          if (!data) return null;
          const empty = data.focus.length + data.next.length + data.watch.length === 0;
          if (data.problem || empty) {
            return (
              <div className="ah-card">
                <EmptyState icon="file-text" title="No current focus recorded">
                  {data.problem ??
                    "The focus is written to brain/now.md in the hub when a session ends with /handoff."}
                </EmptyState>
              </div>
            );
          }
          return (
            <div className="po-focus">
              <FocusCard title="Focus now" icon="flag" items={data.focus} now={clock} />
              <FocusCard title="Up next" icon="arrow-right" items={data.next} now={clock} />
              <FocusCard
                title="Watch out for"
                icon="triangle-alert"
                items={data.watch}
                now={clock}
              />
            </div>
          );
        }}
      </Region>
    </Section>
  );
}

/** Where a run is among the six steps, as segments plus the step in words. */
function StepProgress({ run }: { run: WorkflowRun }) {
  const failed = run.stage === "FAILED";
  const at = failed ? (run.failure?.stage ?? "PICKED") : run.stage;
  const index = Math.max(
    0,
    STAGES.findIndex((s) => s.id === at),
  );
  const words =
    run.stage === "REPORTED"
      ? "Done"
      : failed
        ? `Stopped while ${(STEP_WORDS[at] ?? at).toLowerCase()}`
        : `${STEP_WORDS[at] ?? at} · step ${String(index + 1)} of ${String(STAGES.length)}`;
  return (
    <div className="po-steps">
      <div className="po-steps-bar" aria-hidden="true">
        {STAGES.map((s, i) => (
          <span
            key={s.id}
            data-state={
              run.stage === "REPORTED" || i < index
                ? "done"
                : i === index
                  ? failed
                    ? "failed"
                    : "active"
                  : undefined
            }
          />
        ))}
      </div>
      <span className="ah-small" style={{ color: failed ? "var(--failed)" : "var(--text-muted)" }}>
        {words}
      </span>
    </div>
  );
}

function TaskRow({ run, now }: { run: WorkflowRun; now: number }) {
  const failed = run.stage === "FAILED";
  const done = run.stage === "REPORTED";
  const budget = budgetOf(run);
  const cost = toNumber(run.cost_usd);
  let note: string;
  if (failed) note = run.failure?.reason ? `Problem: ${run.failure.reason}` : "Needs a look";
  else if (done) note = run.pr_url ? "Pull request opened" : "Finished without a pull request";
  else note = `Started ${fmtDuration(durationSeconds(run.started_at, null, now))} ago`;
  return (
    <AppLink
      href={`/runs/${encodeURIComponent(run.id)}`}
      className="po-task"
      data-failed={failed || undefined}
    >
      <span className="po-task-title">
        <span>
          <span className="ah-mono ah-small" style={{ fontWeight: 500, marginRight: 6 }}>
            {run.issue?.key ?? run.id.slice(0, 8)}
          </span>
          {run.issue?.title ?? ""}
        </span>
        <span className="ah-small ah-subtle po-task-note">{note}</span>
      </span>
      <StepProgress run={run} />
      <span>
        {budget !== null && cost !== null && !done && !failed ? (
          <BudgetBar spent={cost} budget={budget} label="Budget" />
        ) : (
          <span className="ah-small ah-num" style={{ fontWeight: 400 }}>
            {fmtMoney(cost)}
          </span>
        )}
      </span>
      <Icon name="chevron-right" size="sm" style={{ color: "var(--text-subtle)" }} />
    </AppLink>
  );
}

function TasksSection({ project }: { project: string }) {
  const runs = useProjectRuns(project);
  const now = useNow(30_000);
  return (
    <Section
      id="work"
      title="Tickets the agents are working on"
      sub="Agents move them on their own; open one to see the detail"
      action={
        <OpenLink href={`/runs?project=${encodeURIComponent(project)}`}>All tickets</OpenLink>
      }
    >
      <Region query={runs} title="the agents' tickets" lines={4}>
        {() => {
          const columns = kanban(runs.data?.items ?? [], now);
          const working = STAGES.filter((s) => s.id !== "REPORTED").flatMap((s) => columns[s.id]);
          const ordered = [...working, ...columns.FAILED, ...columns.REPORTED];
          if (ordered.length === 0) {
            return (
              <div className="ah-card po-empty">
                <Icon name="moon" />
                <span>
                  <b>No agent is working on a ticket right now.</b> Agents pick up Linear tickets
                  labelled <span className="ah-mono">agent-ready</span>.
                </span>
              </div>
            );
          }
          return (
            <div className="ah-card po-tasks">
              {working.length === 0 && (
                <div className="po-empty" style={{ borderBottom: "1px solid var(--border)" }}>
                  <Icon name="moon" />
                  <span>
                    <b>No agent is working on a ticket right now.</b> Here is what finished this
                    week.
                  </span>
                </div>
              )}
              {ordered.slice(0, TASKS_VISIBLE).map((run) => (
                <TaskRow key={run.id} run={run} now={now} />
              ))}
            </div>
          );
        }}
      </Region>
    </Section>
  );
}

function RecentWorkSection({ project, hubPath }: { project: string; hubPath: string }) {
  const sessions = useRecentSessions(project);
  const navigate = useNavigate();
  const now = useNow(30_000);
  const columns: DataTableColumn<Session>[] = [
    {
      id: "session",
      label: "What",
      render: (s) => <SessionLabel session={s} />,
    },
    {
      id: "outcome",
      label: "Status",
      render: (s) => {
        const badge = sessionBadge(s);
        return <StatusBadge status={badge.status} inferred={s.end_inferred} />;
      },
    },
    {
      id: "started",
      label: "Started",
      render: (s) => (
        <span className="ah-small ah-muted">
          <Time iso={s.started_at} ago={Math.max(0, (now - Date.parse(s.started_at)) / 1000)} />
        </span>
      ),
    },
    {
      id: "duration",
      label: "Took",
      align: "right",
      render: (s) => (
        <span className="ah-num" style={{ fontWeight: 400 }}>
          {fmtDuration(durationSeconds(s.started_at, s.ended_at, now))}
        </span>
      ),
    },
    {
      id: "cost",
      label: "Cost",
      align: "right",
      render: (s) => <Money value={s.cost_usd} />,
    },
  ];
  return (
    <Section
      id="sessions"
      title="Recent work"
      sub="The last sessions on this project, running ones first"
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

function HealthBlock({
  project,
  findings,
}: {
  project: string;
  findings: ReturnType<typeof useFindings>;
}) {
  return (
    <div>
      <div className="ah-row">
        <h3>Health checks</h3>
        <span className="ah-grow" />
        <OpenLink href={`/health?scope=${encodeURIComponent(project)}`}>Open Health</OpenLink>
      </div>
      <Region query={findings} title="health">
        {() => {
          const items = findings.data?.items ?? [];
          if (items.length === 0) return <div className="ah-small">No findings.</div>;
          return (
            <>
              <div className="ah-small" style={{ marginBottom: 4 }}>
                {healthLine(healthSummary(items))}
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
          );
        }}
      </Region>
    </div>
  );
}

function ReposBlock({ project }: { project: string }) {
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
    <div>
      <h3>Repositories</h3>
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
    </div>
  );
}

function SetupSection({
  project,
  findings,
}: {
  project: ProjectDetail;
  findings: ReturnType<typeof useFindings>;
}) {
  const summary = findings.data ? healthSummary(findings.data.items) : null;
  const problems = summary ? summary.error + summary.warning : 0;
  const pending = project.lock_state === "sync_pending" || project.lock_state === "drift";
  return (
    <details id="po-setup" className="ah-card po-details">
      <summary>
        <Icon name="chevron-right" size="sm" className="po-chevron" />
        Setup and health
        <span className="ah-small ah-subtle" style={{ fontWeight: 400 }}>
          for engineers · repositories, checks and hub configuration
        </span>
        <span className="ah-grow" />
        {summary && problems > 0 && (
          <StatusBadge
            status={summary.error ? "failed" : "waiting"}
            label={plural(problems, "thing to fix", "things to fix")}
          />
        )}
      </summary>
      <div className="po-details-body">
        <HealthBlock project={project.name} findings={findings} />
        <ReposBlock project={project.name} />
        <div>
          <h3>Hub</h3>
          <dl className="po-meta">
            <dt>Hub repository</dt>
            <dd className="ah-mono" title={project.hub_path}>
              {project.hub_repo}
            </dd>
            <dt>Tracker</dt>
            <dd>
              {project.tracker.kind === "linear" ? "Linear" : project.tracker.kind} team{" "}
              <span className="ah-mono">{project.tracker.teams.join(", ") || "—"}</span>
            </dd>
            <dt>Platform</dt>
            <dd className="ah-row" style={{ gap: 8 }}>
              <span className="ah-mono">{project.platform_version}</span> pinned
              {pending && (
                <Tooltip label="hub.lock records what hub sync last wrote. Run ./hub sync, review the diff, open a hub PR.">
                  <StatusBadge
                    status="waiting"
                    label={`${project.lock_state === "drift" ? "Drift" : "Sync pending"} (lock ${project.lock_version ?? "—"}, pin ${project.platform_version})`}
                  />
                </Tooltip>
              )}
            </dd>
            {project.modules.length > 0 && (
              <>
                <dt>Modules</dt>
                <dd className="ah-row" style={{ gap: 4 }}>
                  {project.modules.map((m) => (
                    <span key={m} className="ah-fm-chip">
                      {m}
                    </span>
                  ))}
                </dd>
              </>
            )}
          </dl>
        </div>
      </div>
    </details>
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

/**
 * Project overview (spec 12), written for anyone on the team: what needs you, this week in numbers,
 * the team's focus, the agents' tickets and recent work; engineering detail folds away at the end.
 */
export function ProjectOverviewScreen() {
  const { project: name = "" } = useParams();
  const project = useProject(name);
  const findings = useFindings(name);
  const summary = useProjectSummary(name);
  useRefreshOnCounts([
    "/api/v1/workflow-runs",
    "/api/v1/sessions",
    "/api/v1/approvals",
    "/api/v1/projects",
    "/api/v1/needs-you",
  ]);
  if (project.isPending) {
    return (
      <div style={{ padding: "16px 32px" }} className="ah-stack" aria-busy="true">
        <Skeleton width={240} height={28} />
        <Skeleton width={620} />
        <div
          style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginTop: 16 }}
        >
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="ah-card" style={{ padding: 16 }}>
              <Skeleton lines={2} />
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
  const live = summary.data?.items.find((p) => p.name === name)?.live_sessions ?? 0;
  return (
    <div className="ah-stack po-page" style={{ gap: 28 }}>
      <Header
        project={project.data}
        health={findings.data ? healthSummary(findings.data.items) : null}
      />
      <NeedsSection project={name} live={live} />
      <KpiSection project={name} />
      <FocusSection project={name} />
      <TasksSection project={name} />
      <RecentWorkSection project={name} hubPath={project.data.hub_path} />
      <SetupSection project={project.data} findings={findings} />
    </div>
  );
}
