import "./scenarios.css";

import { Fragment, type ReactNode } from "react";

import {
  AppLink,
  CodeBlock,
  CopyButton,
  Icon,
  PathText,
  StatusBadge,
  Time,
  type IconName,
} from "../../components";
import type { Approval } from "../approvals/queries";
import {
  gateRun,
  gateStep,
  scenarioOfLabel,
  scenarioRunHref,
  useOpenHumanGates,
  useScenarioRuns,
} from "./queries";

/* Pieces the three Scenarios screens share: statuses, effects, policy decisions, the draft line
 * and the Waiting for you card (AGH-350 T13; docs/design/control-plane/specs/23-scenarios.md). */

export function Page({ children, label }: { children: ReactNode; label?: string }) {
  return (
    <div
      style={{ padding: "16px 32px 40px", minHeight: "100%" }}
      className="ah-stack"
      aria-label={label}
    >
      {children}
    </div>
  );
}

/** The short id of a scenario run (its id is already 8 hex digits). */
export function shortId(runId: string): string {
  return runId.replace(/-/g, "").slice(0, 8);
}

/** A scenario run's status, icon and label (Cancelled for a stopped one, never color alone). */
export function ScenarioRunBadge({
  status,
  waiting = false,
  title,
}: {
  status: string | null;
  waiting?: boolean;
  title?: string;
}) {
  if (waiting) return <StatusBadge status="waiting" title={title} />;
  switch (status) {
    case "done":
      return <StatusBadge status="done" title={title} />;
    case "failed":
      return <StatusBadge status="failed" title={title} />;
    case "cancelled":
      return <StatusBadge status="stopped" label="Cancelled" title={title} />;
    default:
      return <StatusBadge status="running" title={title} />;
  }
}

const EFFECT_ICON: Readonly<Record<string, IconName>> = {
  read: "file-text",
  write: "file-pen",
  destroy: "triangle-alert",
};

export function EffectBadge({ effect }: { effect: string | null | undefined }) {
  if (!effect) return <span className="ah-subtle">—</span>;
  return (
    <span className="ah-badge ah-badge-quiet">
      <Icon name={EFFECT_ICON[effect] ?? "circle-dashed"} />
      {effect}
    </span>
  );
}

const ASKS_TOOLTIP =
  "The scenario run pauses before this step until you approve it. Reject cancels the scenario run.";

/** Allow, Asks you (neutral: an ask in a plan is not yet waiting) or Denied, with the reason. */
export function PolicyBadge({
  decision,
  reason,
  asksTooltip = ASKS_TOOLTIP,
}: {
  decision: string;
  reason?: string | null | undefined;
  asksTooltip?: string;
}) {
  if (decision === "allow") return <StatusBadge status="done" label="Allow" />;
  if (decision === "ask") {
    return (
      <span className="ah-badge ah-badge-quiet" title={asksTooltip}>
        <Icon name="hand" />
        Asks you
      </span>
    );
  }
  return (
    <span className="ah-stack" style={{ gap: 2 }}>
      <StatusBadge status="blocked" label="Denied" />
      {reason && <span className="ah-small">{sentence(reason)}</span>}
    </span>
  );
}

/** "draft action: commit it to run" → "Draft action: commit it to run." */
export function sentence(text: string): string {
  const trimmed = text.trim();
  if (trimmed === "") return trimmed;
  const head = trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
  return /[.!?]$/.test(head) ? head : `${head}.`;
}

interface Endpoint {
  service: string;
  url: string | null;
  resource: string | null;
}

function isEndpoint(value: unknown): value is Endpoint {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { service?: unknown }).service === "string"
  );
}

/** "service → endpoint" of each input that names a service. */
export function WhereText({
  endpoints,
  environment,
}: {
  endpoints: Record<string, unknown>;
  environment: string;
}) {
  const found = Object.values(endpoints).filter(isEndpoint);
  if (found.length === 0) return <span className="ah-subtle">—</span>;
  return (
    // min-width 0: a flex item's min-content would keep a long name from wrapping (F2-R4).
    <span className="ah-stack" style={{ gap: 2, minWidth: 0 }}>
      {found.map((item) => {
        const where = item.url ?? item.resource;
        return (
          <span key={`${item.service}:${where ?? ""}`} className="ah-small">
            <BreakId id={item.service} /> →{" "}
            {where === null ? (
              <span title={`No endpoint in ${environment}.`}>—</span>
            ) : (
              <PathText path={where} max={28} />
            )}
          </span>
        );
      })}
    </span>
  );
}

/** "Draft: needs acceptance." and the exact commit line of each drafted action (AM-5): nothing
 * commits from hub web. */
