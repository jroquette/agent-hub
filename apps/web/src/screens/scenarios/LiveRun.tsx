import { useMemo, type ReactNode } from "react";

import { AppLink, Button, Icon, StatusBadge, Time } from "../../components";
import { useApi } from "../../lib/api";
import { RunCommands } from "../run-detail/RunCommands";
import { debugReasonWords, shortId, type WaitingRow } from "./parts";
import { blockStateOf, lastLines, runBlock, type BlockState } from "./RunBlocks";
import {
  gateRun,
  gateStep,
  scenarioRunHref,
  useScenarioRunStream,
  type ScenarioDetail,
  type ScenarioRunDetail,
  type ScenarioStep,
} from "./queries";
import { maxChecks } from "./story";

/* The scenario run shown on the blocks (spec 23, build and run on one screen): the one the
 * person picked (`?run=`), else the latest while it runs. Its run strip says where it is (open
 * it, cancel it) and each block (or, written as a graph, each step) gets its state in it, kept
 * live by the run's stream. States show only on the blocks it ran: the same revision of the
 * file, and no edit since. */

export interface ShownRun {
  /** The scenario run shown, or null. */
  runId: string | null;
  strip: ReactNode;
  /** The state of a step of a graph scenario, by node id. */
  stepState: (step: ScenarioStep) => ReactNode;
  /** The state of a block of a scenario written as blocks, by address. */
  blockState: (address: string) => ReactNode;
  /** The values a block kept in the shown run, as `name = value` words. */
  keptOf: (address: string) => string[];
  /** The block (or step) the run is at now: running, paused before it or waiting for you. */
  current: string | null;
  record: ScenarioRunDetail | null;
  /** The run environment's production flag, as the hub reads it now (null while unknown). */
  production: boolean | null;
  live: boolean;
}

const STATE_LABEL: Readonly<Partial<Record<string, string>>> = {
  done: "Done",
  failed: "Failed",
  cancelled: "Cancelled",
  running: "Running",
};

function short(value: unknown): string {
  const written = typeof value === "string" ? value : JSON.stringify(value);
  return written.length > 40 ? `${written.slice(0, 39)}…` : written;
}

