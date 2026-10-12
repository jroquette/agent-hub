import { useState } from "react";
import type { ReactNode } from "react";
import { useNavigate, useSearchParams } from "react-router";

import {
  Button,
  DataTable,
  EmptyState,
  FilterRail,
  Icon,
  IdChip,
  IssueLink,
  Money,
  ProblemError,
  StageChip,
  StatusBadge,
  Tooltip,
  OutsideLink,
} from "../../components";
import type { DataTableColumn, Facet } from "../../components";
import { useNow } from "../../lib/clock";
import { fmtDuration, fmtMoney, toNumber } from "../../lib/format";
import { useScope } from "../../lib/scope";
import { useRefreshOnCounts } from "../portfolio/queries";
import { StaleStamp } from "../portfolio/StaleStamp";
import {
  attemptText,
  budgetOf,
  byAttention,
  chipStage,
  durationSeconds,
  finishedCosts,
  median,
  OUTCOME_BADGE,
  runOutcome,
  stageLabel,
} from "./model";
import { useRuns, type RunFilters, type Stage, type WorkflowRun } from "./queries";

const PAGE = 50;
const STAGE_IDS: readonly Stage[] = [
  "PICKED",
  "WORKTREE",
  "IMPLEMENTING",
  "VERIFYING",
  "PR_OPEN",
  "REPORTED",
  "FAILED",
];
const FILTER_KEYS = ["stage", "outcome", "failure_stage", "repo", "mode"] as const;
type FilterKey = (typeof FILTER_KEYS)[number];

/** Cost against budget in one table row: amber at 80 %, failed at 100 % (spec 13). */
export function CompactBudget({ spent, budget }: { spent: number | null; budget: number | null }) {
  if (budget === null || budget === 0) return <Money value={spent} />;
  const value = spent ?? 0;
  const pct = value / budget;
  const level = pct >= 1 ? "over" : pct >= 0.8 ? "warn" : "ok";
  return (
    <Tooltip
      label={`${fmtMoney(value)} of ${fmtMoney(budget)} budget · ${String(Math.round(pct * 100))} %`}
    >
      <span
        className="ah-budget"
        data-level={level}
        style={{ flexDirection: "row", alignItems: "center", gap: 8, minWidth: 0 }}
      >
        <span
          className="ah-num"
          style={{
            width: 46,
            textAlign: "right",
            color:
              level === "ok" ? undefined : level === "warn" ? "var(--waiting)" : "var(--failed)",
          }}
        >
          {fmtMoney(value)}
        </span>
        <span
          className="ah-budget-track"
          style={{ width: 40, flex: "none" }}
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={budget}
          aria-valuenow={value}
          aria-label={`Cost ${fmtMoney(value)} of ${fmtMoney(budget)}`}
        >
          <span
            className="ah-budget-fill"
            style={{ display: "block", width: `${String(Math.min(100, pct * 100))}%` }}
          />
        </span>
      </span>
    </Tooltip>
  );
}

function asStage(value: string | null): Stage | null {
  return value !== null && (STAGE_IDS as readonly string[]).includes(value)
    ? (value as Stage)
    : null;
}

function readFilters(params: URLSearchParams, project: string | null): RunFilters {
  const outcome = params.get("outcome");
  const mode = params.get("mode");
  return {
    project,
    stage: asStage(params.get("stage")),
    outcome: outcome === "done" || outcome === "failed" ? outcome : null,
    failure_stage: asStage(params.get("failure_stage")),
    repo: params.get("repo"),
    mode: mode === "live" || mode === "dry_run" ? mode : null,
  };
}