export function DraftLine({
  commands,
  action,
  then,
  children,
}: {
  commands: readonly string[];
  action: string;
  then: "plan again" | "check again";
  children?: ReactNode;
}) {
  return (
    <div className="ah-stack" style={{ gap: 6 }}>
      <span className="ah-small">
        <span className="ah-badge ah-badge-quiet">
          <Icon name="pencil" />
          Draft: needs acceptance
        </span>{" "}
        Commit it in the hub checkout, then {then}:
      </span>
      {commands.map((command) => (
        <div key={command} className="ah-row" style={{ gap: 6, alignItems: "flex-start" }}>
          <div className="ah-grow" style={{ minWidth: 0 }}>
            <CodeBlock code={command} noCopy wrap label={`Commit command for ${action}`} />
          </div>
          <CopyButton text={command} label={`Copy the commit command for ${action}`} />
        </div>
      ))}
      {children}
    </div>
  );
}

export interface WaitingRow {
  gate: Approval;
  project: string;
  scenario: string;
}

/** Waiting for you: each scenario run an open gate holds, with a link to answer it there. */
export function WaitingCard({
  rows,
  named = true,
}: {
  rows: readonly WaitingRow[];
  named?: boolean;
}) {
  if (rows.length === 0) return null;
  return (
    <section
      aria-label="Waiting for you"
      className="ah-card ah-stack"
      style={{ gap: 10, padding: 16 }}
    >
      <div className="ah-row" style={{ gap: 6 }}>
        <Icon name="hand" size="sm" style={{ color: "var(--waiting)" }} />
        <span className="ah-overline">Waiting for you</span>
      </div>
      {rows.map(({ gate, project, scenario }) => {
        const run = gateRun(gate) ?? "";
        const id = shortId(run);
        const step = gateStep(gate);
        const what =
          gate.gate_kind === "investigation" ? (
            <>
              paused at <span className="ah-mono">{step}</span>
            </>
          ) : (
            <>
              waits for your approval at <span className="ah-mono">{step}</span>
            </>
          );
        return (
          <div key={gate.id} className="ah-row ah-wrap" style={{ gap: 8 }}>
            <span className="ah-small">
              {named && (
                <>
                  <span className="ah-mono">{scenario}</span> ·{" "}
                </>
              )}
              {named ? "scenario run" : "Scenario run"} <span className="ah-mono">{id}</span> {what}{" "}
              since <Time iso={gate.requested_at} />
            </span>
            <span className="ah-grow" />
            <AppLink href={scenarioRunHref(project, scenario, run)}>
              Open scenario run {id}
              <Icon name="arrow-right" size="sm" />
            </AppLink>
          </div>
        );
      })}
    </section>
  );
}

/** The scenario runs an open gate holds, with the scenario each belongs to. */
export function useWaitingRows(project: string | null): {
  rows: WaitingRow[];
  waitingRuns: Set<string>;
} {
  const gates = useOpenHumanGates(project);
  const runs = useScenarioRuns(project);
  const scenarioOf = new Map<string, { project: string; scenario: string }>();
  for (const run of runs.data?.items ?? []) {
    const scenario = scenarioOfLabel(run.workflow);
    if (scenario !== null) scenarioOf.set(run.id, { project: run.project, scenario });
  }
  const rows: WaitingRow[] = [];
  for (const gate of gates.data?.items ?? []) {
    const run = gateRun(gate);
    const found = run === null ? undefined : scenarioOf.get(run);
    if (found) rows.push({ gate, ...found });
  }
  return { rows, waitingRuns: new Set(rows.map((row) => gateRun(row.gate) ?? "")) };
}

export interface PlanColumn {
  id: string;
  label: string;
  /** A fixed width (the table lays out fixed, so a long value wraps, never hides a column). */
  width?: number | string;
}

export interface PlanGridRow {
  key: string;
  cells: Record<string, ReactNode>;
  /** A full-width row under this one (a draft's commit line). */
  extra?: ReactNode;
}

/** A plan as a table whose columns never overflow: cells wrap, and a row's extra line spans
 * the whole width under it (review B1). */
export function PlanGrid({
  caption,
  columns,
  rows,
  compact = false,
}: {
  caption: string;
  columns: readonly PlanColumn[];
  rows: readonly PlanGridRow[];
  compact?: boolean;
}) {
  return (
    <div className="ah-table-wrap" data-density={compact ? "compact" : undefined}>
      <table className="ah-table sc-plan">
        <caption className="ah-sr">{caption}</caption>
        <colgroup>
          {columns.map((column) => (
            <col key={column.id} style={{ width: column.width }} />
          ))}
        </colgroup>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.id} scope="col">
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <Fragment key={row.key}>
              <tr className="sc-plan-main">
                {columns.map((column) => (
                  <td key={column.id}>{row.cells[column.id]}</td>
                ))}
              </tr>
              {row.extra !== undefined && (
                <tr className="sc-plan-extra">
                  <td colSpan={columns.length}>{row.extra}</td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** An id (`orders/render-invoice-pdf`) that may break only after a `/` or a `-`, never
 * mid-word (review round 2, B1). */
export function BreakId({ id, className = "ah-mono" }: { id: string; className?: string }) {
  const parts = id.split(/(?<=[/-])/);
  return (
    <span className={className}>
      {parts.map((part, i) => (
        <Fragment key={i}>
          {part}
          {i < parts.length - 1 && <wbr />}
        </Fragment>
      ))}
    </span>
  );
}
