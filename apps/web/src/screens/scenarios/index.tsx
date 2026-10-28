import "../features/features.css";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";

import {
  AppLink,
  Button,
  DataTable,
  EmptyState,
  Icon,
  ProblemError,
  SearchField,
  Skeleton,
  STATUS,
  Time,
  useDelayed,
  SKELETON_DELAY_MS,
  type Status,
} from "../../components";
import { useScope } from "../../lib/scope";
import { useRowKeys } from "../../lib/useRowKeys";
import { StaleStamp } from "../portfolio/StaleStamp";
import {
  DeletedToast,
  DeleteScenarioDialog,
  ScenarioMenu,
  scenarioPath,
  type DeletedNotice,
  type DeleteTarget,
} from "./DeleteScenario";
import { Page, ScenarioRunBadge, shortId, useWaitingRows, WaitingCard } from "./parts";
import {
  scenarioHref,
  scenarioRunHref,
  useScenarios,
  type ScenarioCatalog,
  type ScenarioSummary,
} from "./queries";

export { NewScenarioScreen } from "./NewScenario";
export { ScenarioDetailScreen } from "./ScenarioDetail";
export { ScenarioRunScreen } from "./ScenarioRun";

/* Scenarios (AGH-350 T13, spec 23 screen 1): the hubs' scenarios as the Features list shows its
 * rows, how their last scenario run ended, which wait for you, and which files do not load.
 * "New scenario" opens the guided form where Claude writes one; a row's menu deletes one. */

const DELETED_TOAST_MS = 6000;

const EMPTY_BODY =
  "Scenarios are YAML files in the hub's scenarios/<pack>/ folder, and the actions they call are in actions/<pack>/. Describe one and Claude writes it, or add one by hand and check that it loads from a terminal:";

/** Where a scenario's last scenario run stands, as the row shows it. */
type RunState = "waiting" | "running" | "failed" | "done" | "cancelled" | "never";

function runState(item: ScenarioSummary, waitingRuns: Set<string>): RunState {
  const last = item.last_run;
  if (!last) return "never";
  if (last.status === "running") return waitingRuns.has(last.run_id) ? "waiting" : "running";
  return last.status;
}

/** The rows that need you first: waiting, running, failed, then the rest, each by name. */
const RANK: Readonly<Record<RunState, number>> = {
  waiting: 0,
  running: 1,
  failed: 2,
  done: 3,
  cancelled: 3,
  never: 3,
};

const LEAD: Readonly<Record<RunState, { status: Status; color: string } | null>> = {
  waiting: { status: "waiting", color: "var(--waiting)" },
  running: { status: "running", color: "var(--live)" },
  failed: { status: "failed", color: "var(--failed)" },
  done: { status: "done", color: "var(--done)" },
  cancelled: { status: "stopped", color: "var(--text-subtle)" },
  never: null,
};

const STATE_WORDS: Readonly<Record<RunState, string>> = {
  waiting: "Last scenario run waits for you",
  running: "Last scenario run running",
  failed: "Last scenario run failed",
  done: "Last scenario run done",
  cancelled: "Last scenario run cancelled",
  never: "Never run",
};

const rowKey = (item: { project: string; name: string }) => `${item.project}/${item.name}`;

function Summary({ items, waiting }: { items: readonly ScenarioSummary[]; waiting: number }) {
  const packs = new Set(items.map((item) => `${item.project}/${item.pack}`)).size;
  return (
    <p className="ft-summary">
      <span>
        <b>{items.length}</b> {items.length === 1 ? "scenario" : "scenarios"}
      </span>
      <span>
        <b>{packs}</b> {packs === 1 ? "pack" : "packs"}
      </span>
      {waiting > 0 && (
        <span data-group="needs">
          <b>{waiting}</b> {waiting === 1 ? "waits" : "wait"} for you
        </span>
      )}
    </p>
  );
}

function LastRun({ item, state }: { item: ScenarioSummary; state: RunState }) {
  const last = item.last_run;
  if (!last) return <span className="ah-subtle">Never run</span>;
  const id = shortId(last.run_id);
  return (
    <span className="ah-stack" style={{ gap: 2, minWidth: 0 }}>
      <span className="ah-row" style={{ gap: 6, minWidth: 0 }}>
        <ScenarioRunBadge status={last.status} waiting={state === "waiting"} />
        <span className="sc-last-time ah-small ah-muted">
          <Time iso={last.ended_at ?? last.started_at} absolute />
        </span>
      </span>
      <AppLink
        href={scenarioRunHref(item.project, item.name, last.run_id)}
        className="ah-mono ah-small"
        aria-label={`Open scenario run ${id}`}
        onClick={(event) => {
          event.stopPropagation();
        }}
      >
        {id}
      </AppLink>
    </span>
  );
}

