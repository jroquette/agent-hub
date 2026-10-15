import { useParams, useSearchParams } from "react-router";
import type { ReactNode } from "react";

import {
  AppLink,
  Banner,
  BudgetBar,
  Button,
  DataTable,
  EmptyState,
  Icon,
  IdChip,
  IssueLink,
  Money,
  ProblemError,
  Skeleton,
  StagePipeline,
  StatusBadge,
  Tabs,
  Time,
  OutsideLink,
} from "../../components";
import { useNow } from "../../lib/clock";
import { fmtClock, fmtDuration, fmtMoney, toNumber } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { useShell } from "../../shell/AppShell";
import { Breadcrumbs } from "../../shell/Breadcrumbs";
import { StaleStamp } from "../portfolio/StaleStamp";
import {
  budgetOf,
  durationSeconds,
  runBadge,
  runOutcome,
  shortRunId,
  stageLabel,
  STEP_OF,
} from "../runs-list/model";
import type { WorkflowRun } from "../runs-list/queries";
import { graphFailureTitle, isGraphRun } from "./graph";
import { failingSession, failureReason, failureTitle, lanes, loopLabel, pipeline } from "./model";
import { useRun, useRunStream } from "./queries";
import { OpenGates } from "./OpenGates";
import { RunCommands } from "./RunCommands";
import { RunGraph } from "./RunGraph";

const TABS = ["sessions", "gates", "tracker", "caps", "pr"] as const;
type Tab = (typeof TABS)[number];
const NOT_CONNECTED = (source: string) => `${source} is not connected in this version.`;

function Fact({ k, children }: { k: string; children: ReactNode }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "112px 1fr",
        gap: 8,
        padding: "6px 0",
        borderBottom: "1px solid var(--border)",
      }}
    >
      <dt className="ah-small ah-subtle">{k}</dt>
      <dd className="ah-small" style={{ minWidth: 0, overflowWrap: "anywhere", margin: 0 }}>
        {children}
      </dd>
    </div>
  );
}

function UsedLimit({ used, limit, pct }: { used: string; limit: string; pct: number }) {
  const color = pct >= 1 ? "var(--failed)" : pct >= 0.8 ? "var(--waiting)" : "var(--text)";
  return (
    <span className="ah-mono" style={{ color }}>
      {used} / {limit}
    </span>
  );
}

function maxAttempts(run: WorkflowRun): { used: number; limit: number } {
  return run.steps.reduce(
    (acc, step) => ({
      used: Math.max(acc.used, step.attempt),
      limit: Math.max(acc.limit, step.max_attempts),
    }),
    { used: 0, limit: 0 },
  );
}

function RunFacts({ run }: { run: WorkflowRun }) {
  const budget = budgetOf(run);
  const cost = toNumber(run.cost_usd) ?? 0;
  const attempts = maxAttempts(run);
  return (
    <aside className="ah-card" aria-label="Run facts">
      <div className="ah-card-head">
        <b className="ah-small">Run facts</b>
        <span className="ah-grow" />
        <span className="ah-small ah-subtle">from hub.json + executor</span>
      </div>
      <dl style={{ padding: "4px 16px 12px", margin: 0 }}>
        <Fact k="Workflow">
          <span className="ah-mono">{run.workflow}</span>
        </Fact>
        <Fact k="Mode">
          {run.mode === "dry_run" ? "Dry run" : run.mode === "live" ? "Live" : "—"}
        </Fact>
        <Fact k="Budget">
          {budget === null ? (
            <Money value={cost} precise />
          ) : (
            <>
              <UsedLimit used={fmtMoney(cost, 4)} limit={fmtMoney(budget, 4)} pct={cost / budget} />{" "}
              · {Math.round((cost / budget) * 100)} %
            </>
          )}
        </Fact>
        <Fact k="Max turns">
          <span className="ah-mono">
            {run.caps?.max_turns ? `${String(run.caps.max_turns)} per session` : "—"}
          </span>
        </Fact>
        <Fact k="Max attempts">
          {attempts.limit ? (
            <>
              <UsedLimit
                used={String(attempts.used)}
                limit={String(attempts.limit)}
                pct={attempts.used / attempts.limit}
              />{" "}
              per loop
            </>
          ) : (
            "—"
          )}
        </Fact>
        <Fact k="Model">
          <span className="ah-mono">{run.caps?.model ?? "—"}</span>
        </Fact>
        <Fact k="Tracker">
          <span className="ah-mono">{run.caps?.tracker_transport ?? "—"}</span>
        </Fact>
        <Fact k="Repo">
          <span className="ah-mono">{run.repo ?? "—"}</span>
        </Fact>
      </dl>
    </aside>
  );
}

