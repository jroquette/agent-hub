import { useEffect, useState } from "react";

import {
  AppLink,
  Banner,
  Button,
  CodeBlock,
  ConfirmDialog,
  CopyButton,
  Dialog,
  Icon,
  ProblemError,
  Time,
} from "../../components";
import type { ApiProblem } from "../../lib/api";
import { readStored, writeStored } from "../../lib/storage";
import { isRunControlOff } from "./Investigation";
import { DraftLine, ScenarioRunBadge, shortId } from "./parts";
import {
  scenarioRunHref,
  useScenario,
  useStartScenario,
  type PlanRequest,
  type ScenarioDetail,
  type ScenarioMode,
  type ScenarioPlan,
} from "./queries";

/* The run side of the scenario page (spec 23 Screen 2, build and run on one screen): the
 * environment a plan and a start go to, the plan's verdict, the start itself (confirmed), the
 * draft actions to commit before a start, and the scenario runs. The scenario builder lays these
 * out as a run bar over the blocks and a run panel beside them. */

const RECENT = 5;
const POLL_MS = 2000;
const REPORT_WAIT_MS = 30_000;

function recentKey(project: string): string {
  return `ah.scenarios.env.${project}`;
}

export function recentEnvironments(project: string): string[] {
  try {
    const value: unknown = JSON.parse(readStored(recentKey(project)) ?? "[]");
    return Array.isArray(value) ? value.filter((item) => typeof item === "string") : [];
  } catch {
    return [];
  }
}

export function remember(project: string, environment: string): void {
  const next = [environment, ...recentEnvironments(project).filter((e) => e !== environment)];
  writeStored(recentKey(project), JSON.stringify(next.slice(0, RECENT)));
}

/** The environment a page opens on with no `?env=`: the last one used in this browser that is
 * still declared and not production, else the first declared one that is not production. Never
 * production unless the person picks it. */
export function defaultEnvironment(scenario: ScenarioDetail): string {
  const safe = scenario.environments.filter((item) => !item.production);
  const recent = recentEnvironments(scenario.project).find((name) =>
    safe.some((item) => item.name === name),
  );
  return recent ?? safe[0]?.name ?? "";
}

/** An environment's access in words, as the Environments screen says it. */
export function accessWords(environment: ScenarioDetail["environments"][number]): string {
  if (environment.production) return "Production: writes and destroys are denied here.";
  if (environment.access === "write") return "Agents may change data here.";
  if (environment.access === "ask") return "Agents ask before changing data here.";
  return "Agents only read here.";
}

export const MODE_LINE: Record<ScenarioMode, string> = {
  interactive:
    "If a block does not reach its expected state, the scenario run pauses and a read-only agent investigates with you.",
  regression:
    "No agent and no token cost. The first block that does not reach its expected state fails the scenario run.",
};

function names(list: readonly string[]): string {
  if (list.length <= 1) return list.join("");
  return `${list.slice(0, -1).join(", ")} and ${list[list.length - 1] ?? ""}`;
}

function counted(n: number, noun: string): string {
  return `${String(n)} ${n === 1 ? noun : `${noun}s`}`;
}

/** "4 blocks: 2 read, 2 write · 1 asks you". */
export function planCounts(plan: ScenarioPlan, noun = "step"): string {
  const effects = new Map<string, number>();
  for (const row of plan.rows) effects.set(row.effect, (effects.get(row.effect) ?? 0) + 1);
  const parts = ["read", "write", "destroy"]
    .filter((effect) => effects.has(effect))
    .map((effect) => `${String(effects.get(effect))} ${effect}`);
  const asks = plan.rows.filter((row) => row.decision === "ask").length;
  return [
    `${counted(plan.rows.length, noun)}${parts.length > 0 ? `: ${parts.join(", ")}` : ""}`,
    ...(asks > 0 ? [`${String(asks)} asks you`] : []),
  ].join(" · ");
}

export interface Verdict {
  ok: boolean;
  text: string;
  /** Why it cannot start is a draft action to commit: Before you start lists them. */
  drafts: boolean;
}

