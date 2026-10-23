import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { useParams, useSearchParams } from "react-router";

import {
  AppLink,
  Banner,
  Button,
  CodeBlock,
  ConfirmDialog,
  Dialog,
  Icon,
  ProblemError,
  SegmentedControl,
  Skeleton,
  Time,
} from "../../components";
import type { ApiProblem } from "../../lib/api";
import { readStored, writeStored } from "../../lib/storage";
import { TABLET, useMediaQuery } from "../../lib/useMediaQuery";
import { Breadcrumbs } from "../../shell/Breadcrumbs";
import { DiscussButton, useDiscuss, useDiscussTarget } from "../../shell/discuss";
import { StaleStamp } from "../portfolio/StaleStamp";
import { InputField, parsed, type InputSpec } from "../runs-list/StartRun";
import { ActionPanel, FileText } from "./ActionPanel";
import { ScenarioBuilder } from "./builder/ScenarioBuilder";
import { useLatestRun } from "./LiveRun";
import { SCENARIO_BRIEF } from "./NewScenario";
import { Page, ScenarioRunBadge, shortId, useWaitingRows, WaitingCard } from "./parts";
import {
  scenarioRunHref,
  usePlanScenario,
  useScenario,
  useStartScenario,
  type PlanRequest,
  type ScenarioDetail,
  type ScenarioMode,
  type ScenarioPlan,
} from "./queries";
import { Storyline } from "./StepCard";
import { shapeLine } from "./story";

export { pace } from "./story";

/* Scenario detail (AGH-350 T13, spec 23 screen 2): the scenario as a storyline of steps (what
 * each does, the script it runs, where it can stop) beside a sticky run panel (environment,
 * inputs, mode, plan, start, its scenario runs). The plan runs only on the person's click (a
 * strict write that starts plan-mode scripts), never on load, and lays over the step cards; a
 * start is confirmed. */

const RUN_CONTROL_OFF = "urn:agent-hub:problem:run-control-off";
const RECENT = 5;
const POLL_MS = 2000;
const REPORT_WAIT_MS = 30_000;
const SLOW_PLAN_MS = 10_000;
type InputValue = string | number | boolean;

function recentKey(project: string): string {
  return `ah.scenarios.env.${project}`;
}

function recentEnvironments(project: string): string[] {
  try {
    const value: unknown = JSON.parse(readStored(recentKey(project)) ?? "[]");
    return Array.isArray(value) ? value.filter((item) => typeof item === "string") : [];
  } catch {
    return [];
  }
}

function remember(project: string, environment: string): void {
  const next = [environment, ...recentEnvironments(project).filter((e) => e !== environment)];
  writeStored(recentKey(project), JSON.stringify(next.slice(0, RECENT)));
}

function specOf(input: ScenarioDetail["inputs"][number]): InputSpec {
  const type = input.type;
  return {
    name: input.name,
    type: type === "integer" || type === "number" || type === "boolean" ? type : "string",
    required: input.required,
    default: undefined,
    description: input.description ?? null,
  };
}

/** "4 steps: 2 read, 2 write · 1 asks you". */
function planCounts(plan: ScenarioPlan): string {
  const effects = new Map<string, number>();
  for (const row of plan.rows) effects.set(row.effect, (effects.get(row.effect) ?? 0) + 1);
  const parts = ["read", "write", "destroy"]
    .filter((effect) => effects.has(effect))
    .map((effect) => `${String(effects.get(effect))} ${effect}`);
  const steps = `${String(plan.rows.length)} ${plan.rows.length === 1 ? "step" : "steps"}`;
  const asks = plan.rows.filter((row) => row.decision === "ask").length;
  return [`${steps}: ${parts.join(", ")}`, ...(asks > 0 ? [`${String(asks)} asks you`] : [])].join(
    " · ",
  );
}

function names(list: readonly string[]): string {
  if (list.length <= 1) return list.join("");
  return `${list.slice(0, -1).join(", ")} and ${list[list.length - 1] ?? ""}`;
}