function ScenarioRow({
  item,
  state,
  showProject,
  onOpen,
  onDelete,
}: {
  item: ScenarioSummary;
  state: RunState;
  showProject: boolean;
  onOpen: (href: string) => void;
  onDelete: () => void;
}) {
  const href = scenarioHref(item.project, item.name);
  const lead = LEAD[state];
  const icon = lead ? STATUS[lead.status].icon : null;
  const steps = `${String(item.node_count)} ${item.node_count === 1 ? "step" : "steps"}`;
  const label = [
    item.name,
    item.description,
    showProject ? item.project : null,
    `pack ${item.pack}`,
    steps,
    STATE_WORDS[state],
  ]
    .filter(Boolean)
    .join(". ");
  return (
    // The row is one keyboard stop (Enter opens), as the Features and Tickets rows are.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <li
      className="ft-row"
      data-tone={state === "waiting" || state === "failed" ? state : undefined}
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={0}
      data-nav-row=""
      data-row-key={rowKey(item)}
      aria-label={label}
      onClick={() => {
        onOpen(href);
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter" && event.target === event.currentTarget) onOpen(href);
      }}
    >
      <span className="ft-row-lead" aria-hidden="true" style={{ color: lead?.color }}>
        {lead &&
          (icon ? (
            <Icon name={icon} size="sm" />
          ) : (
            <span className="ah-dot ah-pulse ft-row-live" />
          ))}
      </span>
      <div className="ft-row-main">
        <div className="ft-row-head">
          {/* A real link, as the Features rows' title, so it opens in a new tab too. */}
          <Link
            to={href}
            className="ft-row-title"
            tabIndex={-1}
            onClick={(event) => {
              event.stopPropagation();
            }}
          >
            {item.name}
          </Link>
          <span className="ft-row-tag" title={`Pack ${item.pack}`}>
            {item.pack}
          </span>
          {showProject && (
            <span className="ft-row-tag" title={`Project ${item.project}`}>
              {item.project}
            </span>
          )}
        </div>
        <div
          className={item.description ? "ft-row-line" : "ft-row-line ah-subtle"}
          title={item.description ?? undefined}
        >
          {item.description ?? "No description."}
        </div>
      </div>
      <div className="ft-row-meta">
        <span className="sc-steps ah-num">{item.node_count}</span>
        <LastRun item={item} state={state} />
        <ScenarioMenu
          name={item.name}
          openHref={href}
          inProgress={state === "running" || state === "waiting"}
          onDelete={onDelete}
        />
      </div>
    </li>
  );
}

function ColumnHeads() {
  return (
    <div className="ft-cols" aria-hidden="true">
      <span />
      <span>Scenario</span>
      <div className="ft-cols-meta">
        <span className="sc-steps">Steps</span>
        <span>Last scenario run</span>
        <span />
      </div>
    </div>
  );
}

function ScenarioList({
  items,
  waitingRuns,
  query,
  onClear,
  onDelete,
}: {
  items: ScenarioSummary[];
  waitingRuns: Set<string>;
  query: string;
  onClear: () => void;
  onDelete: (item: ScenarioSummary) => void;
}) {
  const navigate = useNavigate();
  const showProject = new Set(items.map((item) => item.project)).size > 1;
  if (items.length === 0) {
    return (
      <div className="ft-empty">
        No scenarios match &quot;{query}&quot;.{" "}
        <Button size="sm" variant="ghost" onClick={onClear}>
          Clear filter
        </Button>
      </div>
    );
  }
  const rows = items
    .map((item) => ({ item, state: runState(item, waitingRuns) }))
    .sort((a, b) => RANK[a.state] - RANK[b.state] || a.item.name.localeCompare(b.item.name));
  return (
    <div className="ft-card sc-list">
      <ColumnHeads />
      <ul className="ft-rows" aria-label="Scenarios">
        {rows.map(({ item, state }) => (
          <ScenarioRow
            key={rowKey(item)}
            item={item}
            state={state}
            showProject={showProject}
            onOpen={(href) => void navigate(href)}
            onDelete={() => {
              onDelete(item);
            }}
          />
        ))}
      </ul>
    </div>
  );
}

function ProblemsTable({ problems }: { problems: ScenarioCatalog["problems"] }) {
  if (problems.length === 0) return null;
  return (
    <section aria-labelledby="sc-problems" className="ah-stack" style={{ gap: 8 }}>
      <h2 id="sc-problems" className="ah-h3" style={{ margin: 0 }}>
        Files that do not load ({problems.length})
      </h2>
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
    </section>
  );
}

