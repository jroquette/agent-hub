import { useEffect, useRef, type ReactNode, type RefObject } from "react";
import { useSearchParams } from "react-router";

import {
  AppLink,
  Button,
  DataTable,
  EmptyState,
  ProblemError,
  Skeleton,
  Time,
  useDelayed,
  SKELETON_DELAY_MS,
} from "../../components";
import { useScope } from "../../lib/scope";
import { useRowKeys } from "../../lib/useRowKeys";
import { typingIn } from "../../shell/goSequence";
import { StaleStamp } from "../portfolio/StaleStamp";
import { Page, ScenarioRunBadge, shortId, useWaitingRows, WaitingCard } from "./parts";
import {
  scenarioHref,
  scenarioRunHref,
  useScenarios,
  type ScenarioCatalog,
  type ScenarioSummary,
} from "./queries";

export { ScenarioDetailScreen } from "./ScenarioDetail";
export { ScenarioRunScreen } from "./ScenarioRun";

/* Scenarios (AGH-350 T13, spec 23 screen 1): the hubs' scenarios, how their last scenario run
 * ended, which wait for you, and which files do not load. Nothing here writes. */

const EMPTY_BODY =
  "Scenarios are YAML files in the hub's scenarios/<pack>/ folder, and the actions they call are in actions/<pack>/. Add one, then check that it loads from a terminal:";

function countLine(items: readonly ScenarioSummary[], waiting: number): string {
  const packs = new Set(items.map((item) => `${item.project}/${item.pack}`)).size;
  const parts = [
    `${String(items.length)} ${items.length === 1 ? "scenario" : "scenarios"} in ${String(packs)} ${packs === 1 ? "pack" : "packs"}`,
  ];
  if (waiting > 0) {
    parts.push(
      waiting === 1
        ? "1 scenario run waits for you"
        : `${String(waiting)} scenario runs wait for you`,
    );
  }
  return parts.join(" · ");
}

function LastRun({ item, waiting }: { item: ScenarioSummary; waiting: boolean }) {
  const last = item.last_run;
  if (!last) return <span className="ah-subtle">Never run</span>;
  const id = shortId(last.run_id);
  return (
    <span className="ah-stack" style={{ gap: 2 }}>
      <span className="ah-row ah-wrap" style={{ gap: 6 }}>
        <ScenarioRunBadge status={last.status} waiting={waiting} />
        <Time iso={last.ended_at ?? last.started_at} absolute />
      </span>
      <AppLink
        href={scenarioRunHref(item.project, item.name, last.run_id)}
        className="ah-mono ah-small"
        aria-label={`Open scenario run ${id}`}
      >
        {id}
      </AppLink>
    </span>
  );
}

function ProblemsTable({ problems }: { problems: ScenarioCatalog["problems"] }) {
  if (problems.length === 0) return null;
  return (
    <DataTable
      caption={`Files that do not load (${String(problems.length)})`}
      density="compact"
      rows={[...problems]}
      rowKey={(p) => `${p.project}/${p.file}/${p.key}`}
      columns={[
        {
          id: "file",
          label: "File",
          render: (p) => (
            <span className="ah-mono" style={{ color: "var(--failed)" }}>
              {p.file}
              {p.line === null ? "" : `:${String(p.line)}`}
            </span>
          ),
        },
        { id: "key", label: "Key", render: (p) => <span className="ah-mono">{p.key}</span> },
        { id: "message", label: "Problem", render: (p) => p.message },
      ]}
    />
  );
}

function ScenarioTable({
  items,
  waitingRuns,
  query,
  onClear,
}: {
  items: ScenarioSummary[];
  waitingRuns: Set<string>;
  query: string;
  onClear: () => void;
}) {
  const showProject = new Set(items.map((item) => item.project)).size > 1;
  return (
    <DataTable
      caption="Scenarios"
      density="compact"
      rows={items}
      rowKey={(item) => `${item.project}/${item.name}`}
      empty={
        <span>
          No scenarios match &quot;{query}&quot;.{" "}
          <Button size="sm" variant="ghost" onClick={onClear}>
            Clear filter
          </Button>
        </span>
      }
      columns={[
        {
          id: "name",
          label: "Scenario",
          render: (item) => (
            <span className="ah-stack" style={{ gap: 2, minWidth: 0 }}>
              <AppLink
                href={scenarioHref(item.project, item.name)}
                className="ah-mono"
                data-nav-row=""
              >
                {item.name}
              </AppLink>
              <span className={item.description ? "ah-small ah-muted" : "ah-small ah-subtle"}>
                {item.description ?? "No description."}
              </span>
            </span>
          ),
        },
        ...(showProject
          ? [
              {
                id: "project",
                label: "Project",
                render: (item: ScenarioSummary) => <span className="ah-mono">{item.project}</span>,
              },
            ]
          : []),
        {
          id: "pack",
          label: "Pack",
          render: (item) => <span className="ah-mono">{item.pack}</span>,
        },
        {
          id: "steps",
          label: "Steps",
          align: "right",
          render: (item) => <span className="ah-num">{item.node_count}</span>,
        },
        {
          id: "last",
          label: "Last scenario run",
          render: (item) => (
            <LastRun
              item={item}
              waiting={item.last_run?.status === "running" && waitingRuns.has(item.last_run.run_id)}
            />
          ),
        },
      ]}
    />
  );
}