function facets(runs: readonly WorkflowRun[], filters: RunFilters): Facet[] {
  const count = (pred: (run: WorkflowRun) => boolean) => runs.filter(pred).length;
  const repos = [
    ...new Set(runs.map((run) => run.repo).filter((repo): repo is string => repo !== null)),
  ];
  if (filters.repo && !repos.includes(filters.repo)) repos.push(filters.repo);
  return [
    {
      id: "stage",
      title: "Stage",
      options: STAGE_IDS.map((stage) => ({
        id: stage,
        label: stageLabel(stage),
        count: count((run) => run.stage === stage),
        checked: filters.stage === stage,
      })),
    },
    {
      id: "outcome",
      title: "Outcome",
      options: [
        {
          id: "done",
          label: "Done",
          count: count((run) => runOutcome(run) === "done"),
          checked: filters.outcome === "done",
        },
        {
          id: "failed",
          label: "Failed",
          count: count((run) => runOutcome(run) === "failed"),
          checked: filters.outcome === "failed",
        },
      ],
    },
    {
      id: "failure_stage",
      title: "Failure stage",
      options: STAGE_IDS.filter((stage) => stage !== "REPORTED" && stage !== "FAILED").map(
        (stage) => ({
          id: stage,
          label: stageLabel(stage),
          count: count((run) => run.failure?.stage === stage),
          checked: filters.failure_stage === stage,
        }),
      ),
    },
    {
      id: "repo",
      title: "Repo",
      options: repos.map((repo) => ({
        id: repo,
        label: repo,
        mono: true,
        count: count((run) => run.repo === repo),
        checked: filters.repo === repo,
      })),
    },
    {
      id: "mode",
      title: "Mode",
      options: [
        {
          id: "live",
          label: "Live",
          count: count((run) => run.mode === "live"),
          checked: filters.mode === "live",
        },
        {
          id: "dry_run",
          label: "Dry run",
          count: count((run) => run.mode === "dry_run"),
          checked: filters.mode === "dry_run",
        },
      ],
    },
  ];
}

function columns(now: number): DataTableColumn<WorkflowRun>[] {
  return [
    {
      id: "issue",
      label: "Issue · run · repo · workflow",
      render: (run) => (
        <div style={{ minWidth: 0, maxWidth: 320, padding: "5px 0" }}>
          <div className="ah-row" style={{ gap: 6, minWidth: 0 }}>
            {run.issue ? (
              <IssueLink id={run.issue.key} title={run.issue.title} href={run.issue.url} />
            ) : (
              <span className="ah-subtle">no issue</span>
            )}
            {run.issue?.title && (
              <span
                style={{
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                  fontWeight: 500,
                }}
                title={run.issue.title}
              >
                {run.issue.title}
              </span>
            )}
          </div>
          <div
            className="ah-row ah-small ah-subtle"
            style={{ gap: 6, minWidth: 0, whiteSpace: "nowrap" }}
          >
            <span style={{ flex: "none" }}>
              <IdChip id={run.id} />
            </span>
            <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
              <span className="ah-mono">{run.repo ?? run.project}</span> ·{" "}
              <span className="ah-mono">{run.workflow}</span>
            </span>
          </div>
        </div>
      ),
    },
    {
      id: "stage",
      label: "Stage · attempt",
      width: 180,
      render: (run) => {
        const outcome = runOutcome(run);
        return (
          <div className="ah-stack" style={{ gap: 2, alignItems: "flex-start" }}>
            {outcome === "failed" ? (
              <Tooltip label={run.failure?.reason ?? "No reason recorded"}>
                <StageChip stage={chipStage(run)} failed />
              </Tooltip>
            ) : (
              <StageChip stage={chipStage(run)} state={outcome === "done" ? "done" : "active"} />
            )}
            <span className="ah-small ah-subtle">{attemptText(run)}</span>
          </div>
        );
      },
    },
    {
      id: "started",
      label: "Started · duration",
      width: 120,
      render: (run) => (
        <div className="ah-stack" style={{ gap: 0 }}>
          <span className="ah-mono" style={{ fontSize: 12 }}>
            {new Date(run.started_at).toLocaleString("en-GB", {
              day: "2-digit",
              month: "short",
              hour: "2-digit",
              minute: "2-digit",
            })}
          </span>
          <span className="ah-small ah-subtle">
            {fmtDuration(durationSeconds(run.started_at, run.ended_at, now))}
          </span>
        </div>
      ),
    },
    {
      id: "cost",
      label: "Cost · mode",
      width: 120,
      render: (run) => (
        <div className="ah-stack" style={{ gap: 2 }}>
          <CompactBudget spent={toNumber(run.cost_usd)} budget={budgetOf(run)} />
          <span className="ah-small ah-subtle" style={{ paddingLeft: 6 }}>
            {run.mode === "dry_run" ? "dry run" : (run.mode ?? "—")}
          </span>
        </div>
      ),
    },
    {
      id: "outcome",
      label: "Outcome · PR",
      width: 120,
      render: (run) => {
        const badge = OUTCOME_BADGE[runOutcome(run)];
        return (
          <div className="ah-stack" style={{ gap: 2, alignItems: "flex-start" }}>
            <StatusBadge status={badge.status} label={badge.label} />
            {run.pr_url ? (
              <OutsideLink className="ah-mono ah-small" href={run.pr_url} title="Opens GitHub">
                PR
                <Icon name="arrow-up-right" size="sm" />
              </OutsideLink>
            ) : (
              <span className="ah-subtle ah-small">no PR</span>
            )}
          </div>
        );
      },
    },
  ];
}