/** The verdict line: may it start, and why not. */
function verdict(plan: ScenarioPlan, stale: string | null): { ok: boolean; text: string } {
  if (stale !== null) return { ok: false, text: stale };
  const denied = plan.rows.filter((row) => row.decision === "deny").map((row) => row.step);
  if (plan.problems.length > 0) {
    const n = plan.problems.length;
    return {
      ok: false,
      text: `Cannot start: the plan has ${String(n)} ${n === 1 ? "problem" : "problems"}.`,
    };
  }
  if (denied.length === 0 && plan.denied) {
    return {
      ok: false,
      text: `Cannot start in ${plan.environment}: the plan does not allow a start there.`,
    };
  }
  if (denied.length > 0) {
    const verb = denied.length > 1 ? "are" : "is";
    return {
      ok: false,
      text: `Cannot start: ${names(denied)} ${verb} denied in ${plan.environment}.`,
    };
  }
  const asks = plan.rows.filter((row) => row.decision === "ask").length;
  const tail =
    asks === 0
      ? ""
      : asks === 1
        ? " 1 step asks you before it runs."
        : ` ${String(asks)} steps ask you before they run.`;
  return { ok: true, text: `Can start in ${plan.environment}.${tail}` };
}

/** Why a plan could not be made, in the design's words (states table). */
function PlanProblem({
  error,
  name,
  environment,
}: {
  error: ApiProblem;
  name: string;
  environment: string;
}) {
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

/** An environment's access in words, as the Environments screen says it. */
function accessWords(environment: ScenarioDetail["environments"][number]): string {
  if (environment.production) return "Production: writes and destroys are denied here.";
  if (environment.access === "write") return "Agents may change data here.";
  if (environment.access === "ask") return "Agents ask before changing data here.";
  return "Agents only read here.";
}

const MODE_LINE: Record<ScenarioMode, string> = {
  interactive:
    "If a step does not reach its expected state, the scenario run pauses and a read-only agent investigates with you.",
  regression:
    "No agent and no token cost. The first step that does not reach its expected state fails the scenario run.",
};

function confirmBody(plan: ScenarioPlan, mode: ScenarioMode): string {
  const effects = new Map<string, number>();
  for (const row of plan.rows) effects.set(row.effect, (effects.get(row.effect) ?? 0) + 1);
  const counts = ["read", "write", "destroy"]
    .filter((e) => effects.has(e))
    .map((e) => `${String(effects.get(e))} ${e}`);
  const asks = plan.rows.filter((row) => row.decision === "ask").map((row) => row.step);
  const n = plan.rows.length;
  const parts = [
    `It runs ${String(n)} ${n === 1 ? "step" : "steps"} in ${plan.environment}: ${names(counts)}.`,
  ];
  if (asks.length > 0)
    parts.push(`${names(asks)} ${asks.length === 1 ? "asks" : "ask"} you before it runs.`);
  parts.push(
    mode === "interactive"
      ? "Interactive mode: a step that does not reach its expected state pauses the scenario run for an investigation. Nothing is rewound afterwards."
      : "Regression mode: the first step that does not reach its expected state fails the scenario run.",
  );
  return parts.join(" ");
}

function useAfter(ms: number, active: boolean): boolean {
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

function PlanCard({
  scenario,
  mode,
  onModeChange,
  onCurrentPlan,
}: {
  scenario: ScenarioDetail;
  mode: ScenarioMode;
  onModeChange: (mode: ScenarioMode) => void;
  /** The plan the cards lay over: the latest one, while the form still matches it. */
  onCurrentPlan: (plan: ScenarioPlan | null) => void;
}) {
  const [params, setParams] = useSearchParams();
  const environment = params.get("env") ?? "";
  const specs = scenario.inputs.map(specOf);
  const [values, setValues] = useState<Record<string, string | boolean>>(() =>
    Object.fromEntries(specs.map((spec) => [spec.name, spec.type === "boolean" ? false : ""])),
  );
  const [bad, setBad] = useState<Record<string, boolean>>({});
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [planned, setPlanned] = useState<{
    key: string;
    request: PlanRequest;
    plan: ScenarioPlan;
  } | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [startedId, setStartedId] = useState<string | null>(null);
  const plan = usePlanScenario(scenario.project, scenario.name);
  const start = useStartScenario(scenario.project, scenario.name);
  const slow = useAfter(SLOW_PLAN_MS, plan.isPending);
  const late = useAfter(REPORT_WAIT_MS, startedId !== null);
  const polled = useScenario(
    scenario.project,
    scenario.name,
    startedId !== null && !late ? POLL_MS : undefined,
  );
  const envId = useId();
  const listId = useId();
  const verdictId = useId();
  const recent = recentEnvironments(scenario.project);
  const tablet = useMediaQuery(TABLET);
  const declared = scenario.environments;
  const controlOff =
    (plan.error?.status === 404 && plan.error.type === RUN_CONTROL_OFF) ||
    (start.error?.status === 404 && start.error.type === RUN_CONTROL_OFF);
  const locked = plan.error?.status === 401 || start.error?.status === 401;

  // Listed: the page stays, its banner and step cards follow the scenario run live (state
  // adjusted while rendering, not in an effect).
  if (startedId !== null && (polled.data?.runs ?? []).some((run) => run.run_id === startedId)) {
    setConfirming(false);
    setStartedId(null);
  }

  const setEnvironment = (next: string) => {
    setParams(
      (current) => {
        const copy = new URLSearchParams(current);
        if (next === "") copy.delete("env");
        else copy.set("env", next);
        return copy;
      },
      { replace: true },
    );
  };

  // A plan's 422 names its inputs by pointer (`/inputs/<name>`): each message goes to its field.
  const serverErrors = new Map<string, string>();
  const otherErrors: string[] = [];
  if (plan.isError && plan.error.status === 422) {
    const fields = new Set(specs.map((spec) => spec.name));
    for (const item of plan.error.errors) {
      const name = /^\/inputs\/([^/]+)$/.exec(item.pointer)?.[1];
      if (name !== undefined && fields.has(name)) {
        if (!serverErrors.has(name)) serverErrors.set(name, item.message);
      } else {
        otherErrors.push(item.message);
      }
    }
  }
  // PlanProblem stays away only when every message sits at a field of the form (review Q6).
  const inputProblems = serverErrors.size > 0 && otherErrors.length === 0;
  const formKey = JSON.stringify([environment, values]);
  const request = (): PlanRequest | null => {
    const inputs: Record<string, InputValue> = {};
    const problems: Record<string, string> = {};
    for (const spec of specs) {
      const value = parsed(spec, values[spec.name] ?? "", bad[spec.name] ?? false);
      if (value instanceof Error) problems[spec.name] = value.message;
      else if (value !== undefined) inputs[spec.name] = value;
    }
    setFieldErrors(problems);
    if (Object.keys(problems).length > 0) return null;
    return { environment, inputs };
  };

  const sendPlan = () => {
    if (environment === "" || plan.isPending || controlOff || locked) return;
    const body = request();
    if (body === null) return;
    remember(scenario.project, environment);
    plan.mutate(body, {
      onSuccess: (result) => {
        setPlanned({ key: formKey, request: body, plan: result });
      },
    });
  };

  const shown = planned?.plan ?? null;
  const undeclared = shown !== null && shown.access === null;
  const stale =
    planned !== null && planned.key !== formKey
      ? `This plan is for ${planned.request.environment}${Object.entries(planned.request.inputs)
          .map(([k, v]) => ` with ${k} ${String(v)}`)
          .join("")}. Plan again to start with the new values.`
      : null;
  const judged = shown === null || undeclared ? null : verdict(shown, stale);
  const canStart = judged?.ok === true && !controlOff && !locked;
  const current = shown !== null && !undeclared && stale === null ? shown : null;
  useEffect(() => {
    onCurrentPlan(current);
  }, [current, onCurrentPlan]);

  const field = (spec: InputSpec): ReactNode => (
    <InputField
      key={spec.name}
      spec={spec}
      value={values[spec.name] ?? ""}
      error={fieldErrors[spec.name] ?? serverErrors.get(spec.name) ?? null}
      disabled={plan.isPending}
      onChange={(value, isBad) => {
        setValues((current) => ({ ...current, [spec.name]: value }));
        setBad((current) => ({ ...current, [spec.name]: isBad }));
      }}
    />
  );

  const planLabel = plan.isPending
    ? "Planning…"
    : canStart
      ? "Plan again"
      : environment === ""
        ? "Plan"
        : `Plan in ${environment}`;
  const access = declared.find((item) => item.name === environment) ?? null;

  return (
    <section aria-label="Run it" className="ah-card ah-card-body ah-stack" style={{ gap: 14 }}>
      <h2 className="ah-h3" style={{ margin: 0 }}>
        Run it
      </h2>
      {controlOff && (
        <Banner tone="info" boxed>
          <span className="ah-stack" style={{ gap: 6 }}>
            <span>
              Plans and scenario runs cannot start from the agent-hub container: it has no
              credentials and no env files. Run hub web on your machine, or plan from a terminal:
            </span>
            <CodeBlock
              code={`./hub scenario plan ${scenario.name} --env ${environment || "<environment>"}`}
            />
          </span>
        </Banner>
      )}
      <form
        className="ah-stack"
        style={{ gap: 12 }}
        onSubmit={(event) => {
          event.preventDefault();
          sendPlan();
        }}
      >
        <div className="ah-stack" style={{ gap: 4 }}>
          <label htmlFor={envId} className="ah-small">
            Environment
          </label>
          {declared.length > 0 ? (
            <select
              id={envId}
              className="ah-input"
              value={environment}
              disabled={plan.isPending}
              aria-describedby={`${envId}-help`}
              onChange={(event) => {
                setEnvironment(event.target.value);
              }}
            >
              <option value="">Choose an environment</option>
              {declared.map((item) => (
                <option key={item.name} value={item.name}>
                  {item.name} · {item.production ? "production · " : ""}access {item.access}
                </option>
              ))}
            </select>
          ) : (
            <>
              <input
                id={envId}
                className="ah-input"
                list={listId}
                value={environment}
                disabled={plan.isPending}
                aria-describedby={`${envId}-help`}
                onChange={(event) => {
                  setEnvironment(event.target.value.trim());
                }}
              />
              <datalist id={listId}>
                {recent.map((item) => (
                  <option key={item} value={item} />
                ))}
              </datalist>
            </>
          )}
          <span id={`${envId}-help`} className="ah-small ah-subtle">
            {access !== null
              ? accessWords(access)
              : declared.length === 0
                ? "No environment is declared in this hub: name one to plan in."
                : environment === ""
                  ? "Name an environment to plan in."
                  : "The environment to plan in, as declared in hub.json or hub.local.json."}
          </span>
        </div>
        {specs.map(field)}
        <div className="ah-stack" style={{ gap: 4 }}>
          <span className="ah-small">Mode</span>
          <SegmentedControl
            label="Mode"
            value={mode}
            onChange={(id) => {
              onModeChange(id === "regression" ? "regression" : "interactive");
            }}
            options={[
              { id: "interactive", label: "Interactive" },
              { id: "regression", label: "Regression" },
            ]}
          />
          <span className="ah-small ah-muted">
            {MODE_LINE[mode]} Steps that ask still pause for your approval.
          </span>
        </div>
        <div className="ah-stack" style={{ gap: 4 }}>
          <Button
            type="submit"
            variant={canStart ? "default" : "primary"}
            icon="list-checks"
            disabled={environment === "" || plan.isPending || controlOff || locked}
          >
            {planLabel}
          </Button>
          <span className="ah-small ah-subtle">
            Plans run each action&apos;s script in plan mode, with no credential. Nothing acts on
            the system.
          </span>
        </div>
      </form>
      {plan.isPending && (
        <span role="status" className="ah-small">
          Planning in {environment}… each step&apos;s script runs in plan mode.
          {slow && " Still planning. A plan stops after 5 min."}
        </span>
      )}
      {serverErrors.size > 0 && otherErrors.length > 0 && (
        <ul role="alert" className="ah-small" style={{ margin: 0, color: "var(--failed)" }}>
          {otherErrors.map((message) => (
            <li key={message}>{message}</li>
          ))}
        </ul>
      )}
      {plan.isError && !controlOff && !inputProblems && (
        <PlanProblem
          error={plan.error}
          name={scenario.name}
          environment={plan.variables.environment}
        />
      )}
      {shown === null && !plan.isPending && !plan.isError && (
        <span className="ah-small ah-muted">
          Plan the scenario to see what each step will do in an environment.
        </span>
      )}
      {undeclared && (
        <div role="alert" className="ah-stack" style={{ gap: 6 }}>
          <span>
            Environment {shown.environment} is not declared in this hub. Declare it in hub.json, or
            in hub.local.json for yourself:
          </span>
          <CodeBlock code={`./hub env add ${shown.environment} --access read`} />
        </div>
      )}
      {shown !== null && !undeclared && (
        <div
          className="ah-stack"
          style={{
            gap: 8,
            opacity: plan.isPending ? 0.6 : 1,
            borderTop: "1px solid var(--border)",
            paddingTop: 12,
          }}
          aria-busy={plan.isPending}
        >
          <span className="ah-small">
            <b className="ah-mono">
              {shown.environment} · {shown.production ? "production · " : ""}access {shown.access}
            </b>
          </span>
          <span className="ah-small ah-muted">{planCounts(shown)}</span>
          {shown.production && (
            <Banner tone="info" boxed live={false}>
              {shown.environment} is a production environment: writes and destroys are denied there.
            </Banner>
          )}
          {shown.problems.map((problem) => (
            <span
              key={problem}
              className="ah-row ah-small"
              style={{ gap: 6, color: "var(--failed)" }}
            >
              <Icon name="circle-x" size="sm" />
              {problem}
            </span>
          ))}
        </div>
      )}
      {judged !== null && (
        <div className="ah-stack" style={{ gap: 8 }}>
          <span
            id={verdictId}
            role="status"
            className="ah-row"
            style={{ gap: 6, color: judged.ok ? "var(--text)" : "var(--failed)" }}
          >
            <Icon name={judged.ok ? "circle-check" : "octagon-x"} size="sm" />
            {judged.text}
          </span>
          {tablet ? (
            <span className="ah-small">Starting a scenario run needs a desktop screen.</span>
          ) : (
            <Button
              variant="primary"
              icon="play"
              disabled={!canStart || startedId !== null}
              aria-describedby={verdictId}
              onClick={() => {
                start.reset();
                setConfirming(true);
              }}
            >
              Start scenario run
            </Button>
          )}
        </div>
      )}
      {confirming && shown !== null && planned !== null && startedId === null && (
        <ConfirmDialog
          title={`Start a scenario run in ${shown.environment}?`}
          confirmLabel="Start scenario run"
          cancelLabel="Back to plan"
          tone="primary"
          pending={start.isPending}
          onCancel={() => {
            setConfirming(false);
          }}
          onConfirm={() => {
            start.mutate(
              { ...planned.request, mode },
              {
                onSuccess: (accepted) => {
                  setStartedId(accepted.run_id);
                },
              },
            );
          }}
        >
          <span className="ah-stack" style={{ gap: 8 }}>
            <span>{confirmBody(shown, mode)}</span>
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
                      code={`./hub scenario run ${scenario.name} --env ${shown.environment}`}
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
      {confirming && shown !== null && startedId !== null && (
        // Started: no second start is ever offered (review Q1), only the way to it and Back.
        <Dialog
          title={`Start a scenario run in ${shown.environment}?`}
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
    </section>
  );
}

const RUNS_SHOWN = 5;

function RunsList({ scenario }: { scenario: ScenarioDetail }) {
  const [all, setAll] = useState(false);
  const runs = scenario.runs;
  const shown = all ? runs : runs.slice(0, RUNS_SHOWN);
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
        <span className="ah-small ah-muted">No scenario runs yet. Plan, then start one above.</span>
      ) : (
        <ul className="ah-stack" style={{ gap: 6, margin: 0, padding: 0, listStyle: "none" }}>
          {shown.map((run) => (
            <li
              key={run.run_id}
              className="ah-row ah-small"
              style={{ gap: 8 }}
              title={[run.environment, run.mode].filter(Boolean).join(" · ")}
            >
              <ScenarioRunBadge status={run.status} />
              <AppLink
                href={scenarioRunHref(scenario.project, scenario.name, run.run_id)}
                className="ah-mono"
                data-nav-row=""
              >
                {shortId(run.run_id)}
              </AppLink>
              <span className="ah-muted">{run.environment ?? "—"}</span>
              <span className="ah-grow" />
              <Time iso={run.started_at} />
            </li>
          ))}
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

/** What Discuss talks about on this page: the scenario file and the actions it calls. */
function useScenarioDiscuss(scenario: ScenarioDetail) {
  const actions = scenario.actions.map((action) => action.path ?? action.ref);
  useDiscussTarget({
    key: `scenario:${scenario.project}:${scenario.name}`,
    project: scenario.project,
    kind: "Scenario",
    title: scenario.name,
    path: scenario.path ?? null,
    brief: [
      SCENARIO_BRIEF,
      `This conversation is about the scenario \`${scenario.path ?? `scenarios/${scenario.pack}/${scenario.name}.yaml`}\`${
        actions.length > 0 ? ` and the actions it calls (${actions.join(", ")})` : ""
      }. Read them before you answer.`,
    ].join("\n"),
    starters: [
      {
        label: "Explain this scenario",
        message: `Explain step by step what ${scenario.name} does, which scripts it runs and where it can stop.`,
      },
      {
        label: "Add a step",
        message: `Add a step to ${scenario.name}: `,
      },
    ],
  });
}

function Crumbs({ scenario }: { scenario: ScenarioDetail }) {
  return (
    <Breadcrumbs
      items={[
        { label: "Portfolio", href: "/" },
        { label: scenario.project, href: `/projects/${encodeURIComponent(scenario.project)}` },
        { label: "Scenarios", href: "/scenarios" },
        { label: scenario.name, mono: true },
      ]}
    />
  );
}

function Header({ scenario }: { scenario: ScenarioDetail }) {
  useScenarioDiscuss(scenario);
  return (
    <>
      <Breadcrumbs
        items={[
          { label: "Portfolio", href: "/" },
          { label: scenario.project, href: `/projects/${encodeURIComponent(scenario.project)}` },
          { label: "Scenarios", href: "/scenarios" },
          { label: scenario.name, mono: true },
        ]}
      />
      <div className="ah-row ah-wrap" style={{ gap: 12 }}>
        <h1 className="ah-h1 ah-mono">{scenario.name}</h1>
        <span className="ah-small ah-muted">
          pack {scenario.pack} · revision {scenario.revision}
        </span>
        <span className="ah-grow" />
        <StaleStamp />
        <DiscussButton />
      </div>
      {scenario.description && <p style={{ margin: 0 }}>{scenario.description}</p>}
    </>
  );
}

type DetailView = "steps" | "document";

function DocumentView({ scenario }: { scenario: ScenarioDetail }) {
  const { setOpen } = useDiscuss();
  return (
    <section aria-label="Document" className="ah-card ah-card-body ah-stack" style={{ gap: 10 }}>
      <span className="ah-small ah-muted">
        The scenario file, read-only. Edit the file, or ask Claude, and this page updates.
      </span>
      <FileText
        path={scenario.path ?? `scenarios/${scenario.pack}/${scenario.name}.yaml`}
        text={scenario.document_text}
      />
      <div className="ah-row" style={{ gap: 8 }}>
        <Button
          icon="message-square"
          onClick={() => {
            setOpen(true);
          }}
        >
          Edit with Claude
        </Button>
      </div>
    </section>
  );
}

/** Build mode: the breadcrumbs, then the builder (its own one-row toolbar) to the bottom. */
function BuildPage({ scenario, children }: { scenario: ScenarioDetail; children: ReactNode }) {
  useScenarioDiscuss(scenario);
  return (
    <div className="ah-stack sb-page">
      <Crumbs scenario={scenario} />
      {children}
    </div>
  );
}

function DetailBody({ scenario }: { scenario: ScenarioDetail }) {
  const [params, setParams] = useSearchParams();
  const { rows } = useWaitingRows(scenario.project);
  const mine = rows.filter((row) => row.scenario === scenario.name);
  const [mode, setMode] = useState<ScenarioMode>("interactive");
  const [plan, setPlan] = useState<ScenarioPlan | null>(null);
  const opener = useRef<HTMLElement | null>(null);
  const latest = useLatestRun(scenario, mine);
  const view: DetailView = params.get("view") === "document" ? "document" : "steps";
  const actionRef = params.get("action");
  const actions = scenario.actions;
  const openAction = actions.find((action) => action.ref === actionRef) ?? null;
  const setParam = (key: string, value: string | null) => {
    setParams(
      (current) => {
        const copy = new URLSearchParams(current);
        if (value === null) copy.delete(key);
        else copy.set(key, value);
        return copy;
      },
      { replace: true },
    );
  };
  const page: "build" | "run" = params.get("mode") === "run" ? "run" : "build";
  const modeSwitch = (
    <SegmentedControl
      label="Mode"
      value={page}
      onChange={(id) => {
        setParam("mode", id === "run" ? "run" : null);
      }}
      options={[
        { id: "build", label: "Build", icon: "puzzle" },
        { id: "run", label: "Run", icon: "play" },
      ]}
    />
  );
  if (page === "build") {
    return (
      <BuildPage scenario={scenario}>
        <WaitingCard rows={mine} named={false} />
        <ScenarioBuilder
          scenario={scenario}
          mode={mode}
          onRun={() => {
            setParam("mode", "run");
          }}
        />
      </BuildPage>
    );
  }
  return (
    <Page>
      <div className="sc-detail ah-stack" style={{ gap: 16 }}>
        <Header scenario={scenario} />
        <div className="ah-row ah-wrap" style={{ gap: 12 }}>
          {modeSwitch}
        </div>
        <WaitingCard rows={mine} named={false} />
        <div className="sc-columns">
          <div className="ah-stack" style={{ gap: 12, minWidth: 0 }}>
            <div className="ah-row ah-wrap" style={{ gap: 12 }}>
              <SegmentedControl
                label="View"
                value={view}
                onChange={(id) => {
                  setParam("view", id === "document" ? "document" : null);
                }}
                options={[
                  { id: "steps", label: "Steps", icon: "list-checks" },
                  { id: "document", label: "Document", icon: "file-text" },
                ]}
              />
              <span className="ah-grow" />
              <span className="ah-small ah-muted">{shapeLine(scenario)}</span>
            </div>
            {latest.banner}
            {view === "steps" ? (
              <Storyline
                statusOf={latest.statusOf}
                name={scenario.name}
                steps={scenario.steps}
                actions={actions}
                mode={mode}
                plan={plan}
                onOpenAction={(ref) => {
                  opener.current = document.activeElement as HTMLElement | null;
                  setParam("action", ref);
                }}
              />
            ) : (
              <DocumentView scenario={scenario} />
            )}
          </div>
          <aside
            className="sc-run-panel ah-stack"
            style={{ gap: 12 }}
            aria-label={`Run ${scenario.name}`}
          >
            <PlanCard
              scenario={scenario}
              mode={mode}
              onModeChange={setMode}
              onCurrentPlan={setPlan}
            />
            <RunsList scenario={scenario} />
          </aside>
        </div>
      </div>
      {openAction && (
        <ActionPanel
          action={openAction}
          steps={scenario.steps}
          openerRef={opener}
          onClose={() => {
            setParam("action", null);
          }}
          onShowStep={(id) => {
            setParam("action", null);
            document.getElementById(`step-${id}`)?.scrollIntoView({ block: "start" });
          }}
        />
      )}
    </Page>
  );
}

/** `/scenarios/:project/:name`: one scenario, its plan in an environment and its runs. */
export function ScenarioDetailScreen() {
  const { project = "", name = "" } = useParams();
  const scenario = useScenario(project, name);
  if (scenario.isPending) {
    return (
      <Page>
        <Skeleton width={320} height={28} />
        <Skeleton width={560} height={14} />
        <Skeleton height={120} />
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} height={20} />
        ))}
      </Page>
    );
  }
  if (scenario.isError) {
    if (scenario.error.status === 404) {
      return (
        <Page>
          <h1 className="ah-h2">Scenario {name} not found</h1>
          <p className="ah-muted" style={{ margin: 0 }}>
            Project {project} has no scenario {name} that loads. It may have been renamed, or its
            file may not load.
          </p>
          <AppLink className="ah-btn" href="/scenarios">
            Go to Scenarios
          </AppLink>
        </Page>
      );
    }
    return (
      <Page>
        <ProblemError
          title="Could not load the scenario"
          detail={scenario.error.detail}
          status={scenario.error.status}
          onRetry={() => void scenario.refetch()}
        />
      </Page>
    );
  }
  return <DetailBody scenario={scenario.data} />;
}