function Loading() {
  const shown = useDelayed(SKELETON_DELAY_MS);
  const announced = useDelayed(1000);
  if (!shown) return null;
  return (
    <div className="ft-card sc-list" aria-busy="true">
      {announced && (
        <span className="ah-sr" role="status">
          Loading scenarios
        </span>
      )}
      <ColumnHeads />
      <ul className="ft-rows" aria-hidden="true">
        {Array.from({ length: 4 }, (_, i) => (
          <li key={i} className="ft-row" style={{ cursor: "default" }}>
            <span className="ft-row-lead" />
            <div className="ft-row-main">
              <Skeleton width={180} />
              <Skeleton width={320} />
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** What the scenario's page hands the list after it deleted the scenario. */
interface ListState {
  deleted?: DeletedNotice;
}

/** `/scenarios`: the scenarios of the project in scope (or every one). */
export function ScenariosScreen() {
  const [scope] = useScope();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const newScenario = () => {
    void navigate("/scenarios/new");
  };
  const query = params.get("q") ?? "";
  const scenarios = useScenarios(scope);
  const { rows, waitingRuns } = useWaitingRows(scope);
  const filter = useRef<HTMLInputElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const list = useRef<HTMLDivElement>(null);
  useRowKeys(list);

  const [deleting, setDeleting] = useState<DeleteTarget | null>(null);
  const [notice, setNotice] = useState<DeletedNotice | null>(
    () => (location.state as ListState | null)?.deleted ?? null,
  );
  // Where focus goes once the list read the hub again after a delete: the next row, else the
  // previous, else the filter (a row key, "filter", or "heading" after a delete from the
  // scenario's page).
  const focusAfter = useRef<string | null>(
    (location.state as ListState | null)?.deleted ? "heading" : null,
  );

  useEffect(() => {
    if (notice === null) return undefined;
    const timer = setTimeout(() => {
      setNotice(null);
    }, DELETED_TOAST_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [notice]);

  // The notice is read once: Back or a reload does not show it again.
  useEffect(() => {
    if ((location.state as ListState | null)?.deleted === undefined) return;
    void navigate(`${location.pathname}${location.search}`, { replace: true, state: null });
  }, [location.state, location.pathname, location.search, navigate]);

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

  useEffect(() => {
    const target = focusAfter.current;
    if (target === null || scenarios.isFetching) return;
    focusAfter.current = null;
    if (target === "heading") {
      heading.current?.focus();
    } else if (target === "filter") {
      (filter.current ?? heading.current)?.focus();
    } else {
      const row = list.current?.querySelector<HTMLElement>(
        `[data-row-key="${CSS.escape(target)}"]`,
      );
      (row ?? filter.current ?? heading.current)?.focus();
    }
  }, [scenarios.isFetching, scenarios.dataUpdatedAt]);

  const startDelete = (item: ScenarioSummary) => {
    setDeleting({
      project: item.project,
      name: item.name,
      pack: item.pack,
      path: scenarioPath(item),
    });
  };

  const afterDelete = (deleted: DeleteTarget, done: DeletedNotice) => {
    const order = [...(list.current?.querySelectorAll<HTMLElement>("[data-row-key]") ?? [])].map(
      (row) => row.dataset.rowKey ?? "",
    );
    const at = order.indexOf(rowKey(deleted));
    const next = at < 0 ? undefined : (order[at + 1] ?? order[at - 1]);
    setDeleting(null);
    setNotice(done);
    focusAfter.current = next ?? "filter";
  };

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
          action={
            <Button variant="primary" size="sm" icon="plus" onClick={newScenario}>
              New scenario
            </Button>
          }
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
            <div className="ft-toolbar" role="group" aria-label="Filters">
              <SearchField
                value={query}
                onChange={setQuery}
                label="Filter scenarios by name or description"
                placeholder="Filter scenarios by name or description"
                className="ft-search"
                kbdClassName="ft-search-kbd"
                inputRef={filter}
              />
            </div>
            <div ref={list}>
              <ScenarioList
                items={shown}
                waitingRuns={waitingRuns}
                query={query}
                onClear={() => {
                  setQuery("");
                }}
                onDelete={startDelete}
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
      <div className="sc-page ah-stack" style={{ gap: 16 }}>
        <div className="ft-head">
          <div className="ft-title">
            <h1 ref={heading} className="ah-h1" tabIndex={-1}>
              Scenarios
            </h1>
            <span className="ah-row" style={{ gap: 12 }}>
              <StaleStamp />
              <Button variant="primary" size="sm" icon="plus" onClick={newScenario}>
                New scenario
              </Button>
            </span>
          </div>
          <p className="ah-muted" style={{ margin: 0 }}>
            Flows your hub drives in a declared environment, step by step. Plan one to see what it
            will do before anything runs.
          </p>
          {scenarios.isSuccess && items.length > 0 && (
            <Summary items={items} waiting={rows.length} />
          )}
        </div>
        <WaitingCard rows={rows} />
        {content}
      </div>
      {deleting && (
        <DeleteScenarioDialog
          target={deleting}
          onCancel={() => {
            setDeleting(null);
          }}
          onDeleted={(done) => {
            afterDelete(deleting, done);
          }}
        />
      )}
      <DeletedToast notice={notice} />
    </Page>
  );
}