function Loading() {
  const shown = useDelayed(SKELETON_DELAY_MS);
  const announced = useDelayed(1000);
  if (!shown) return null;
  return (
    <div className="ah-stack" aria-busy="true" style={{ gap: 8 }}>
      {announced && (
        <span className="ah-sr" role="status">
          Loading scenarios
        </span>
      )}
      {Array.from({ length: 6 }, (_, i) => (
        <Skeleton key={i} height={40} />
      ))}
    </div>
  );
}

/** `/scenarios`: the scenarios of the project in scope (or every one). */
export function ScenariosScreen() {
  const [scope] = useScope();
  const [params, setParams] = useSearchParams();
  const query = params.get("q") ?? "";
  const scenarios = useScenarios(scope);
  const { rows, waitingRuns } = useWaitingRows(scope);
  const filter = useRef<HTMLInputElement>(null);
  const table = useRef<HTMLDivElement>(null);
  useRowKeys(table);
  useSlash(filter);

  const setQuery = (next: string) => {
    setParams(
      (current) => {
        const copy = new URLSearchParams(current);
        if (next === "") copy.delete("q");
        else copy.set("q", next);
        return copy;
      },
      { replace: true },
    );
  };

  const items = scenarios.data?.items ?? [];
  const problems = scenarios.data?.problems ?? [];
  const q = query.trim().toLowerCase();
  const shown = items.filter(
    (item) => !q || `${item.name}\n${item.description ?? ""}`.toLowerCase().includes(q),
  );

  let content: ReactNode;
  if (scenarios.isPending) {
    content = <Loading />;
  } else if (scenarios.isError) {
    content = (
      <ProblemError
        title="Could not load scenarios"
        detail={scenarios.error.detail}
        status={scenarios.error.status}
        onRetry={() => void scenarios.refetch()}
      />
    );
  } else if (items.length === 0 && problems.length === 0) {
    content = (
      <div className="ah-card">
        <EmptyState
          icon="clipboard-list"
          title={scope === null ? "No scenarios yet." : `No scenarios in ${scope} yet.`}
          command="./hub scenario list"
        >
          {EMPTY_BODY}
        </EmptyState>
      </div>
    );
  } else {
    content = (
      <>
        {items.length === 0 ? (
          <div className="ah-card">
            <EmptyState icon="file-x" title="No scenario loads.">
              Fix the files below; this page reads them again on every visit.
            </EmptyState>
          </div>
        ) : (
          <>
            <input
              ref={filter}
              className="ah-input"
              type="search"
              aria-label="Filter scenarios by name or description"
              placeholder="Filter scenarios by name or description"
              value={query}
              style={{ maxWidth: 420 }}
              onChange={(event) => {
                setQuery(event.target.value);
              }}
              onKeyDown={(event) => {
                if (event.key === "Escape") setQuery("");
              }}
            />
            <div ref={table}>
              <ScenarioTable
                items={shown}
                waitingRuns={waitingRuns}
                query={query}
                onClear={() => {
                  setQuery("");
                }}
              />
            </div>
          </>
        )}
        <ProblemsTable problems={problems} />
      </>
    );
  }

  return (
    <Page>
      <div className="ah-stack" style={{ gap: 4 }}>
        <div className="ah-row" style={{ gap: 12 }}>
          <h1 className="ah-h1">Scenarios</h1>
          <span className="ah-grow" />
          <StaleStamp />
        </div>
        <p className="ah-muted" style={{ margin: 0 }}>
          Flows your hub drives in a declared environment, step by step. Plan one to see what it
          will do before anything runs.
        </p>
        {scenarios.isSuccess && (items.length > 0 || rows.length > 0) && (
          <span className="ah-small ah-subtle">{countLine(items, rows.length)}</span>
        )}
      </div>
      <WaitingCard rows={rows} />
      {content}
    </Page>
  );
}

/** `/` focuses the filter (spec 01 keyboard map). */
function useSlash(target: RefObject<HTMLInputElement | null>) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "/" || event.defaultPrevented || typingIn(event.target)) return;
      if (target.current === null) return;
      event.preventDefault();
      target.current.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, [target]);
}