/** Workflow runs (spec 13): what is in flight and what broke. */
export function RunsListScreen() {
  const [scope] = useScope();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const [limit, setLimit] = useState(PAGE);
  const filters = readFilters(params, scope);
  const runs = useRuns(filters, limit);
  const now = useNow(15_000);
  useRefreshOnCounts(["/api/v1/workflow-runs"]);
  const filtered = FILTER_KEYS.some((key) => params.get(key) !== null);

  const toggle = (facet: string, option: string) => {
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (next.get(facet) === option) next.delete(facet);
        else next.set(facet, option);
        return next;
      },
      { replace: true },
    );
  };
  const clear = () => {
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        for (const key of FILTER_KEYS) next.delete(key satisfies FilterKey);
        return next;
      },
      { replace: true },
    );
  };

  const items = byAttention(runs.data?.items ?? []);
  const reported = items.filter((run) => runOutcome(run) === "done").length;
  const failed = items.filter((run) => runOutcome(run) === "failed").length;
  const running = items.length - reported - failed;
  const mid = median(finishedCosts(items));
  const neverAny = runs.isSuccess && items.length === 0 && !filtered;

  let content: ReactNode;
  if (runs.isError) {
    content = (
      <ProblemError
        title="Could not load workflow runs"
        detail={runs.error.detail}
        status={runs.error.status}
        onRetry={() => void runs.refetch()}
      />
    );
  } else if (neverAny) {
    content = (
      <div className="ah-card">
        <EmptyState
          icon="route"
          title="No workflow runs yet."
          command="./hub run <issue> --dry-run"
        >
          Runs appear when the executor picks an issue labelled agent-ready. Start one from the
          terminal (proposed CLI):
        </EmptyState>
      </div>
    );
  } else {
    content = (
      <DataTable
        caption="Workflow runs, failed and in progress first"
        columns={columns(now)}
        rows={items}
        rowKey={(run) => run.id}
        loading={runs.isPending}
        density="compact"
        onRowClick={(run) => void navigate(`/runs/${encodeURIComponent(run.id)}`)}
        empty={
          <span className="ah-row" style={{ gap: 8, padding: 16 }}>
            No runs match these filters.
            <Button size="sm" variant="ghost" onClick={clear}>
              Clear filters
            </Button>
          </span>
        }
        footer={
          <>
            <span>
              {runs.isPending
                ? "Loading runs…"
                : `Showing ${String(items.length)} of ${String(Math.max(items.length, runs.data.total_estimate))} · sorted by attention, then started`}
            </span>
            {runs.data?.next_cursor && limit < 200 && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setLimit(Math.min(200, limit + PAGE));
                }}
              >
                Show more
              </Button>
            )}
            <span className="ah-row" style={{ gap: 4 }}>
              <Icon name="link" size="sm" />
              Filters are in the URL
            </span>
          </>
        }
      />
    );
  }

  return (
    <div
      style={{ padding: "16px 32px 40px", position: "relative", minHeight: "100%" }}
      className="ah-stack"
    >
      <div className="ah-stack" style={{ gap: 6 }}>
        <div className="ah-row" style={{ gap: 12 }}>
          <h1 className="ah-h1">Workflow runs</h1>
          <StaleStamp />
        </div>
        <div className="ah-row ah-wrap" style={{ gap: 12 }}>
          {runs.isSuccess && (
            <span className="ah-muted">
              <span className="ah-num">{items.length}</span> runs ·{" "}
              <span className="ah-num">{reported}</span> reported ·{" "}
              <span className="ah-num" style={{ color: failed ? "var(--failed)" : undefined }}>
                {failed}
              </span>{" "}
              failed · <span className="ah-num">{running}</span> in progress
              {mid !== null && (
                <>
                  {" "}
                  · median <span className="ah-num">{fmtMoney(mid)}</span>
                </>
              )}
            </span>
          )}
          <span className="ah-grow" />
          <Button variant="primary" icon="play" phase="P4">
            Start run on an issue
          </Button>
        </div>
      </div>
      <div style={{ display: "flex", gap: 24, alignItems: "flex-start", marginTop: 8 }}>
        {!neverAny && (
          <FilterRail
            facets={facets(items, filters)}
            onToggle={toggle}
            footer={
              <Button size="sm" variant="ghost" icon="x" onClick={clear} disabled={!filtered}>
                Clear all
              </Button>
            }
          />
        )}
        <div className="ah-grow" style={{ minWidth: 0 }}>
          {content}
        </div>
      </div>
    </div>
  );
}