function FailureBanner({ run, onTab }: { run: WorkflowRun; onTab: (tab: Tab) => void }) {
  const failure = run.failure;
  const stage = failure?.stage ?? "PICKED";
  const session = failingSession(run);
  const moment =
    failure?.failing_event_id && session
      ? `/sessions/${session}?tab=timeline&event=${failure.failing_event_id}`
      : null;
  return (
    <section
      aria-label="Failure"
      style={{
        background: "var(--failed-soft)",
        borderLeft: "4px solid var(--failed)",
        borderRadius: "var(--radius-lg)",
        padding: "12px 16px",
        display: "grid",
        gridTemplateColumns: "24px 1fr",
        gap: 10,
      }}
    >
      <Icon name="octagon-x" style={{ color: "var(--failed)", marginTop: 2 }} />
      <div className="ah-stack" style={{ gap: 6 }}>
        <b>{isGraphRun(run) ? graphFailureTitle(run) : failureTitle(run, stageLabel(stage))}</b>
        <div>{failureReason(run)}</div>
        {failure?.diagnosis_comment_url && (
          <div className="ah-small ah-muted">
            <OutsideLink href={failure.diagnosis_comment_url}>
              Diagnosis posted to {run.issue?.key ?? "the issue"}
              <Icon name="arrow-up-right" size="sm" />
            </OutsideLink>
          </div>
        )}
        <div className="ah-row ah-wrap" style={{ gap: 8, marginTop: 2 }}>
          {moment ? (
            <AppLink
              className="ah-btn ah-btn-primary"
              href={moment}
              style={{ textDecoration: "none" }}
            >
              Open failing moment
              <Icon name="arrow-right" size="sm" />
            </AppLink>
          ) : (
            <Button
              variant="primary"
              icon="terminal"
              onClick={() => {
                onTab("gates");
              }}
            >
              Open gate log
            </Button>
          )}
          {moment && (
            <Button
              variant="ghost"
              icon="terminal"
              onClick={() => {
                onTab("gates");
              }}
            >
              View gate log
            </Button>
          )}
          {moment && session && (
            <span className="ah-small ah-subtle">
              Session {shortRunId(session)} · the event that failed
            </span>
          )}
        </div>
      </div>
    </section>
  );
}