export function useShownRun({
  scenario,
  waiting,
  chosen,
  edited,
  onHide,
}: {
  scenario: ScenarioDetail;
  waiting: readonly WaitingRow[];
  /** `?run=`: a scenario run picked to show, null for the latest while it runs. */
  chosen: string | null;
  /** The blocks were changed since the file was read: a run's states no longer fit them. */
  edited: boolean;
  onHide: () => void;
}): ShownRun {
  const latest = scenario.runs[0];
  const picked = scenario.runs.find((run) => run.run_id === chosen);
  const ref = picked ?? (latest?.status === "running" ? latest : undefined);
  const runId = ref?.run_id ?? "";
  const run = useApi(
    "/api/v1/workflow-runs/{run_id}",
    { path: { run_id: runId } },
    { enabled: runId !== "" },
  );
  const live =
    ref !== undefined &&
    (run.data?.status ?? ref.status) === "running" &&
    run.data?.status !== "done" &&
    run.data?.status !== "failed";
  useScenarioRunStream(runId, live && runId !== "");
  const recordQuery = useApi(
    "/api/v1/scenario-runs/{run_id}",
    { path: { run_id: runId } },
    { enabled: runId !== "", refetchInterval: live ? 15_000 : false },
  );
  const record = runId === "" ? null : (recordQuery.data ?? null);
  const lines = useMemo(() => lastLines(record?.timeline ?? []), [record?.timeline]);
  const environment = scenario.environments.find((env) => env.name === ref?.environment);
  const production = environment === undefined ? null : environment.production;

  if (ref === undefined || run.data === undefined) {
    return {
      runId: null,
      strip: null,
      stepState: () => null,
      blockState: () => null,
      keptOf: () => [],
      current: null,
      record: null,
      production: null,
      live: false,
    };
  }
  const data = run.data;
  const sameRevision =
    data.revision === undefined || data.revision === null || data.revision === scenario.revision;
  const fits = sameRevision && !edited;
  const mine = waiting.filter((row) => gateRun(row.gate) === ref.run_id);
  const isLive = data.status === "running";
  const pause = isLive ? (record?.debug ?? null) : null;
  const prefix = isLive ? "" : "Last run: ";

  // A scenario written as blocks: each block's state from the run's record.
  const blockStateRaw = (address: string): BlockState => {
    if (!fits || record === null) return null;
    const block = runBlock(record, address);
    if (block === undefined) return null;
    const entry = scenario.blocks.find((each) => each.address === address)?.entry_nodes ?? [];
    if (mine.some((row) => entry.includes(gateStep(row.gate)))) return "waiting";
    return blockStateOf(record, block, lines);
  };
  const waitingWords = (address: string): string => {
    const entry = scenario.blocks.find((each) => each.address === address)?.entry_nodes ?? [];
    const gate = mine.find((row) => entry.includes(gateStep(row.gate)));
    return gate?.gate.gate_kind === "investigation"
      ? "Waiting for you: investigation"
      : "Waiting for you: approval";
  };
  const blockState = (address: string): ReactNode => {
    const state = blockStateRaw(address);
    if (state === null) return null;
    if (state === "paused") return <StatusBadge status="waiting" label="Paused before it" />;
    if (state === "waiting") return <StatusBadge status="waiting" label={waitingWords(address)} />;
    if (state === "pending") return <span className="ah-small ah-subtle">Not started</span>;
    if (state === "skipped") return <span className="ah-small ah-subtle">{prefix}Skipped</span>;
    if (state === "running") {
      const entry = scenario.blocks.find((each) => each.address === address)?.entry_nodes ?? [];
      const polls = (record?.polls ?? []).filter((poll) => entry.includes(poll.node)).length;
      return (
        <StatusBadge
          status="running"
          label={polls > 0 ? `Running · check ${String(polls)}` : "Running"}
        />
      );
    }
    const at = lines.get(address)?.at ?? null;
    return (
      <span className="ah-row ah-small" style={{ gap: 6 }}>
        {prefix && <span className="ah-subtle">{prefix}</span>}
        <StatusBadge status={state} />
        {at && <Time iso={at} />}
      </span>
    );
  };

  const keptOf = (address: string): string[] => {
    if (!fits || record === null) return [];
    const entry = scenario.blocks.find((each) => each.address === address)?.entry_nodes ?? [];
    return record.captures
      .filter((capture) => entry.includes(capture.node))
      .map((capture) => `${capture.name} = ${short(capture.value)}`);
  };

  // A graph scenario: each step's state from the run's steps.
  const stepState = (step: ScenarioStep): ReactNode => {
    if (!fits) return null;
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
    if (last.status === "running") {
      const polls = (record?.polls ?? []).filter((poll) => poll.node === step.id).length;
      const most = step.every && step.timeout ? maxChecks(step.every, step.timeout) : null;
      const label =
        step.type === "expect" && polls > 0
          ? `Running · check ${String(polls)}${most === null ? "" : ` of at most ${String(most)}`}`
          : "Running";
      return <StatusBadge status="running" label={label} />;
    }
    if (last.status === "ok" || last.status === "failed") {
      return (
        <span className="ah-row ah-small" style={{ gap: 6 }}>
          {prefix && <span className="ah-subtle">{prefix}</span>}
          <StatusBadge
            status={last.status === "ok" ? "done" : "failed"}
            title={last.reason ?? last.failure_kind ?? undefined}
          />
          {last.ended_at && <Time iso={last.ended_at} />}
        </span>
      );
    }
    return <span className="ah-small ah-subtle">{prefix}Skipped</span>;
  };

  // Where the run is now: the first block (in reading order) running, paused or waiting.
  const current = !isLive
    ? null
    : scenario.version === 2
      ? (scenario.blocks
          .map((block) => block.address)
          .find((address) => {
            const state = blockStateRaw(address);
            return state === "running" || state === "paused" || state === "waiting";
          }) ?? null)
      : (data.steps.find((step) => step.status === "running")?.key ?? null);

  const where = ref.environment ? ` in ${ref.environment}` : "";
  const modeWords = ref.mode
    ? ` · ${ref.mode === "regression" ? "Regression" : "Interactive"}`
    : "";
  const status = isLive
    ? mine.length > 0
      ? "waiting"
      : pause !== null
        ? "waiting"
        : "running"
    : data.status;
  let sentence: ReactNode;
  if (isLive && mine.length > 0) {
    sentence = (
      <>
        waits for you{current ? ` at ${scenario.version === 2 ? "block" : "step"} ${current}` : ""}:{" "}
        {mine[0]?.gate.gate_kind === "investigation" ? "an investigation" : "an approval"}
      </>
    );
  } else if (pause !== null) {
    sentence = (
      <>
        is paused before block {pause.block} {debugReasonWords(pause.reason)}
        {where}
      </>
    );
  } else if (isLive) {
    sentence = (
      <>
        is running{where}
        {modeWords}
        {current ? ` · at ${scenario.version === 2 ? "block" : "step"} ${current}` : ""} · started{" "}
        <Time iso={ref.started_at} />
      </>
    );
  } else {
    sentence = (
      <>
        · {STATE_LABEL[data.status] ?? data.status}
        {where}
        {ref.ended_at ? (
          <>
            {" "}
            at <Time iso={ref.ended_at} />
          </>
        ) : null}
      </>
    );
  }

  const strip = (
    <section
      className="sb-strip"
      aria-label={`Scenario run ${shortId(ref.run_id)}`}
      data-status={status}
    >
      <Icon
        name={
          status === "waiting"
            ? pause !== null
              ? "circle-pause"
              : "hand"
            : status === "running"
              ? "radio"
              : status === "failed"
                ? "circle-x"
                : "circle-check"
        }
        size="sm"
      />
      <span className="sb-strip-text" role="status">
        Scenario run <span className="ah-mono">{shortId(ref.run_id)}</span> {sentence}
        {!sameRevision && " · it ran an older revision of the file, so its states are on its page"}
        {sameRevision && edited && " · you changed the blocks since, so its states are hidden"}
      </span>
      <span className="ah-grow" />
      <AppLink href={scenarioRunHref(scenario.project, scenario.name, ref.run_id)}>
        Open scenario run
        <Icon name="arrow-right" size="sm" />
      </AppLink>
      {isLive ? (
        <RunCommands run={data} noun="scenario run" only={["cancel"]} />
      ) : (
        <Button size="sm" variant="ghost" icon="eye-off" onClick={onHide}>
          Hide its states
        </Button>
      )}
    </section>
  );

  return {
    runId: ref.run_id,
    strip,
    stepState,
    blockState,
    keptOf,
    current,
    record,
    production,
    live: isLive,
  };
}