/** The verdict line: may it start, and why not. */
export function verdict(plan: ScenarioPlan, stale: string | null, noun = "step"): Verdict {
  if (stale !== null) return { ok: false, text: stale, drafts: false };
  const drafts = plan.rows.filter((row) => row.needs_acceptance).map((row) => row.action);
  const unique = [...new Set(drafts)];
  if (unique.length > 0) {
    return {
      ok: false,
      text: `Cannot start: ${counted(unique.length, "draft action")} ${
        unique.length === 1 ? "needs" : "need"
      } acceptance. See Before you start.`,
      drafts: true,
    };
  }
  const denied = plan.rows.filter((row) => row.decision === "deny").map((row) => row.step);
  if (plan.problems.length > 0) {
    const n = plan.problems.length;
    return {
      ok: false,
      text: `Cannot start: the plan has ${counted(n, "problem")}.`,
      drafts: false,
    };
  }
  if (denied.length === 0 && plan.denied) {
    return {
      ok: false,
      text: `Cannot start in ${plan.environment}: the plan does not allow a start there.`,
      drafts: false,
    };
  }
  if (denied.length > 0) {
    const verb = denied.length > 1 ? "are" : "is";
    return {
      ok: false,
      text: `Cannot start: ${names(denied)} ${verb} denied in ${plan.environment}.`,
      drafts: false,
    };
  }
  return {
    ok: true,
    text: `Can start in ${plan.environment} · ${planCounts(plan, noun)}`,
    drafts: false,
  };
}

/** Why a plan could not be made, in the design's words (states table). */
export function PlanProblem({
  error,
  name,
  environment,
}: {
  error: ApiProblem;
  name: string;
  environment: string;
}) {
  if (isRunControlOff(error)) {
    return (
      <Banner tone="info" boxed>
        <span className="ah-stack" style={{ gap: 6 }}>
          <span>
            Plans and scenario runs cannot start from the agent-hub container: it has no credentials
            and no env files. Run hub web on your machine, or plan from a terminal:
          </span>
          <CodeBlock code={`./hub scenario plan ${name} --env ${environment || "<environment>"}`} />
        </span>
      </Banner>
    );
  }
  if (error.status === 401) {
    return (
      <Banner tone="error" boxed>
        Planning is locked in this browser. Open the link hub web printed when it started (it ends
        with ?token=…) once in this browser.
      </Banner>
    );
  }
  if (error.status === 409 && error.code === "hub_local_invalid") {
    return (
      <Banner tone="error" boxed>
        hub.local.json cannot be read or conflicts with hub.json, so the environments are unknown.
        Run ./hub doctor to see the problem, fix the file, then plan again.
      </Banner>
    );
  }
  if (error.status === 502) {
    return (
      <div className="ah-stack" style={{ gap: 6 }} role="alert">
        <span>
          The plan did not finish in 5 min, so it was stopped. A plan-mode script may hang: run it
          from a terminal to see which.
        </span>
        <CodeBlock code={`./hub scenario plan ${name} --env ${environment}`} />
      </div>
    );
  }
  return (
    <ProblemError
      title="Could not plan the scenario"
      detail={error.detail}
      status={error.status}
      compact
    />
  );
}

export function confirmBody(
  plan: ScenarioPlan,
  mode: ScenarioMode,
  breakpoints: readonly string[],
  noun = "step",
): string {
  const effects = new Map<string, number>();
  for (const row of plan.rows) effects.set(row.effect, (effects.get(row.effect) ?? 0) + 1);
  const counts = ["read", "write", "destroy"]
    .filter((e) => effects.has(e))
    .map((e) => `${String(effects.get(e))} ${e}`);
  const asks = plan.rows.filter((row) => row.decision === "ask").map((row) => row.step);
  const parts = [
    `It runs ${counted(plan.rows.length, noun)} in ${plan.environment}: ${names(counts)}.`,
  ];
  if (asks.length > 0)
    parts.push(`${names(asks)} ${asks.length === 1 ? "asks" : "ask"} you before it runs.`);
  if (breakpoints.length > 0)
    parts.push(
      breakpoints.length === 1
        ? `It pauses before block ${names(breakpoints)}, its breakpoint.`
        : `It pauses before blocks ${names(breakpoints)}, its breakpoints.`,
    );
  parts.push(
    mode === "interactive"
      ? `Interactive mode: a ${noun} that does not reach its expected state pauses the scenario run for an investigation. Nothing is rewound afterwards.`
      : `Regression mode: the first ${noun} that does not reach its expected state fails the scenario run.`,
  );
  return parts.join(" ");
}

export function useAfter(ms: number, active: boolean): boolean {
  const [passed, setPassed] = useState(false);
  const [was, setWas] = useState(active);
  if (was !== active) {
    // A new wait starts over (state adjusted while rendering, not in an effect).
    setWas(active);
    setPassed(false);
  }
  useEffect(() => {
    if (!active) return;
    const timer = setTimeout(() => {
      setPassed(true);
    }, ms);
    return () => {
      clearTimeout(timer);
    };
  }, [ms, active]);
  return passed && active;
}

/** Start scenario run: the button, its confirm and the wait for the run's first event. Once the
 * run is listed the page stays and `onStarted` gets its id, so the blocks follow it. */