function Gantt({ run, now }: { run: WorkflowRun; now: number }) {
  const { tz } = usePreferences();
  const { lanes: rows, from, to } = lanes(run, now);
  if (rows.length === 0) {
    return (
      <EmptyState icon="hourglass" title="No sessions in this run yet">
        The run is at {stageLabel(run.stage)}. Sessions appear when the Implement step starts.
      </EmptyState>
    );
  }
  const pct = (t: number) => ((t - from) / (to - from)) * 100;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => from + f * (to - from));
  const color = {
    ok: "var(--chart-1)",
    failed: "var(--failed)",
    running: "var(--live)",
    skipped: "var(--border-strong)",
  } as const;
  return (
    <div className="ah-stack" style={{ gap: 4 }} role="list" aria-label="Steps over time">
      <div style={{ display: "grid", gridTemplateColumns: "170px 1fr", gap: 8 }} aria-hidden="true">
        <span />
        <div style={{ position: "relative", height: 16 }} className="ah-small ah-subtle">
          {ticks.map((t, i) => (
            <span
              key={t}
              style={{
                position: "absolute",
                left: `${String(pct(t))}%`,
                transform:
                  i === 0
                    ? undefined
                    : i === ticks.length - 1
                      ? "translateX(-100%)"
                      : "translateX(-50%)",
                fontSize: 11,
              }}
            >
              {fmtClock(new Date(t), tz)}
            </span>
          ))}
        </div>
      </div>
      {rows.map((lane) => (
        <div
          key={lane.id}
          role="listitem"
          style={{
            display: "grid",
            gridTemplateColumns: "170px 1fr",
            gap: 8,
            alignItems: "center",
            minHeight: 34,
          }}
        >
          <div className="ah-stack" style={{ gap: 2, minWidth: 0 }}>
            <span className="ah-small" style={{ fontWeight: 500 }}>
              {lane.label}
              <span className="ah-subtle" style={{ fontWeight: 400 }}>
                {" · "}
                {fmtDuration((lane.end - lane.start) / 1000)}
              </span>
              {lane.status === "failed" && (
                <Icon
                  name="x"
                  size="sm"
                  style={{ color: "var(--failed)", verticalAlign: "-3px", marginLeft: 2 }}
                />
              )}
            </span>
            <span className="ah-row ah-wrap" style={{ gap: 4 }}>
              {lane.sessions.length === 0 ? (
                <span className="ah-small ah-subtle">script step</span>
              ) : (
                lane.sessions.map((sid) => (
                  <AppLink key={sid} href={`/sessions/${sid}`} className="ah-mono ah-small">
                    {shortRunId(sid)}
                  </AppLink>
                ))
              )}
            </span>
          </div>
          <div
            style={{
              position: "relative",
              height: 20,
              background: "var(--surface-sunken)",
              borderRadius: "var(--radius-sm)",
            }}
          >
            <span
              title={`${lane.label} · ${lane.status} · ${fmtDuration((lane.end - lane.start) / 1000)}`}
              style={{
                position: "absolute",
                top: 3,
                bottom: 3,
                left: `${String(pct(lane.start))}%`,
                width: `max(4px, ${String(pct(lane.end) - pct(lane.start))}%)`,
                background: color[lane.status],
                borderRadius: "var(--radius-sm)",
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

function GatesTab({ run }: { run: WorkflowRun }) {
  if (run.gate_results.length === 0) {
    return (
      <EmptyState icon="hourglass" title="No gate has run yet.">
        Gates run in Verifying: the repo&apos;s fast check, then its full check.
      </EmptyState>
    );
  }
  return (
    <DataTable
      caption="Gate results"
      density="compact"
      rowKey={(gate) => gate.event_id}
      rows={run.gate_results}
      columns={[
        {
          id: "command",
          label: "Command",
          render: (gate) => <span className="ah-mono">{gate.command ?? "—"}</span>,
        },
        {
          id: "exit",
          label: "Exit",
          align: "right",
          render: (gate) =>
            gate.exit_code === null || gate.exit_code === undefined ? (
              "—"
            ) : (
              <span className={`ah-exit ${gate.exit_code === 0 ? "ah-exit-ok" : "ah-exit-bad"}`}>
                {gate.exit_code}
              </span>
            ),
        },
        {
          id: "duration",
          label: "Duration",
          align: "right",
          render: (gate) =>
            gate.duration_ms === null || gate.duration_ms === undefined
              ? "—"
              : fmtDuration(gate.duration_ms / 1000),
        },
        {
          id: "result",
          label: "Result",
          render: (gate) => <StatusBadge status={gate.result === "passed" ? "passed" : "failed"} />,
        },
      ]}
    />
  );
}

function CapsTab({ run }: { run: WorkflowRun }) {
  const budget = budgetOf(run);
  const cost = toNumber(run.cost_usd) ?? 0;
  const attempts = maxAttempts(run);
  const rows: [string, string, string, number | null][] = [
    [
      "Budget",
      fmtMoney(cost, 4),
      budget === null ? "—" : fmtMoney(budget, 4),
      budget ? cost / budget : null,
    ],
    ["Max turns per session", "—", run.caps?.max_turns ? String(run.caps.max_turns) : "—", null],
    [
      "Max attempts per loop",
      String(attempts.used),
      attempts.limit ? String(attempts.limit) : "—",
      attempts.limit ? attempts.used / attempts.limit : null,
    ],
  ];
  return (
    <div className="ah-stack" style={{ gap: 8 }}>
      <DataTable
        caption="Caps"
        density="compact"
        rowKey={(row) => row[0]}
        rows={rows}
        columns={[
          { id: "cap", label: "Cap", render: (row) => row[0] },
          {
            id: "used",
            label: "Used / limit",
            align: "right",
            render: (row) => <UsedLimit used={row[1]} limit={row[2]} pct={row[3] ?? 0} />,
          },
          {
            id: "pct",
            label: "Share",
            render: (row) =>
              row[3] === null ? (
                <span className="ah-small ah-subtle">—</span>
              ) : (
                <span className="ah-small ah-subtle">
                  {Math.round(row[3] * 100)} %{row[3] >= 1 ? " · cap reached" : ""}
                </span>
              ),
          },
        ]}
      />
      <div className="ah-small ah-mono ah-muted">
        {run.session_ids.length} {run.session_ids.length === 1 ? "session" : "sessions"} · total{" "}
        {fmtMoney(cost, 4)} ·{" "}
        {run.cost_source === "executor" ? "reported by the executor" : "estimated from transcripts"}
      </div>
    </div>
  );
}

function PrTab({ run }: { run: WorkflowRun }) {
  if (run.pr_url) {
    return (
      <div className="ah-stack" style={{ gap: 12 }}>
        <div className="ah-row ah-wrap" style={{ gap: 12 }}>
          <Icon name="git-pull-request" />
          <OutsideLink href={run.pr_url}>
            Open the pull request
            <Icon name="arrow-up-right" size="sm" />
          </OutsideLink>
        </div>
        <p className="ah-small ah-muted" style={{ margin: 0 }}>
          {NOT_CONNECTED("GitHub")} CI checks and review rounds are not shown.
        </p>
      </div>
    );
  }
  if (run.stage === "FAILED") {
    return (
      <EmptyState icon="git-pull-request" title="No PR.">
        The run failed before the PR open stage. CI checks run only once a PR exists.
      </EmptyState>
    );
  }
  return (
    <EmptyState icon="git-pull-request" title="No PR yet">
      The PR appears when the run reaches PR open.
    </EmptyState>
  );
}

function OutcomeLine({ run }: { run: WorkflowRun }) {
  const { tz } = usePreferences();
  if (run.stage !== "REPORTED") return null;
  return (
    <div
      className="ah-row ah-wrap"
      style={{
        gap: 8,
        background: "var(--done-soft)",
        borderRadius: "var(--radius-lg)",
        padding: "10px 16px",
      }}
    >
      <Icon name="circle-check" style={{ color: "var(--done)" }} />
      <span>
        Reported{run.ended_at ? ` at ${fmtClock(run.ended_at, tz)}` : ""}
        {run.pr_url ? " · PR opened" : " · no PR"}
      </span>
    </div>
  );
}

function Header({ run, now }: { run: WorkflowRun; now: number }) {
  const outcome = runOutcome(run);
  const badge = runBadge(run);
  const budget = budgetOf(run);
  const cost = toNumber(run.cost_usd);
  const retryFrom = run.failure
    ? (STEP_OF[run.failure.stage === "FAILED" ? "PICKED" : run.failure.stage] ?? "verify")
    : "verify";
  return (
    <div
      style={{
        position: "sticky",
        top: 0,
        zIndex: "var(--z-sticky)",
        background: "var(--bg)",
        borderBottom: "1px solid var(--border)",
        padding: "12px 32px",
      }}
    >
      <Breadcrumbs
        items={[
          { label: run.project, href: `/projects/${encodeURIComponent(run.project)}` },
          { label: "Workflow runs", href: "/runs" },
          { label: `Run ${run.issue?.key ?? shortRunId(run.id)}` },
        ]}
      />
      <div className="ah-row ah-wrap" style={{ gap: 12, marginTop: 8 }}>
        {run.issue && <IssueLink id={run.issue.key} href={run.issue.url} />}
        <h1 className="ah-h2">{run.issue?.title ?? `Run ${shortRunId(run.id)}`}</h1>
        <StatusBadge
          status={badge.status}
          label={badge.label === "Done" ? "Reported" : badge.label}
          title={run.delivery_reason ?? undefined}
        />
        {run.mode === "dry_run" && <StatusBadge status="idle" label="Dry run" />}
        <StaleStamp />
        <span className="ah-grow" />
        <RunCommands run={run} />
        {outcome === "failed" && !isGraphRun(run) && (
          <Button variant="primary" icon="rotate-ccw" phase="P4">
            Retry from {retryFrom}
          </Button>
        )}
        {run.issue?.url && (
          <OutsideLink className="ah-btn" href={run.issue.url} style={{ textDecoration: "none" }}>
            Open issue {run.issue.key}
            <Icon name="arrow-up-right" size="sm" />
          </OutsideLink>
        )}
      </div>
      <div
        className="ah-row ah-wrap ah-small"
        style={{ gap: 16, marginTop: 8, color: "var(--text-muted)" }}
      >
        <IdChip id={run.id} kind="run" />
        <span className="ah-mono">{run.workflow}</span>
        <span>
          <span className="ah-subtle">repo </span>
          <span className="ah-mono" style={{ color: "var(--text)" }}>
            {run.repo ?? "—"}
          </span>
        </span>
        <span className="ah-badge ah-badge-live ah-badge-quiet">
          <Icon name="play" />
          {run.mode === "dry_run" ? "dry run" : (run.mode ?? "mode unknown")}
        </span>
      </div>
      <div
        className="ah-row ah-wrap ah-small"
        style={{ gap: 16, marginTop: 8, color: "var(--text-muted)" }}
      >
        <span>
          <span className="ah-subtle">Started </span>
          <Time iso={run.started_at} absolute />
        </span>
        <span>
          <span className="ah-subtle">Duration </span>
          <span className="ah-num" style={{ fontWeight: 400 }}>
            {fmtDuration(durationSeconds(run.started_at, run.ended_at, now))}
            {run.ended_at ? "" : " · running"}
          </span>
        </span>
        {budget !== null && cost !== null ? (
          <div style={{ width: 220 }}>
            <BudgetBar spent={cost} budget={budget} label="Cost vs budget" />
          </div>
        ) : (
          <span>
            <span className="ah-subtle">Cost </span>
            <Money value={run.cost_usd} />
          </span>
        )}
        <span>
          {run.session_ids.length} {run.session_ids.length === 1 ? "session" : "sessions"}
        </span>
        {run.pr_url ? (
          <OutsideLink className="ah-row" href={run.pr_url} style={{ gap: 4 }}>
            <Icon name="git-pull-request" size="sm" />
            PR
            <Icon name="arrow-up-right" size="sm" />
          </OutsideLink>
        ) : (
          <span className="ah-subtle">no PR</span>
        )}
      </div>
    </div>
  );
}

function RunNotFound({ runId }: { runId: string }) {
  const { openPalette } = useShell();
  return (
    <div style={{ padding: 32, maxWidth: 760 }} className="ah-stack">
      <h1 className="ah-h2">Run {shortRunId(runId)} not found</h1>
      <p className="ah-muted" style={{ margin: 0 }}>
        No workflow run with id {runId}. It may belong to a hub that is no longer registered.
      </p>
      <div className="ah-row" style={{ gap: 8 }}>
        <Button
          icon="search"
          onClick={() => {
            openPalette(runId);
          }}
        >
          Search with Ctrl K
        </Button>
        <AppLink className="ah-btn" href="/runs">
          Go to Workflow runs
        </AppLink>
      </div>
    </div>
  );
}

function RunBody({ run }: { run: WorkflowRun }) {
  const [params, setParams] = useSearchParams();
  const now = useNow(run.ended_at ? 60_000 : 1000);
  useRunStream(run.id, run.ended_at === null);
  const steps = pipeline(run, now);
  const loop = loopLabel(steps);
  const tabParam = params.get("tab");
  const tab: Tab = (TABS as readonly string[]).includes(tabParam ?? "")
    ? (tabParam as Tab)
    : "sessions";
  const setTab = (next: Tab) => {
    setParams(
      (current) => {
        const copy = new URLSearchParams(current);
        copy.set("tab", next);
        return copy;
      },
      { replace: true },
    );
  };
  return (
    <div style={{ position: "relative", minHeight: "100%" }}>
      <Header run={run} now={now} />
      <div style={{ padding: "16px 32px 40px" }} className="ah-stack">
        {run.stage === "FAILED" && <FailureBanner run={run} onTab={setTab} />}
        {run.mode === "dry_run" && (
          <Banner tone="info" boxed>
            Dry run: no commands executed and nothing written to Linear. Below is what a live run
            would do.
          </Banner>
        )}
        <OutcomeLine run={run} />
        {isGraphRun(run) && <OpenGates run={run} />}
        {isGraphRun(run) ? (
          <RunGraph run={run} now={now} />
        ) : (
          <div>
            <div className="ah-row" style={{ marginBottom: 8 }}>
              <span className="ah-overline">Stages</span>
            </div>
            <StagePipeline steps={steps} />
            {loop && (
              <div
                className="ah-row ah-small"
                style={{ gap: 4, marginTop: 8, color: "var(--failed)", fontWeight: 500 }}
              >
                <Icon name="rotate-ccw" size="sm" />
                {loop}
              </div>
            )}
          </div>
        )}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(0, 1fr) 340px",
            gap: 16,
            alignItems: "start",
          }}
        >
          <div className="ah-stack" style={{ gap: 12, minWidth: 0 }}>
            <Tabs
              label="Run detail"
              value={tab}
              onChange={(id) => {
                setTab(id as Tab);
              }}
              tabs={[
                { id: "sessions", label: "Sessions (Gantt)", count: run.session_ids.length },
                { id: "gates", label: "Gates", count: run.gate_results.length },
                { id: "tracker", label: "Tracker writes" },
                { id: "caps", label: "Caps" },
                { id: "pr", label: "PR and CI" },
              ]}
            />
            <div role="tabpanel" aria-label={tab}>
              {tab === "sessions" && (
                <div className="ah-card" style={{ padding: "12px 12px 8px" }}>
                  <div className="ah-row ah-small ah-subtle" style={{ marginBottom: 6, gap: 12 }}>
                    <span>
                      Wall clock · one lane per step attempt · click a session id to open it
                    </span>
                    <span className="ah-grow" />
                    <span className="ah-legend">
                      <span>
                        <i style={{ background: "var(--chart-1)" }} />
                        passed
                      </span>
                      <span>
                        <i style={{ background: "var(--live)" }} />
                        running
                      </span>
                      <span>
                        <i style={{ background: "var(--failed)" }} />
                        failed
                      </span>
                    </span>
                  </div>
                  <Gantt run={run} now={now} />
                </div>
              )}
              {tab === "gates" && <GatesTab run={run} />}
              {tab === "tracker" && (
                <EmptyState icon="plug" title="No tracker writes shown.">
                  {NOT_CONNECTED("Linear")} Labels and comments the run writes appear here once it
                  is.
                </EmptyState>
              )}
              {tab === "caps" && <CapsTab run={run} />}
              {tab === "pr" && <PrTab run={run} />}
            </div>
          </div>
          <RunFacts run={run} />
        </div>
      </div>
    </div>
  );
}

/** Run detail (spec 13, screen 2): where the run stopped, why, and what to open next. */
export function RunDetailScreen() {
  const { runId = "" } = useParams();
  const run = useRun(runId);
  if (run.isPending) {
    return (
      <div style={{ padding: "16px 32px" }} className="ah-stack" aria-busy="true">
        <Skeleton width={420} height={28} />
        <Skeleton width={680} height={14} />
        <Skeleton width={560} height={14} />
        <div style={{ display: "flex", gap: 0, marginTop: 12 }}>
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} height={64} radius={0} style={{ flex: 1, marginLeft: i ? 2 : 0 }} />
          ))}
        </div>
        {Array.from({ length: 5 }, (_, i) => (
          <Skeleton key={i} width={`${String(30 + ((i * 23) % 50))}%`} height={16} />
        ))}
      </div>
    );
  }
  if (run.isError) {
    if (run.error.status === 404) return <RunNotFound runId={runId} />;
    return (
      <div style={{ padding: 32, maxWidth: 760 }} className="ah-stack">
        <ProblemError
          title="Could not load run"
          detail={run.error.detail}
          status={run.error.status}
          onRetry={() => void run.refetch()}
        />
      </div>
    );
  }
  return <RunBody run={run.data} />;
}
