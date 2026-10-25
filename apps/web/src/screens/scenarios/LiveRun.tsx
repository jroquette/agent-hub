import type { ReactNode } from "react";

import { AppLink, Banner, Icon, StatusBadge, Time } from "../../components";
import { RunCommands } from "../run-detail/RunCommands";
import { useRun } from "../run-detail/queries";
import { shortId, type WaitingRow } from "./parts";
import {
  gateRun,
  gateStep,
  scenarioRunHref,
  useScenarioRun,
  useScenarioRunStream,
  type ScenarioDetail,
  type ScenarioStep,
} from "./queries";
import { maxChecks } from "./story";

/* The latest scenario run on the scenario detail: a banner while it runs (open it, cancel it)
 * and each step card's status in it, kept live by the run's stream. Only when it ran the
 * revision on screen: an older file's steps may not be these. */

export interface LatestRun {
  banner: ReactNode;
  statusOf: (step: ScenarioStep) => ReactNode;
}

export function useLatestRun(scenario: ScenarioDetail, waiting: readonly WaitingRow[]): LatestRun {
  const latest = scenario.runs[0];
  const runId = latest?.run_id ?? "";
  const running = latest?.status === "running";
  const run = useRun(runId);
  const live = running && run.data?.status !== "done" && run.data?.status !== "failed";
  useScenarioRunStream(runId, live && runId !== "");
  const record = useScenarioRun(runId, live && runId !== "");
  if (latest === undefined || run.data === undefined) {
    return { banner: null, statusOf: () => null };
  }
  const data = run.data;
  const sameRevision =
    data.revision === undefined || data.revision === null || data.revision === scenario.revision;
  const mine = waiting.filter((row) => gateRun(row.gate) === latest.run_id);
  const isLive = data.status === "running";
  // A run in a debug pause (a scenario written as blocks) still runs: it waits for Step or
  // Continue on its own page.
  const pause = isLive ? (record.data?.debug ?? null) : null;

  const banner =
    isLive && mine.length === 0 ? (
      <Banner tone="info" icon={pause === null ? "radio" : "circle-pause"} boxed live={false}>
        <span className="ah-row ah-wrap" style={{ gap: 8 }}>
          <span>
            Scenario run <span className="ah-mono">{shortId(latest.run_id)}</span>
            {pause === null
              ? ` is running${latest.environment ? ` in ${latest.environment}` : ""}`
              : ` is paused before block ${pause.block} ${
                  pause.reason === "step" ? "after a Step" : "at its breakpoint"
                }${latest.environment ? `, in ${latest.environment}` : ""}`}
            {latest.mode ? ` · ${latest.mode === "regression" ? "Regression" : "Interactive"}` : ""}{" "}
            · started <Time iso={latest.started_at} />
            {!sameRevision && " · it uses an older revision of the file"}
          </span>
          <span className="ah-grow" />
          <AppLink href={scenarioRunHref(scenario.project, scenario.name, latest.run_id)}>
            Open scenario run
            <Icon name="arrow-right" size="sm" />
          </AppLink>
          <RunCommands run={data} noun="scenario run" only={["cancel"]} />
        </span>
      </Banner>
    ) : null;

  const statusOf = (step: ScenarioStep): ReactNode => {
    if (!sameRevision) return null;
    if (pause !== null && (pause.node === step.id || pause.node === `${step.id}__ask`)) {
      return <StatusBadge status="waiting" label="Paused before it" />;
    }
    const gate = mine.find((row) => gateStep(row.gate) === step.id);
    if (gate) {
      return (
        <StatusBadge
          status="waiting"
          label={
            gate.gate.gate_kind === "investigation"
              ? "Waiting for you: investigation"
              : "Waiting for you: approval"
          }
        />
      );
    }
    const attempts = data.steps.filter((item) => item.key === step.id);
    const last = attempts.at(-1);
    if (last === undefined) {
      return isLive ? <span className="ah-small ah-subtle">Not started</span> : null;
    }
    const prefix = isLive ? "" : "Last run: ";
    if (last.status === "running") {
      const polls = (record.data?.polls ?? []).filter((poll) => poll.node === step.id).length;
      const most = step.every && step.timeout ? maxChecks(step.every, step.timeout) : null;
      const label =
        step.type === "expect" && polls > 0
          ? `Running · check ${String(polls)}${most === null ? "" : ` of at most ${String(most)}`}`
          : "Running";
      return <StatusBadge status="running" label={label} />;
    }
    if (last.status === "ok") {
      return (
        <span className="ah-row ah-small" style={{ gap: 6 }}>
          <span className="ah-subtle">{prefix}</span>
          <StatusBadge status="done" />
          {last.ended_at && <Time iso={last.ended_at} />}
        </span>
      );
    }
    if (last.status === "failed") {
      return (
        <span className="ah-row ah-small" style={{ gap: 6 }}>
          <span className="ah-subtle">{prefix}</span>
          <StatusBadge status="failed" title={last.reason ?? last.failure_kind ?? undefined} />
          {last.ended_at && <Time iso={last.ended_at} />}
        </span>
      );
    }
    return <span className="ah-small ah-subtle">{prefix}Skipped</span>;
  };
  return { banner, statusOf };
}