export function StartScenarioRun({
  scenario,
  plan,
  request,
  mode,
  breakpoints,
  disabled,
  disabledReason,
  noun = "step",
  onStarted,
}: {
  scenario: ScenarioDetail;
  plan: ScenarioPlan;
  request: PlanRequest;
  mode: ScenarioMode;
  breakpoints: readonly string[];
  disabled: boolean;
  disabledReason?: string | undefined;
  noun?: string;
  onStarted: (runId: string) => void;
}) {
  const start = useStartScenario(scenario.project, scenario.name);
  const [confirming, setConfirming] = useState(false);
  const [startedId, setStartedId] = useState<string | null>(null);
  const late = useAfter(REPORT_WAIT_MS, startedId !== null);
  const polled = useScenario(
    scenario.project,
    scenario.name,
    startedId !== null && !late ? POLL_MS : undefined,
  );
  // Listed: the dialog closes (state adjusted while rendering, not in an effect); the blocks
  // already follow the scenario run (`onStarted` ran when the start was accepted).
  if (startedId !== null && (polled.data?.runs ?? []).some((run) => run.run_id === startedId)) {
    setConfirming(false);
    setStartedId(null);
  }
  return (
    <>
      <Button
        variant="primary"
        icon="play"
        disabled={disabled || startedId !== null}
        title={disabled ? disabledReason : undefined}
        onClick={() => {
          start.reset();
          setConfirming(true);
        }}
      >
        Start scenario run
      </Button>
      {confirming && startedId === null && (
        <ConfirmDialog
          title={`Start a scenario run in ${plan.environment}?`}
          confirmLabel="Start scenario run"
          cancelLabel="Back to plan"
          tone="primary"
          pending={start.isPending}
          onCancel={() => {
            setConfirming(false);
          }}
          onConfirm={() => {
            start.mutate(
              {
                ...request,
                mode,
                ...(breakpoints.length > 0 ? { breakpoints: [...breakpoints] } : {}),
              },
              {
                onSuccess: (accepted) => {
                  setStartedId(accepted.run_id);
                  onStarted(accepted.run_id);
                },
              },
            );
          }}
        >
          <span className="ah-stack" style={{ gap: 8 }}>
            <span>{confirmBody(plan, mode, breakpoints, noun)}</span>
            {start.isPending && <span role="status">Starting the scenario run…</span>}
            {start.isError && (
              <span role="alert" className="ah-stack" style={{ gap: 2, color: "var(--text)" }}>
                <b>Could not start the scenario run</b>
                {start.error.status === 502 ? (
                  <>
                    <span>
                      hub web could not launch hub scenario run. Run it from a terminal to see why:
                    </span>
                    <CodeBlock
                      code={`./hub scenario run ${scenario.name} --env ${plan.environment}`}
                    />
                  </>
                ) : (
                  <span>{start.error.detail ?? start.error.title}</span>
                )}
                {start.error.status === 409 && <span>Nothing was started.</span>}
              </span>
            )}
          </span>
        </ConfirmDialog>
      )}
      {confirming && startedId !== null && (
        // Started: no second start is ever offered, only the way to it and Back.
        <Dialog
          title={`Start a scenario run in ${plan.environment}?`}
          pending={!late}
          onClose={
            late
              ? () => {
                  setConfirming(false);
                }
              : undefined
          }
          footer={
            <Button
              disabled={!late}
              onClick={() => {
                setConfirming(false);
              }}
            >
              Back to plan
            </Button>
          }
        >
          {late ? (
            <span role="status" className="ah-stack" style={{ gap: 4 }}>
              <span>
                The scenario run has not reported in 30 s. Its output is in .agent-runs/web/
                {startedId}.log in the hub.
              </span>
              <AppLink href={scenarioRunHref(scenario.project, scenario.name, startedId)}>
                Open scenario run {shortId(startedId)} anyway
              </AppLink>
            </span>
          ) : (
            <span role="status">Started. Waiting for the scenario run&apos;s first event…</span>
          )}
        </Dialog>
      )}
    </>
  );
}

