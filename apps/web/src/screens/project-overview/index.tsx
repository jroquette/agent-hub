import "./project-overview.css";

import { useRef, type ComponentProps, type ReactNode } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";

import {
  AppLink,
  Banner,
  BudgetBar,
  Button,
  DataTable,
  EmptyState,
  Icon,
  KpiStat,
  NeedsYouList,
  ProblemError,
  ProvenanceBadge,
  Skeleton,
  StatusBadge,
  Time,
  Tooltip,
} from "../../components";
import type { DataTableColumn, IconName, Provenance } from "../../components";
import { STAGES } from "../../components";
import { useNow } from "../../lib/clock";
import { fmtAgo, fmtDuration, fmtMoney, toNumber } from "../../lib/format";
import { useRowKeys } from "../../lib/useRowKeys";
import { useShell } from "../../shell/AppShell";
import { Breadcrumbs } from "../../shell/Breadcrumbs";
import { featureHref } from "../features/FeatureChip";
import { issueId, reasonOf, type Reason } from "../features/groups";
import { useFeatureNames } from "../features/names";
import { useFeatures } from "../features/queries";
import { ConfigSource } from "../hub-config";
import { NEEDS_MAX, costDelta, needsEntry, orderNeeds } from "../portfolio/model";
import { useNeedsYou, useRefreshOnCounts } from "../portfolio/queries";
import { StaleStamp } from "../portfolio/StaleStamp";
import { budgetOf, durationSeconds, finishedCosts, median } from "../runs-list/model";
import type { WorkflowRun } from "../runs-list/queries";
import { ScenarioRunBadge } from "../scenarios/parts";
import { scenarioOfLabel, scenarioRunHref } from "../scenarios/queries";
import { TicketItem } from "../tickets";
import { ticketsOf } from "../tickets/model";
import {
  daysSince,
  healthBadge,
  healthLine,
  healthSummary,
  kanban,
  RECENT_VISIBLE,
  recentFeatures,
  recentTickets,
  runsInOrder,
  STALE_DAYS,
  topFindings,
  type RecentFeature,
} from "./model";
import {
  useFindings,
  useProject,
  useProjectNow,
  useProjectRepos,
  useProjectRuns,
  useProjectConfig,
  useProjectSessions,
  useProjectSummary,
  type NowItem,
  type ProjectDetail,
  type RepoView,
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
            <a
              href="#po-setup"
              style={{ textDecoration: "none" }}
              onClick={() => {
                // The section is folded by default; following the link opens it.
                const setup = document.getElementById("po-setup");
                if (setup instanceof HTMLDetailsElement) setup.open = true;
              }}
            >
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
  // A scenario run is called so, never "run" alone, and opens on its own page (E-15); it has
  // no workflow stages and no pull request: its own status and times say where it is (F4).
  const scenario = run.kind === "scenario" ? scenarioOfLabel(run.workflow) : null;
  if (scenario !== null) {
    note =
      run.ended_at === null
        ? `Started ${fmtDuration(durationSeconds(run.started_at, null, now))} ago`
        : `Ended ${fmtDuration(durationSeconds(run.ended_at, null, now))} ago`;
  }
  return (
    <AppLink
      href={
        scenario === null
          ? `/runs/${encodeURIComponent(run.id)}`
          : scenarioRunHref(run.project, scenario, run.id)
      }
      className="po-task"
      data-failed={failed || undefined}
    >
      <span className="po-task-title">
        {scenario === null ? (
          <span>
            <span className="ah-mono ah-small" style={{ fontWeight: 500, marginRight: 6 }}>
              {run.issue?.key ?? run.id.slice(0, 8)}
            </span>
            {run.issue?.title ?? ""}
          </span>
        ) : (
          <span>
            <span className="ah-small" style={{ fontWeight: 500, marginRight: 6 }}>
              Scenario run <span className="ah-mono">{run.id.slice(0, 8)}</span>
            </span>
            <span className="ah-mono">{scenario}</span>
          </span>
        )}
        <span className="ah-small ah-subtle po-task-note">{note}</span>
      </span>
      {scenario === null ? <StepProgress run={run} /> : <ScenarioRunBadge status={run.status} />}
      <span>
        {scenario !== null ? null : budget !== null && cost !== null && !done && !failed ? (
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
          const { working, ordered } = runsInOrder(runs.data?.items ?? [], now);
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

const FEATURE_TONE: Record<NonNullable<Reason["tone"]>, string> = {
  blocked: "var(--blocked)",
  failed: "var(--failed)",
  waiting: "var(--waiting)",
  done: "var(--done)",
};

const RECENT_SUB = "What the team worked on in the last 7 days · costs estimated from transcripts";

/** A tooltip on plain text, reachable by keyboard; nothing when there is nothing to say. */
function Hint({ label, children }: { label: ReactNode; children: ReactNode }) {
  if (!label) return <>{children}</>;
  return (
    <Tooltip label={label}>
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
      <span className="po-hint" tabIndex={0}>
        {children}
      </span>
    </Tooltip>
  );
}

/** A feature worked on this week, read only: its name, where it is on the golden path, when and cost. */
function RecentFeatureItem({
  row,
  name,
  now,
  onOpen,
}: {
  row: RecentFeature;
  name: string | null;
  now: number;
  onOpen: (href: string) => void;
}) {
  const f = row.feature;
  const reason = reasonOf(f);
  const href = featureHref(f) + (reason.doc ? `?doc=${reason.doc}` : "");
  const ago = Math.max(0, (now - Date.parse(row.lastActivityAt)) / 1000);
  return (
    // The row is one keyboard stop (Enter opens), as on Features.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <li
      className="ft-row"
      data-tone={reason.needs !== null ? (reason.tone ?? undefined) : undefined}
      data-muted={reason.group === "shipped" || undefined}
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={0}
      data-nav-row=""
      aria-label={[name ?? f.slug, reason.line, `worked on ${fmtAgo(ago)}`].join(". ")}
      onClick={() => {
        onOpen(href);
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter" && event.target === event.currentTarget) onOpen(href);
      }}
    >
      <span
        className="ft-row-lead"
        aria-hidden="true"
        style={reason.tone ? { color: FEATURE_TONE[reason.tone] } : undefined}
      >
        {reason.icon && <Icon name={reason.icon} size="sm" />}
      </span>
      <div className="ft-row-main">
        <div className="ft-row-head">
          <span className="ft-row-title" data-named={name ? "" : undefined} title={f.slug}>
            {name ?? f.slug}
          </span>
        </div>
        <div className="ft-row-line" title={reason.line}>
          {reason.line} · worked on <Time iso={row.lastActivityAt} ago={ago} />
        </div>
      </div>
      <div className="ft-row-meta">
        <span className="ah-small ah-muted ah-mono">{fmtMoney(row.costUsd)}</span>
      </div>
    </li>
  );
}

function RecentList({
  id,
  title,
  href,
  linkText,
  children,
}: {
  id: string;
  title: string;
  href: string;
  linkText: string;
  children: ReactNode;
}) {
  return (
    <div className="po-recent-col">
      <div className="po-recent-head">
        <h3 id={id}>{title}</h3>
        <OpenLink href={href}>{linkText}</OpenLink>
      </div>
      {children}
    </div>
  );
}

function RecentSkeleton() {
  return (
    <div aria-busy="true">
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
    </div>
  );
}

/** The features and tickets the team worked on this week; sessions stay on Sessions. */
function RecentWorkSection({ project, hubPath }: { project: string; hubPath: string }) {
  const features = useFeatures(project);
  const sessions = useProjectSessions(project);
  const runs = useProjectRuns(project);
  const nameOf = useFeatureNames();
  const navigate = useNavigate();
  const now = useNow(30_000);
  const listRef = useRef<HTMLDivElement>(null);
  useRowKeys(listRef);
  const open = (href: string) => void navigate(href);
  const scope = encodeURIComponent(project);

  const sessionItems = sessions.data?.items ?? [];
  const featureItems = features.data?.items ?? [];
  const featureIssues = new Map(
    featureItems.flatMap((f) =>
      f.issues.map(
        (i) =>
          [issueId(i).toUpperCase(), { project: f.project, slug: f.slug, title: null }] as const,
      ),
    ),
  );
  // Only the runs listed in "Tickets the agents are working on" are left out here.
  const runIssues = new Set(
    runsInOrder(runs.data?.items ?? [], now)
      .ordered.slice(0, TASKS_VISIBLE)
      .flatMap((r) => (r.issue ? [r.issue.key.toUpperCase()] : [])),
  );
  const featureRows = recentFeatures(featureItems, sessionItems, now).slice(0, RECENT_VISIBLE);
  const ticketRows = recentTickets(ticketsOf(sessionItems, featureIssues), runIssues, now).slice(
    0,
    RECENT_VISIBLE,
  );

  if (sessions.isSuccess && sessionItems.length === 0) {
    return (
      <Section id="recent" title="Recent work" sub={RECENT_SUB}>
        <div className="ah-card">
          <EmptyState
            icon="square-terminal"
            title="No sessions yet."
            command={`cd ${hubPath} && claude`}
          >
            Start Claude Code in the hub directory with hub web running:
          </EmptyState>
        </div>
      </Section>
    );
  }

  return (
    <Section id="recent" title="Recent work" sub={RECENT_SUB}>
      <div className="po-recent" ref={listRef}>
        <RecentList
          id="po-recent-features"
          title="Features"
          href={`/features?scope=${scope}`}
          linkText="Open Features"
        >
          {features.isPending || sessions.isPending ? (
            <RecentSkeleton />
          ) : features.isError ? (
            <ProblemError
              title="Could not load features"
              detail={features.error.detail}
              status={features.error.status}
              onRetry={() => void features.refetch()}
            />
          ) : sessions.isError ? (
            // Which feature was worked on is read from the sessions; without them it is unknown.
            <ProblemError
              title="Could not tell which features were worked on"
              detail={sessions.error.detail}
              status={sessions.error.status}
              onRetry={() => void sessions.refetch()}
            />
          ) : featureRows.length === 0 ? (
            <div className="ah-card po-empty">No feature was worked on in the last 7 days.</div>
          ) : (
            <div className="ft-card">
              <ul className="ft-rows" aria-labelledby="po-recent-features">
                {featureRows.map((row) => (
                  <RecentFeatureItem
                    key={row.feature.slug}
                    row={row}
                    name={nameOf(row.feature)}
                    now={now}
                    onOpen={open}
                  />
                ))}
              </ul>
            </div>
          )}
        </RecentList>
        <RecentList
          id="po-recent-tickets"
          title="Tickets"
          href={`/tickets?scope=${scope}`}
          linkText="Open Tickets"
        >
          {sessions.isPending ? (
            <RecentSkeleton />
          ) : sessions.isError ? (
            <ProblemError
              title="Could not load tickets"
              detail={sessions.error.detail}
              status={sessions.error.status}
              onRetry={() => void sessions.refetch()}
            />
          ) : ticketRows.length === 0 ? (
            <div className="ah-card po-empty">No ticket was worked on in the last 7 days.</div>
          ) : (
            <div className="ft-card">
              <ul className="ft-rows" aria-labelledby="po-recent-tickets">
                {ticketRows.map((row) => (
                  <TicketItem
                    key={row.issue}
                    row={row}
                    showProject={false}
                    now={now}
                    onOpen={open}
                  />
                ))}
              </ul>
            </div>
          )}
        </RecentList>
      </div>
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
  const total = findings.data?.items.length ?? 0;
  return (
    <div>
      <div className="po-recent-head">
        <h3>Health checks</h3>
        <OpenLink href={`/health?scope=${encodeURIComponent(project)}`}>
          {total > 0 ? `See all ${plural(total, "finding")}` : "Open Health"}
        </OpenLink>
      </div>
      <Region query={findings} title="health">
        {() => {
          const items = findings.data?.items ?? [];
          if (items.length === 0) return <div className="ah-small">No findings.</div>;
          return (
            <>
              <div className="ah-small ah-muted" style={{ marginBottom: 4 }}>
                {healthLine(healthSummary(items))}
              </div>
              <ul className="po-findings">
                {topFindings(items).map((f) => {
                  const [icon, color] = SEVERITY_ICON[f.severity];
                  const where = f.path ? `${f.path}${f.line ? `:${String(f.line)}` : ""}` : null;
                  return (
                    <li key={`${f.rule}:${f.path ?? ""}:${String(f.line)}`} className="po-finding">
                      <Icon name={icon} size="sm" style={{ color }} title={f.severity} />
                      <span className="po-finding-text">
                        <span className="po-finding-message" title={f.message}>
                          {f.message}
                        </span>
                        {where && (
                          <span className="ah-mono ah-subtle po-finding-path" title={where}>
                            {where}
                          </span>
                        )}
                      </span>
                      <span className="ah-small ah-subtle ah-mono">{f.rule}</span>
                    </li>
                  );
                })}
              </ul>
            </>
          );
        }}
      </Region>
    </div>
  );
}

/** A repo's checks in words; the commands themselves sit in the tooltip. */
function checksLook(repo: RepoView): { icon: IconName; color: string; label: string } {
  const fast = Boolean(repo.check_fast);
  const full = Boolean(repo.check);
  if (fast && full) return { icon: "circle-check", color: "var(--done)", label: "Fast and full" };
  if (full) return { icon: "triangle-alert", color: "var(--waiting)", label: "No fast check" };
  if (fast) return { icon: "triangle-alert", color: "var(--waiting)", label: "No full check" };
  return { icon: "circle-x", color: "var(--failed)", label: "No checks" };
}

function ChecksCell({ repo }: { repo: RepoView }) {
  const look = checksLook(repo);
  const tip = (
    <span className="po-check-tip">
      <span>Fast check</span>
      <code className="ah-mono">{repo.check_fast || "none"}</code>
      <span>Full check</span>
      <code className="ah-mono">{repo.check || "none"}</code>
    </span>
  );
  return (
    <Tooltip label={tip}>
      {/* Focusable so keyboard users reach the commands in its tooltip. */}
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
      <span className="ah-row ah-small" style={{ gap: 4 }} tabIndex={0}>
        <Icon name={look.icon} size="sm" style={{ color: look.color }} />
        {look.label}
      </span>
    </Tooltip>
  );
}

function InstructionsCell({ repo }: { repo: RepoView }) {
  if (!repo.agents_md_present)
    return (
      <Tooltip label="Each repo needs its own AGENTS.md. Run hub doctor for the fix.">
        <span className="ah-row ah-small" style={{ gap: 4, color: "var(--failed)" }}>
          <Icon name="circle-x" size="sm" />
          Missing
        </span>
      </Tooltip>
    );
  const lines = repo.agents_md_lines ?? 0;
  const long = lines > 100;
  return (
    <span
      className="ah-row ah-small"
      style={{ gap: 4, color: long ? "var(--waiting)" : undefined }}
    >
      <Icon
        name={long ? "triangle-alert" : "circle-check"}
        size="sm"
        style={{ color: long ? "var(--waiting)" : "var(--done)" }}
      />
      {repo.agents_md_lines ?? "?"} lines{long ? ", over 100" : ""}
    </span>
  );
}

function ReposBlock({ project }: { project: string }) {
  const repos = useProjectRepos(project);
  const columns: DataTableColumn<RepoView>[] = [
    { id: "repo", label: "Repo", render: (r) => <b style={{ fontWeight: 500 }}>{r.name}</b> },
    { id: "role", label: "What it is", render: (r) => r.role ?? "—" },
    {
      id: "branch",
      label: "Main branch",
      render: (r) => <span className="ah-mono ah-small">{r.default_branch ?? "—"}</span>,
    },
    {
      id: "prs",
      label: "Open pull requests",
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
    { id: "checks", label: "Checks", render: (r) => <ChecksCell repo={r} /> },
    { id: "agents", label: "Agent instructions", render: (r) => <InstructionsCell repo={r} /> },
  ];
  return (
    <div>
      <div className="po-recent-head">
        <h3>Repositories</h3>
        <OpenLink href={`/projects/${encodeURIComponent(project)}/config#repositories`}>
          Open hub configuration
        </OpenLink>
      </div>
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

type HubConfig = NonNullable<ReturnType<typeof useProjectConfig>["data"]>;
/** Who set a value, as Hub configuration's `ConfigSource` names it. */
type Source = ComponentProps<typeof ConfigSource>["source"];
interface Sourced {
  source: Source;
  where: string;
}

/** Who set a value, shown only when a person did (the team or you); built-in values say nothing. */
function SetBy({ value }: { value: Sourced }) {
  if (value.source === "default" || value.source === "commit_title") return null;
  return <ConfigSource source={value.source} where={value.where} />;
}

function Mono({ children }: { children: ReactNode }) {
  return <code className="ah-mono">{children}</code>;
}

/** One sentence of a setup card, with who set it at the end when a person did. */
function Fact({ children, setBy }: { children: ReactNode; setBy?: Sourced | undefined }) {
  return (
    <li className="po-fact">
      <span className="po-fact-text">{children}</span>
      {setBy && <SetBy value={setBy} />}
    </li>
  );
}

function SetupCard({
  icon,
  title,
  link,
  children,
}: {
  icon: IconName;
  title: string;
  link?: { href: string; text: string } | undefined;
  children: ReactNode;
}) {
  return (
    <div className="ah-card po-config-card">
      <div className="po-config-card-head">
        <Icon name={icon} size="sm" />
        <h3>{title}</h3>
        <span className="ah-grow" />
        {link && <OpenLink href={link.href}>{link.text}</OpenLink>}
      </div>
      <ul className="po-facts">{children}</ul>
    </div>
  );
}

/** What each pattern placeholder means, in words (docs/design/project-config.md). */
const PLACEHOLDER_WORDS: Record<string, string> = {
  ISSUE: "issue key",
  issue_lower: "issue key, lower case",
  slug: "short description",
  prefix: "your branch prefix",
  type: "kind of change",
  scope: "area",
  summary: "summary",
};

/** A naming pattern as text with each placeholder as a word chip. */
function PatternWords({ pattern }: { pattern: string }) {
  // The chips are words, so a screen reader reads the pattern in order as it is shown.
  const parts = pattern.split(/(\{\w+\})/).filter(Boolean);
  return (
    <span className="po-pattern">
      {parts.map((p, i) => {
        const key = /^\{(\w+)\}$/.exec(p)?.[1];
        return key ? (
          <span key={i} className="ah-fm-chip">
            {PLACEHOLDER_WORDS[key] ?? p}
          </span>
        ) : (
          <span key={i} className="ah-mono">
            {p}
          </span>
        );
      })}
    </span>
  );
}

function namesList(items: readonly string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1] ?? ""}`;
}

function TrackerFacts({ config }: { config: HubConfig }) {
  const { tracker } = config;
  const where = tracker.kind === "linear" ? "Linear" : tracker.kind;
  const teams = tracker.teams.length ? tracker.teams : ["—"];
  return (
    <>
      <Fact>
        Agents pick up {where} issues in team{teams.length > 1 ? "s" : ""}{" "}
        <Mono>{namesList(teams)}</Mono> labelled <Mono>{tracker.ready_label}</Mono>.
      </Fact>
      <Fact>
        While working they move an issue from <Mono>{tracker.started_state}</Mono> to{" "}
        <Mono>{tracker.review_state}</Mono>.
      </Fact>
      <Fact>
        When they fail they add the label <Mono>{tracker.failed_label}</Mono>.
      </Fact>
    </>
  );
}

function NamingFacts({ config }: { config: HubConfig }) {
  const [branch, commit, pr] = config.conventions;
  const prFollows = pr.source === "commit_title" || pr.pattern === commit.pattern;
  const prefix = config.branch_prefix.value;
  const usesPrefix = branch.pattern.includes("{prefix}");
  const example = (p: { example: string | null }) =>
    p.example ? (
      <>
        Example with a made-up issue: <code className="ah-mono">{p.example}</code>
      </>
    ) : null;
  return (
    <>
      <Fact setBy={branch}>
        <span className="po-fact-label">Branches</span>
        <Hint label={example(branch)}>
          <PatternWords pattern={branch.pattern} />
        </Hint>
      </Fact>
      <Fact setBy={commit}>
        <span className="po-fact-label">
          {prFollows ? "Commit and pull request titles" : "Commit titles"}
        </span>
        <Hint label={example(commit)}>
          <PatternWords pattern={commit.pattern} />
        </Hint>
      </Fact>
      {!prFollows && (
        <Fact setBy={pr}>
          <span className="po-fact-label">Pull request titles</span>
          <Hint label={example(pr)}>
            <PatternWords pattern={pr.pattern} />
          </Hint>
        </Fact>
      )}
      {prefix && (
        <Fact setBy={config.branch_prefix}>
          {usesPrefix ? (
            <>
              Your branches start with <Mono>{prefix}</Mono>.
            </>
          ) : (
            <span className="ah-muted">
              Your branch prefix <Mono>{prefix}</Mono> is not used: the branch pattern has no place
              for it.
            </span>
          )}
        </Fact>
      )}
      {config.author_name.value && (
        <Fact setBy={config.author_name}>Commits are signed {config.author_name.value}.</Fact>
      )}
    </>
  );
}

/** The badge on an environment the hub marks as the live, customer-facing one. */
const LIVE_ENV_LABEL = "Production";

const ACCESS_WORDS: Record<"read" | "write" | "ask", string> = {
  write: "can change",
  read: "can read",
  ask: "ask you before changing",
};

/** The guard's rules as sentences, zeros left out, then what agents may do in each environment. */
function GuardFacts({ project, config }: { project: string; config: HubConfig }) {
  const { guard, environments } = config;
  const blocked = guard.blocked_words.team.length + guard.blocked_words.local.length;
  const envs = environments.environments;
  const byAccess = (["write", "ask", "read"] as const)
    .map((access) => ({ access, list: envs.filter((e) => e.access === access) }))
    .filter((g) => g.list.length > 0);
  const anyRule =
    guard.ask_before_edit.length + guard.deny_paths.length + guard.deny_hosts.length + blocked >
      0 || guard.infra_on;
  const envHref = `/projects/${encodeURIComponent(project)}/environments`;
  return (
    <>
      {guard.ask_before_edit.length > 0 && (
        <Fact>
          <Hint
            label={
              <span className="po-path-list">
                {guard.ask_before_edit.slice(0, 10).map((p) => (
                  <code key={p} className="ah-mono">
                    {p}
                  </code>
                ))}
                {guard.ask_before_edit.length > 10 && (
                  <span>and {String(guard.ask_before_edit.length - 10)} more</span>
                )}
              </span>
            }
          >
            Agents ask you before editing{" "}
            {plural(guard.ask_before_edit.length, "file or folder", "files and folders")}.
          </Hint>
        </Fact>
      )}
      {guard.deny_paths.length > 0 && (
        <Fact>
          Agents never read or edit{" "}
          {plural(guard.deny_paths.length, "file or folder", "files and folders")}.
        </Fact>
      )}
      {guard.deny_hosts.length > 0 && (
        <Fact>Agents never contact {plural(guard.deny_hosts.length, "host")}.</Fact>
      )}
      {blocked > 0 && (
        <Fact>
          {plural(blocked, "word is", "words are")} blocked from anything the agents write.
        </Fact>
      )}
      {guard.infra_on && <Fact>The infra guard is on.</Fact>}
      {!anyRule && <Fact>No rules beyond the built-in ones.</Fact>}
      {byAccess.map(({ access, list }) => (
        <Fact key={access}>
          Agents {ACCESS_WORDS[access]} {plural(list.length, "environment")}:{" "}
          {list.map((e, i) => (
            <span key={e.name}>
              {i > 0 && ", "}
              <AppLink href={envHref}>{e.name}</AppLink>
              {e.source === "hub.local.json" && <span className="ah-muted"> (yours)</span>}
              {e.production && (
                <>
                  {" "}
                  <StatusBadge status="waiting" label={LIVE_ENV_LABEL} />
                </>
              )}
            </span>
          ))}
          .
        </Fact>
      ))}
      {environments.services.length > 0 && (
        <Fact>
          {plural(
            environments.services.length,
            "service has its address",
            "services have their addresses",
          )}{" "}
          listed.
        </Fact>
      )}
    </>
  );
}

function HubFacts({ project, config }: { project: ProjectDetail; config: HubConfig }) {
  const pending = project.lock_state === "sync_pending" || project.lock_state === "drift";
  const repos = config.repos.map((r) => r.dir);
  return (
    <>
      <Fact>
        Rules and memory live in{" "}
        <a
          href={`https://github.com/${project.hub_repo}`}
          target="_blank"
          rel="noreferrer"
          title={project.hub_path}
        >
          {project.hub_repo} <Icon name="external-link" size="sm" />
        </a>
        .
      </Fact>
      <Fact>
        {plural(repos.length, "repository", "repositories")}: {namesList(repos)}.
      </Fact>
      <Fact>
        Platform <Mono>{project.platform_version}</Mono>
        {pending ? (
          <>
            {" "}
            <Tooltip label="hub.lock records what hub sync last wrote. Run ./hub sync, review the diff, open a hub PR.">
              <StatusBadge
                status="waiting"
                label={`${project.lock_state === "drift" ? "Drift" : "Sync pending"} (lock ${project.lock_version ?? "—"}, pin ${project.platform_version})`}
              />
            </Tooltip>
          </>
        ) : (
          " · up to date"
        )}
      </Fact>
    </>
  );
}

/** What hub.json (and my hub.local.json) set for this project, in plain sentences. */
function ConfigSection({ project }: { project: ProjectDetail }) {
  const config = useProjectConfig(project.name);
  const home = `/projects/${encodeURIComponent(project.name)}/config`;
  return (
    <Section
      id="config"
      title="How this project is set up"
      sub="From hub.json and your hub.local.json"
      action={<OpenLink href={home}>Open hub configuration</OpenLink>}
    >
      <Region query={config} title="the hub configuration" lines={4}>
        {() =>
          config.data && (
            <div className="po-config">
              <SetupCard
                icon="list-checks"
                title="Where the work comes from"
                link={{ href: `${home}#tracker`, text: "See tracker" }}
              >
                <TrackerFacts config={config.data} />
              </SetupCard>
              <SetupCard
                icon="git-branch"
                title="How work is named"
                link={{ href: `${home}#repositories`, text: "See naming" }}
              >
                <NamingFacts config={config.data} />
              </SetupCard>
              <SetupCard
                icon="shield-alert"
                title="What agents may touch"
                link={{ href: `${home}#guard`, text: "See guard" }}
              >
                <GuardFacts project={project.name} config={config.data} />
              </SetupCard>
              <SetupCard icon="box" title="The hub">
                <HubFacts project={project} config={config.data} />
              </SetupCard>
            </div>
          )
        }
      </Region>
    </Section>
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
  return (
    <details id="po-setup" className="ah-card po-details">
      <summary>
        <Icon name="chevron-right" size="sm" className="po-chevron" />
        Setup and health
        <span className="ah-small ah-subtle" style={{ fontWeight: 400 }}>
          for engineers · repositories and checks
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
      <ConfigSection project={project.data} />
      <SetupSection project={project.data} findings={findings} />
    </div>
  );
}
