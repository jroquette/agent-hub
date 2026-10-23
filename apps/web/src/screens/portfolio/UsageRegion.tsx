import { useState } from "react";

import {
  Button,
  DataTable,
  ProblemError,
  SegmentedControl,
  Skeleton,
  Time,
} from "../../components";
import type { DataTableColumn } from "../../components";
import { useNow } from "../../lib/clock";
import { useSkillUsage, type UsageDays, type UsageRow } from "./queries";

/** The rows shown before "Show all N" (spec 12's cap rule: working memory, as Needs you). */
export const USAGE_VISIBLE = 10;
const WINDOWS: readonly UsageDays[] = [7, 30, 90];
const EMPTY_ONE = "No skills or agents in this hub's .claude folder.";
const EMPTY_ALL = "No skills or agents in the hubs' .claude folders.";
const NOT_READ = "Some items were not read; the list may be incomplete.";

function runsIn(row: UsageRow, days: UsageDays): number {
  if (days === 7) return row.runs_7d;
  if (days === 30) return row.runs_30d;
  return row.runs_90d;
}

function usageColumns(days: UsageDays, single: boolean, now: number): DataTableColumn<UsageRow>[] {
  const columns: DataTableColumn<UsageRow>[] = [
    {
      id: "name",
      label: "Name",
      render: (row) => (
        <span className="ah-mono">{row.kind === "skill" ? `/${row.name}` : row.name}</span>
      ),
    },
    {
      id: "kind",
      label: "Kind",
      render: (row) => (row.kind === "skill" ? "Skill" : "Agent"),
    },
    {
      id: "runs",
      label: `Runs · ${String(days)} d`,
      align: "right",
      hint: `Runs in the last ${String(days)} days`,
      render: (row) => {
        const runs = runsIn(row, days);
        return <span className={runs === 0 ? "ah-num ah-muted" : "ah-num"}>{String(runs)}</span>;
      },
    },
    {
      id: "last",
      label: "Last used",
      render: (row) =>
        row.last_used_at ? (
          <Time
            iso={row.last_used_at}
            ago={Math.max(0, (now - Date.parse(row.last_used_at)) / 1000)}
          />
        ) : (
          <span className="ah-muted">Not in 90 d</span>
        ),
    },
  ];
  if (single) return columns;
  return [{ id: "project", label: "Project", render: (row) => row.project }, ...columns];
}

function NotRead() {
  return (
    <p className="ah-small ah-muted" style={{ margin: "8px 0 0" }}>
      {NOT_READ}
    </p>
  );
}

/**
 * Skills and agents (spec 12, AGH-482): the hub's own skills and agents with their runs in the
 * chosen window, never used first. The window is local state (30 d by default, as the Toolkit),
 * not the page's `?period=`.
 */
export function UsageRegion({ project, single }: { project: string | null; single: boolean }) {
  const [days, setDays] = useState<UsageDays>(30);
  const [all, setAll] = useState(false);
  const usage = useSkillUsage(project, days);
  const now = useNow(60_000);
  let body;
  if (usage.isPending) {
    body = <Skeleton lines={4} />;
  } else if (usage.isError) {
    body = (
      <ProblemError
        title="Could not load skill and agent usage"
        detail={usage.error.detail}
        status={usage.error.status}
        compact
        onRetry={() => void usage.refetch()}
      />
    );
  } else if (usage.data.items.length === 0) {
    body = (
      <>
        <p className="ah-small ah-muted" style={{ margin: 0 }}>
          {single ? EMPTY_ONE : EMPTY_ALL}
        </p>
        {usage.data.truncated && <NotRead />}
      </>
    );
  } else {
    const items = usage.data.items;
    const shown = all ? items : items.slice(0, USAGE_VISIBLE);
    body = (
      <>
        <DataTable
          caption="Skills and agents"
          density="compact"
          columns={usageColumns(days, single, now)}
          rows={shown}
          rowKey={(row) => `${row.project}/${row.kind}/${row.name}`}
        />
        {shown.length < items.length && (
          <Button
            size="sm"
            variant="ghost"
            style={{ marginTop: 8 }}
            onClick={() => {
              setAll(true);
            }}
          >
            Show all {items.length}
          </Button>
        )}
        {usage.data.truncated && <NotRead />}
      </>
    );
  }
  return (
    <section
      aria-labelledby="usage-title"
      aria-busy={usage.isPending || usage.isPlaceholderData ? "true" : undefined}
    >
      <div className="ah-section-title ah-wrap">
        <div className="ah-stack" style={{ gap: 2 }}>
          <h2 id="usage-title" className="ah-h3" style={{ fontSize: 14 }}>
            Skills and agents
          </h2>
          <span className="ah-small ah-subtle">
            Runs in the last {days} days · never used first
          </span>
        </div>
        <span className="ah-grow" />
        <SegmentedControl
          label="Usage window"
          value={String(days)}
          onChange={(id) => {
            setDays(Number(id) as UsageDays);
          }}
          options={WINDOWS.map((window) => ({ id: String(window), label: `${String(window)} d` }))}
        />
      </div>
      {body}
    </section>
  );
}
