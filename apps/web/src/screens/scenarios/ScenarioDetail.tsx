import { useEffect, useId, useState, type ReactNode } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";

import {
  AppLink,
  Banner,
  Button,
  CodeBlock,
  ConfirmDialog,
  Dialog,
  DataTable,
  EmptyState,
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
import { DiscussButton, useDiscussTarget } from "../../shell/discuss";
import { StaleStamp } from "../portfolio/StaleStamp";
import { InputField, parsed, type InputSpec } from "../runs-list/StartRun";
import { STEP_KINDS, stepKind } from "../workflows/steps";
import {
  DraftLine,
  EffectBadge,
  Page,
  PlanGrid,
  PolicyBadge,
  ScenarioRunBadge,
  shortId,
  useWaitingRows,
  WaitingCard,
  WhereText,
} from "./parts";
import {
  scenarioRunHref,
  usePlanScenario,
  useScenario,
  useStartScenario,
  type PlanRequest,
  type ScenarioDetail,
  type ScenarioMode,
  type ScenarioPlan,
  type ScenarioPlanRow,
  type ScenarioStep,
} from "./queries";

/* Scenario detail (AGH-350 T13, spec 23 screen 2): what the scenario does in an environment,
 * step by step, and whether it may start. The plan runs only on the person's click (a strict
 * write that starts plan-mode scripts), never on load; a start is confirmed. */

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

const UNIT: Readonly<Record<string, string>> = { s: "s", m: "min", h: "h", ms: "ms" };

/** "10s" → "10 s", "5m" → "5 min" (Content › Formatting); anything else as written. */
export function pace(value: string): string {
  const match = /^(\d+)(ms|s|m|h)$/.exec(value.trim());
  return match ? `${match[1] ?? ""} ${UNIT[match[2] ?? ""] ?? ""}` : value;
}

/** Each arg's value; a run-time one stays its placeholder, with a tooltip (principle 3). */
function Values({ row }: { row: ScenarioPlanRow }) {
  const entries = Object.entries(row.args);
  const suffix =
    row.every !== null && row.timeout !== null
      ? ` (every ${pace(row.every)}, up to ${pace(row.timeout)})`
      : "";
  if (entries.length === 0) return <span className="ah-small ah-subtle">No values{suffix}</span>;
  return (
    <span className="ah-small">
      {entries.map(([key, value], index) => {
        const runtime = /^<\$CTX\.([a-z0-9_]+) from ([^>]+)>$/i.exec(value);
        return (
          <span key={key}>
            {index > 0 && ", "}
            {runtime ? (
              <span
                className="ah-mono ah-subtle"
                title={`Known at run time: captured by step ${runtime[2] ?? ""}`}
              >
                {value}
              </span>
            ) : (
              <span className="ah-mono">{value}</span>
            )}
          </span>
        );
      })}
      {suffix}
    </span>
  );
}

function whatItDoes(row: ScenarioPlanRow): string {
  return row.plan === "runs with values known at run time"
    ? "Runs with values known at run time"
    : row.plan;
}

const PLAN_COLUMNS = [
  { id: "step", label: "Step", width: "24%" },
  { id: "action", label: "Action", width: "18%" },
  { id: "effect", label: "Effect", width: 96 },
  { id: "where", label: "Service → endpoint" },
  { id: "policy", label: "Policy", width: 168 },
] as const;

function PlanTable({ plan, scenario }: { plan: ScenarioPlan; scenario: string }) {
  return (
    <PlanGrid
      caption={`Plan of ${scenario} in ${plan.environment}`}
      columns={PLAN_COLUMNS}
      rows={plan.rows.map((row) => ({
        key: row.step,
        cells: {
          step: (
            <span
              className="ah-stack"
              style={{ gap: 2 }}
              title={`Pinned when the scenario run starts: ${row.content_hash}`}
            >
              <span className="ah-mono">{row.step}</span>
              <Values row={row} />
            </span>
          ),
          action: <span className="ah-mono ah-small">{row.action}</span>,
          effect: <EffectBadge effect={row.effect} />,
          where: (
            <span className="ah-stack" style={{ gap: 2 }}>
              <WhereText endpoints={row.endpoints} environment={plan.environment} />
              <span className="ah-small ah-muted">{whatItDoes(row)}</span>
            </span>
          ),
          policy: <PolicyBadge decision={row.decision} reason={row.reason} />,
        },
        ...(row.needs_acceptance && row.accept_command
          ? {
              extra: (
                <DraftLine commands={[row.accept_command]} action={row.action} then="plan again" />
              ),
            }
          : {}),
      }))}
    />
  );
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

function StepByStep({ steps }: { steps: readonly ScenarioStep[] }) {
  return (
    <section
      aria-label="Step by step"
      className="ah-card ah-card-body ah-stack"
      style={{ gap: 12 }}
    >
      <h2 className="ah-h3" style={{ margin: 0 }}>
        Step by step
      </h2>
      <ol className="ah-stack" style={{ gap: 8, margin: 0, paddingLeft: 0, listStyle: "none" }}>
        {steps.map((step, index) => {
          const kind = STEP_KINDS[stepKind(step.type)];
          const what =
            step.type === "action"
              ? `Action ${step.action ?? ""}`
              : step.type === "expect"
                ? `Expect ${step.action ?? ""}`
                : step.type === "approval"
                  ? "Approval by you"
                  : step.type === "wait"
                    ? "Wait"
                    : kind.one;
          return (
            <li key={step.id} className="ah-row" style={{ gap: 8, alignItems: "flex-start" }}>
              <span className="ah-num ah-subtle" style={{ width: 20 }}>
                {index + 1}
              </span>
              <span title={kind.hint}>
                <Icon name={kind.icon} />
              </span>
              <span className="ah-stack" style={{ gap: 2 }}>
                <span className="ah-mono">{step.id}</span>
                <span className="ah-small ah-muted">
                  {what}
                  {step.depends_on.length > 0 && ` · after ${step.depends_on.join(", ")}`}
                </span>
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function RunsCard({ scenario }: { scenario: ScenarioDetail }) {
  const runs = scenario.runs;
  return (
    <section
      aria-label="Scenario runs"
      className="ah-card ah-card-body ah-stack"
      style={{ gap: 12 }}
    >
      <h2 className="ah-h3" style={{ margin: 0 }}>
        Scenario runs ({runs.length})
      </h2>
      {runs.length === 0 ? (
        <EmptyState icon="clipboard-list" title="No scenario runs yet.">
          Start one from the plan above.
        </EmptyState>
      ) : (
        <DataTable
          caption={`Scenario runs of ${scenario.name}`}
          density="compact"
          rows={[...runs]}
          rowKey={(run) => run.run_id}
          columns={[
            {
              id: "run",
              label: "Scenario run",
              render: (run) => (
                <AppLink
                  href={scenarioRunHref(scenario.project, scenario.name, run.run_id)}
                  className="ah-mono"
                  data-nav-row=""
                >
                  {shortId(run.run_id)}
                </AppLink>
              ),
            },
            {
              id: "status",
              label: "Status",
              render: (run) => <ScenarioRunBadge status={run.status} />,
            },
            {
              id: "where",
              label: "Environment",
              render: (run) => (
                <span className="ah-small">
                  {run.environment ?? "—"}
                  {run.mode ? ` · ${run.mode}` : ""}
                </span>
              ),
            },
            {
              id: "started",
              label: "Started",
              render: (run) => <Time iso={run.started_at} absolute />,
            },
          ]}
        />
      )}
    </section>
  );
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

function PlanCard({ scenario }: { scenario: ScenarioDetail }) {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const environment = params.get("env") ?? "";
  const specs = scenario.inputs.map(specOf);
  const [values, setValues] = useState<Record<string, string | boolean>>(() =>
    Object.fromEntries(specs.map((spec) => [spec.name, spec.type === "boolean" ? false : ""])),
  );
  const [bad, setBad] = useState<Record<string, boolean>>({});
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [mode, setMode] = useState<ScenarioMode>("interactive");
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

  useEffect(() => {
    if (startedId === null) return;
    if ((polled.data?.runs ?? []).some((run) => run.run_id === startedId)) {
      void navigate(scenarioRunHref(scenario.project, scenario.name, startedId));
    }
  }, [polled.data, startedId, navigate, scenario.project, scenario.name]);

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
  if (plan.isError && plan.error.status === 422) {
    for (const item of plan.error.errors) {
      const name = /^\/inputs\/([^/]+)$/.exec(item.pointer)?.[1];
      if (name !== undefined && !serverErrors.has(name)) serverErrors.set(name, item.message);
    }
  }
  const inputProblems = serverErrors.size > 0;
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

  return (
    <section aria-label="Plan" className="ah-card ah-card-body ah-stack" style={{ gap: 12 }}>
      <h2 className="ah-h3" style={{ margin: 0 }}>
        Plan
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
        className="ah-row ah-wrap"
        style={{ gap: 12, alignItems: "flex-end" }}
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
            {environment === ""
              ? "Name an environment to plan in."
              : "The environment to plan in, as declared in hub.json or hub.local.json."}
          </span>
        </div>
        {specs.map(field)}
        <Button
          type="submit"
          variant="primary"
          icon="list-checks"
          disabled={environment === "" || plan.isPending || controlOff || locked}
        >
          {plan.isPending ? "Planning…" : environment === "" ? "Plan" : `Plan in ${environment}`}
        </Button>
      </form>
      <span className="ah-small ah-subtle">
        Plans run each action&apos;s script in plan mode, with no credential. Nothing acts on the
        system.
      </span>
      {plan.isPending && (
        <span role="status" className="ah-small">
          Planning in {environment}… each step&apos;s script runs in plan mode.
          {slow && " Still planning. A plan stops after 5 min."}
        </span>
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
          style={{ gap: 10, opacity: plan.isPending ? 0.6 : 1 }}
          aria-busy={plan.isPending}
        >
          <div className="ah-row ah-wrap ah-small" style={{ gap: 12 }}>
            <b className="ah-mono">
              {shown.environment} · {shown.production ? "production · " : ""}access {shown.access}
            </b>
            <span className="ah-grow" />
            <span className="ah-muted">{planCounts(shown)}</span>
          </div>
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
          <PlanTable plan={shown} scenario={scenario.name} />
        </div>
      )}
      {judged !== null && (
        <div
          className="ah-stack"
          style={{ gap: 8, borderTop: "1px solid var(--border)", paddingTop: 12 }}
        >
          <span
            id={verdictId}
            role="status"
            className="ah-row"
            style={{ gap: 6, color: judged.ok ? "var(--text)" : "var(--failed)" }}
          >
            <Icon name={judged.ok ? "circle-check" : "octagon-x"} size="sm" />
            {judged.text}
          </span>
          <div className="ah-row ah-wrap" style={{ gap: 12 }}>
            <span className="ah-small">Mode</span>
            <SegmentedControl
              label="Mode"
              value={mode}
              onChange={(id) => {
                setMode(id === "regression" ? "regression" : "interactive");
              }}
              options={[
                { id: "interactive", label: "Interactive" },
                { id: "regression", label: "Regression" },
              ]}
            />
            <span className="ah-grow" />
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
          <span className="ah-small ah-muted">
            {MODE_LINE[mode]} Steps that ask still pause for your approval.
          </span>
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

function Header({ scenario }: { scenario: ScenarioDetail }) {
  useDiscussTarget({
    key: `scenario:${scenario.project}:${scenario.name}`,
    project: scenario.project,
    kind: "Scenario",
    title: scenario.name,
    brief: `It is a scenario in the hub's \`scenarios/${scenario.pack}/\` folder.`,
  });
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

function DetailBody({ scenario }: { scenario: ScenarioDetail }) {
  const { rows } = useWaitingRows(scenario.project);
  const mine = rows.filter((row) => row.scenario === scenario.name);
  return (
    <Page>
      <Header scenario={scenario} />
      <WaitingCard rows={mine} named={false} />
      <PlanCard scenario={scenario} />
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))",
          gap: 16,
          alignItems: "start",
        }}
      >
        <StepByStep steps={scenario.steps} />
        <RunsCard scenario={scenario} />
      </div>
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