/** The draft actions a start would refuse, each with its commit command, gathered once. */
export function BeforeYouStart({ scenario }: { scenario: ScenarioDetail }) {
  const drafts = scenario.actions.filter((action) => action.draft);
  if (drafts.length === 0) return null;
  const commands = drafts.flatMap((action) =>
    action.accept_command ? [action.accept_command] : [],
  );
  return (
    <section
      aria-label="Before you start"
      id="before-you-start"
      className="ah-card ah-card-body ah-stack"
      style={{ gap: 10 }}
      tabIndex={-1}
    >
      <span className="ah-row" style={{ gap: 8 }}>
        <h2 className="ah-h3" style={{ margin: 0 }}>
          Before you start ({drafts.length})
        </h2>
        <span className="ah-grow" />
        {commands.length > 1 && (
          <CopyButton text={commands.join(" && ")} label="Copy all the commit commands" />
        )}
      </span>
      <span className="ah-small ah-muted">
        {drafts.length === 1
          ? `${drafts[0]?.name ?? ""} is a draft action: a scenario run cannot start until it is committed.`
          : `${names(drafts.map((action) => action.name))} are draft actions: a scenario run cannot start until they are committed.`}
      </span>
      <DraftLine commands={commands} action="the draft actions" then="plan again" />
    </section>
  );
}

const RUNS_SHOWN = 5;

/** The scenario runs, newest first; each can be shown on the blocks. */
export function RunsList({
  scenario,
  shown,
  onShow,
}: {
  scenario: ScenarioDetail;
  shown: string | null;
  onShow: (runId: string | null) => void;
}) {
  const [all, setAll] = useState(false);
  const runs = scenario.runs;
  const listed = all ? runs : runs.slice(0, RUNS_SHOWN);
  return (
    <section
      aria-label="Scenario runs"
      className="ah-card ah-card-body ah-stack"
      style={{ gap: 10 }}
    >
      <h2 className="ah-h3" style={{ margin: 0 }}>
        Scenario runs ({runs.length})
      </h2>
      {runs.length === 0 ? (
        <span className="ah-small ah-muted">
          No scenario runs yet. Plan, then start one from the bar above.
        </span>
      ) : (
        <ul className="sc-runs">
          {listed.map((run) => {
            const on = shown === run.run_id;
            return (
              <li
                key={run.run_id}
                className="sc-runs-row ah-small"
                data-shown={on ? "true" : undefined}
                title={[run.environment, run.mode].filter(Boolean).join(" · ")}
              >
                <ScenarioRunBadge status={run.status} />
                <AppLink
                  href={scenarioRunHref(scenario.project, scenario.name, run.run_id)}
                  className="ah-mono"
                  aria-label={`Open scenario run ${shortId(run.run_id)}`}
                  data-nav-row=""
                >
                  {shortId(run.run_id)}
                </AppLink>
                <span className="ah-muted">{run.environment ?? "—"}</span>
                <span className="ah-grow" />
                <Time iso={run.started_at} />
                <Button
                  size="sm"
                  variant="ghost"
                  icon={on ? "eye-off" : "scan-eye"}
                  aria-pressed={on}
                  title={on ? "Hide its states on the blocks" : "Show its states on the blocks"}
                  onClick={() => {
                    onShow(on ? null : run.run_id);
                  }}
                >
                  {on ? "Shown" : "Show"}
                </Button>
              </li>
            );
          })}
        </ul>
      )}
      {runs.length > RUNS_SHOWN && (
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            setAll(!all);
          }}
        >
          {all ? "Show fewer" : `Show all ${String(runs.length)}`}
        </Button>
      )}
    </section>
  );
}

/** This plan: where it was made, what it counts, its production note and problems. */
export function PlanSummary({
  plan,
  pending,
  stale,
  noun = "step",
}: {
  plan: ScenarioPlan;
  pending: boolean;
  stale: boolean;
  noun?: string;
}) {
  return (
    <section
      aria-label="This plan"
      className="ah-card ah-card-body ah-stack"
      style={{ gap: 8, opacity: pending ? 0.6 : 1 }}
      aria-busy={pending}
    >
      <h2 className="ah-h3" style={{ margin: 0 }}>
        This plan
      </h2>
      <span className="ah-small">
        <b className="ah-mono">
          {plan.environment} · {plan.production ? "production · " : ""}access{" "}
          {plan.access ?? "unknown"}
        </b>
      </span>
      <span className="ah-small ah-muted">{planCounts(plan, noun)}</span>
      {stale && (
        <span className="ah-small ah-row" style={{ gap: 6 }}>
          <Icon name="clock" size="sm" /> Planned before your changes: plan again to start.
        </span>
      )}
      {plan.production && (
        <Banner tone="info" boxed live={false}>
          {plan.environment} is a production environment: writes and destroys are denied there, and
          breakpoints are off.
        </Banner>
      )}
      {plan.problems.map((problem) => (
        <span key={problem} className="ah-row ah-small" style={{ gap: 6, color: "var(--failed)" }}>
          <Icon name="circle-x" size="sm" />
          {problem}
        </span>
      ))}
    </section>
  );
}
